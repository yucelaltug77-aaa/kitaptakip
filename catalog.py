import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

import requests

OPEN_LIBRARY_API = "https://openlibrary.org/search.json"
OPEN_LIBRARY_BASE = "https://openlibrary.org"
ARCHIVE_BASE = "https://archive.org/details"
ARCHIVE_SEARCH_API = "https://archive.org/advancedsearch.php"
HEADERS = {"User-Agent": "KitapTakip/1.0 (personal Turkish reading tracker)"}
FIELDS = ",".join(
    (
        "key", "title", "author_name", "first_publish_year", "edition_count",
        "cover_i", "language", "ebook_access", "ia", "public_scan_b",
        "ratings_count", "ratings_average", "subject", "isbn",
        "number_of_pages_median",
    )
)


def _request_catalog(params):
    response = requests.get(
        OPEN_LIBRARY_API, params=params, headers=HEADERS, timeout=5
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("docs"), list):
        raise ValueError("Open Library kataloğundan beklenen yanıt alınamadı.")
    return payload["docs"]


def _request_archive(identifiers):
    response = requests.get(
        ARCHIVE_SEARCH_API,
        params={
            "q": f"identifier:({' OR '.join(identifiers)}) AND mediatype:texts",
            "fl[]": ["identifier", "title", "language", "mediatype"],
            "output": "json",
            "rows": str(len(identifiers)),
        },
        headers=HEADERS,
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    docs = payload.get("response", {}).get("docs")
    if not isinstance(docs, list):
        raise ValueError("Internet Archive kataloğundan beklenen yanıt alınamadı.")
    return docs


def _request_editions(work_key, offset):
    response = requests.get(
        f"{OPEN_LIBRARY_BASE}{work_key}/editions.json",
        params={"limit": 100, "offset": offset},
        headers=HEADERS,
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("Open Library baskı kayıtlarından beklenen yanıt alınamadı.")
    return payload


def _apply_turkish_edition(book):
    work_key = book.get("_work_key", "")
    if not work_key:
        return None
    offset = 0
    while offset < 300:
        payload = _request_editions(work_key, offset)
        entries = payload["entries"]
        for edition in entries:
            languages = {
                item.get("key", "").rsplit("/", 1)[-1]
                for item in edition.get("languages", [])
                if isinstance(item, dict)
            }
            if "tur" not in languages or not edition.get("title"):
                continue
            book["title"] = edition["title"].strip()
            book["catalog_url"] = (
                OPEN_LIBRARY_BASE + edition["key"]
                if re.fullmatch(r"/books/OL\d+M", edition.get("key", ""))
                else OPEN_LIBRARY_BASE + work_key
            )
            publication_date = str(edition.get("publish_date", ""))
            year = re.search(r"\b(?:18|19|20)\d{2}\b", publication_date)
            if year:
                book["first_publish_year"] = int(year.group(0))
            pages = edition.get("number_of_pages")
            if isinstance(pages, int) and pages > 0:
                book["total_pages"] = pages
            isbn = edition.get("isbn_13") or edition.get("isbn_10") or []
            if isbn:
                book["isbn"] = isbn[0]
            cover = (edition.get("covers") or [None])[0]
            if isinstance(cover, int):
                book["cover_url"] = f"https://covers.openlibrary.org/b/id/{cover}-M.jpg"
            book["_expected_free_title"] = book["title"]
            return book
        if not entries or len(entries) < 100:
            return None
        offset += 100
    return None


def localize_turkish_editions(books):
    candidates = [book for book in books if book.get("_work_key")]
    with ThreadPoolExecutor(max_workers=4) as executor:
        localized = list(executor.map(_apply_turkish_edition, candidates))
    localized_by_key = {
        book["_work_key"]: book for book in localized if book is not None
    }
    return [
        localized_by_key[book["_work_key"]]
        for book in candidates
        if book["_work_key"] in localized_by_key
    ]


def normalize_book(record):
    languages = record.get("language") or []
    if isinstance(languages, str):
        languages = [languages]
    if "tur" not in languages:
        return None

    key = record.get("key", "")
    if not re.fullmatch(r"/works/OL\d+W", key):
        return None

    archive_ids = record.get("ia") or []
    if isinstance(archive_ids, str):
        archive_ids = [archive_ids]
    archive_ids = [
        identifier for identifier in archive_ids
        if isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", identifier)
    ]

    cover_id = record.get("cover_i")
    isbn_list = record.get("isbn") or []
    if isinstance(isbn_list, str):
        isbn_list = [isbn_list]
    subjects = record.get("subject") or []
    if isinstance(subjects, str):
        subjects = [subjects]
    ratings_count = record.get("ratings_count") or 0
    edition_count = record.get("edition_count") or 0
    first_publish_year = record.get("first_publish_year") or 0
    authors = record.get("author_name") or []
    if isinstance(authors, str):
        authors = [authors]
    average_rating = record.get("ratings_average")
    if not isinstance(average_rating, (int, float)):
        average_rating = None
    return {
        "title": record.get("title", "").strip(),
        "author": ", ".join(authors),
        "first_publish_year": first_publish_year if isinstance(first_publish_year, int) else 0,
        "total_pages": record.get("number_of_pages_median") or "",
        "edition_count": edition_count if isinstance(edition_count, int) else 0,
        "ratings_count": ratings_count if isinstance(ratings_count, int) else 0,
        "average_rating": average_rating,
        "isbn": isbn_list[0] if isbn_list else "",
        "subjects": subjects[:5],
        "language": "Türkçe",
        "catalog_url": OPEN_LIBRARY_BASE + key,
        "_work_key": key,
        "_archive_ids": archive_ids,
        "_has_public_scan": bool(record.get("public_scan_b")) or record.get("ebook_access") == "public",
        "cover_url": (
            f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
            if isinstance(cover_id, int) else ""
        ),
        "free_read_url": "",
        "free_read_available": False,
        "source": "Open Library",
    }


def verify_free_reading_links(books):
    eligible = [
        book for book in books
        if book.get("_has_public_scan") and book.get("_archive_ids")
    ][:8]
    identifiers = list(dict.fromkeys(
        identifier
        for book in eligible
        for identifier in book["_archive_ids"][:12]
    ))
    if not identifiers:
        return books

    documents = _request_archive(identifiers[:100])
    turkish_docs = {}
    for document in documents:
        identifier = document.get("identifier", "")
        language = document.get("language", "")
        languages = language if isinstance(language, list) else [language]
        language_codes = {_normalized_text(str(value)) for value in languages}
        if (
            identifier in identifiers
            and document.get("mediatype") == "texts"
            and language_codes & {"tur", "turkish", "turkce"}
            and re.fullmatch(r"[A-Za-z0-9_.-]+", identifier)
        ):
            turkish_docs[identifier] = document

    for book in eligible:
        for identifier in book["_archive_ids"]:
            document = turkish_docs.get(identifier)
            if not document:
                continue
            expected_title = book.get("_expected_free_title")
            if expected_title:
                target = _normalized_text(expected_title)
                archive_title = _normalized_text(document.get("title", ""))
                if target != archive_title and (
                    not target.startswith(archive_title)
                    and not archive_title.startswith(target)
                ):
                    continue
            book["free_read_url"] = f"{ARCHIVE_BASE}/{quote(identifier, safe='')}"
            book["free_read_title"] = document.get("title") or book["title"]
            book["free_read_available"] = True
            break
    return books


def sort_catalog(books, sort_by):
    if sort_by == "year":
        return sorted(
            books,
            key=lambda book: (book["first_publish_year"] > 0, book["first_publish_year"]),
            reverse=True,
        )
    if sort_by == "popularity":
        return sorted(
            books,
            key=lambda book: (book["ratings_count"], book["average_rating"] or 0),
            reverse=True,
        )
    return sorted(
        books,
        key=lambda book: (book["edition_count"], book["first_publish_year"]),
        reverse=True,
    )


def search_turkish_books(query, sort_by="editions", limit=12):
    docs = _request_catalog(
        {
            "q": query,
            "language": "tur",
            "fields": FIELDS,
            "limit": min(max(limit, 1), 100),
        }
    )
    books = [normalize_book(doc) for doc in docs]
    books = [book for book in books if book and book["title"]]
    ranked = sort_catalog(books, sort_by)[:min(max(limit, 1), 24)]
    localized = localize_turkish_editions(ranked)
    return sort_catalog(localized, sort_by)


def _normalized_text(value):
    value = unicodedata.normalize("NFKD", value or "").casefold()
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def find_free_reading(title, author="", isbn=""):
    params = {
        "language": "tur",
        "fields": FIELDS,
        "limit": 25,
    }
    if isbn:
        params["isbn"] = isbn
    else:
        params["title"] = title
        if author:
            params["author"] = author
    target_isbn = re.sub(r"[^0-9Xx]", "", isbn)
    candidates = []
    for record in _request_catalog(params):
        book = normalize_book(record)
        if not book or not book["_has_public_scan"]:
            continue
        if target_isbn:
            record_isbns = record.get("isbn") or []
            if isinstance(record_isbns, str):
                record_isbns = [record_isbns]
            if target_isbn not in {
                re.sub(r"[^0-9Xx]", "", value) for value in record_isbns
            }:
                continue
        book["_expected_free_title"] = title
        candidates.append(book)
    localized = localize_turkish_editions(candidates)
    exact_matches = [
        book for book in localized
        if _normalized_text(book["title"]) == _normalized_text(title)
    ]
    verified = verify_free_reading_links(exact_matches)
    return next(
        (book for book in verified if book["free_read_available"]),
        None,
    )


def catalog_search_url(title, author=""):
    query = " ".join(part for part in (title, author) if part).strip()
    return f"{OPEN_LIBRARY_BASE}/search?{urlencode({'q': query})}"


def kitapyurdu_search_url(title, author=""):
    query = " ".join(part for part in (title, author) if part).strip()
    return f"https://www.kitapyurdu.com/index.php?route=product/search&filter_name={quote(query)}"


def recommend_from_reading(read_books, sort_by="editions", limit=18):
    completed = [book for book in read_books if book.get("shelf") == "Okundu"]
    preferences = completed or [
        book for book in read_books if book.get("shelf") == "Okunuyor"
    ] or read_books
    existing_titles = {_normalized_text(book.get("title", "")) for book in read_books}
    seen_authors = set()
    recommendations = []
    for reference in preferences:
        author = (reference.get("author") or "").strip()
        normalized_author = _normalized_text(author)
        if not author or normalized_author in seen_authors:
            continue
        seen_authors.add(normalized_author)
        docs = _request_catalog(
            {
                "author": author,
                "language": "tur",
                "fields": FIELDS,
                "limit": 30,
            }
        )
        for record in docs:
            book = normalize_book(record)
            if not book or _normalized_text(book["title"]) in existing_titles:
                continue
            if normalized_author and normalized_author not in _normalized_text(book["author"]):
                continue
            book["recommendation_reason"] = (
                f"{reference['title']} kitabını okuduğun için "
                f"{author or 'bu yazar'}den bir öneri."
            )
            recommendations.append(book)
        if len(seen_authors) >= 3:
            break
    unique = {}
    for book in recommendations:
        unique.setdefault(_normalized_text(book["title"]), book)
    return sort_catalog(list(unique.values()), sort_by)[:limit]
