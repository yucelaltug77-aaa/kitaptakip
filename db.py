import os
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "data" / "kitap.db"))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                cover_path TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                isbn TEXT NOT NULL DEFAULT '',
                publication_year TEXT NOT NULL DEFAULT '',
                total_pages INTEGER NOT NULL CHECK(total_pages > 0),
                current_page INTEGER NOT NULL DEFAULT 0,
                shelf TEXT NOT NULL DEFAULT 'Okunacak'
                    CHECK(shelf IN ('Okunacak', 'Okunuyor', 'Okundu')),
                added_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE UNIQUE INDEX IF NOT EXISTS unique_book_isbn
                ON books(isbn) WHERE isbn != '';
            CREATE UNIQUE INDEX IF NOT EXISTS unique_book_title_author
                ON books(lower(title), lower(author));
            CREATE TABLE IF NOT EXISTS reading_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                page INTEGER NOT NULL,
                read_date TEXT NOT NULL,
                logged_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS reading_logs_book_date
                ON reading_logs(book_id, read_date, id);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings(key, value) VALUES ('annual_goal', '24');
            """
        )
        reading_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(reading_logs)")
        }
        if "minutes" not in reading_columns:
            connection.execute(
                "ALTER TABLE reading_logs ADD COLUMN minutes INTEGER NOT NULL DEFAULT 0"
            )
        if "note" not in reading_columns:
            connection.execute(
                "ALTER TABLE reading_logs ADD COLUMN note TEXT NOT NULL DEFAULT ''"
            )


def add_book(data):
    shelf = data.get("shelf", "Okunacak")
    today = datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()
    try:
        with connect() as connection:
            cursor = connection.execute(
                """INSERT INTO books
                   (title, author, publisher, cover_url, source_url, isbn,
                    publication_year, total_pages, shelf, current_page, added_at,
                    started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["title"], data.get("author", ""), data.get("publisher", ""),
                    data.get("cover_url", ""), data.get("source_url", ""),
                    data.get("isbn", ""), data.get("publication_year", ""),
                    data["total_pages"], data.get("shelf", "Okunacak"),
                    data.get("current_page", 0),
                    datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
                    data.get("started_at") or (today if shelf == "Okunuyor" else None),
                    data.get("finished_at") or (today if shelf == "Okundu" else None),
                ),
            )
            book_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Bu kitap kitaplığında zaten kayıtlı.") from error
    if data.get("cover_url"):
        try:
            from scraper import download_cover

            relative_path = download_cover(data["cover_url"], book_id)
            if relative_path:
                with connect() as connection:
                    connection.execute(
                        "UPDATE books SET cover_path = ? WHERE id = ?",
                        (relative_path, book_id),
                    )
        except (OSError, ValueError, requests.RequestException):
            logging.getLogger(__name__).exception("Kapak indirilemedi; varsayılan kapak kullanılacak")
    return book_id


def get_books(shelf=None, query="", sort="recent"):
    order_by = {
        "recent": "added_at DESC, id DESC",
        "title": "lower(title), lower(author)",
        "author": "lower(author), lower(title)",
        "progress": "CAST(current_page AS REAL) / total_pages DESC, lower(title)",
        "rating": "rating DESC, lower(title)",
    }.get(sort, "added_at DESC, id DESC")
    filters = []
    parameters = []
    if shelf:
        filters.append("shelf = ?")
        parameters.append(shelf)
    if query:
        filters.append("(title LIKE ? ESCAPE '\\' OR author LIKE ? ESCAPE '\\' OR isbn LIKE ? ESCAPE '\\')")
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        parameters.extend([f"%{escaped_query}%"] * 3)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM books {where_clause} ORDER BY {order_by}", parameters
        ).fetchall()
        return [dict(row) for row in rows]


def get_book(book_id):
    with connect() as connection:
        row = connection.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return dict(row) if row else None


