# Kastamonu Üniversitesi ÜBYS Not Bildirim Botu (GitHub Actions + Telegram)

Kastamonu Üniversitesi Öğrenci Bilgi Sistemi'ne (`https://ubys.kastamonu.edu.tr`) sürekli girip çıkma zahmetini ortadan kaldıran, **7/24 bulutta (GitHub Actions)** ücretsiz çalışıp yeni bir **Vize, Final, Bütünleme, Kısa Sınav, Ödev, Geçme Notu veya Harf Notu (HBN)** girildiğinde ya da güncellendiğinde telefonunuza anlık **Telegram** bildirimi gönderen hafif ve kararlı otomasyon botu.

---

## Yenilikler ve Özellikler

- **Selenium/Tarayıcı Gerektirmez:** Eski Selenium + ChromeDriver + `iframe` tabanlı yaklaşım yerine doğrudan hafif HTTP istekleri (`httpx` + `BeautifulSoup`) kullanır. Tarayıcı çökmesi, bekleme süresi veya `iframe` hatası olmadan birkaç saniyede tamamlanır.
- **Public Repo + Gizli Gist Uyumu:** Notlarınızın durum kaydı asla bu açık (Public) repoya yazılmaz; doğrudan gizli (Secret) **GitHub Gist** içinde `grades_state.json` olarak tutulur (eski `notlar.json` ile çakışmaz).
- **Tam Not ve Detay Takibi:** Hem ana not tablosunu (`Class/Index`) hem de her dersin detay sayfasını (`ClassDetail`) tarayarak sınav puanı, sınıf ortalaması, sınıf sıralaması, ilan tarihi, geçme notu ve harf notu değişikliklerini yakalar.
- **Geriye Dönük Secret Desteği:** Mevcut `OGRENCI_NO`, `SIFRE`, `BOT_TOKEN`, `CHAT_ID`, `GIST_ID`, `GIST_TOKEN` secret isimleriyle doğrudan çalışır (yeni `UBYS_USERNAME`, `UBYS_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` isimlerini de destekler).
- **Akıllı Hata Yönetimi:** Giriş hatasında spam yapmadan tek seferlik uyarı gönderir; geçici ağ hatalarında art arda hata sayacını takip eder.

---

## Kurulum ve Etkinleştirme (GitHub Actions)

### 1. Mevcut Secret Bilgilerini Kontrol Etme

Reponuzda **Settings → Secrets and variables → Actions** altında aşağıdaki **Repository secrets** değerlerinin tanımlı olduğundan emin olun:

| Secret Adı (veya Alternatifi) | Açıklama |
| --- | --- |
| `OGRENCI_NO` (veya `UBYS_USERNAME`) | ÜBYS kullanıcı adınız (öğrenci numaranız) |
| `SIFRE` (veya `UBYS_PASSWORD`) | ÜBYS parolanız |
| `BOT_TOKEN` (veya `TELEGRAM_BOT_TOKEN`) | `@BotFather`'dan aldığınız Telegram Bot Token'ı |
| `CHAT_ID` (veya `TELEGRAM_CHAT_ID`) | Bildirim alacak Telegram Chat ID |
| `GIST_ID` | Not durumunun saklanacağı **Secret (Gizli)** Gist ID'si |
| `GIST_TOKEN` | `gist` yetkisine sahip GitHub Personal Access Token |

> **Önemli Gizlilik Notu:** Bu repo **Public (Açık)** olduğu için `GIST_ID` ve `GIST_TOKEN` değerlerinin girili olması önemlidir; aksi hâlde GitHub Actions her çalışmada sıfırdan başlar. Kişisel not durumunuz yalnızca kendi gizli Gist'inizde (`grades_state.json`) saklanır.

### 2. GitHub Actions'ı Yeniden Aktif Etme ve İlk Test

Daha önce workflow'u durdurduysanız:

1. Reponuzda **Actions** sekmesine tıklayın.
2. Sol menüden **Kastamonu ÜBYS Not Takibi** workflow'unu seçin ve gerekirse **"Enable workflow"** butonuna basın.
3. Sağ üstteki **Run workflow** menüsünü açın:
   - İlk olarak **`test_notify`** kutucuğunu işaretleyip (`true`) **Run workflow** diyebilirsiniz. Bu işlem ÜBYS'ye bağlanıp mevcut not özetini Telegram'a gönderir ancak Gist durumunu değiştirmez.
   - Bağlantı sorunsuz çalıştıktan sonra `test_notify` işaretsiz (`false`) şekilde bir kez **Run workflow** çalıştırın. Bu adım Gist üzerinde `grades_state.json` başlangıç kaydını oluşturur ve bildirim takibini başlatır.

---

## Çalışma Sıklığı

Public repolarda GitHub Actions dakikaları ücretsiz ve sınırsızdır. Varsayılan [check-grades.yml](.github/workflows/check-grades.yml) zamanlaması:

- `*/15 5-22 * * *` → **Türkiye saatiyle 08:00 – 01:59** arasında **her 15 dakikada bir** kontrol yapar.
- İsterseniz cron satırını `'*/15 * * * *'` yaparak 7/24 çalışmasını sağlayabilirsiniz.

*(İsteğe bağlı: Repository **Variables** bölümüne `ALL_SEMESTERS=true`, `NOTIFY_ON_FIRST_RUN=false` veya çoklu rol varsa `UBYS_USER_GROUP_ID` ekleyebilirsiniz.)*

---

## Kendi Bilgisayarınızda, VPS'te veya Docker ile Çalıştırma

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Linux/macOS için: cp .env.example .env
```

`.env` dosyasını doldurduktan sonra:

- **Ekran testi (durumu değiştirmez):** `python -m src.main --test`
- **Ekran + Telegram test mesajı:** `python -m src.main --test --notify-test`
- **Tek seferlik gerçek kontrol:** `python -m src.main --once`
- **Sürekli arka plan döngüsü:** `python -m src.main --loop`
- **Docker Compose ile:** `docker compose up -d --build`

### Sorun Giderme (`--dump-html`)

ÜBYS arayüzü güncellenirse yerelde `python -m src.main --test --dump-html` komutunu çalıştırarak HTML örneklerini `debug_html/` klasörüne kaydedip inceleyebilirsiniz.

---

## Lisans

Bu proje [GPL-3.0](LICENSE) lisansı ile sunulmaktadır.
