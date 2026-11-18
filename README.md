# Kastamonu Üniversitesi Öğrenci Asistanı (Swiss Tool)

Kastamonu Üniversitesi öğrencileri için **7/24 bulutta (GitHub Actions)** ücretsiz çalışan, Selenium/ChromeDriver gerektirmeyen, hafif ve modüler **Telegram öğrenci asistanı**:

1. **ÜBYS Not Bildirimi (`https://ubys.kastamonu.edu.tr`):** Vize, Final, Bütünleme, Kısa Sınav, Ödev, Geçme Notu ve Harf Notu (`HBN`) değişikliklerini sınıf ortalaması ve sıralamayla birlikte anlık bildirir.
2. **Final Hedef & Harf Notu Hesaplayıcı:** Kastamonu Üniversitesi harf skalasına göre (`DC ≥55`, `CC ≥60`, `CB ≥65`, `BB ≥75`, `BA ≥85`, `AA ≥90`) Vize notunuz açıklandığında finalden en az kaç almanız gerektiğini hesaplar. ÜBYS ders detayı, ÜBYS Eğitim Kataloğu (`Bologna`) veya `COURSE_WEIGHTS` ayarından dersin kendi **Vize/Final oranını (`%30/%70`, `%40/%60` vb.)** otomatik okur.
3. **Gün Bazlı Devamsızlık Takibi (`%70 Teorik / %80 Uygulamalı`):** ÜBYS Eğitim Kataloğu'ndan (`Bologna`) her dersin gerçek **Teorik (`T`) + Uygulama (`U`) + Laboratuvar (`L`)** haftalık saatlerini otomatik çeker (14 günlük Gist önbellekli). KÜ Yönetmeliği Madde 16'ya göre toplam hakkınızı ve kalan hakkınızı **gün/hafta** (`4 gün hakkın var`, `Kalan: 2 gün` vb.) + saat karşılığı olarak gösterir ve kritik sınırda uyarır.
4. **Transkript & GANO Takibi:** Tam transkript özetinizi (`YANO` / `GANO` / kredi / ders harf notları) çeker ve GANO'nuz değiştiğinde farkıyla (`📈` / `📉`) bildirir.
5. **SKS Yemekhane Menüsü (`https://sks.kastamonu.edu.tr`):** Hafta içi her sabah güncel günün yemek listesini, yemek başı ve toplam kaloriyi gönderir.
6. **Akademik Takvim Takibi (`https://akademiktakvim.kastamonu.edu.tr`):** Sınav, kayıt yenileme, ders ekle-sil ve resmî tatiller için **7 / 3 / 1 / 0 gün** kala hatırlatma, her Pazartesi haftalık özet ve **Google Takvime Ekle** bağlantısı sunar.

---

## Öne Çıkan Özellikler

- **Sıfır Tarayıcı / Yüksek Hız:** Eski Selenium + ChromeDriver + `iframe` yapısı yerine doğrudan resmi uç noktalara `httpx` + `BeautifulSoup` ile bağlanır.
- **Public Repo + Gizli Gist Güvenliği:** Durum verileriniz asla açık (Public) repoya yazılmaz; gizli (Secret) **GitHub Gist** içindeki `grades_state.json` dosyasında tutulur.
- **Modül İzolasyonu:** Yemekhane veya Takvim sitesinde geçici kesinti olsa bile ÜBYS not takibi kesintisiz çalışmaya devam eder.
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
| `GIST_ID` | Durum verilerinin saklanacağı **Secret Gist** ID'si |
| `GIST_TOKEN` | Yalnızca `gist` yetkisine sahip GitHub Personal Access Token |

### 2. İsteğe Bağlı Repository Variables

**Settings → Secrets and variables → Actions → Variables** sekmesinden özelleştirebilirsiniz:

