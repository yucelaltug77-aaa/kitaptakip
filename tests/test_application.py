from datetime import date
import sqlite3

import pytest

import db
from application import (
    annual_goal_status,
    app,
    build_achievements,
    estimate_days_to_finish,
    local_today,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.test_client() as test_client:
        yield test_client


def authenticated(client):
    with client.session_transaction() as session:
        session["logged_in"] = True


def test_login_is_required(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_accepts_configured_single_user(client):
    response = client.post("/login", data={"username": "test", "password": "123"})
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/")
    assert client.get("/").status_code == 200


def test_dashboard_shows_reading_mission_and_achievements(client):
    authenticated(client)
    book_id = db.add_book(
        {"title": "Bugünün Kitabı", "author": "Yazar", "total_pages": 200,
         "shelf": "Okunuyor", "current_page": 40}
    )
    db.log_reading(book_id, 40, local_today().isoformat(), 25, "Güzel bir bölüm.")
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Bugünün Kitabı" in html
    assert "Bu haftanın yolculuğu" in html
    assert "Başarı koleksiyonun" in html
    assert "Güzel bir bölüm." in html
    assert "25" in html


def test_achievement_unlocks_are_based_on_lifetime_reading(client):
    book_id = db.add_book(
        {"title": "Bitmiş kitap", "total_pages": 100, "shelf": "Okundu"}
    )
    badges = build_achievements(
        [db.get_book(book_id)],
        [{"pages_read": 100, "minutes": 300}],
        longest_streak=7,
    )
    unlocked = {badge["id"] for badge in badges if badge["unlocked"]}
    assert {"first-session", "pages-100", "book-1", "streak-3", "streak-7", "minutes-300"} <= unlocked


def test_stats_page_renders_goal_and_chart(client):
    authenticated(client)
    response = client.get("/stats")
    assert response.status_code == 200
    assert "Aylık okunan sayfa" in response.get_data(as_text=True)
    assert "Okuma takvimi" in response.get_data(as_text=True)


def test_monthly_page_goal_can_be_updated(client):
    authenticated(client)
    response = client.post(
        "/stats", data={"goal_type": "monthly_pages", "monthly_page_goal": "250"}
    )
    assert response.status_code == 302
    assert db.get_setting("monthly_page_goal") == "250"


@pytest.mark.parametrize(
    ("goal_type", "field", "value", "key"),
    [
        ("weekly_pages", "weekly_page_goal", "180", "weekly_page_goal"),
        ("daily_minutes", "daily_minute_goal", "35", "daily_minute_goal"),
    ],
)
def test_mission_goals_can_be_updated(client, goal_type, field, value, key):
    authenticated(client)
    response = client.post("/stats", data={"goal_type": goal_type, field: value})
    assert response.status_code == 302
    assert db.get_setting(key) == value


def test_search_page_offers_manual_add_for_empty_results(client, monkeypatch):
    import application

    authenticated(client)
    monkeypatch.setattr(application, "search_books", lambda query: [])
    response = client.get("/search?q=deneme")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Kitap bulunamadı" in html
    assert 'id="manual-add"' in html


def test_discover_search_is_turkish_and_keeps_catalog_links(client, monkeypatch):
    import application

    authenticated(client)
    sample_book = {
        "title": "Türkçe Roman",
        "author": "Örnek Yazar",
        "first_publish_year": 1928,
        "edition_count": 8,
        "ratings_count": 15,
        "average_rating": 4.2,
        "isbn": "9780000000000",
        "total_pages": 240,
        "catalog_url": "https://openlibrary.org/works/OL123456W",
        "cover_url": "",
        "free_read_url": "https://archive.org/details/ornekroman00yaza",
        "free_read_available": True,
        "recommendation_reason": "",
        "language": "Türkçe",
    }
    monkeypatch.setattr(application, "search_turkish_books", lambda query, sort: [sample_book])
    response = client.get("/discover?q=roman&sort=year")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Türkçe Roman" in html
    assert "Yasal ücretsiz oku" in html
    assert "https://archive.org/details/ornekroman00yaza" in html
    assert "gerçek tiraj değildir" in html


def test_discover_recommends_from_books_already_read(client, monkeypatch):
    import application

    authenticated(client)
    db.add_book({"title": "Okuduğum", "author": "Örnek Yazar", "total_pages": 100, "shelf": "Okundu"})
    sample = {
        "title": "Öneri",
        "_work_key": "/works/OL123456W",
        "author": "Örnek Yazar",
        "first_publish_year": 1930,
        "edition_count": 2,
        "ratings_count": 3,
        "average_rating": 4.0,
        "isbn": "",
        "total_pages": 100,
        "catalog_url": "https://openlibrary.org/works/OL123456W",
        "cover_url": "",
        "free_read_url": "",
        "free_read_available": False,
        "recommendation_reason": "Okuduğum kitabını okuduğun için Örnek Yazar'dan bir öneri.",
        "language": "Türkçe",
    }
    monkeypatch.setattr(
        application, "recommend_from_reading",
        lambda books, sort, limit=18: [sample],
    )
    monkeypatch.setattr(application, "localize_turkish_editions", lambda books: books)
    response = client.get("/discover")
    assert response.status_code == 200
    assert "Okuduğum kitabını okuduğun için" in response.get_data(as_text=True)


def test_book_detail_shows_verified_free_read_link(client, monkeypatch):
    import application

    authenticated(client)
    book_id = db.add_book({"title": "Açık Kitap", "author": "Yazar", "total_pages": 100})
    monkeypatch.setattr(
        application,
        "find_free_reading",
        lambda title, author, isbn: {
            "free_read_url": "https://archive.org/details/publicbook",
        },
    )
    response = client.get(f"/books/{book_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Türkçe ücretsiz ve yasal tam metni oku" in html
    assert "https://archive.org/details/publicbook" in html


def test_book_progress_rejects_invalid_and_decreasing_pages(client):
    authenticated(client)
    book_id = db.add_book({"title": "Deneme", "total_pages": 200})
    response = client.post(f"/books/{book_id}/reading", data={"page": "201"})
    assert response.status_code == 302
    assert db.get_book(book_id)["current_page"] == 0
    client.post(f"/books/{book_id}/reading", data={"page": "80"})
    client.post(f"/books/{book_id}/reading", data={"page": "79"})
    assert db.get_book(book_id)["current_page"] == 80
    assert db.get_book(book_id)["shelf"] == "Okunuyor"


def test_reading_session_records_date_duration_and_note(client):
    authenticated(client)
    book_id = db.add_book({"title": "Günlük", "total_pages": 200})
    response = client.post(
        f"/books/{book_id}/reading",
        data={
            "page": "45",
            "read_date": "2026-11-20",
            "minutes": "35",
            "note": "Güzel bir bölüm.",
        },
    )
    assert response.status_code == 302
    entry = db.get_readings(book_id)[0]
    assert entry["page"] == 45
    assert entry["read_date"] == "2026-11-20"
    assert entry["minutes"] == 35
    assert entry["note"] == "Güzel bir bölüm."


def test_backdated_reading_keeps_latest_progress_and_enforces_page_order(client):
    authenticated(client)
    book_id = db.add_book({"title": "Tarihli", "total_pages": 200})
    client.post(
        f"/books/{book_id}/reading",
        data={"page": "80", "read_date": "2026-11-22"},
    )
    client.post(
        f"/books/{book_id}/reading",
        data={"page": "40", "read_date": "2026-11-20"},
    )
    assert db.get_book(book_id)["current_page"] == 80
    entries = db.get_readings(book_id)
    assert [entry["page"] for entry in entries] == [40, 80]
    client.post(
        f"/books/{book_id}/reading",
        data={"page": "90", "read_date": "2026-11-20"},
    )
    assert db.get_book(book_id)["current_page"] == 80
    assert [entry["page"] for entry in db.get_readings(book_id)] == [40, 80]


def test_book_detail_edit_and_delete_work(client):
    authenticated(client)
    book_id = db.add_book({"title": "Düzenle", "author": "Yazar", "total_pages": 100})
    detail = client.get(f"/books/{book_id}")
    assert detail.status_code == 200
    assert "Okuma geçmişi" in detail.get_data(as_text=True)
    response = client.post(
        f"/books/{book_id}/edit",
        data={"title": "Düzenlendi", "author": "Yeni yazar", "total_pages": "120"},
    )
    assert response.status_code == 302
    assert db.get_book(book_id)["title"] == "Düzenlendi"
    client.post(
        f"/books/{book_id}/reading",
        data={"page": "20", "read_date": "2026-11-24", "minutes": "10", "note": "Not"},
    )
    history = db.get_readings(book_id)
    response = client.post(
        f"/books/{book_id}/reading/{history[0]['id']}/delete"
    )
    assert response.status_code == 302
    assert db.get_readings(book_id) == []
    client.post(f"/books/{book_id}/delete")
    assert db.get_book(book_id) is None


def test_extending_completed_book_reopens_it(client):
    authenticated(client)
    book_id = db.add_book(
        {
            "title": "Yeniden okumalık",
            "total_pages": 100,
            "current_page": 100,
            "shelf": "Okundu",
            "finished_at": "2026-01-01",
        }
    )
    response = client.post(
        f"/books/{book_id}/edit",
        data={"title": "Yeniden okumalık", "total_pages": "120"},
    )
    assert response.status_code == 302
    book = db.get_book(book_id)
    assert book["shelf"] == "Okunuyor"
    assert book["finished_at"] is None


def test_existing_reading_database_is_migrated_without_losing_sessions(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE reading_logs (
                id INTEGER PRIMARY KEY,
                book_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                read_date TEXT NOT NULL,
                logged_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO reading_logs(book_id, page, read_date, logged_at) "
            "VALUES (9, 25, '2026-11-20', '2026-11-20T12:00:00')"
        )
    db.init_db()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(reading_logs)")}
        old_session = connection.execute(
            "SELECT page, minutes, note FROM reading_logs WHERE book_id = 9"
        ).fetchone()
    assert {"minutes", "note"} <= columns
    assert old_session == (25, 0, "")


def test_library_search_and_sort(client):
    authenticated(client)
    db.add_book({"title": "Zebra", "author": "Ayşe", "total_pages": 100})
    db.add_book({"title": "Alfa", "author": "Zeynep", "total_pages": 100})
    assert [book["title"] for book in db.get_books(shelf="Okunacak", sort="title")] == [
        "Alfa", "Zebra"
    ]
    response = client.get("/library?shelf=Okunacak&q=ayşe")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Zebra" in html
    assert "Alfa" not in html


def test_finishing_book_moves_it_to_read_shelf(client):
    authenticated(client)
    book_id = db.add_book({"title": "Biten Kitap", "total_pages": 20})
    client.post(f"/books/{book_id}/reading", data={"page": "20"})
    book = db.get_book(book_id)
    assert book["shelf"] == "Okundu"
    assert book["finished_at"]


def test_duplicate_book_is_rejected(client):
    db.add_book({"title": "Aynı Kitap", "author": "Yazar", "total_pages": 100})
    with pytest.raises(ValueError, match="zaten kayıtlı"):
        db.add_book({"title": "Aynı Kitap", "author": "Yazar", "total_pages": 100})


def test_estimated_completion_uses_recent_reading_speed():
    history = [(date(2026, 11, 20), 30), (date(2026, 11, 24), 70)]
    assert estimate_days_to_finish(170, 70, history, date(2026, 11, 24)) == 10
    assert estimate_days_to_finish(70, 70, history, date(2026, 11, 24)) == 0
    assert estimate_days_to_finish(170, 70, [(date(2026, 11, 24), 70)], date(2026, 11, 24)) is None


@pytest.mark.parametrize(
    ("completed", "goal", "expected"),
    [
        (9, 24, "Bu yıl 9/24, hedefinin 15 kitap gerisindesin."),
        (24, 24, "Bu yıl 24/24, yıllık hedefini tamamladın!"),
        (25, 24, "Bu yıl 25/24, hedefini 1 kitap aştın!"),
    ],
)
def test_annual_goal_status(completed, goal, expected):
    assert annual_goal_status(completed, goal) == expected


def test_manual_book_add_requires_positive_page_count(client):
    authenticated(client)
    response = client.post(
        "/books/add",
        data={"title": "Sayfasız", "total_pages": "0", "shelf": "Okunacak"},
    )
    assert response.status_code == 302
    assert db.get_books() == []
