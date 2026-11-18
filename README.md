# Kastamonu Üniversitesi Öğrenci Asistanı (Swiss Tool)

Kastamonu Üniversitesi öğrencileri için **7/24 bulutta (GitHub Actions)** ücretsiz çalışan, Selenium/ChromeDriver gerektirmeyen, hafif ve modüler **Telegram asistanı**:

1. **ÜBYS Not Bildirimi (`https://ubys.kastamonu.edu.tr`):** Vize, Final, Bütünleme, Kısa Sınav, Ödev, Geçme Notu ve Harf Notu (`HBN`) değişikliklerini, sınıf ortalaması ve sıralamayla birlikte anlık bildirir.
2. **SKS Yemekhane Menüsü (`https://sks.kastamonu.edu.tr`):** Hafta içi her sabah güncel günün yemek listesini ve yemek başı / toplam kalori bilgisini gönderir.
3. **Akademik Takvim Takibi (`https://akademiktakvim.kastamonu.edu.tr`):** Yaklaşan sınavlar, kayıt yenileme, ders ekle-sil ve resmî tatiller için **7 / 3 / 1 / 0 gün** kala otomatik hatırlatma, her Pazartesi haftalık özet ve tek tıkla **Google Takvime Ekle** bağlantısı sunar.

---

## Öne Çıkan Özellikler

- **Sıfır Tarayıcı / Yüksek Hız:** Eski Selenium + ChromeDriver + `iframe` yapısı yerine doğrudan resmi sayfa uç noktalarına ve API'lere `httpx` + `BeautifulSoup` ile bağlanır.
- **Public Repo + Gizli Gist Güvenliği:** Durum verileriniz asla açık (Public) repoya yazılmaz; gizli (Secret) **GitHub Gist** içindeki `grades_state.json` dosyasında tutulur.
- **Birim Seçenekli Akademik Takvim:** `GENEL` dışında `TIP`, `VET`, `DIS`, `LISANSUSTU`, `TURIZM` fakülte/enstitü özel takvimlerini destekler (`BOLUM_TIPI` secret'ınızla da otomatik uyumludur).
- **Modül İzolasyonu:** Yemekhane veya Takvim sitesinde geçici bir bakım olsa bile ÜBYS not takibi kesintisiz çalışmaya devam eder.
- **Geriye Dönük Secret Uyumu:** Mevcut `OGRENCI_NO`, `SIFRE`, `BOT_TOKEN`, `CHAT_ID`, `GIST_ID`, `GIST_TOKEN`, `BOLUM_TIPI` secret isimlerinizle ek ayar yapmadan çalışır.

---

## GitHub Actions Kurulumu

### 1. Repository Secrets

**Settings → Secrets and variables → Actions → Repository secrets** altında şu değerler yer alır:

| Secret Adı (veya Alternatifi) | Açıklama |
| --- | --- |
| `OGRENCI_NO` (veya `UBYS_USERNAME`) | ÜBYS kullanıcı adınız (öğrenci numaranız) |
| `SIFRE` (veya `UBYS_PASSWORD`) | ÜBYS parolanız |
| `BOT_TOKEN` (veya `TELEGRAM_BOT_TOKEN`) | `@BotFather`'dan aldığınız Telegram Bot Token'ı |
| `CHAT_ID` (veya `TELEGRAM_CHAT_ID`) | Bildirim alacak Telegram Chat ID |
| `GIST_ID` | Not ve bildirim durumunun saklanacağı **Secret Gist** ID'si |
| `GIST_TOKEN` | Yalnızca `gist` yetkisine sahip GitHub Personal Access Token |

### 2. İsteğe Bağlı Repository Variables

**Settings → Secrets and variables → Actions → Variables** sekmesinden davranışları özelleştirebilirsiniz:

| Variable Adı | Varsayılan | Açıklama |
| --- | --- | --- |
| `ENABLE_GRADES` | `true` | ÜBYS not takibini açar/kapatır |
| `ENABLE_DINING` | `true` | Hafta içi yemekhane menüsü bildirimini açar/kapatır |
| `ENABLE_CALENDAR` | `true` | Akademik takvim hatırlatma ve haftalık özetini açar/kapatır |
| `CALENDAR_FACULTY` | `GENEL` | `GENEL`, `TIP`, `VET`, `DIS`, `LISANSUSTU`, `TURIZM` (veya `BOLUM_TIPI`) |
| `CALENDAR_CATEGORIES` | `STUDENT` | `STUDENT` (Ders/Sınav/Kayıt/Tatil/KUZEM/OSD), `ALL` veya virgüllü liste |
| `CALENDAR_REMINDER_DAYS` | `7,3,1,0` | Etkinlik başlamadan kaç gün önce hatırlatılacağı |
| `DINING_NOTIFY_HOUR` | `8` | Yemekhane bildiriminin gönderileceği en erken saat (TR saati) |
| `ALL_SEMESTERS` | `false` | Tüm geçmiş dönem derslerini de tarar |
| `NOTIFY_ON_FIRST_RUN` | `true` | İlk kurulumda mevcut ders özetini gönderir |

### 3. Actions Üzerinden Manuel Çalıştırma (`workflow_dispatch`)

**Actions → Kastamonu ÜBYS Swiss Bot → Run workflow** menüsünden `mode` seçerek istediğiniz modülü anında test edebilirsiniz:

- `once`: Normal tam çalıştırma (notlar + saat uygunsa günlük yemekhane/takvim). `test_notify: true` ile çalıştırırsanız durum değiştirmeden tüm modülleri test eder.
- `test_all`: Etkin tüm modülleri test eder (`test_notify: true` ise Telegram'a da gönderir).
- `dining`: Yalnızca günün/yaklaşan yemekhane menüsünü çeker (`test_notify: true` ise Telegram'a yollar).
- `calendar`: Yalnızca akademik takvim özetini çeker (`test_notify: true` ise Telegram'a yollar).
- `force_daily`: Saat veya hafta içi koşuluna bakmadan günlük yemekhane ve takvim özetini Telegram'a gönderir.

---

## Yerel Bilgisayarda, VPS'te veya Docker ile Kullanım

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Linux/macOS için: cp .env.example .env
```

Hızlı CLI komutları:

- **Sadece yemekhane menüsünü gör (şifre gerektirmez):** `python -m src.main --dining`
- **Sadece akademik takvimi gör (şifre gerektirmez):** `python -m src.main --calendar`
- **Tüm modülleri ekranda test et:** `python -m src.main --test`
- **Tüm modülleri test edip Telegram'a gönder:** `python -m src.main --test --notify-test`
- **Tek seferlik tam çalıştırma:** `python -m src.main --once`
- **Günlük yemekhane ve takvimi zorla gönder:** `python -m src.main --once --force-daily`
- **Sürekli arka plan döngüsü:** `python -m src.main --loop`
- **Docker Compose ile:** `docker compose up -d --build`

---

## Lisans

Bu proje [GPL-3.0](LICENSE) lisansı ile sunulmaktadır.
