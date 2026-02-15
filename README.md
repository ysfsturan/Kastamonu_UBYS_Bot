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
1.  [gist.github.com](https://gist.github.com) adresine gidin.
2.  Dosya adı kısmına `notlar.json` yazın.
3.  İçerik kısmına sadece iki süslü parantez koyun: `{}`
4.  Yeşil butondan **"Create secret gist"** seçeneğini seçip oluşturun.
5.  Tarayıcı adres çubuğundaki linkin sonundaki karmaşık kodu kopyalayın. (Bu sizin `GIST_ID` niz olacak).

### 3. Erişim İzni (Token) Alın
1.  GitHub'da **Settings** -> **Developer Settings** -> **Personal access tokens** -> **Tokens (classic)** yolunu izleyin.
2.  **"Generate new token (classic)"** diyerek yeni bir token oluşturun.
3.  İsim verin (Örn: UBYS Bot) ve izinlerden (Scopes) sadece **`gist`** kutucuğunu işaretleyin.
4.  En altta oluşturulan kodu kopyalayın. (Bu sizin `GIST_TOKEN` ınız olacak).

### 4. Telegram Botunu Ayarlayın
1.  Telegram'da **[@BotFather](https://t.me/BotFather)**'ı bulun ve `/newbot` komutu ile yeni bir bot oluşturun. Size vereceği **API Token**'ı kaydedin.
2.  Telegram'da **[@userinfobot](https://t.me/userinfobot)**'u açıp `/start` diyerek kendi **Chat ID**'nizi öğrenin.

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
1.  **Actions** sekmesine gidin.
2.  Sol taraftaki **UBYS Bot Daily Run** workflow'unu seçin.
3.  Sağ taraftaki **Run workflow** butonuna basın.

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