def get_readings(book_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM reading_logs WHERE book_id = ? ORDER BY read_date, id",
            (book_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def log_reading(book_id, page, read_date, minutes=0, note=""):
    with connect() as connection:
        connection.execute(
            """INSERT INTO reading_logs(book_id, page, read_date, logged_at, minutes, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                book_id, page, read_date, datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
                minutes, note,
            ),
        )
        connection.execute(
            """UPDATE books SET current_page = (
                   SELECT page FROM reading_logs WHERE book_id = ?
                   ORDER BY read_date DESC, id DESC LIMIT 1
               ) WHERE id = ?""",
            (book_id, book_id),
        )


def delete_reading(reading_id, book_id):
    with connect() as connection:
        connection.execute(
            "DELETE FROM reading_logs WHERE id = ? AND book_id = ?", (reading_id, book_id)
        )
        latest = connection.execute(
            "SELECT page FROM reading_logs WHERE book_id = ? ORDER BY read_date DESC, id DESC LIMIT 1",
            (book_id,),
        ).fetchone()
        book = connection.execute(
            "SELECT total_pages, shelf FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        current_page = latest["page"] if latest else 0
        shelf = book["shelf"]
        finished_at = None
        if shelf == "Okundu" and current_page < book["total_pages"]:
            shelf = "Okunuyor" if current_page else "Okunacak"
            finished_at = ""
        connection.execute(
            """UPDATE books SET current_page = ?, shelf = ?,
               finished_at = CASE WHEN ? = '' THEN NULL ELSE finished_at END
               WHERE id = ?""",
            (current_page, shelf, finished_at, book_id),
        )


def delete_last_reading(book_id):
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM reading_logs WHERE book_id = ? ORDER BY read_date DESC, id DESC LIMIT 1",
            (book_id,),
        ).fetchone()
    if row:
        delete_reading(row["id"], book_id)


def update_book(book_id, data):
    try:
        with connect() as connection:
            connection.execute(
                """UPDATE books SET title = ?, author = ?, publisher = ?, isbn = ?,
                   publication_year = ?, total_pages = ?,
                   shelf = CASE WHEN shelf = 'Okundu' AND current_page < ?
                                     AND total_pages != ?
                                THEN 'Okunuyor' ELSE shelf END,
                   finished_at = CASE WHEN current_page < ? AND total_pages != ?
                                       THEN NULL ELSE finished_at END,
                   source_url = ?, cover_url = ?
                   WHERE id = ?""",
                (
                    data["title"], data.get("author", ""), data.get("publisher", ""),
                    data.get("isbn", ""), data.get("publication_year", ""), data["total_pages"],
                    data["total_pages"], data["total_pages"], data["total_pages"],
                    data["total_pages"], data.get("source_url", ""),
                    data.get("cover_url", ""),
                    book_id,
                ),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("Bu kitap veya ISBN zaten kitaplığında kayıtlı.") from error


def delete_book(book_id):
    with connect() as connection:
        connection.execute("DELETE FROM books WHERE id = ?", (book_id,))


def update_shelf(book_id, shelf, started_at=None, finished_at=None):
    with connect() as connection:
        if started_at is not None or finished_at is not None:
            connection.execute(
                """UPDATE books SET shelf = ?,
                   started_at = COALESCE(?, started_at),
                   finished_at = CASE WHEN ? = '' THEN NULL ELSE COALESCE(?, finished_at) END
                   WHERE id = ?""",
                (shelf, started_at, finished_at, finished_at, book_id),
            )
        else:
            connection.execute("UPDATE books SET shelf = ? WHERE id = ?", (shelf, book_id))


def save_rating(book_id, rating, note):
    with connect() as connection:
        connection.execute(
            "UPDATE books SET rating = ?, note = ? WHERE id = ?",
            (rating, note, book_id),
        )


def get_setting(key, default=None):
    with connect() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with connect() as connection:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
