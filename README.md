# 🎓 Kastamonu Üniversitesi Öğrenci Asistanı (Telegram Botu)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-7%2F24%20%C3%9Ccretsiz-2088FF?logo=githubactions&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Anl%C4%B1k%20Bildirim-26A5E4?logo=telegram&logoColor=white)
![Lisans](https://img.shields.io/badge/Lisans-GPL--3.0-green)

Kastamonu Üniversitesi öğrencileri için geliştirilmiş, **bilgisayar veya sunucu açık bırakmadan tamamen ücretsiz** bulutta (`GitHub Actions`) çalışan 7/24 Telegram asistanı.  
Sınav notun açıklandığı anda sınıf ortalaması ve final hedefleriyle Telegram'a bildirir; yanında gün bazlı devamsızlık takibi, transkript/GANO özeti, günlük yemekhane menüsü ve akademik takvim hatırlatmalarını cebine getirir.

> **Hızlı Geçiş:** [Ne İşe Yarar?](#-ne-i%CC%87%C5%9Fe-yarar) • [Örnek Mesajlar](#-telegramda-nas%C4%B1l-g%C3%B6r%C3%BCn%C3%BCr) • [Telegram Komutları](#-telegram-bot-komutlar%C4%B1-) • [5 Dakikada Kurulum](#-5-dakikada-%C3%BCcretsiz-kurulum-ad%C4%B1m-ad%C4%B1m) • [Tek Tıkla Kullanım](#%EF%B8%8F-i%CC%87stedi%C4%9Fin-zaman-tek-t%C4%B1kla-%C3%A7al%C4%B1%C5%9Ft%C4%B1rma-run-workflow) • [Özelleştirme](#%EF%B8%8F-i%CC%87ste%C4%9Fe-ba%C4%9Fl%C4%B1-%C3%B6zelle%C5%9Ftirmeler-variables) • [Güvenlik](#-g%C3%BCvenlik-ve-gizlilik-%C5%9Fifrem-g%C3%BCvende-mi) • [Sorun Giderme](#-s%C4%B1k-sorulan-sorular-ve-sorun-giderme) • [Yerel / Docker](#-kendi-bilgisayar%C4%B1nda--docker-ile-%C3%A7al%C4%B1%C5%9Ft%C4%B1rma-geli%C5%9Ftiriciler-i%CC%87%C3%A7in)

---

## ✨ Ne İşe Yarar?

- 🔔 **Anlık Not Bildirimi (`ÜBYS`)**  
  Vize, Final, Bütünleme, Kısa Sınav, Ödev, Geçme Notu veya Harf Notu (`HBN`) girildiği ya da güncellendiği anda sınıf ortalaması ve sıralamanla birlikte Telegram'a bildirim gelir.
- 🎯 **Finalden Kaç Almalıyım? Hesaplayıcı**  
  Vize notun açıklandığında Kastamonu Üniversitesi resmi harf skalasına göre (`DC ≥55`, `CC ≥60`, `CB ≥65`, `BB ≥75`, `BA ≥85`, `AA ≥90`) her harf notu için finalden en az kaç alman gerektiğini otomatik hesaplar (`%30/%70`, `%40/%60` vb. dersin kendi oranına göre).
- 📋 **Gün Bazlı Devamsızlık Takibi (`%70 Teorik / %80 Uygulama`)**  
  ÜBYS Eğitim Kataloğu'ndan her dersinin gerçek **Teorik (`T`) + Uygulama (`U`) + Laboratuvar (`L`)** saatlerini otomatik çeker; **"4 gün hakkın var"** / **"Tam gün: 2 gün hakkın var"** şeklinde gün + saat olarak gösterir ve sınır azalınca uyarır.
- 📊 **Tahmini Dönem YANO / GANO & Onur Belgesi Hesabı**  
  Dönem içi notların geldikçe tahmini dönem sonu ortalamanı (`YANO`), yeni genel ortalamanı (`GANO`), **Onur (`3.00+`) / Yüksek Onur (`3.50+`)** durumunu ve `DC/DD` koşullu geçme riskini (`GANO ≥ 2.00`) hesaplar.
- 🗓️ **Günlük Ders Programı & Sınav Takvimi Hatırlatıcı**  
  ÜBYS'deki ders programını çekip hafta içi her sabah *"Bugünkü derslerin ve saat/derslikleri"* mesajı atar; sınav haftasında tarih, saat ve salon bilgisiyle **7 / 3 / 1 / 0 gün kala** hatırlatma gönderir.
- 📢 **Üniversite, OİDB, SKS, Fakülte/MYO ve Ders Materyal/Ödev Takibi**  
  `oidb.kastamonu.edu.tr`, `sks.kastamonu.edu.tr`, kendi eklediğin fakülte/MYO siteleri, ÜBYS portalı ve ders içindeki yeni PDF/ödev/duyuruları tarayıp yeni bir şey eklendiğinde anında bildirir.
- 🍽️ **Günlük Yemekhane Menüsü + 🌤️ Kuzeykent Hava Durumu**  
  Hafta içi her sabah güncel yemek listesi ve kalorileriyle birlikte **Kastamonu / Kuzeykent Kampüsü** hava durumunu ve kıyafet tavsiyesini (ayaz, yağmur, kar, rüzgâr) tek mesajda gönderir.
- 📅 **Akademik Takvim & 📆 Pazar Akşamı Haftalık Özet**  
  Önemli akademik tarihler için **7 / 3 / 1 / 0 gün kala** hatırlatma + **Google Takvime Ekle** bağlantısı sunar; her Pazar saat `20:00`'de yaklaşan sınavlar, kritik devamsızlıklar ve takvim özetini tek brifingte toplar.
- 💬 **Telegram'dan Komutla Sorgulama (`/yemek`, `/hesapla`, `/devamsizlik`...)**  
  İstediğin zaman bota mesaj atıp menü, hava durumu, final hesabı, devamsızlık veya ders programı isteyebilirsin.

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

Kendi botuna Telegram sohbetinden aşağıdaki komutları gönderebilirsin *(GitHub Actions modunda ücretsiz çalıştığı için ~15 dakikalık döngüde yanıtlanır; bilgisayar/VPS üzerinde `--listen` ile çalıştırırsan saniyesinde yanıt verir)*:

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

## 🚀 5 Dakikada Ücretsiz Kurulum (Adım Adım)

Kod bilmene veya bilgisayarına bir şey kurmana gerek yok. Her şey tarayıcı üzerinden 5 basit adımda tamamlanır:

### Adım 1: Projeyi Kendi GitHub Hesabına Kopyala (`Fork`)
1. GitHub hesabına giriş yap ve bu sayfanın sağ üstündeki **Fork** düğmesine tıkla → **Create fork**.
2. **Önemli:** Kopyaladığın deponun görünürlüğünü **Public (Herkese Açık)** olarak bırak.
   - *Neden?* GitHub, Public depolarda **Actions sürelerini ücretsiz ve sınırsız** verir (`Private` depolarda aylık kota dolar).
   - *Merak etme:* Senin şifrelerin ve notların kesinlikle repoda durmaz; hepsi Adım 3 ve Adım 4'teki şifreli/gizli alanlarda saklanır.

### Adım 2: Kendi Telegram Botunu Oluştur (`TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`)
1. Telegram'da aramaya **`@BotFather`** yaz (yanında mavi tik olan resmi botu aç).
2. `/newbot` komutunu gönder.
   - Senden botuna bir isim (örn: `Benim UBYS Botum`) ve sonunda `bot` geçen bir kullanıcı adı (örn: `ahmet_ubys_bot`) isteyecek.
   - İşlem bitince sana `123456789:ABCdef...` şeklinde bir **Token** verecek. Bunu bir yere not al (`TELEGRAM_BOT_TOKEN`).
3. BotFather'ın verdiği `t.me/...` linkinden kendi oluşturduğun bota gir ve mutlaka alttaki **Başlat (`/start`)** butonuna bas. *(Bunu yapmazsan bot sana mesaj atamaz!)*
4. Şimdi kendi Telegram ID'ni öğrenmek için Telegram'da **`@userinfobot`** (veya `@RawDataBot`) botunu aç ve **Başlat**'a bas. Sana verdiği sayı (`Id`, örn: `987654321`) senin **`TELEGRAM_CHAT_ID`** değerindir.

### Adım 3: Notların Saklanacağı Gizli Alanı Oluştur (`GIST_ID` & `GIST_TOKEN`)
Depo herkese açık (`Public`) olduğu için bot, senin not geçmişini kodların içine değil; yalnızca senin erişebildiğin gizli bir **Secret Gist** not defterine kaydeder.

1. **`GIST_ID` oluşturma:**
   - [https://gist.github.com](https://gist.github.com) adresine git.
   - **Filename including extension** kutusuna tam olarak şunu yaz: `grades_state.json`
   - Altındaki büyük içerik kutusuna sadece iki süslü parantez yaz: `{}`
   - Sağ alttaki yeşil düğmenin yanındaki oka basıp **Create secret gist** seçeneğiyle oluştur (`Create public gist` değil, mutlaka **secret** seç!).
   - Açılan sayfanın tarayıcı adres çubuğundaki son uzun kod senin **`GIST_ID`** değerindir (`https://gist.github.com/kullaniciadin/` kısmından sonraki **uzun harf/rakam dizisi**).
2. **`GIST_TOKEN` oluşturma:**
   - [GitHub Tokens (Classic)](https://github.com/settings/tokens/new) sayfasını aç.
   - **Note** kısmına `UBYS Gist` gibi bir ad ver, **Expiration** için uygun bir süre seç (örneğin `No expiration` veya `1 year`).
   - Aşağıdaki izin kutularından **yalnızca `gist`** kutucuğunu işaretle (başka hiçbir kutucuğu işaretleme).
   - En alttaki **Generate token** düğmesine bas ve çıkan `ghp_...` kodunu kopyala (sayfadan çıkınca bir daha görünmez). Bu senin **`GIST_TOKEN`** değerindir.

### Adım 4: Bilgileri GitHub'a Güvenli Şekilde Ekle (`Secrets`)
Kendi `Fork`ladığın deponun sayfasına dön:
**Settings → Secrets and variables → Actions → Repository secrets → New repository secret** yolunu izle ve aşağıdaki **6 sırrı** tek tek ekle:

| Secret Adı | İçine Ne Yazacaksın? | Eski/Alternatif İsim |
| --- | --- | --- |
| `UBYS_USERNAME` | ÜBYS kullanıcı adın (genellikle **öğrenci numaran**) | `OGRENCI_NO` |
| `UBYS_PASSWORD` | ÜBYS giriş şifren | `SIFRE` |
| `TELEGRAM_BOT_TOKEN` | Adım 2'de `@BotFather`'dan aldığın Bot Token | `BOT_TOKEN` |
| `TELEGRAM_CHAT_ID` | Adım 2'de öğrendiğin Telegram ID numaran *(birden çok hesap için virgülle ayırabilirsin)* | `CHAT_ID` |
| `GIST_ID` | Adım 3'te oluşturduğun Secret Gist'in ID kodu | — |
| `GIST_TOKEN` | Adım 3'te aldığın sadece `gist` yetkili `ghp_...` token | — |


### Adım 5: Botu Aç ve İlk Testi Yap!
1. Deponun üst menüsünden **Actions** sekmesine tıkla.
2. *"Workflows aren't being run on this forked repository"* yazısı çıkarsa yeşil **`I understand my workflows, go ahead and enable them`** butonuna tıkla.
3. Sol menüden **Kastamonu ÜBYS Swiss Bot**'u seç.
4. Sağ taraftaki **Run workflow** açılır menüsüne tıkla:
   - **Çalıştırma kipi (`mode`):** `test_all` seç
   - **`Telegram'a test bildirimi gönder` (`test_notify`)** kutusunu işaretle ✅
   - Yeşil **Run workflow** düğmesine bas.
5. Yaklaşık **1 dakika** içinde Telegram'a ders notların, gün bazlı devamsızlık hakların, transkript özetin, günün yemek listesi ve yaklaşan akademik takvim etkinliklerin gelecektir! 🎉

Bot bundan sonra **Türkiye saatiyle 08:00 – 01:59 arası her 15 dakikada bir** otomatik olarak ÜBYS'yi kontrol eder; ayrıca yemekhane menüsü ve akademik takvim saatlerini takip eder.

---

## 🕹️ İstediğin Zaman Tek Tıkla Çalıştırma (`Run workflow`)

**Actions → Kastamonu ÜBYS Swiss Bot → Run workflow** menüsünden zamanlanmış saati beklemeden istediğin modülü tek tıkla çalıştırabilirsin:

| Kip (`mode`) | Ne Yapar? |
| --- | --- |
| `once` | Normal tam kontrolü şimdi çalıştırır (`test_notify` işaretliyse durum dosyasını bozmadan Telegram'a test özeti atar). |
| `test_all` | Kayıtlı not durumunu değiştirmeden tüm modülleri dener. |
| `attendance` | Aktif dönem derslerinin **gün bazlı devamsızlık haklarını** gösterir. |
| `transcript` | ÜBYS **transkriptini ve GANO / YANO** özetini çeker. |
| `gpa` | Tahmini dönem sonu **YANO / GANO & Onur Belgesi** durumunu hesaplar. |
| `schedule` | ÜBYS **haftalık ders programını** çeker. |
| `exams` | ÜBYS **vize/final sınav takvimini** ve salonları çeker. |
| `announcements` | OİDB, SKS ve okul **güncel duyurularını** listeler. |
| `weather` | **Kuzeykent kampüsü 3 günlük hava durumunu** gösterir. |
| `dining` | **Günün veya yaklaşan yemekhane menüsünü** (+ hava durumunu) gösterir. |
| `calendar` | **Akademik takvimde** devam eden ve yaklaşan tarihleri özetler. |
| `briefing` | **Haftalık toplu öğrenci özet brifingini** üretir. |
| `commands` | Telegram'da bota yazdığın bekleyen `/` komutlarını hemen yanıtlar. |
| `force_daily` | Günlük yemekhane, takvim, ders programı ve brifingi saat/tekrar sınırını aşarak zorla gönderir. |

*(İstediğin kipi Telegram'a da göndermek için `Telegram'a test bildirimi gönder` kutusunu işaretlemen yeterli.)*

---

## ⚙️ İsteğe Bağlı Özelleştirmeler (`Variables`)

Hiçbir ek ayar yapmazsan bot tüm özellikleri varsayılan Kastamonu Üniversitesi kurallarıyla otomatik çalıştırır. Değiştirmek istediklerini **Settings → Secrets and variables → Actions → Variables → New repository variable** yolundan ekleyebilirsin:

- **Kendi fakültenin veya MYO'nun duyurularını da eklemek için:**  
  Varsayılan olarak OİDB, SKS ve ÜBYS duyuruları taranır. Kendi okulunun web sayfasını da eklemek için `ANNOUNCEMENT_URLS` değişkeni ekleyebilirsin:
  ```text
  KMYO|https://kmyo.kastamonu.edu.tr/
  ```
- **Bazı derslerin vize/final oranı farklıysa (örn. `%30/%70`):**  
  Bot dersin oranını ÜBYS ve Eğitim Kataloğu'ndan otomatik okur. Hoca derste farklı bir oran açıkladıysa `COURSE_WEIGHTS` değişkeni ekleyip tüm kaynakların önüne geçirebilirsin:
  ```text
  BPBZ201:30/70, BPBZ207:40/60
  ```
- **Fakültene özel akademik takvim görmek için:**  
  `CALENDAR_FACULTY` değişkenine `GENEL`, `TIP`, `VET`, `DIS`, `LISANSUSTU` veya `TURIZM` (ya da kendi birim adını) yazabilirsin.
- **İstemediğin bir özelliği kapatmak için:**  
  Örneğin yemekhane, hava durumu veya duyuru bildirimini istemiyorsan `ENABLE_DINING`, `ENABLE_WEATHER` veya `ENABLE_ANNOUNCEMENTS` değerini `false` yapman yeterlidir.

<details>
<summary>📋 Tüm İsteğe Bağlı Ayarlar (Tam Liste)</summary>

| Variable Adı | Varsayılan | Açıklama |
| --- | --- | --- |
| `ENABLE_GRADES` | `true` | ÜBYS not takibini açar/kapatır |
| `ENABLE_DINING` | `true` | Hafta içi yemekhane menüsü bildirimini açar/kapatır |
| `ENABLE_WEATHER` | `true` | Sabah menüsü ve brifinge Kuzeykent hava durumunu ekler |
| `WEATHER_LOCATION` | `Kastamonu (Kuzeykent)` | Hava durumu başlığında görünecek konum adı |
| `WEATHER_LAT` / `WEATHER_LON` | `41.4307` / `33.7764` | Hava durumu koordinatları (Kuzeykent Kampüsü) |
| `ENABLE_CALENDAR` | `true` | Akademik takvim hatırlatma ve Pazartesi özetini açar/kapatır |
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
| `ENABLE_WEEKLY_BRIEFING` | `true` | Pazar akşamları haftalık toplu öğrenci brifingi gönderir |
| `WEEKLY_BRIEFING_HOUR` | `20` | Pazar günü haftalık brifing saati (`0-23`, TR saati) |
| `ENABLE_COMMANDS` | `true` | Telegram'dan gelen `/` komutlarını yanıtlar |
| `ENABLE_CATALOG` | `true` | ÜBYS Eğitim Kataloğu'ndan derslerin gerçek `T+U+L` saatlerini ve değerlendirme oranlarını otomatik çeker (`14` gün Gist önbellekli) |
| `UBYS_PROGRAM` | *(otomatik)* | Eğitim Kataloğu bölüm eşleşmesi için bölüm adı veya ID sabitlemesi |
| `MIDTERM_WEIGHT` | `0.40` | Varsayılan vize oranı (`0.40` veya `40`) |
| `FINAL_WEIGHT` | `0.60` | Varsayılan final oranı (`0.60` veya `60`) |
| `FINAL_MIN_SCORE` | `0` | Fakülte/bölüm final alt barajı (genel yönetmelik için `0`) |
| `COURSE_WEIGHTS` | *(boş)* | Ders bazlı özel vize/final oranı (`BPBZ201:30/70,BPBZ207:40/60`) |
| `SEMESTER_WEEKS` | `14` | Devamsızlık hesabında dönem hafta sayısı |
| `THEORY_MIN_ATTENDANCE` | `70` | Teorik ders devam zorunluluğu (`%70`) |
| `PRACTICE_MIN_ATTENDANCE` | `80` | Uygulamalı ders devam zorunluluğu (`%80`) |
| `COURSE_HOURS` | *(boş)* | Ders bazlı özel haftalık `T+U` saati (`BPBZ201:3+1,BPBZ207:4+0`) |
| `CALENDAR_FACULTY` | `GENEL` | Takvim birimi (`GENEL`, `TIP`, `VET`, `DIS`, `LISANSUSTU`, `TURIZM` — `BOLUM_TIPI` de desteklenir) |
| `CALENDAR_CATEGORIES` | `STUDENT` | Takvim filtresi (`STUDENT`, `ALL` veya virgüllü kategori listesi) |
| `CALENDAR_REMINDER_DAYS` | `7,3,1,0` | Etkinlik başlamadan kaç gün önce tek seferlik hatırlatma atılacağı |
| `DINING_NOTIFY_HOUR` | `8` | Yemekhane bildiriminin gönderileceği en erken saat (Türkiye saati, `0-23`) |
| `ALL_SEMESTERS` | `false` | `true` yapılırsa geçmiş dönem derslerini de tarar |
| `UBYS_USER_GROUP_ID` | *(otomatik)* | Birden fazla ÜBYS rolü olan kullanıcılar için öğrenci rolü ID'si |
| `NOTIFY_ON_FIRST_RUN` | `true` | İlk kurulumda mevcut ders özetini Telegram'a gönderir |

</details>

---

## 🔒 Güvenlik ve Gizlilik (Şifrem Güvende mi?)

- **Şifrelerin Şifrelenmiş Tutulur:** `UBYS_USERNAME`, `UBYS_PASSWORD`, `TELEGRAM_BOT_TOKEN` gibi tüm bilgiler **GitHub Secrets** içinde şifreli saklanır; GitHub Actions günlüklerinde bile otomatik olarak `***` şeklinde gizlenir ve hiçbir zaman kod dosyalarına yazılmaz.
- **Notların Açık Repoya Yazılmaz:** Not geçmişin, GANO'n ve katalog önbelleğin senin **Secret Gist** (`GIST_ID`) dosyanda tutulur; açık (`Public`) repoya hiçbir kişisel veri gönderilmez.
- **Üçüncü Taraf Sunucu Yoktur:** Bot tamamen **senin kendi GitHub hesabında** çalışır ve yalnızca resmi `*.kastamonu.edu.tr`, `api.open-meteo.com`, `api.telegram.org` ve `api.github.com` adresleriyle haberleşir.
- **Açık Kaynak:** Tüm Python kodları bu depoda şeffaf şekilde incelenebilir.

---

## ❓ Sık Sorulan Sorular ve Sorun Giderme

- **Telegram'dan hiç mesaj gelmiyor, ne yapmalıyım?**  
  1. Kendi oluşturduğun bota Telegram'da girip **`/start`** (Başlat) butonuna bastığından emin ol.  
  2. `TELEGRAM_CHAT_ID` içinde kendi sayısal ID'nin (`@userinfobot` çıktısı) doğru yazıldığını ve başında/sonunda boşluk olmadığını kontrol et.

- **`GitHub Gist / Durum Okuma Hatası (HTTP 401)` uyarısı aldım:**  
  `GIST_TOKEN` süren dolmuş veya token oluşturulurken **`gist`** kutucuğu işaretlenmemiş demektir. [GitHub Tokens](https://github.com/settings/tokens/new) sayfasından sadece `gist` yetkili yeni bir token üretip **Settings → Secrets → `GIST_TOKEN`** değerini güncellemen yeterlidir (not geçmişin silinmez).

- **ÜBYS şifremi değiştirdim, bot hata vermeye başladı:**  
  **Settings → Secrets → `UBYS_PASSWORD`** değerini yeni şifrenle güncelle; bot bir sonraki çalıştırmada kaldığı yerden devam eder. *(Güvenlik nedeniyle şifre hatalıysa tekrar kilitlenmemek için hata uyarısı yalnızca 1 kez atılır.)*

- **GitHub'dan "60 gün boyunca depoda değişiklik yapılmadığı için zamanlanmış çalışma durdurulacak" e-postası geldi:**  
  GitHub kuralı gereği bir depoya 60 gün boyunca commit atılmazsa otomatik cron çalışması duraklatılır. **Actions** sekmesine girip **Enable workflow**'a tıklaman veya depoda küçük bir düzenleme yapman 2 aylığına yeniden aktif eder.

- **Bir dersimin vize/final oranı veya teorik/uygulama saati hocanın söylediğiyle uyuşmuyor:**  
  Hocalar dönem içinde Eğitim Kataloğu'ndan farklı oran/saat uygulayabiliyor. **Settings → Variables** içine `COURSE_WEIGHTS` (örn. `BPBZ201:30/70`) veya `COURSE_HOURS` (örn. `BPBZ201:3+1`) ekleyerek o dersi hemen düzeltebilirsin.

---

## 💻 Kendi Bilgisayarında / Docker ile Çalıştırma (Geliştiriciler İçin)

<details>
<summary>🛠️ Yerel Kurulum, CLI Komutları, Testler ve Docker</summary>

### Kurulum

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

</details>

---

## 📄 Lisans ve Notlar

Bu proje [GPL-3.0](LICENSE) lisansı ile sunulan bağımsız ve açık kaynaklı bir öğrenci aracıdır; Kastamonu Üniversitesi'nin resmî uygulaması değildir.
