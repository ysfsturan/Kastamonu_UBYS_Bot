<div align="right">
  <a href="#-english">🇬🇧 English</a> • <a href="#-türkçe">🇹🇷 Türkçe</a>
</div>

# 🇬🇧 English

# 🎓 Kastamonu University UBYS Bot

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-4.0%2B-43B02A?style=for-the-badge&logo=selenium&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)

This project is a comprehensive bot developed for **Kastamonu University** students.

Instead of constantly visiting different sites (UBYS, SKS, Academic Calendar) to check for updates, this bot runs automatically on **GitHub Actions** (4 times a day) and instantly sends every relevant update directly to your phone via **Telegram**.

---

## 🚀 Features

### 📊 1. Advanced Grade Tracking (UBYS)
* **🔐 Secure Data:** Your grades are kept encrypted on **GitHub Secret Gist**. No one else can see them.
* **⚡ Instant Notification:** Sends a notification with the course name and grade when a new score is entered (Midterm, Final, Makeup, Homework).
* **🧠 Target Calculation:** When your midterm grade is announced, it calculates what you need to score on the final to pass the course (CC) or achieve a high grade (AA).
* **🎓 GPA Tracking:** Notifies you when your GPA (GANO) or Semester GPA (YANO) changes on your transcript.

### 📅 2. Smart Academic Calendar
* **⏳ Countdown:** Starts a countdown timer 45 days before important dates like Midterms, Finals, and Registration Week.
* **🛡️ Department Filter:** Automatically filters out the dates of faculties that don't concern you, such as Medicine or Veterinary, and shows only the ones relevant to you.

### 🍽️ 3. Cafeteria Menu (SKS)
* **🥘 Daily Menu:** Reports what will be served in the cafeteria that day (Soup, Main Course, Dessert, etc.) every morning.
* **💤 Weekend Mode:** Does not send unnecessary notifications on weekends since the cafeteria is closed.

---

## 🛠️ Installation Guide

Follow the steps below in order to run this project on your own account.

### 1. Fork the Repo
Copy the project to your own GitHub account by clicking the **Fork** button in the top right corner.