| Variable Adı | Varsayılan | Açıklama |
| --- | --- | --- |
| `ENABLE_GRADES` | `true` | ÜBYS not takibini açar/kapatır |
| `ENABLE_DINING` | `true` | Hafta içi yemekhane menüsü bildirimini açar/kapatır |
| `ENABLE_CALENDAR` | `true` | Akademik takvim hatırlatma ve haftalık özetini açar/kapatır |
| `ENABLE_ATTENDANCE` | `true` | Devamsızlık hakkı ve kritik eşik takibini açar/kapatır |
| `ENABLE_TRANSCRIPT` | `true` | GANO değişimi ve transkript özetini açar/kapatır |
| `ENABLE_CATALOG` | `true` | ÜBYS Eğitim Kataloğu'ndan dersin gerçek `T+U` saatlerini ve değerlendirme oranlarını otomatik çeker |
| `UBYS_PROGRAM` | *(otomatik)* | Kataloğun kullanacağı bölüm adı veya ID'si (boş bırakılırsa otomatik algılanır) |
| `MIDTERM_WEIGHT` | `0.40` | Varsayılan vize etki oranı (`0.40` veya `40`) |
| `FINAL_WEIGHT` | `0.60` | Varsayılan final etki oranı (`0.60` veya `60`) |
| `FINAL_MIN_SCORE` | `0` | Fakülte final alt barajı (genel yönetmelik için `0`) |
| `COURSE_WEIGHTS` | *(boş)* | Ders bazlı özel vize/final oranı (`BPBZ201:30/70,BPBZ207:40/60`; tüm kaynaklara göre önceliklidir) |
| `SEMESTER_WEEKS` | `14` | Devamsızlık hesabında dönem hafta sayısı |
| `THEORY_MIN_ATTENDANCE` | `70` | Teorik ders devam zorunluluğu (`%70`) |
| `PRACTICE_MIN_ATTENDANCE` | `80` | Uygulamalı ders devam zorunluluğu (`%80`) |
| `COURSE_HOURS` | *(boş)* | Ders bazlı özel haftalık `T+U` saati (`BPBZ201:3+1,BPBZ207:4+0`) |
| `CALENDAR_FACULTY` | `GENEL` | `GENEL`, `TIP`, `VET`, `DIS`, `LISANSUSTU`, `TURIZM` (veya `BOLUM_TIPI`) |
| `CALENDAR_CATEGORIES` | `STUDENT` | `STUDENT` (Ders/Sınav/Kayıt/Tatil/KUZEM/OSD), `ALL` veya virgüllü liste |
| `CALENDAR_REMINDER_DAYS` | `7,3,1,0` | Etkinlik başlamadan kaç gün önce hatırlatılacağı |
| `DINING_NOTIFY_HOUR` | `8` | Yemekhane bildiriminin gönderileceği en erken saat (TR saati) |
| `ALL_SEMESTERS` | `false` | Tüm geçmiş dönem derslerini de tarar |
| `NOTIFY_ON_FIRST_RUN` | `true` | İlk kurulumda mevcut ders özetini gönderir |

### 3. Actions Üzerinden Manuel Çalıştırma (`workflow_dispatch`)

**Actions → Kastamonu ÜBYS Swiss Bot → Run workflow** menüsünden `mode` seçebilirsiniz:

- `once`: Normal tam çalıştırma (`test_notify: true` seçilirse durum değiştirmeden tüm modülleri test eder).
- `test_all`: Etkin tüm modülleri (notlar + devamsızlık + transkript + yemekhane + takvim) test eder.
- `dining`: Yalnızca günün/yaklaşan yemekhane menüsünü çeker (`test_notify: true` ile Telegram'a gönderir).
- `calendar`: Yalnızca akademik takvim özetini çeker (`test_notify: true` ile Telegram'a gönderir).
- `transcript`: Yalnızca ÜBYS transkript & GANO özetini çeker (`test_notify: true` ile Telegram'a gönderir).
- `attendance`: Yalnızca aktif dönem devamsızlık hakkı raporunu çeker (`test_notify: true` ile Telegram'a gönderir).
- `force_daily`: Saat/hafta içi kısıtını aşarak günlük yemekhane ve takvim özetini gönderir.

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

- **Çevrimdışı Final Hedef Hesapla:** `python -m src.main --calc 100` (özel oran için `--weights 30/70` eklenebilir)
- **Devamsızlık Raporu:** `python -m src.main --attendance`
- **Transkript & GANO Özeti:** `python -m src.main --transcript`
- **Yemekhane Menüsü (şifresiz):** `python -m src.main --dining`
- **Akademik Takvim (şifresiz):** `python -m src.main --calendar`
- **Tüm Modülleri Test Et:** `python -m src.main --test` (Telegram için `--notify-test` ekleyin)
- **Tek Seferlik Tam Kontrol:** `python -m src.main --once`
- **Sürekli Arka Plan Döngüsü:** `python -m src.main --loop`
- **Docker Compose ile:** `docker compose up -d --build`

---

## Lisans

Bu proje [GPL-3.0](LICENSE) lisansı ile sunulmaktadır.
