# Kitap Takip

Okuduğun kitapları, sayfa ilerlemeni ve yıllık okuma hedefini takip et.

## Yeni özellikler

- **Bugün panosu:** Günün özeti, okumaya devam ettiğin kitap, haftalık görevler, günlük okuma molası, son oturumlar ve sana özel günlük not.
- **Rozet koleksiyonu:** İlk oturum, 100/1.000 sayfa, tamamlanan kitap, okuma serisi ve toplam okuma süresi kilometre taşları.
- **Keşfet:** Okuduğun Türkçe kitapların yazarlarından öneriler; baskı kayıtlarına, yayın yılına ve okur puanı sayısına göre sıralama.
- **Yasal ücretsiz okuma:** Tam metin erişimi Open Library tarafından “public”/kamuya açık olarak işaretlenmiş Türkçe eserlerde doğrudan Archive.org okuma bağlantısı. Ödünç alınabilen kitaplar ücretsiz tam metin gibi etiketlenmez.
- Kitapyurdu, Open Library katalog ve varsa doğrulanmış ücretsiz okuma bağlantıları kitap arama ve detay ekranlarında görünür.
- Kitaplık sekmelerinde kitap adı, yazar veya ISBN ile arama; ada, yazara, ilerlemeye, puana ya da eklenme zamanına göre sıralama.
- Her kitap için ayrı detay sayfası: kitap bilgileri, ilerleme, puan ve kişisel not.
- Tarih, okunan son sayfa, dakika ve kısa not içeren okuma oturumları; eski oturumları görüntüleme ve tek tek silme.
- Hatalı bir oturum silinirse okuma ilerlemesi geçmişteki son kayıttan yeniden hesaplanır.
- İstatistiklerde yıllık kitap hedefi, aylık sayfa hedefi, aylık grafik, son 90 günlük okuma takvimi, toplam sayfa/süre ve okuma serisi.
- Mevcut SQLite veritabanı açılışta yeni oturum alanlarına yükseltilir; kitap ve geçmiş kayıtların korunur.

Giriş yaptıktan sonra **Bugün** panosu açılır. Kitap detayına ulaşmak için kitaplığında kitap başlığına veya **Detaylar ve okuma geçmişi** bağlantısına tıkla. Yeni okuma girişi için tarih, okunan son sayfa ve istersen süre/not gir. İstatistik sayfasından yıllık kitap, aylık/haftalık sayfa ve günlük dakika hedeflerini kendine göre ayarla; pano görevlerini bu hedeflere göre günceller.

Üst menüdeki **Keşfet** sayfası tamamladığın kitapların yazarlarına göre Türkçe öneriler sunar; arama kutusuyla katalogda başka kitapları da arayabilirsin. “Baskı kayıtları” Open Library kataloğundaki eser/baskı sayısıdır, baskı adedi veya tiraj değildir. Satış adetleri açık bir kaynaktan alınamadığı için satış sıralaması sunulmaz; “okur puanı” sıralaması yalnızca platformdaki puan sayısını popülerlik göstergesi olarak kullanır. Katalog verileri internet bağlantısı gerektirir.

## Windows'ta çalıştırma

İlk kurulumda şu adımları bir kez yap:

1. Bilgisayarında Python 3.11 veya daha yeni bir sürüm yüklü olsun. Yüklü değilse [python.org/downloads](https://www.python.org/downloads/) adresinden indirip kur. Kurulum ekranında **Add Python to PATH** seçeneğini işaretle.
2. Bu proje klasörünü VS Code'da aç.
3. VS Code menüsünden **Terminal → New Terminal** seç. Açılan terminalin proje klasöründe olduğuna emin ol; satırın sonunda `kitaptakip` klasör adı görünmeli.
4. Aşağıdaki komutları terminale **tek tek** yapıştırıp her birinden sonra Enter'a bas:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   Kurulum birkaç dakika sürebilir. Başarılı olduğunda terminalde hata yerine `Successfully installed ...` mesajlarını görürsün.

Uygulamayı her açışında:

1. VS Code'da **Terminal → New Terminal** seç.
2. Şu komutu çalıştır:

   ```powershell
   .\.venv\Scripts\python.exe application.py
   ```

3. Tarayıcıda [http://127.0.0.1:5000](http://127.0.0.1:5000) adresini aç.
4. Giriş bilgileri: kullanıcı adı `test`, parola `123`.

Uygulamayı kapatmak için terminale dönüp **Ctrl+C** tuşlarına bas. Terminal penceresini kapatmak da sunucuyu durdurur. Sonraki sefer yalnızca uygulamayı başlatma adımlarını tekrarla; bağımlılıkları tekrar kurmana gerek yok.

Kitap veritabanı `data/kitap.db`, kapak görselleri `static/kapaklar/` klasöründe saklanır. Bu klasörleri silme; silersen kayıtların veya kapakların kaybolur.

## Docker ile çalıştırma (isteğe bağlı)

Bu yöntem için Docker Desktop kurulu ve çalışır durumda olmalıdır. Docker Desktop yoksa yukarıdaki Windows adımlarını kullan; Docker kurmak zorunlu değildir.

1. Docker Desktop'ı kurup aç.
2. VS Code'da proje klasörünü aç ve **Terminal → New Terminal** seç.
3. Şunu çalıştır:

   ```powershell
   docker compose up -d --build
   ```

4. Tarayıcıda [http://localhost:5010](http://localhost:5010) adresini aç. Giriş bilgileri yine `test` / `123`.

Container'ı durdurmak için terminalde şu komutu çalıştır:

```powershell
docker compose down
```

Docker kullanmıyorsan bu bölümü atlayabilirsin.

## Testleri çalıştırma (isteğe bağlı)

VS Code terminalinde şu komutu çalıştır:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
