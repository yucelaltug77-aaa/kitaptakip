# Proje: Kitap Okuma Takibi (kitaptakip)
Okuduğum kitapları, ilerlememi ve yıllık hedefimi takip eden web uygulaması. Kitaplar Kitapyurdu'ndan canlı çekilir.

## Login
- Tek kullanıcı: `test` / `123` (koda sabit). Girişsiz hiçbir sayfa açılmaz.

## Kitap kaynağı (requests + BeautifulSoup)
- Arama: `https://www.kitapyurdu.com/index.php?route=product/search&filter_name=<kelime>`
- Kitap adı, yazar veya ISBN ile aranır.
- Sonuçtan: ad, yazar, yayınevi, kapak, link. Detay sayfasından: sayfa sayısı, ISBN, yayın yılı.
- Seçiciler: arama kartı `.ky-product`, ad+link `a.ky-product-title`, yazar `.ky-product-author a`, yayınevi `.ky-product-publisher a`, kapak `a.ky-product-cover img`. Detayda `.ky-pd-attributes__item` satırları ("Sayfa Sayısı:", "ISBN:").
- SSL hatası için `truststore` kullanılır: modül yüklenirken bir kez `truststore.inject_into_ssl()` çağrılır. `session.verify`'a SSLContext **verilmez** (requests sadece bool/dosya yolu kabul eder, TypeError verir).
- İsteklerde tarayıcı `User-Agent` başlığı gönderilir; yoksa Kitapyurdu 403 döner.
- Scraper'ı doğrularken düz `requests` ile değil, uygulamanın kendi fonksiyonlarıyla uçtan uca dene (arama → detay → kayıt → kapak dosyası).
- İsteklerde 5 sn zaman aşımı.
- Akış: kullanıcı navbar'dan arama yapar → sonuçlar listelenir → istediği kitabı Okunacak, Okunuyor veya Okundu rafına ekler.
- Kapak `static/kapaklar/` içine indirilir, kitap SQLite'a kaydedilir; kayıtlı kitap için siteye tekrar gidilmez.
- Sayfa sayısı veya kapak gelmezse kullanıcı elle girer; kapak yoksa varsayılan görsel gösterilir.
- Sonuç yoksa: "Kitap bulunamadı, elle ekleyebilirsin". Site yanıt vermezse: "Şu an kitap aranamıyor, elle ekleyebilirsin". İkisinde de elle ekleme formu çıkar.

## Özellikler
- Raflar: Okunacak, Okunuyor, Okundu. İlk sayfa girişinde Okunuyor'a, son sayfada Okundu'ya otomatik geçer ve bitiş tarihi yazılır; elle de değişir.
- Kitap kartı: kapak, ad, yazar, ilerleme çubuğu, "Kitapyurdu'nda gör" linki.
- "Bugün okudum": kalınan sayfa girilir. Son kayıt silinebilir.
- 1-5 yıldız puan ve kısa not.
- Bitiş tahmini: son 7 günün hızına göre "Bu hızla X günde bitirirsin".
- İstatistik: yıllık hedef (ayarlardan, varsayılan 24) ve durum ("Bu yıl 9/24, hedefin 2 kitap gerisindesin"), aylık okunan sayfa grafiği, okuma serisi.

## Kurallar
- Sayfa sayısı > 0. Okunan sayfa ≤ toplam sayfa ve ≥ önceki kayıt.
- Aynı kitap iki kez eklenemez.

## Teknik
- Python + Flask + SQLite. Giriş dosyası application.py, nesne `app`.
- Dosyalar: application.py, scraper.py, db.py, templates/, static/style.css, tests/.
- Bootstrap 5, Bootstrap Icons, Chart.js (CDN). Mobil uyumlu.
- Saat dilimi Europe/Istanbul. SECRET_KEY ortam değişkeninden okunur.
- Testler (pytest): sayfa kuralları, bitiş tahmini, yıllık hedef.
- SQLite dosyası `data/kitap.db` (Docker volume'u bu klasör); tablolar açılışta `CREATE TABLE IF NOT EXISTS` ile kurulur.
- requirements.txt: flask, requests, beautifulsoup4, truststore, gunicorn, pytest

## Tasarım (tek static/style.css)
- Açık tema. Ana renk #EC691F (hover #CA5516), sayfa zemini #f0f2f5, metin #1e293b.
- Raf rozetleri: Okunacak gri, Okunuyor turuncu, Okundu yeşil. Yıldız sarı.
- Kartlar beyaz, köşe yuvarlak (12px), hafif gölge.
- Navbar: solda "📚 Kitap Takip", ortada arama kutusu, sağda Kitaplık · İstatistik · Ayarlar · Çıkış.
- Arama sonuçları: kart ızgarası; her kartta kapak, ad, yazar ve Okunacak / Okunuyor / Okundu butonları.
- Kitaplık: raf sekmeleri, kart ızgarası (masaüstü 4, tablet 2, mobil 1 sütun).
- Login: ortada tek kart, turuncu "Giriş" butonu.

## Docker (aynen oluşturulur)
Dockerfile:
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 kitaptakipappuser && chown -R kitaptakipappuser:kitaptakipappuser /app && sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:5010", "--workers", "2", "--timeout", "60", "application:app"]
```
entrypoint.sh:
```sh
#!/bin/sh
set -e
mkdir -p /app/data /app/static/kapaklar
chown -R kitaptakipappuser:kitaptakipappuser /app/data /app/static/kapaklar
exec gosu kitaptakipappuser "$@"
```
docker-compose.yml:
```yaml
services:
  kitaptakip:
    build: .
    container_name: kitaptakip
    restart: unless-stopped
    ports: ["5010:5010"]
    environment:
      - TZ=Europe/Istanbul
      - SECRET_KEY=degistir-beni
    volumes:
      - kitaptakip_data:/app/data
      - kitaptakip_kapaklar:/app/static/kapaklar
volumes:
  kitaptakip_data:
  kitaptakip_kapaklar:
```
.dockerignore (her biri ayrı satır): `.git/ .venv/ __pycache__/ *.pyc tests/ data/ static/kapaklar/`
.gitattributes: `*.sh text eol=lf` (entrypoint.sh CRLF olursa container açılmaz)

## Çalışma şekli
- Önce mimariyi kısaca yaz, onayımı al, sonra kodla.
- Bitirmeden önce: `.venv` kur, `pytest` çalıştır, uygulamayı açıp "suç ve ceza" arayarak bir kitap ekle. Sonra `docker compose up -d --build` ile container'ı kaldır, http://localhost:5010'da login'i ve aynı aramayı container içinde de dene. Neyi denediğini yaz.
- README kısa: kurulum ve `docker compose up -d --build` → http://localhost:5010
