import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
import truststore
from bs4 import BeautifulSoup

truststore.inject_into_ssl()

BASE_URL = "https://www.kitapyurdu.com"
SEARCH_URL = BASE_URL + "/index.php?route=product/search&filter_name={}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}
COVER_DIR = Path(__file__).resolve().parent / "static" / "kapaklar"


def _text(element):
    return element.get_text(" ", strip=True) if element else ""


def _detail(session, url):
    try:
        response = session.get(url, timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        return {}
    soup = BeautifulSoup(response.text, "html.parser")
    values = {}
    for row in soup.select(".ky-pd-attributes__item"):
        text = _text(row)
        if ":" not in text:
            continue
        label, value = text.split(":", 1)
        values[label.strip().lower()] = value.strip()
    pages = re.search(r"\d[\d.]*", values.get("sayfa sayısı", ""))
    year_text = " ".join(
        values.get(label, "")
        for label in ("yayın tarihi", "yayın yılı", "basım yılı")
    )
    publication_year = re.search(r"\b(?:19|20)\d{2}\b", year_text)
    return {
        "total_pages": int(pages.group(0).replace(".", "")) if pages else "",
        "isbn": values.get("isbn", ""),
        "publication_year": publication_year.group(0) if publication_year else "",
    }


def search_books(query):
    with requests.Session() as session:
        session.headers.update(HEADERS)
        response = session.get(SEARCH_URL.format(requests.utils.quote(query)), timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for card in soup.select(".ky-product"):
            title_link = card.select_one("a.ky-product-title")
            if not title_link:
                continue
            image_link = card.select_one("a.ky-product-cover img")
            href = urljoin(BASE_URL, title_link.get("href", ""))
            result = {
                "title": _text(title_link),
                "author": _text(card.select_one(".ky-product-author a")),
                "publisher": _text(card.select_one(".ky-product-publisher a")),
                "cover_url": urljoin(BASE_URL, image_link.get("src", "")) if image_link else "",
                "source_url": href,
            }
            result.update(_detail(session, href))
            results.append(result)
            if len(results) >= 12:
                break
        return results


def download_cover(url, book_id):
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, headers=HEADERS, timeout=5)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    extensions = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/gif": ".gif",
    }
    extension = extensions.get(content_type)
    if not extension:
        suffix = Path(url.split("?", 1)[0]).suffix.lower()
        extension = suffix if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg"
    if extension == ".jpeg":
        extension = ".jpg"
    content = response.content
    if not content or len(content) > 10 * 1024 * 1024:
        raise ValueError("Kapak görseli boş veya izin verilen boyuttan büyük.")
    digest = hashlib.sha256(content).hexdigest()[:10]
    filename = f"{book_id}-{digest}{extension}"
    (COVER_DIR / filename).write_bytes(content)
    return f"kapaklar/{filename}"
