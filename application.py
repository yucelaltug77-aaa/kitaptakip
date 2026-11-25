import os
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, flash, redirect, render_template, request, session, url_for
import requests

from catalog import (
    catalog_search_url,
    find_free_reading,
    kitapyurdu_search_url,
    localize_turkish_editions,
    recommend_from_reading,
    search_turkish_books,
    sort_catalog,
    verify_free_reading_links,
)
from db import (
    add_book,
    delete_book,
    delete_last_reading,
    delete_reading,
    get_book,
    get_books,
    get_readings,
    get_setting,
    init_db,
    log_reading,
    save_rating,
    set_setting,
    update_shelf,
    update_book,
)
from scraper import search_books

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-development-key-change-me")
app.config["TIMEZONE"] = ZoneInfo("Europe/Istanbul")
init_db()


def local_today():
    return datetime.now(app.config["TIMEZONE"]).date()


def estimate_days_to_finish(total_pages, current_page, reading_history, today=None):
    remaining = max(0, total_pages - current_page)
    if not remaining:
        return 0
    today = today or local_today()
    cutoff = today - timedelta(days=6)
    recent = []
    for logged_on, page in reading_history:
        if isinstance(logged_on, str):
            logged_on = date.fromisoformat(logged_on[:10])
        if logged_on >= cutoff:
            recent.append((logged_on, page))
    earlier = [
        (date.fromisoformat(logged_on[:10]) if isinstance(logged_on, str) else logged_on, page)
        for logged_on, page in reading_history
        if (date.fromisoformat(logged_on[:10]) if isinstance(logged_on, str) else logged_on) < cutoff
    ]
    if earlier:
        recent.insert(0, earlier[-1])
    if len(recent) < 2:
        return None
    recent.sort(key=lambda entry: entry[0])
    pages_read = recent[-1][1] - recent[0][1]
    elapsed_days = max(1, (recent[-1][0] - recent[0][0]).days)
    if pages_read <= 0:
        return None
    return max(1, (remaining * elapsed_days + pages_read - 1) // pages_read)


def annual_goal_status(completed, goal):
    difference = goal - completed
    if difference > 0:
        return f"Bu yıl {completed}/{goal}, hedefinin {difference} kitap gerisindesin."
    if difference < 0:
        return f"Bu yıl {completed}/{goal}, hedefini {-difference} kitap aştın!"
    return f"Bu yıl {completed}/{goal}, yıllık hedefini tamamladın!"


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "test" and request.form.get("password") == "123":
            session.clear()
            session["logged_in"] = True
            destination = request.args.get("next", "")
            if not destination.startswith("/") or destination.startswith("//"):
                destination = url_for("dashboard")
            return redirect(destination)
        flash("Kullanıcı adı veya parola hatalı.", "danger")
    return render_template("login.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def reading_streak(reading_dates, today):
    streak = 0
    check_date = today if today in reading_dates else today - timedelta(days=1)
    while check_date in reading_dates:
        streak += 1
        check_date -= timedelta(days=1)
    return streak


def longest_reading_streak(reading_dates):
    longest = current = 0
    previous = None
    for reading_day in sorted(reading_dates):
        current = current + 1 if previous and reading_day == previous + timedelta(days=1) else 1
        longest = max(longest, current)
        previous = reading_day
    return longest


def build_achievements(books, sessions, longest_streak):
    completed = sum(book["shelf"] == "Okundu" for book in books)
    pages = sum(entry["pages_read"] for entry in sessions)
    minutes = sum(entry["minutes"] for entry in sessions)
    milestones = [
        ("first-session", "İlk adım", "İlk okuma oturumunu kaydettin.", "bi-book", len(sessions) >= 1),
        ("pages-100", "Yüzlük", "Toplam 100 sayfa okudun.", "bi-file-earmark-text", pages >= 100),
        ("pages-1000", "Sayfa avcısı", "Toplam 1.000 sayfayı tamamladın.", "bi-stack", pages >= 1000),
        ("book-1", "İlk bitiriş", "İlk kitabını bitirdin.", "bi-trophy", completed >= 1),
        ("book-5", "Kitap kurdu", "Beş kitabı tamamladın.", "bi-stars", completed >= 5),
        ("streak-3", "Ritim yakalandı", "Üç günlük okuma serisi yaptın.", "bi-fire", longest_streak >= 3),
        ("streak-7", "Haftalık ritim", "Yedi gün üst üste okudun.", "bi-lightning", longest_streak >= 7),
        ("minutes-300", "Zaman yolcusu", "Kitaplarla beş saat geçirdin.", "bi-hourglass-split", minutes >= 300),
    ]
    return [
        {"id": key, "title": title, "description": description, "icon": icon, "unlocked": unlocked}
        for key, title, description, icon, unlocked in milestones
    ]


@app.get("/")
@login_required
def dashboard():
    today = local_today()
    weekdays = (
        "Pazartesi", "Salı", "Çarşamba", "Perşembe",
        "Cuma", "Cumartesi", "Pazar",
    )
    months = (
        "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
    )
    today_label = f"{weekdays[today.weekday()]}, {today.day} {months[today.month - 1]} {today.year}"
    books = get_books()
    reading_books = [book for book in books if book["shelf"] == "Okunuyor"]
    all_sessions = []
    today_pages = 0
    today_minutes = 0
    week_pages = 0
    week_sessions = 0
    reading_dates = set()
    for book in books:
        previous_page = 0
        for entry in get_readings(book["id"]):
            entry_date = date.fromisoformat(entry["read_date"][:10])
            entry["pages_read"] = max(0, entry["page"] - previous_page)
            entry["book_title"] = book["title"]
            entry["book_id"] = book["id"]
            previous_page = entry["page"]
            all_sessions.append(entry)
            reading_dates.add(entry_date)
            if entry_date == today:
                today_pages += entry["pages_read"]
                today_minutes += entry["minutes"]
            if entry_date >= today - timedelta(days=today.weekday()):
                week_pages += entry["pages_read"]
                week_sessions += 1
    current_streak = reading_streak(reading_dates, today)
    weekly_goal = int(get_setting("weekly_page_goal", "100"))
    daily_goal = int(get_setting("daily_minute_goal", "20"))
    annual_goal = int(get_setting("annual_goal", "24"))
    books_completed = sum(
        book["shelf"] == "Okundu" and book["finished_at"]
        and date.fromisoformat(book["finished_at"][:10]).year == today.year
        for book in books
    )
    year_progress = min(100, books_completed * 100 // annual_goal)
    sessions_recent = sorted(
        all_sessions,
        key=lambda item: (item["read_date"], item["id"]),
        reverse=True,
    )[:5]
    weekly_progress = min(100, week_pages * 100 // weekly_goal)
    daily_progress = min(100, today_minutes * 100 // daily_goal)
    if reading_books:
        focus_book = max(
            reading_books,
            key=lambda book: (book["current_page"] / book["total_pages"], book["title"]),
        )
    else:
        focus_book = None
    quotes = [
        ("Bugün birkaç sayfa; yarın daha geniş bir dünya.", "Bugünün okuma notu"),
        ("Her kitap, kendine açtığın yeni bir penceredir.", "Bugünün okuma notu"),
        ("Küçük bir okuma molası, güne güzel bir iz bırakır.", "Bugünün okuma notu"),
        ("Bir sonraki sayfada ne olduğunu yalnızca okuyarak öğrenirsin.", "Bugünün okuma notu"),
        ("Okumak için doğru an, ayırdığın o birkaç dakikadır.", "Bugünün okuma notu"),
        ("Her biten bölüm, başladığın yolculuğun yeni bir durağıdır.", "Bugünün okuma notu"),
        ("Bugün okuduğun bir sayfa bile yarına eşlik eder.", "Bugünün okuma notu"),
    ]
    quote, quote_author = quotes[today.toordinal() % len(quotes)]
    current_hour = datetime.now(app.config["TIMEZONE"]).hour
    greeting = "Günaydın" if current_hour < 12 else (
        "İyi günler" if current_hour < 18 else "İyi akşamlar"
    )
    achievements = build_achievements(
        books, all_sessions, longest_reading_streak(reading_dates)
    )
    return render_template(
        "dashboard.html", today=today, today_label=today_label, greeting=greeting, books=books,
        reading_books=reading_books, focus_book=focus_book, today_pages=today_pages,
        today_minutes=today_minutes, weekly_goal=weekly_goal, daily_goal=daily_goal,
        week_pages=week_pages, week_sessions=week_sessions,
        weekly_progress=weekly_progress, daily_progress=daily_progress,
        current_streak=current_streak, annual_goal=annual_goal,
        books_completed=books_completed, year_progress=year_progress,
        recent_sessions=sessions_recent, achievements=achievements,
        unlocked_count=sum(item["unlocked"] for item in achievements),
        quote=quote, quote_author=quote_author,
    )


@app.get("/library")
@login_required
def library():
    shelf = request.args.get("shelf", "Okunuyor")
    if shelf not in ("Okunacak", "Okunuyor", "Okundu"):
        shelf = "Okunuyor"
    query = request.args.get("q", "").strip()[:100]
    sort = request.args.get("sort", "recent")
    if sort not in ("recent", "title", "author", "progress", "rating"):
        sort = "recent"
    shelf_counts = {
        name: len(get_books(shelf=name))
        for name in ("Okunacak", "Okunuyor", "Okundu")
    }
    books = get_books(shelf=shelf, query=query, sort=sort)
    for book in books:
        history = get_readings(book["id"])
        book["estimate_days"] = estimate_days_to_finish(
            book["total_pages"], book["current_page"],
            [(entry["read_date"], entry["page"]) for entry in history],
        )
        book["last_reading_id"] = history[-1]["id"] if history else None
    return render_template(
        "library.html", books=books, active_shelf=shelf, shelf_counts=shelf_counts,
        query=query, sort=sort,
    )


@app.get("/discover")
@login_required
def discover():
    query = request.args.get("q", "").strip()[:120]
    sort_by = request.args.get("sort", "editions")
    if sort_by not in ("editions", "year", "popularity"):
        sort_by = "editions"
    books = get_books()
    recommendations = []
    unavailable = False
    try:
        if query:
            recommendations = search_turkish_books(query, sort_by)[:12]
        else:
            recommendations = localize_turkish_editions(
                recommend_from_reading(books, sort_by, limit=12)
            )
            recommendations = sort_catalog(recommendations, sort_by)
        owned_titles = {
            " ".join((book["title"] or "").casefold().split()) for book in books
        }
        recommendations = [
            book for book in recommendations
            if " ".join(book["title"].casefold().split()) not in owned_titles
        ]
    except (requests.RequestException, ValueError):
        logging.getLogger(__name__).exception("Open Library kitap kataloğu isteği başarısız")
        unavailable = True
        flash("Kitap kataloğuna şu an ulaşılamıyor. Biraz sonra yeniden deneyebilirsin.", "warning")
    if recommendations:
        try:
            verify_free_reading_links(recommendations)
        except (requests.RequestException, ValueError):
            logging.getLogger(__name__).exception(
                "Türkçe açık erişim bağlantıları doğrulanamadı"
            )
            flash(
                "Ücretsiz okuma bağlantıları doğrulanamadı; katalog önerileri yine kullanılabilir.",
                "warning",
            )
    return render_template(
        "discover.html", query=query, sort_by=sort_by,
        recommendations=recommendations, unavailable=unavailable,
        has_reading_history=bool(books),
    )


@app.get("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results = []
    unavailable = False
    if query:
        try:
            results = search_books(query)
            for book in results:
                book["catalog_url"] = catalog_search_url(
                    book.get("title", ""), book.get("author", "")
                )
        except Exception:
            app.logger.exception("Kitapyurdu araması başarısız oldu")
            unavailable = True
            flash("Şu an kitap aranamıyor, elle ekleyebilirsin.", "warning")
    return render_template("search.html", query=query, results=results, unavailable=unavailable)


@app.post("/books/add")
@login_required
def create_book():
    data = {
        "title": request.form.get("title", "").strip(),
        "author": request.form.get("author", "").strip(),
        "publisher": request.form.get("publisher", "").strip(),
        "cover_url": request.form.get("cover_url", "").strip(),
        "source_url": request.form.get("source_url", "").strip(),
        "isbn": request.form.get("isbn", "").strip(),
        "publication_year": request.form.get("publication_year", "").strip(),
        "total_pages": request.form.get("total_pages", "").strip(),
        "shelf": request.form.get("shelf", "Okunacak"),
    }
    if not data["title"]:
        flash("Kitap adı zorunludur.", "danger")
        return redirect(request.referrer or url_for("library"))
    try:
        pages = int(data["total_pages"])
        if pages <= 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Sayfa sayısı sıfırdan büyük bir tam sayı olmalıdır.", "danger")
        return redirect(request.referrer or url_for("library"))
    if data["shelf"] not in ("Okunacak", "Okunuyor", "Okundu"):
        data["shelf"] = "Okunacak"
    data["total_pages"] = pages
    try:
        add_book(data)
    except ValueError as error:
        flash(str(error), "warning")
        return redirect(request.referrer or url_for("library"))
    flash("Kitap kitaplığına eklendi.", "success")
    return redirect(url_for("library", shelf=data["shelf"]))


@app.post("/books/<int:book_id>/reading")
@login_required
def add_reading(book_id):
    book = get_book(book_id)
    if not book:
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    try:
        page = int(request.form.get("page", ""))
    except ValueError:
        flash("Geçerli bir sayfa numarası gir.", "danger")
        return redirect(url_for("library", shelf=book["shelf"]))
    if page <= 0 or page > book["total_pages"]:
        flash(f"Sayfa numarası 1 ile {book['total_pages']} arasında olmalıdır.", "danger")
        return redirect(url_for("library", shelf=book["shelf"]))
    history = get_readings(book_id)
    read_date = request.form.get("read_date", local_today().isoformat())
    try:
        reading_day = date.fromisoformat(read_date)
    except ValueError:
        flash("Geçerli bir okuma tarihi seç.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))
    if reading_day > local_today():
        flash("Okuma tarihi gelecek bir gün olamaz.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))
    prior = [entry for entry in history if entry["read_date"] <= read_date]
    later = [entry for entry in history if entry["read_date"] > read_date]
    previous_page = prior[-1]["page"] if prior else 0
    next_page = later[0]["page"] if later else book["total_pages"]
    if page < previous_page or page > next_page:
        flash("Okunan sayfa önceki ve sonraki kayıtlarla tutarlı olmalıdır.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))
    try:
        minutes = int(request.form.get("minutes", "0") or 0)
        if not 0 <= minutes <= 1440:
            raise ValueError
    except ValueError:
        flash("Okuma süresi 0 ile 1440 dakika arasında olmalıdır.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))
    note = request.form.get("note", "").strip()
    if len(note) > 500:
        flash("Oturum notu en fazla 500 karakter olabilir.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))
    log_reading(book_id, page, read_date, minutes, note)
    latest = get_readings(book_id)[-1]
    current_page = latest["page"]
    if current_page >= book["total_pages"]:
        update_shelf(
            book_id, "Okundu",
            started_at=read_date if not book["started_at"] else None,
            finished_at=latest["read_date"],
        )
        flash("Tebrikler, kitabı bitirdin!", "success")
    elif book["shelf"] != "Okunuyor" and page > 0:
        update_shelf(
            book_id, "Okunuyor",
            started_at=read_date if not book["started_at"] else None,
            finished_at="",
        )
        flash("Okuma ilerlemen kaydedildi.", "success")
    else:
        flash("Okuma ilerlemen kaydedildi.", "success")
    return redirect(url_for("book_detail", book_id=book_id))


@app.post("/books/<int:book_id>/reading/delete")
@login_required
def remove_last_reading(book_id):
    book = get_book(book_id)
    if book:
        delete_last_reading(book_id)
        flash("Son sayfa kaydı silindi.", "success")
        return redirect(url_for("book_detail", book_id=book_id))
    flash("Kitap bulunamadı.", "danger")
    return redirect(url_for("library"))


@app.post("/books/<int:book_id>/reading/<int:reading_id>/delete")
@login_required
def remove_reading(book_id, reading_id):
    if not get_book(book_id):
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    delete_reading(reading_id, book_id)
    flash("Okuma oturumu silindi.", "success")
    return redirect(url_for("book_detail", book_id=book_id))


@app.get("/books/<int:book_id>")
@login_required
def book_detail(book_id):
    book = get_book(book_id)
    if not book:
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    history = get_readings(book_id)
    sessions = []
    previous_page = 0
    for entry in history:
        entry["pages_read"] = max(0, entry["page"] - previous_page)
        previous_page = entry["page"]
    sessions = list(reversed(history))
    estimate = estimate_days_to_finish(
        book["total_pages"], book["current_page"],
        [(entry["read_date"], entry["page"]) for entry in history],
    )
    catalog_url = catalog_search_url(book["title"], book["author"])
    shop_url = kitapyurdu_search_url(book["title"], book["author"])
    free_reading = None
    try:
        free_reading = find_free_reading(book["title"], book["author"], book["isbn"])
    except (requests.RequestException, ValueError):
        logging.getLogger(__name__).exception(
            "Kitap için yasal ücretsiz tam metin aranamadı: %s", book["id"]
        )
        flash("Ücretsiz okuma kaynağı şu an doğrulanamadı; katalog bağlantısı kullanılabilir.", "warning")
    return render_template(
        "book_detail.html", book=book, sessions=sessions, estimate=estimate,
        today=local_today().isoformat(), catalog_url=catalog_url,
        free_reading=free_reading, shop_url=shop_url,
    )


@app.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@login_required
def edit_book(book_id):
    book = get_book(book_id)
    if not book:
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        try:
            total_pages = int(request.form.get("total_pages", ""))
            if not title or total_pages <= 0 or total_pages < book["current_page"]:
                raise ValueError
        except ValueError:
            flash(
                f"Kitap adı gerekli; sayfa sayısı 1 veya daha fazla ve mevcut ilerlemeden "
                f"({book['current_page']}) az olamaz.",
                "danger",
            )
            return render_template("edit_book.html", book={**book, **request.form})
        data = {
            "title": title, "author": request.form.get("author", "").strip(),
            "publisher": request.form.get("publisher", "").strip(),
            "isbn": request.form.get("isbn", "").strip(),
            "publication_year": request.form.get("publication_year", "").strip(),
            "total_pages": total_pages,
            "source_url": request.form.get("source_url", "").strip(),
            "cover_url": request.form.get("cover_url", "").strip(),
        }
        try:
            update_book(book_id, data)
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("edit_book.html", book={**book, **data})
        flash("Kitap bilgileri güncellendi.", "success")
        return redirect(url_for("book_detail", book_id=book_id))
    return render_template("edit_book.html", book=book)


@app.post("/books/<int:book_id>/delete")
@login_required
def remove_book(book_id):
    if not get_book(book_id):
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    delete_book(book_id)
    flash("Kitap ve okuma geçmişi silindi.", "success")
    return redirect(url_for("library"))


@app.post("/books/<int:book_id>/shelf")
@login_required
def change_shelf(book_id):
    shelf = request.form.get("shelf", "")
    if shelf not in ("Okunacak", "Okunuyor", "Okundu"):
        flash("Geçersiz raf seçimi.", "danger")
        return redirect(url_for("library"))
    book = get_book(book_id)
    if not book:
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    update_shelf(
        book_id, shelf,
        started_at=local_today().isoformat() if shelf == "Okunuyor" and not book["started_at"] else None,
        finished_at=local_today().isoformat() if shelf == "Okundu" else ("" if shelf != "Okundu" else None),
    )
    flash("Kitap rafı güncellendi.", "success")
    return redirect(url_for("library", shelf=shelf))


@app.post("/books/<int:book_id>/rating")
@login_required
def rate_book(book_id):
    book = get_book(book_id)
    if not book:
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    try:
        rating = int(request.form.get("rating", "0"))
        if rating not in range(0, 6):
            raise ValueError
    except ValueError:
        flash("Puan 0 ile 5 arasında olmalıdır.", "danger")
        return redirect(url_for("library", shelf=book["shelf"]))
    save_rating(book_id, rating or None, request.form.get("note", "").strip()[:1000])
    flash("Puan ve not kaydedildi.", "success")
    return redirect(url_for("library", shelf=book["shelf"]))


@app.route("/stats", methods=["GET", "POST"])
@login_required
def stats():
    if request.method == "POST":
        goal_type = request.form.get("goal_type")
        if goal_type in ("monthly_pages", "weekly_pages", "daily_minutes"):
            try:
                field, minimum, maximum = {
                    "monthly_pages": ("monthly_page_goal", 1, 100000),
                    "weekly_pages": ("weekly_page_goal", 1, 100000),
                    "daily_minutes": ("daily_minute_goal", 1, 1440),
                }[goal_type]
                goal = int(request.form.get(field, ""))
                if goal < minimum or goal > maximum:
                    raise ValueError
            except ValueError:
                flash("Hedef değeri izin verilen aralıkta olmalıdır.", "danger")
                return redirect(url_for("stats"))
            setting_key = {
                "monthly_pages": "monthly_page_goal",
                "weekly_pages": "weekly_page_goal",
                "daily_minutes": "daily_minute_goal",
            }[goal_type]
            set_setting(setting_key, str(goal))
            flash("Okuma hedefi güncellendi.", "success")
            return redirect(url_for("stats", _anchor="hedef"))
        try:
            goal = int(request.form.get("annual_goal", ""))
            if goal < 1 or goal > 1000:
                raise ValueError
        except ValueError:
            flash("Yıllık hedef 1 ile 1000 arasında olmalıdır.", "danger")
            return redirect(url_for("stats"))
        set_setting("annual_goal", str(goal))
        flash("Yıllık hedef güncellendi.", "success")
        return redirect(url_for("stats"))
    now = local_today()
    books = get_books()
    completed = sum(
        1 for book in books
        if book["shelf"] == "Okundu" and book["finished_at"]
        and date.fromisoformat(book["finished_at"][:10]).year == now.year
    )
    goal = int(get_setting("annual_goal", "24"))
    monthly = {month: 0 for month in range(1, 13)}
    year_pages = 0
    year_minutes = 0
    year_sessions = 0
    activity = {}
    for book in books:
        previous = 0
        for entry in get_readings(book["id"]):
            current = entry["page"]
            logged_date = date.fromisoformat(entry["read_date"][:10])
            pages_read = max(0, current - previous)
            activity[logged_date] = activity.get(logged_date, 0) + pages_read
            if logged_date.year == now.year:
                monthly[logged_date.month] += pages_read
                year_pages += pages_read
                year_minutes += entry["minutes"]
                year_sessions += 1
            previous = current
    reading_dates = {
        date.fromisoformat(entry["read_date"][:10])
        for book in books for entry in get_readings(book["id"])
    }
    streak = 0
    check_date = now if now in reading_dates else now - timedelta(days=1)
    while check_date in reading_dates:
        streak += 1
        check_date -= timedelta(days=1)
    max_streak = current_streak = 0
    previous_day = None
    for reading_day in sorted(reading_dates):
        current_streak = (
            current_streak + 1
            if previous_day and reading_day == previous_day + timedelta(days=1)
            else 1
        )
        max_streak = max(max_streak, current_streak)
        previous_day = reading_day
    monthly_goal = int(get_setting("monthly_page_goal", "120"))
    weekly_goal = int(get_setting("weekly_page_goal", "100"))
    daily_goal = int(get_setting("daily_minute_goal", "20"))
    month_pages = monthly[now.month]
    calendar = []
    for offset in range(89, -1, -1):
        day = now - timedelta(days=offset)
        calendar.append({"date": day.isoformat(), "pages": activity.get(day, 0)})
    return render_template(
        "stats.html", completed=completed, goal=goal,
        goal_status=annual_goal_status(completed, goal),
        monthly_pages=[monthly[month] for month in range(1, 13)],
        streak=streak, max_streak=max_streak, year_pages=year_pages,
        year_minutes=year_minutes, year_sessions=year_sessions,
        monthly_goal=monthly_goal, month_pages=month_pages,
        month_goal_percent=min(100, month_pages * 100 // monthly_goal),
        weekly_goal=weekly_goal, daily_goal=daily_goal, calendar=calendar,
    )


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
