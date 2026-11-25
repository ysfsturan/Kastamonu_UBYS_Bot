# 🎓 Kastamonu Üniversitesi Öğrenci Asistanı (Telegram Botu)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Render](https://img.shields.io/badge/Render-7%2F24%20%C3%9Ccretsiz-46E3B7?logo=render&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-Haz%C4%B1r-2496ED?logo=docker&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Anl%C4%B1k%20Bot-26A5E4?logo=telegram&logoColor=white)
![Lisans](https://img.shields.io/badge/Lisans-GPL--3.0-green)

Kastamonu Üniversitesi'nin **tüm fakülte, yüksekokul, meslek yüksekokulu (MYO) ve enstitü** öğrencileri için geliştirilmiş; bilgisayar veya sunucu açık bırakmadan bulutta **Render** üzerinde **7/24 ücretsiz** çalışan otomatik Telegram öğrenci asistanı.

Öğrencinin kayıtlı olduğu **fakülte/bölüm ve aktif dönemini otomatik tanıyarak** sınav notu girildiğinde sınıf ortalaması ve final hedefleriyle Telegram'a bildirir; hafta içi her sabah **tam `08:00`'de** günün yemekhane menüsünü, Kuzeykent hava durumunu ve ders programını gönderir; Telegram'dan yazdığın `/yemek`, `/notlar`, `/devamsizlik`, `/hesapla` gibi komutlara da **saniyesinde** yanıt verir.

> **Hızlı Geçiş:** [Ne İşe Yarar?](#-ne-i%CC%87%C5%9Fe-yarar) • [Örnek Mesajlar](#-telegramda-nas%C4%B1l-g%C3%B6r%C3%BCn%C3%BCr) • [Telegram Komutları](#-telegram-bot-komutlar%C4%B1-) • [5 Dakikada Kurulum (Render)](#-5-dakikada-%C3%BCcretsiz-kurulum-render--ad%C4%B1m-ad%C4%B1m) • [Özelleştirme](#%EF%B8%8F-i%CC%87ste%C4%9Fe-ba%C4%9Fl%C4%B1-%C3%B6zelle%C5%9Ftirmeler-environment-variables) • [Güvenlik](#-g%C3%BCvenlik-ve-gizlilik-%C5%9Fifrem-g%C3%BCvende-mi) • [Sorun Giderme](#-s%C4%B1k-sorulan-sorular-ve-sorun-giderme) • [Yerel / Docker / Geliştiriciler](#-yerel-bilgisayar--docker--manuel-actions-geli%C5%9Ftiriciler-i%CC%87%C3%A7in)

---

## ✨ Ne İşe Yarar?

- 🔔 **Anlık Not Bildirimi (`ÜBYS`)**  
  Vize, Final, Bütünleme, Kısa Sınav, Ödev, Geçme Notu veya Harf Notu (`HBN`) girildiği ya da güncellendiği anda sınıf ortalaması ve sıralamanla birlikte Telegram'a bildirim gelir *(varsayılan olarak her 20 dakikada bir otomatik kontrol edilir)*.
- 🎯 **Finalden Kaç Almalıyım? Hesaplayıcı**  
  Vize notun açıklandığında Kastamonu Üniversitesi resmi harf skalasına göre (`DC ≥55`, `CC ≥60`, `CB ≥65`, `BB ≥75`, `BA ≥85`, `AA ≥90`) her harf notu için finalden en az kaç alman gerektiğini otomatik hesaplar (`%30/%70`, `%40/%60` vb. dersin kendi oranına göre).
- 📋 **Gün Bazlı Devamsızlık Takibi (`%70 Teorik / %80 Uygulama`)**  
  ÜBYS Eğitim Kataloğu'ndan her dersinin gerçek **Teorik (`T`) + Uygulama (`U`) + Laboratuvar (`L`)** saatlerini otomatik çeker; *"4 gün hakkın var"* / *"Tam gün: 2 gün hakkın var"* şeklinde gün + saat olarak gösterir ve sınır azalınca uyarır.
- 📊 **Tahmini Dönem YANO / GANO & Onur Belgesi Hesabı**  
  Dönem içi notların geldikçe tahmini dönem sonu ortalamanı (`YANO`), yeni genel ortalamanı (`GANO`), **Onur (`3.00+`) / Yüksek Onur (`3.50+`)** durumunu ve `DC/DD` koşullu geçme riskini (`GANO ≥ 2.00`) hesaplar.
- 🗓️ **Hafta İçi `08:00` Ders Programı & Sınav Takvimi Hatırlatıcı**  
  Hafta sonları hariç hafta içi her sabah **tam `08:00` TR**'de *"Bugünkü derslerin ve saat/derslikleri"* mesajını atar; sınav haftasında tarih, saat ve salon bilgisiyle **7 / 3 / 1 / 0 gün kala** hatırlatma gönderir.
- 📢 **Fakülte/MYO Duyuruları, Bölüm Sınav PDF'leri ve Ders Materyalleri**  
  ÜBYS hesabından okuduğu **fakülte/MYO ve bölüm/sınıf adına göre** kendi biriminin web sayfasını otomatik algılar; `oidb.kastamonu.edu.tr`, `sks.kastamonu.edu.tr`, ÜBYS duyuruları, bölüm sınav programı PDF/Excel bağlantıları ve ders içine yüklenen yeni dosya/ödevleri bildirir.
- 🍽️ **Günlük Yemekhane Menüsü + 🌤️ Kuzeykent Hava Durumu**  
  Hafta içi her sabah **`08:00`'de** güncel yemek listesi ve kalorileriyle birlikte **Kastamonu / Kuzeykent Kampüsü** hava durumunu ve kıyafet tavsiyesini (ayaz, yağmur, kar, rüzgâr) tek mesajda gönderir. *(Yemekhane kapalıysa hava durumunu bağımsız olarak iletir.)*
- 📅 **Akademik Takvim Takibi**  
  Önemli akademik tarihler için **7 / 3 / 1 / 0 gün kala** hatırlatma + **Google Takvime Ekle** bağlantısı sunar.
- 💬 **7/24 Anlık Telegram Komutları (`/yemek`, `/hesapla`, `/notlar`...)**  
  İstediğin an Telegram'dan bota mesaj atıp saniyesinde menü, hava durumu, final hesabı, devamsızlık, ders programı, sınav takvimi veya transkript isteyebilirsin.

---

## 📱 Telegram'da Nasıl Görünür?

**Not Bildirimi + Final Hedefleri:**
```text
🔔 ÜBYS Not Bildirimi

📚 BPBZ201 - İnternet Programcılığı
2026 - Güz
🆕 Ara Sınav - Vize: 100
   └ Sınıf Ort: 64.5 | Sıralama: 1 / 82
🎯 Final Hedefleri (%40/%60):
   • DC (Şartlı) (≥55): Finalden 25+
   • CC (≥60): Finalden 34+
   • CB (≥65): Finalden 42+
   • BB (≥75): Finalden 59+
   • BA (≥85): Finalden 75+
   • AA (≥90): Finalden 84+
```

**Gün Bazlı Devamsızlık Raporu:**
```text
📋 Devamsızlık Takip Raporu

🟢 BPBZ201 - İnternet Programcılığı
   └ Karma (%70 T / %80 U | 3T+1U) | Hak: Teorik 4 gün (12 saat), Uyg 2 gün (2 saat) • Tam gün: 2 gün hakkın var | Devamlı
🟢 BPBZ207 - Bilgisayar Ağları
   └ Teorik (%70 | 4T) | 4 gün hakkın var (16 saat) | Devamlı
```

**Günlük Yemekhane Menüsü + Hava Durumu:**
```text
🍽️ Günün Yemekhane Menüsü
📅 19 Kasım 2026, Perşembe

🥣 Ezogelin Ç. (185 kkal)
🍖 Püreli Rosto Köfte (370 kkal)
🍝 Sebzeli Makarna (348 kkal)
🥗 Cevizli Kabak Tatlısı (194 kkal)

🔥 Toplam Kalori: ~1097 kkal

❄️ Kastamonu (Kuzeykent): Parçalı Bulutlu, -1° / 8°C (Yağış %20)
🧥 Sabah/akşam ayaz ve don riski var; sıkı giyin.
```

---

## 💬 Telegram Bot Komutları (`/`)

Render üzerinde `--serve` kipinde çalışan bot, Telegram sohbetinden gönderdiğin aşağıdaki komutları **7/24 anında** yanıtlar:

| Komut | Açıklama |
| --- | --- |
| `/yardim` | Kullanılabilir tüm komutları listeler |
| `/notlar` | Güncel dönem ders notlarını listeler |
| `/devamsizlik` | Gün ve saat bazlı devamsızlık haklarını gösterir |
| `/hesapla 80` veya `/hesapla 80 30/70` | Vize notuna göre finalden gereken puanları hesaplar |
| `/yemek` | Günün/yaklaşan yemekhane menüsü ve kampüs hava durumunu atar |
| `/hava` | Kuzeykent Kampüsü güncel & 3 günlük hava durumu |
| `/program` veya `/program bugun` | Haftalık veya bugünkü ders programını gösterir |
| `/sinav` | Yaklaşan sınav tarihlerini, saatlerini ve salonları listeler |
| `/duyuru` | OİDB, SKS, Fakülte/MYO ve ÜBYS güncel duyurularını getirir |
| `/takvim` | Akademik takvimde devam eden ve yaklaşan tarihleri gösterir |
| `/transkript` | Dönem ortalamalarını (YANO) ve GANO özetini verir |
| `/gano` | Tahmini dönem sonu YANO/GANO ve Onur belgesi durumu |
| `/ozet` | Haftalık toplu öğrenci brifingini oluşturur |

*(Güvenlik nedeniyle bot yalnızca senin `TELEGRAM_CHAT_ID` hesabından gelen komutlara yanıt verir.)*

---

## 🚀 5 Dakikada Ücretsiz Kurulum (Render — Adım Adım)

Kod bilmene veya bilgisayarını açık bırakmana gerek yok. Kurulum tamamen tarayıcı üzerinden 5 adımda tamamlanır:

### Adım 1: Projeyi Kendi GitHub Hesabına Kopyala (`Fork`)
1. GitHub hesabına giriş yap ve bu sayfanın sağ üstündeki **Fork** düğmesine tıkla → **Create fork**.
2. Depo görünürlüğünü ister **Public**, ister **Private** yapabilirsin *(şifrelerin ve not geçmişin kesinlikle repoda tutulmaz)*.

### Adım 2: Kendi Telegram Botunu Oluştur (`TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`)
1. Telegram'da aramaya **`@BotFather`** yaz (mavi tikli resmi botu aç) ve `/newbot` komutunu gönder.
   - Botuna bir isim (örn: `Benim UBYS Botum`) ve sonunda `bot` geçen bir kullanıcı adı (örn: `ahmet_ubys_bot`) ver.
   - Sana `123456789:ABCdef...` şeklinde bir **Token** verecek. Bunu kaydet (`TELEGRAM_BOT_TOKEN`).
2. BotFather'ın verdiği `t.me/...` linkinden kendi botuna gir ve mutlaka alttaki **Başlat (`/start`)** butonuna bas. *(Bunu yapmazsan bot sana mesaj atamaz.)*
3. Kendi sayısal Telegram ID'ni öğrenmek için **`@userinfobot`** (veya `@RawDataBot`) botunu açıp **Başlat**'a bas. Verdiği sayı senin **`TELEGRAM_CHAT_ID`** değerindir.

### Adım 3: Notların Saklanacağı Gizli Alanı Oluştur (`GIST_ID` & `GIST_TOKEN`)
Sunucu yeniden başlatıldığında veya güncellendiğinde not geçmişin kaybolmasın diye bot, verilerini yalnızca senin erişebildiğin gizli bir **Secret Gist** dosyasına kaydeder:

1. **`GIST_ID` oluşturma:**
   - [https://gist.github.com](https://gist.github.com) adresine git.
   - **Filename including extension** kutusuna tam olarak şunu yaz: `grades_state.json`
   - Altındaki içerik kutusuna sadece iki süslü parantez yaz: `{}`
   - Sağ alttaki oka basıp **Create secret gist** seç (`Create public gist` değil, mutlaka **secret** olmalı).
   - Açılan sayfanın adres çubuğundaki sondaki uzun kod senin **`GIST_ID`** değerindir.
2. **`GIST_TOKEN` oluşturma:**
   - [GitHub Tokens (Classic)](https://github.com/settings/tokens/new) sayfasını aç.
   - **Note** kısmına `UBYS Gist` yaz, **Expiration** süresini seç (örn. `No expiration` veya `1 year`).
   - İzinlerden **yalnızca `gist`** kutucuğunu işaretle.
   - **Generate token** düğmesine bas ve çıkan `ghp_...` kodunu kopyala (`GIST_TOKEN`).

### Adım 4: Botu Render Üzerinde Yayına Al
1. [Render Dashboard](https://dashboard.render.com/) hesabına GitHub ile giriş yap.
2. **New + → Web Service** (veya Blueprint için [render.yaml](render.yaml)) seçip `Fork`ladığın `Kastamonu_UBYS_Bot` reposunu bağla ve şu alanları kontrol et:
   - **Language:** `Docker` *(depodaki [Dockerfile](Dockerfile) otomatik olarak `python -m src.main --serve` çalıştırır)*
   - **Branch:** `main`
   - **Region:** `Frankfurt (EU Central)`
   - **Instance Type:** `Free ($0 / month)`
   - **Health Check Path:** `/health`
3. **Environment Variables** bölümüne aşağıdaki değişkenleri ekle:

| Key | Value (Ne Yazacaksın?) | Zorunlu mu? |
| --- | --- | --- |
| `UBYS_USERNAME` | ÜBYS kullanıcı adın (genellikle **öğrenci numaran**) | ✅ Evet |
| `UBYS_PASSWORD` | ÜBYS giriş şifren | ✅ Evet |
| `TELEGRAM_BOT_TOKEN` | Adım 2'de `@BotFather`'dan aldığın Bot Token | ✅ Evet |
| `TELEGRAM_CHAT_ID` | Adım 2'de öğrendiğin Telegram ID *(çoklu hesap için virgülle ayır)* | ✅ Evet |
| `GIST_ID` | Adım 3'te oluşturduğun Secret Gist ID'si | ✅ Evet |
| `GIST_TOKEN` | Adım 3'te aldığın `gist` yetkili `ghp_...` token | ✅ Evet |
| `ENABLE_WEEKLY_BRIEFING` | `false` *(yalnızca hafta içi `08:00` istiyorsan ekle; Pazar özeti de istersen `true` bırak)* | İsteğe bağlı |

4. **Deploy Web Service** butonuna bas. 1–2 dakika içinde servis **Live** olacak ve Telegram'a ilk başlangıç mesajın gelecektir.

### Adım 5: Botu 7/24 Uyanık Tut (UptimeRobot Ping)
Render'ın ücretsiz planında bir web servisi **15 dakika boyunca dışarıdan HTTP isteği almazsa uyku moduna geçer**. Bot uyuduğunda sabah `08:00`'de uyanamaz ve `/` komutlarına anlık cevap veremez.

Bunu önlemek için ücretsiz bir izleme servisine botunun `/health` adresini veriyoruz; o servis senin yerine 5 dakikada bir *"ayakta mısın?"* diye yoklama atarak botu uyanık tutar *(Render Free aylık 750 ücretsiz saat verdiği için tek bir servis ay boyunca hiç uyumadan %100 ücretsiz çalışır)*:

1. Render servisinin üstünde görünen adresin sonuna `/health` ekleyip tarayıcıda aç:  
   `https://<servis-adin>.onrender.com/health`  
   Ekranda `{"status": "ok", ...}` görüyorsan tamamdır.
2. [uptimerobot.com](https://uptimerobot.com) (veya [cron-job.org](https://cron-job.org)) üzerinde ücretsiz hesap aç.
3. **+ Add New Monitor** deyip şu 4 alanı doldur ve kaydet:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `UBYS Bot`
   - **URL:** `https://<servis-adin>.onrender.com/health`
   - **Monitoring Interval:** `5 minutes`

Artık bilgisayarın kapalı olsa bile bot 7/24 aktif kalır; hafta içi her sabah **tam `08:00` TR**'de günlük özetini atar, gün içi not/duyuru geldiğinde bildirir ve `/` komutlarına saniyesinde yanıt verir.

---

## ⚙️ İsteğe Bağlı Özelleştirmeler (`Environment Variables`)

Hiçbir ek ayar yapmazsan bot tüm özellikleri varsayılan Kastamonu Üniversitesi kurallarıyla otomatik çalıştırır. Değiştirmek istediklerini Render'daki servisinin **Environment** sekmesine ekleyebilirsin:

- **Kendi fakültenin veya MYO'nun duyurularını da eklemek için:**  
  Bot, ÜBYS hesabından okuduğu fakülte/MYO adına göre kendi biriminin sayfasını, OİDB, SKS ve ÜBYS duyurularını **otomatik olarak** tarar. Ekstra farklı bir sayfa eklemek istersen `ANNOUNCEMENT_URLS` ekleyebilirsin:
  ```text
  MMF|https://mmf.kastamonu.edu.tr/
  ```
- **Bazı derslerin vize/final oranı farklıysa (örn. `%30/%70`):**  
  Bot dersin oranını ÜBYS ve Eğitim Kataloğu'ndan otomatik okur. Hoca farklı bir oran uyguluyorsa `COURSE_WEIGHTS` ile öncelik verebilirsin:
  ```text
  KOD101:30/70, KOD202:40/60
  ```
- **Fakültene özel akademik takvim görmek için:**  
  `CALENDAR_FACULTY` değişkenine `GENEL`, `TIP`, `VET`, `DIS`, `LISANSUSTU` veya `TURIZM` yazabilirsin.
- **İstemediğin bir özelliği kapatmak için:**  
  Örneğin yemekhane, hava durumu veya duyuru bildirimini kapatmak için `ENABLE_DINING`, `ENABLE_WEATHER` veya `ENABLE_ANNOUNCEMENTS` değerini `false` yapman yeterlidir.

<details>
<summary>📋 Tüm İsteğe Bağlı Ayarlar (Tam Liste)</summary>

| Variable Adı | Varsayılan | Açıklama |
| --- | --- | --- |
| `CHECK_INTERVAL_MINUTES` | `20` | `--serve` ve `--loop` kiplerinde arka plan ÜBYS kontrol aralığı (dakika) |
| `ENABLE_GRADES` | `true` | ÜBYS not takibini açar/kapatır |
| `ENABLE_DINING` | `true` | Hafta içi yemekhane menüsü bildirimini açar/kapatır |
| `ENABLE_WEATHER` | `true` | Sabah menüsüne (veya yemekhane kapalıysa tek başına) Kuzeykent hava durumunu ekler |
| `WEATHER_LOCATION` | `Kastamonu (Kuzeykent)` | Hava durumu başlığında görünecek konum adı |
| `WEATHER_LAT` / `WEATHER_LON` | `41.4307` / `33.7764` | Hava durumu koordinatları (Kuzeykent Kampüsü) |
| `ENABLE_CALENDAR` | `true` | Akademik takvim hatırlatma ve Pazartesi özetini açar/kapatır |
| `CALENDAR_NOTIFY_HOUR` | `8` | Akademik takvim kontrol saati (`0-23`, TR saati) |
| `CALENDAR_LOOKAHEAD_DAYS` | `30` | Haftalık özetlerde kaç gün ileriye bakılacağı |
| `CALENDAR_WEEKLY_SUMMARY` | `true` | Pazartesi günleri devam eden & yaklaşan takvim özeti gönderir |
| `ENABLE_ATTENDANCE` | `true` | Devamsızlık hakkı ve kritik eşik takibini açar/kapatır |
| `ENABLE_TRANSCRIPT` | `true` | GANO değişimi ve transkript takibini açar/kapatır |
| `ENABLE_ANNOUNCEMENTS` | `true` | OİDB, SKS, ÜBYS ve fakülte duyurularını tarar |
| `ANNOUNCEMENT_URLS` | *(boş)* | Ek duyuru siteleri (`Etiket\|https://...` veya sadece URL, virgülle ayrılır) |
| `ANNOUNCEMENT_KEYWORDS` | *(boş)* | Duyurular için anahtar kelime filtresi (boş = tüm yeni duyurular) |
| `ENABLE_SCHEDULE` | `true` | Hafta içi sabah günün ders programını gönderir |
| `ENABLE_EXAM_SCHEDULE` | `true` | ÜBYS sınav takviminden yaklaşan sınavları hatırlatır |
| `SCHEDULE_NOTIFY_HOUR` | `8` | Sabah ders programı bildirimi saati (`0-23`, TR saati) |
| `EXAM_REMINDER_DAYS` | `7,3,1,0` | Sınavdan kaç gün önce hatırlatma gönderileceği |
| `ENABLE_MATERIALS` | `true` | Ders içine yüklenen yeni PDF/ödev/duyuruları bildirir |
| `ENABLE_WEEKLY_BRIEFING` | `true` | Pazar akşamları haftalık toplu öğrenci brifingi gönderir (`false` ile kapatılabilir) |
| `WEEKLY_BRIEFING_HOUR` | `20` | Pazar haftalık brifing en erken saati (TR saati) |
| `ENABLE_COMMANDS` | `true` | Telegram'dan gelen `/` komutlarını yanıtlar |
| `ENABLE_CATALOG` | `true` | ÜBYS Eğitim Kataloğu'ndan derslerin gerçek `T+U+L` saatlerini ve değerlendirme oranlarını otomatik çeker (`14` gün Gist önbellekli) |
| `UBYS_PROGRAM` | *(otomatik)* | Eğitim Kataloğu bölüm eşleşmesi için bölüm adı veya ID sabitlemesi |
| `MIDTERM_WEIGHT` | `0.40` | Varsayılan vize oranı (`0.40` veya `40`) |
| `FINAL_WEIGHT` | `0.60` | Varsayılan final oranı (`0.60` veya `60`) |
| `FINAL_MIN_SCORE` | `0` | Fakülte/bölüm final alt barajı (genel yönetmelik için `0`) |
| `COURSE_WEIGHTS` | *(boş)* | Ders bazlı özel vize/final oranı (`KOD101:30/70,KOD202:40/60`) |
| `SEMESTER_WEEKS` | `14` | Devamsızlık hesabında dönem hafta sayısı |
| `THEORY_MIN_ATTENDANCE` | `70` | Teorik ders devam zorunluluğu (`%70`) |
| `PRACTICE_MIN_ATTENDANCE` | `80` | Uygulamalı ders devam zorunluluğu (`%80`) |
| `COURSE_HOURS` | *(boş)* | Ders bazlı özel haftalık `T+U` saati (`KOD101:3+1,KOD202:4+0`) |
| `CALENDAR_FACULTY` | `GENEL` | Takvim birimi (`GENEL`, `TIP`, `VET`, `DIS`, `LISANSUSTU`, `TURIZM`) |
| `CALENDAR_CATEGORIES` | `STUDENT` | Takvim filtresi (`STUDENT`, `ALL` veya virgüllü kategori listesi) |
| `CALENDAR_REMINDER_DAYS` | `7,3,1,0` | Etkinlik başlamadan kaç gün önce tek seferlik hatırlatma atılacağı |
| `DINING_NOTIFY_HOUR` | `8` | Yemekhane ve hava durumu bildiriminin gönderileceği saat (Türkiye saati, `0-23`) |
| `DINING_SHEET_URL` | *(otomatik)* | SKS yerine doğrudan Google Sheets CSV/edit bağlantısı |
| `ALL_SEMESTERS` | `false` | `true` yapılırsa geçmiş dönem derslerini de tarar |
| `UBYS_USER_GROUP_ID` | *(otomatik)* | Birden fazla ÜBYS rolü olan kullanıcılar için öğrenci rolü ID'si |
| `NOTIFY_ON_FIRST_RUN` | `true` | İlk kurulumda mevcut ders özetini Telegram'a gönderir |

</details>

---

## 🔒 Güvenlik ve Gizlilik (Şifrem Güvende mi?)

- **Bilgilerin Şifreli Saklanır:** `UBYS_USERNAME`, `UBYS_PASSWORD`, `TELEGRAM_BOT_TOKEN` ve `GIST_TOKEN` yalnızca senin Render servisinin **Environment Variables** alanında saklanır; kaynak kodda veya `/health` yanıtında kesinlikle yer almaz.
- **Notların Açık Repoya Yazılmaz:** Not geçmişin, GANO'n ve katalog önbelleğin senin **Secret Gist** (`GIST_ID`) dosyanda tutulur.
- **Üçüncü Taraf Veri Toplama Yoktur:** Bot yalnızca resmi `*.kastamonu.edu.tr`, `api.open-meteo.com` / `wttr.in`, `api.telegram.org` ve `api.github.com` adresleriyle doğrudan haberleşir.
- **Açık Kaynak:** Tüm Python kodları bu depoda şeffaf şekilde incelenebilir.

---

## ❓ Sık Sorulan Sorular ve Sorun Giderme

- **Telegram'dan hiç mesaj gelmiyor, ne yapmalıyım?**  
  1. Kendi oluşturduğun bota Telegram'da girip **`/start`** (Başlat) butonuna bastığından emin ol.  
  2. `TELEGRAM_CHAT_ID` içinde kendi sayısal ID'nin (`@userinfobot` çıktısı) doğru yazıldığını ve başında/sonunda boşluk olmadığını kontrol et.

- **Sabah `08:00` mesajı gelmedi veya `/` komutları gecikiyor:**  
  Render Free servisi 15 dakika istek almazsa uyur. **Adım 5**'teki gibi UptimeRobot üzerinden `https://<servis-adin>.onrender.com/health` adresine **5 dakikalık** ping tanımladığından ve Render hesabındaki toplam Free saat kotasının (aylık 750 saat) dolmadığından emin ol.

- **Render loglarında `Telegram getUpdates çakışması (HTTP 409)` gördüm:**  
  Yeni bir kod yüklemesi (deploy) sırasında eski ve yeni container aynı anda birkaç saniye açık kalırsa Telegram geçici 409 döndürür; bot bunu otomatik algılayıp 5 saniye bekler ve eski container kapanınca normale döner. Aynı bot token'ını başka bir yerde (`GitHub Actions --commands` veya yerel `--listen`) aynı anda çalıştırmadığından emin ol.

- **`GitHub Gist / Durum Okuma Hatası (HTTP 401)` uyarısı aldım:**  
  `GIST_TOKEN` süren dolmuş veya token oluşturulurken **`gist`** kutucuğu işaretlenmemiş demektir. [GitHub Tokens](https://github.com/settings/tokens/new) sayfasından sadece `gist` yetkili yeni bir token üretip Render'da `GIST_TOKEN` değerini güncellemen yeterlidir (not geçmişin silinmez).

- **ÜBYS şifremi değiştirdim, bot hata vermeye başladı:**  
  Render → **Environment** içinden `UBYS_PASSWORD` değerini yeni şifrenle güncelle ve servisi yeniden başlat; bot kaldığı yerden devam eder. *(Güvenlik nedeniyle şifre hatalıysa tekrar kilitlenmemek için hata uyarısı yalnızca 1 kez atılır.)*

- **Bir dersimin vize/final oranı veya teorik/uygulama saati hocanın söylediğiyle uyuşmuyor:**  
  Render → **Environment** içine `COURSE_WEIGHTS` (örn. `KOD101:30/70`) veya `COURSE_HOURS` (örn. `KOD101:3+1`) ekleyerek o dersi hemen düzeltebilirsin.

---

## 💻 Yerel Bilgisayar / Docker / Manuel Actions (Geliştiriciler İçin)

<details>
<summary>🛠️ Yerel Kurulum, CLI Komutları, Testler, Docker ve Manuel GitHub Actions</summary>

### Yerel Kurulum

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Linux/macOS: cp .env.example .env
```

`.env` dosyanı doldurduktan sonra kullanabileceğin komutlar:

| Komut | Açıklama |
| --- | --- |
| `python -m src.main --serve` | Render/bulut için 7/24 zamanlayıcı + anlık Telegram komutları + `/health` sunucusu başlatır |
| `python -m src.main --serve --port 8080` | `--serve` kipini özel bir HTTP portuyla başlatır |
| `python -m src.main --calc 100` | Vize notuna göre final hedeflerini çevrimdışı hesaplar |
| `python -m src.main --calc 100 --weights 30/70` | Özel vize/final oranıyla (`%30/%70` vb.) final hedeflerini hesaplar |
| `python -m src.main --attendance` | Aktif dönem derslerinin gün/saat devamsızlık raporunu gösterir |
| `python -m src.main --transcript` | Transkript ve GANO özetini ekrana yazar |
| `python -m src.main --dining` | Günün/yaklaşan yemekhane menüsünü (+ hava durumu) gösterir (ÜBYS şifresi gerektirmez) |
| `python -m src.main --weather` | Kuzeykent kampüsü güncel ve 3 günlük hava durumunu gösterir (şifresiz) |
| `python -m src.main --announcements` | OİDB, SKS ve okul güncel duyurularını listeler (şifresiz) |
| `python -m src.main --calendar` | Akademik takvim özetini gösterir (ÜBYS şifresi gerektirmez) |
| `python -m src.main --gpa` | Tahmini dönem sonu YANO/GANO ve Onur belgesi durumunu hesaplar |
| `python -m src.main --schedule` | ÜBYS haftalık ders programını gösterir |
| `python -m src.main --exams` | ÜBYS vize/final sınav takvimini gösterir |
| `python -m src.main --briefing` | Haftalık toplu öğrenci brifingini oluşturur |
| `python -m src.main --commands` | Telegram'da bekleyen `/` komutlarını tek seferde yanıtlar |
| `python -m src.main --listen` | Telegram komutları için anlık sürekli dinleyici (`long polling`) başlatır |
| `python -m src.main --test` | Etkin tüm modülleri durum dosyasını bozmadan test eder (`--notify-test` ile Telegram'a atar) |
| `python -m src.main --once` | Tek seferlik tam kontrol + durum kaydı yapar |
| `python -m src.main --loop` | Belirlenen aralıklarla (`CHECK_INTERVAL_MINUTES`) sürekli çalışır |

### Docker ile Çalıştırma

```bash
docker compose up -d --build
```

### Birim Testlerini Çalıştırma

```bash
python -m unittest discover -s tests -v
```

### İsteğe Bağlı Manuel GitHub Actions (`Run workflow`)

Depodaki `.github/workflows/check-grades.yml` iş akışı yalnızca **Actions → Kastamonu ÜBYS Swiss Bot → Run workflow** üzerinden tek seferlik manuel test/önizleme için tutulur (`test_all`, `dining`, `calendar`, `transcript`, `attendance`, `gpa`, `schedule`, `exams`, `announcements`, `weather`, `briefing`, `force_daily`). Otomatik zamanlanmış çalışma Render üzerinden yapılır.

</details>

---

## 📄 Lisans ve Notlar

Bu proje [GPL-3.0](LICENSE) lisansı ile sunulan bağımsız ve açık kaynaklı bir öğrenci aracıdır; Kastamonu Üniversitesi'nin resmî uygulaması değildir.
