import catalog


def catalog_record(**overrides):
    record = {
        "key": "/works/OL123456W",
        "title": "Türkçe Roman",
        "author_name": ["Örnek Yazar"],
        "first_publish_year": 1928,
        "edition_count": 8,
        "cover_i": 42,
        "language": ["tur"],
        "ebook_access": "public",
        "ia": ["ornekroman00yaza"],
        "public_scan_b": True,
        "ratings_count": 15,
        "ratings_average": 4.2,
        "subject": ["Roman"],
        "isbn": ["9780000000000"],
        "number_of_pages_median": 240,
    }
    return {**record, **overrides}


def test_catalog_normalizes_turkish_book_without_guessing_text_language():
    book = catalog.normalize_book(catalog_record())
    assert book["language"] == "Türkçe"
    assert book["edition_count"] == 8
    assert book["total_pages"] == 240
    assert not book["free_read_available"]
    assert book["free_read_url"] == ""
    assert book["catalog_url"] == "https://openlibrary.org/works/OL123456W"


def test_catalog_uses_an_actual_turkish_edition_title_and_metadata(monkeypatch):
    book = catalog.normalize_book(catalog_record())
    monkeypatch.setattr(
        catalog,
        "_request_editions",
        lambda work_key, offset: {
            "size": 1,
            "entries": [
                {
                    "key": "/books/OL123456M",
                    "title": "Türkçe Roman",
                    "languages": [{"key": "/languages/tur"}],
                    "publish_date": "2019",
                    "number_of_pages": 255,
                    "isbn_13": ["9781111111111"],
                    "covers": [99],
                }
            ],
        },
    )
    localized = catalog.localize_turkish_editions([book])
    assert localized[0]["title"] == "Türkçe Roman"
    assert localized[0]["first_publish_year"] == 2019
    assert localized[0]["total_pages"] == 255
    assert localized[0]["isbn"] == "9781111111111"
    assert localized[0]["catalog_url"] == "https://openlibrary.org/books/OL123456M"


def test_catalog_never_calls_borrowable_books_free_or_returns_other_languages():
    borrowable = catalog.normalize_book(
        catalog_record(ebook_access="borrowable", public_scan_b=False)
    )
    english = catalog.normalize_book(catalog_record(language=["eng"]))
    assert borrowable is not None
    assert not borrowable["free_read_available"]
    assert borrowable["free_read_url"] == ""
    assert english is None


def test_catalog_links_only_archive_items_confirmed_turkish_and_public(monkeypatch):
    book = catalog.normalize_book(catalog_record())
    monkeypatch.setattr(
        catalog,
        "_request_archive",
        lambda identifiers: [
            {
                "identifier": "ornekroman00yaza",
                "title": "Turkish novel",
                "language": "tur",
                "mediatype": "texts",
            }
        ],
    )
    catalog.verify_free_reading_links([book])
    assert book["free_read_available"]
    assert book["free_read_url"] == "https://archive.org/details/ornekroman00yaza"


def test_catalog_rejects_non_turkish_archive_scan_even_when_work_has_turkish_editions(monkeypatch):
    book = catalog.normalize_book(catalog_record())
    monkeypatch.setattr(
        catalog,
        "_request_archive",
        lambda identifiers: [
            {
                "identifier": "ornekroman00yaza",
                "title": "Russian edition",
                "language": "rus",
                "mediatype": "texts",
            }
        ],
    )
    catalog.verify_free_reading_links([book])
    assert not book["free_read_available"]


def test_catalog_does_not_link_a_turkish_scan_with_a_different_book_title(monkeypatch):
    book = catalog.normalize_book(catalog_record())
    book["_expected_free_title"] = "Another novel"
    monkeypatch.setattr(
        catalog,
        "_request_archive",
        lambda identifiers: [
            {
                "identifier": "ornekroman00yaza",
                "title": "Türkçe Roman",
                "language": "tur",
                "mediatype": "texts",
            }
        ],
    )
    catalog.verify_free_reading_links([book])
    assert not book["free_read_available"]


def test_catalog_sorting_uses_catalog_editions_year_and_rating_counts():
    books = [
        catalog.normalize_book(catalog_record(
            key="/works/OL1W", title="Bir", edition_count=2,
            first_publish_year=2000, ratings_count=90,
        )),
        catalog.normalize_book(catalog_record(
            key="/works/OL2W", title="İki", edition_count=10,
            first_publish_year=1950, ratings_count=4,
        )),
        catalog.normalize_book(catalog_record(
            key="/works/OL3W", title="Üç", edition_count=4,
            first_publish_year=2020, ratings_count=30,
        )),
    ]
    assert [book["title"] for book in catalog.sort_catalog(books, "editions")] == [
        "İki", "Üç", "Bir"
    ]
    assert [book["title"] for book in catalog.sort_catalog(books, "year")] == [
        "Üç", "Bir", "İki"
    ]
    assert [book["title"] for book in catalog.sort_catalog(books, "popularity")] == [
        "Bir", "Üç", "İki"
    ]


def test_free_book_lookup_requires_exact_turkish_title_author_and_public_access(monkeypatch):
    monkeypatch.setattr(
        catalog, "_request_catalog",
        lambda params: [
            catalog_record(title="Başka kitap"),
            catalog_record(author_name=["Başka Yazar"]),
            catalog_record(ebook_access="borrowable", public_scan_b=False),
            catalog_record(key="/works/OL987654W"),
        ],
    )
    match = catalog.find_free_reading("Türkçe Roman", "Örnek Yazar", "978-0-000-00000-1")
    assert match is None

    monkeypatch.setattr(
        catalog, "_request_catalog",
        lambda params: [catalog_record()],
    )
    monkeypatch.setattr(
        catalog, "_request_editions",
        lambda work_key, offset: {
            "size": 1,
            "entries": [
                {
                    "key": "/books/OL123456M",
                    "title": "Türkçe Roman",
                    "languages": [{"key": "/languages/tur"}],
                }
            ],
        },
    )
    monkeypatch.setattr(
        catalog, "_request_archive",
        lambda identifiers: [
            {
                "identifier": "ornekroman00yaza",
                "title": "Türkçe Roman",
                "language": "tur",
                "mediatype": "texts",
            }
        ],
    )
    match = catalog.find_free_reading("Türkçe Roman", "Örnek Yazar", "9780000000000")
    assert match["free_read_available"]


def test_recommendations_use_read_authors_exclude_owned_books_and_add_reason(monkeypatch):
    monkeypatch.setattr(
        catalog, "_request_catalog",
        lambda params: [
            catalog_record(title="Zaten okundu", author_name=["Örnek Yazar"]),
            catalog_record(key="/works/OL234567W", title="Yeni Roman"),
            catalog_record(key="/works/OL345678W", title="English", language=["eng"]),
        ],
    )
    books = catalog.recommend_from_reading(
        [{"title": "Zaten okundu", "author": "Örnek Yazar", "shelf": "Okundu"}]
    )
    assert [book["title"] for book in books] == ["Yeni Roman"]
    assert "Zaten okundu" in books[0]["recommendation_reason"]