### 2. Create a Secret Database (Gist)
1. Go to [gist.github.com](https://gist.github.com).
2. Type `notlar.json` in the filename section.
3. Put only two curly braces in the content section: `{}`
4. Select the **"Create secret gist"** option from the green button and create it.
5. Copy the complex code at the end of the link in your browser's address bar. (This will be your `GIST_ID`).

### 3. Get an Access Token
1. On GitHub, navigate to **Settings** -> **Developer Settings** -> **Personal access tokens** -> **Tokens (classic)**.
2. Create a new token by clicking **"Generate new token (classic)"**.
3. Give it a name (e.g., UBYS Bot) and check only the **`gist`** box under the scopes.
4. Copy the generated code at the bottom. (This will be your `GIST_TOKEN`).

### 4. Set Up the Telegram Bot
1. Find **[@BotFather](https://t.me/BotFather)** on Telegram and create a new bot with the `/newbot` command. Save the **API Token** it gives you.
2. Open **[@userinfobot](https://t.me/userinfobot)** on Telegram and send `/start` to find out your own **Chat ID**.

### 5. Define GitHub Secrets
You must introduce your credentials to the project for the bot to work. Go to **Settings** > **Secrets and variables** > **Actions** on your repo page, click `New repository secret`, and add the following variables:

| Secret Name | Value (Example) | Description |
| :--- | :--- | :--- |
| `OGRENCI_NO` | `242609006` | Your UBYS Student number |
| `SIFRE` | `password123` | Your UBYS login password |
| `BOT_TOKEN` | `123456:ABC...` | Token received from Telegram BotFather |
| `CHAT_ID` | `987654321` | Your Telegram user ID |
| `GIST_ID` | `abc123xyz...` | The Gist ID you got in step 2 |
| `GIST_TOKEN` | `ghp_12345...` | The GitHub Token you got in step 3 |
| `BOLUM_TIPI` | `GENEL` | Type `GENEL` for regular departments, `TIP` for Medicine, `VET` for Veterinary. |

### 6. Activate the Bot
After setting everything up, run the bot manually for the first time:
1. Go to the **Actions** tab.
2. Select the **UBYS Bot Daily Run** workflow on the left side.
3. Press the **Run workflow** button on the right side.

🎉 **Congratulations!** Your bot is now set up. It will run automatically 4 times a day (09:00, 13:00, 17:00, 21:00).

---

## ❓ Frequently Asked Questions

**Q: Is my password safe?**
A: Yes. Even if your GitHub Repo is "Public", no one else can see your passwords because you store them inside **Secrets**.

**Q: Can my grades be seen by others?**
A: No. Since the Gist where your grades are saved is "Secret", no one without the direct link can access it.

**Q: How often does the bot run?**
A: By default, it runs 4 times a day at **09:00, 13:00, 17:00, and 21:00** Turkish time.

---

## 📞 Contact & Support

If you notice a bug or have a feature request regarding the project, please open an **[Issue](https://github.com/ysfsturan/Kastamonu_UBYS_Bot/issues)**.

<div align="center">

---

## ⚠️ Legal Disclaimer

This project was developed entirely for **educational purposes** and is strictly for personal use.

The project has **no** official affiliation, collaboration, or connection with the **Kastamonu University IT Department** or any official unit of the university. The 100% accuracy of the data provided by the bot (exam dates, grades, etc.) is not guaranteed; it is the user's responsibility to follow official announcements.

Any technical and legal responsibility that may arise from the use of the software belongs entirely to the user.

---

Made with ❤️ by <a href="https://www.linkedin.com/in/yusufsamituran" target="_blank"><b>Yusuf Sami Turan</b></a>

</div>

<br><br>

---

# 🇹🇷 Türkçe

# 🎓 Kastamonu Üniversitesi UBYS Bot

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-4.0%2B-43B02A?style=for-the-badge&logo=selenium&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)

Bu proje, **Kastamonu Üniversitesi** öğrencileri için geliştirilmiş kapsamlı bir botdur.

Sürekli farklı sitelere (UBYS, SKS, Akademik Takvim) girip kontrol etmek yerine; bu bot **GitHub Actions** üzerinde (günde 4 kez) otomatik çalışır ve sizi ilgilendiren her gelişmeyi **Telegram** üzerinden anlık olarak telefonunuza gönderir.

---

## 🚀 Özellikler

### 📊 1. Gelişmiş Not Takibi (UBYS)
* **🔐 Güvenli Veri:** Notlarınız **GitHub Secret Gist** üzerinde şifreli tutulur. Sizden başka kimse göremez.
* **⚡ Anlık Bildirim:** Yeni not girildiğinde (Vize, Final, Büt, Ödev) ders adı ve notuyla birlikte bildirim atar.
* **🧠 Hedef Hesaplama:** Vize notunuz açıklandığında, dersi geçmek (CC) veya derece yapmak (AA) için finalden kaç almanız gerektiğini hesaplar.
* **🎓 GANO Takibi:** Transkriptinizde GANO veya YANO değiştiğinde haber verir.

### 📅 2. Akıllı Akademik Takvim
* **⏳ Geri Sayım:** Vize, Final, Kayıt Haftası gibi önemli tarihlere 45 gün kala geri sayım sayacı başlatır.
* **🛡️ Bölüm Filtresi:** Tıp veya Veterinerlik gibi sizi ilgilendirmeyen fakültelerin tarihlerini otomatik filtreler, sadece sizi ilgilendirenleri gösterir.

### 🍽️ 3. Yemekhane Menüsü (SKS)
* **🥘 Günün Menüsü:** Her sabah o gün yemekhanede ne çıkacağını (Çorba, Ana Yemek, Tatlı vb.) size raporlar.
* **💤 Hafta Sonu Modu:** Hafta sonları yemekhane kapalı olduğu için boş yere bildirim atmaz.

---

## 🛠️ Kurulum Rehberi

Bu projeyi kendi hesabınızda çalıştırmak için aşağıdaki adımları sırasıyla uygulayın.

### 1. Repoyu Forklayın
Sağ üst köşedeki **Fork** butonuna tıklayarak projeyi kendi GitHub hesabınıza kopyalayın.

### 2. Gizli Veritabanı (Gist) Oluşturun
1. [gist.github.com](https://gist.github.com) adresine gidin.
2. Dosya adı kısmına `notlar.json` yazın.
3. İçerik kısmına sadece iki süslü parantez koyun: `{}`
4. Yeşil butondan **"Create secret gist"** seçeneğini seçip oluşturun.
5. Tarayıcı adres çubuğundaki linkin sonundaki karmaşık kodu kopyalayın. (Bu sizin `GIST_ID` niz olacak).

### 3. Erişim İzni (Token) Alın
1. GitHub'da **Settings** -> **Developer Settings** -> **Personal access tokens** -> **Tokens (classic)** yolunu izleyin.
2. **"Generate new token (classic)"** diyerek yeni bir token oluşturun.
3. İsim verin (Örn: UBYS Bot) ve izinlerden (Scopes) sadece **`gist`** kutucuğunu işaretleyin.
4. En altta oluşturulan kodu kopyalayın. (Bu sizin `GIST_TOKEN` ınız olacak).

### 4. Telegram Botunu Ayarlayın
1. Telegram'da **[@BotFather](https://t.me/BotFather)**'ı bulun ve `/newbot` komutu ile yeni bir bot oluşturun. Size vereceği **API Token**'ı kaydedin.
2. Telegram'da **[@userinfobot](https://t.me/userinfobot)**'u açıp `/start` diyerek kendi **Chat ID**'nizi öğrenin.

### 5. GitHub Secrets Tanımlama
Botun çalışması için şifrelerinizi projeye tanıtmalısınız. Repo sayfanızda **Settings** > **Secrets and variables** > **Actions** kısmına gidin ve `New repository secret` diyerek şu değişkenleri ekleyin:

| Secret Adı | Değer (Örnek) | Açıklama |
| :--- | :--- | :--- |
| `OGRENCI_NO` | `242609006` | UBYS Öğrenci numaranız |
| `SIFRE` | `sifreniz123` | UBYS giriş şifreniz |
| `BOT_TOKEN` | `123456:ABC...` | Telegram BotFather'dan alınan token |
| `CHAT_ID` | `987654321` | Telegram kullanıcı ID'niz |
| `GIST_ID` | `abc123xyz...` | 2. adımda aldığınız Gist ID |
| `GIST_TOKEN` | `ghp_12345...` | 3. adımda aldığınız GitHub Token |
| `BOLUM_TIPI` | `GENEL` | Normal bölümler için `GENEL`, Tıp için `TIP`, Veterinerlik için `VET` yazın. |

### 6. Botu Aktifleştirin
Her şeyi ayarladıktan sonra botu ilk kez manuel çalıştırın:
1. **Actions** sekmesine gidin.
2. Sol taraftaki **UBYS Bot Daily Run** workflow'unu seçin.
3. Sağ taraftaki **Run workflow** butonuna basın.

🎉 **Tebrikler!** Artık botunuz kuruldu. Günde 4 kez (09:00, 13:00, 17:00, 21:00) otomatik çalışacaktır.

---

## ❓ Sıkça Sorulan Sorular

**S: Şifrem güvende mi?**
C: Evet. GitHub Reponuz "Public" olsa bile, şifrelerinizi **Secrets** içine girdiğiniz için sizden başka kimse göremez.

**S: Notlarım başkaları tarafından görülebilir mi?**
C: Hayır. Notlarınızın kaydedildiği Gist "Secret" (Gizli) olduğu için linki bilmeyen kimse erişemez.

**S: Bot ne sıklıkla çalışıyor?**
C: Varsayılan olarak Türkiye saatiyle **09:00, 13:00, 17:00 ve 21:00** olmak üzere günde 4 kez çalışır.

---

## 📞 İletişim & Destek

Proje ile ilgili bir hata fark ederseniz veya özellik isteğiniz varsa lütfen bir **[Issue](https://github.com/ysfsturan/Kastamonu_UBYS_Bot/issues)** açın.

<div align="center">

---

## ⚠️ Yasal Uyarı

Bu proje tamamen **eğitim amaçlı** geliştirilmiştir ve sadece kişisel kullanım içindir.

Projenin, **Kastamonu Üniversitesi Bilgi İşlem Daire Başkanlığı** veya üniversitenin herhangi bir resmi birimi ile hiçbir resmi bağı, iş birliği veya ilişiği **yoktur**. Botun sağladığı verilerin (sınav tarihleri, notlar vb.) %100 doğruluğu garanti edilmez; resmi duyuruları takip etmek kullanıcının sorumluluğundadır.

Yazılımın kullanımından doğabilecek her türlü teknik ve yasal sorumluluk tamamen kullanıcıya aittir.

---

Made with ❤️ by <a href="https://www.linkedin.com/in/yusufsamituran" target="_blank"><b>Yusuf Sami Turan</b></a>

</div>
