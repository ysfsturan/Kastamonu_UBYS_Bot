import time
import os
import json
import re
import math
import csv
import io
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

UBYS_URL = "https://ubys.kastamonu.edu.tr/"
SKS_URL = "https://sks.kastamonu.edu.tr/"
TAKVIM_URL = "https://akademiktakvim.kastamonu.edu.tr/"

OGRENCI_NO = os.environ.get("OGRENCI_NO")
SIFRE = os.environ.get("SIFRE")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GIST_ID = os.environ.get("GIST_ID")
GIST_TOKEN = os.environ.get("GIST_TOKEN")
BOLUM_TIPI = os.environ.get("BOLUM_TIPI", "GENEL")

XPATH_KULLANICI_ADI = '//*[@id="username"]'
XPATH_SIFRE = '//*[@id="password"]'
XPATH_GIRIS_BUTONU = '//*[@id="loginForm"]/div[3]/div[1]/button'

def telegram_gonder(mesaj):
    if not mesaj or not mesaj.strip():
        return
    try:
        if BOT_TOKEN and CHAT_ID:
            if len(mesaj) > 4000:
                for i in range(0, len(mesaj), 4000):
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                  json={"chat_id": CHAT_ID, "text": mesaj[i:i+4000], "parse_mode": "Markdown"})
            else:
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                              json={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"})
            print("📤 Telegram mesajı gönderildi.")
    except Exception as e:
        print(f"Telegram Hatası: {e}")

def akademik_takvim_sayaci(driver):
    print(f"📅 Takvim Modu: {BOLUM_TIPI} taranıyor...")
    
    aylar = {
        "Oca": 1, "Şub": 2, "Mar": 3, "Nis": 4, "May": 5, "Haz": 6,
        "Tem": 7, "Ağu": 8, "Eyl": 9, "Eki": 10, "Kas": 11, "Ara": 12,
        "Ocak": 1, "Şubat": 2, "Mart": 3, "Nisan": 4, "Mayıs": 5, "Haziran": 6,
        "Temmuz": 7, "Ağustos": 8, "Eylül": 9, "Ekim": 10, "Kasım": 11, "Aralık": 12
    }
    
    try:
        driver.get(TAKVIM_URL)
        wait = WebDriverWait(driver, 20)
        
        if BOLUM_TIPI != "GENEL":
            fakulte = "Tıp Fakültesi" if BOLUM_TIPI == "TIP" else "Veteriner" if BOLUM_TIPI == "VET" else ""
            if fakulte:
                try:
                    btn = wait.until(EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{fakulte}')]")))
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(3)
                except: pass

        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 700):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        metinler = [s.strip() for s in soup.get_text(separator="\n").split("\n") if len(s.strip()) > 1]
        
        bugun = datetime.now()
        mesaj_listesi = []
        eklenenler = set()
        tarih_regex = re.compile(r'(\d{1,2})\s+([a-zA-ZğüşıöçĞÜŞİÖÇ]+)\s+(\d{4})')
        
        gereksiz_kelimeler = ["Senato", "Yönetim Kurulu", "Akademik Kurul", "Anabilim Dalı", "Danışma Kurulu"]
        if BOLUM_TIPI == "GENEL": gereksiz_kelimeler.append("Ders Kurulu")

        for i, satir in enumerate(metinler):
            if "Tarih:" in satir:
                try:
                    if i > 0: etkinlik_adi = metinler[i-1].strip()
                    else: continue

                    if any(g in etkinlik_adi for g in gereksiz_kelimeler): continue

                    if i + 1 < len(metinler):
                        tarih_satiri = metinler[i+1].strip()
                        match = tarih_regex.search(tarih_satiri)
                        if match:
                            gun, ay_str, yil = match.groups()
                            ay_num = 0
                            for k, v in aylar.items():
                                if k in ay_str: ay_num = v; break
                            if ay_num == 0: continue

                            tarih_obj = datetime(int(yil), ay_num, int(gun))
                            kalan_gun = (tarih_obj - bugun).days + 1
                            
                            if 0 <= kalan_gun <= 45:
                                anahtar = f"{gun}.{ay_num}.{yil}-{etkinlik_adi}"
                                if anahtar in eklenenler: continue
                                eklenenler.add(anahtar)

                                durum = f"{kalan_gun} gün kaldı"
                                if kalan_gun == 0: durum = "BUGÜN"
                                
                                ikon = "📅"
                                k_isim = etkinlik_adi.lower()
                                if "vize" in k_isim or "ara sınav" in k_isim: ikon = "📝 VİZE"
                                elif "final" in k_isim or "yıl sonu" in k_isim: ikon = "🏁 FİNAL"
                                elif "bütünleme" in k_isim: ikon = "🆘 BÜT"
                                elif "kayıt" in k_isim: ikon = "✍️ KAYIT"
                                elif "tatil" in k_isim or "bayram" in k_isim: ikon = "🏖️ TATİL"
                                
                                mesaj_listesi.append(f"{ikon} *{etkinlik_adi}*\n🗓️ {gun}.{ay_num}.{yil} ({durum})")
                except: continue

        if mesaj_listesi: return "📅 *AKADEMİK TAKVİM*\n\n" + "\n\n".join(mesaj_listesi)
        return None
    except Exception as e:
        print(f"Takvim Hatası: {e}"); return None

def yemek_menusunu_getir(driver):
    print("🥘 Gurme Modu çalışıyor...")
    bugun = datetime.now().strftime("%d.%m.%Y")
    try:
        driver.get(SKS_URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        linkler = driver.find_elements(By.TAG_NAME, "a"); sheet_url = None
        for l in linkler:
            h = l.get_attribute("href"); t = l.text.lower() if l.text else ""
            if h and ("docs.google.com" in h or "drive.google.com" in h):
                if "yemek" in t or "menü" in t: sheet_url = h; break
        if not sheet_url:
             for l in linkler:
                h = l.get_attribute("href")
                if h and ("docs.google.com" in h or "drive.google.com" in h): sheet_url = h; break
        if not sheet_url: return None
        csv_url = sheet_url.split("/edit")[0] + "/export?format=csv" if "/d/" in sheet_url else sheet_url.replace("/view", "/export?format=csv")
        r = requests.get(csv_url); r.encoding = 'utf-8'; csv_io = io.StringIO(r.text); reader = csv.reader(csv_io)
        yemekler = []
        for row in reader:
            if not row: continue
            if bugun in " ".join(row):
                for cell in row:
                    c = cell.strip()
                    if c and bugun not in c and not c.isdigit() and "kcal" not in c.lower() and len(c) > 3:
                        yemekler.append(c)
                break
        if yemekler:
            msj = f"🍽️ *GÜNÜN MENÜSÜ ({bugun})*\n"
            for y in yemekler: msj += f"👉 {y.title()}\n"
            return msj
        return None
    except: return None

def final_ihtiyac_hesapla(vize):
    try:
        v = float(vize.replace(",", "."))
        if v == 0: return None
        h = {"Geçmek (DC)": 55, "Rahat (CC)": 60, "Ortalama (BB)": 75, "Kral (AA)": 90}; m = []
        for k, val in h.items():
            f = math.ceil((val - (v * 0.4)) / 0.6)
            if 0 < f <= 100: m.append(f"{k}: {f}")
        return "\n".join(m)
    except: return None

def gano_cek(driver):
    try:
        driver.get("https://ubys.kastamonu.edu.tr/AIS/Student/Transkript/Index")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Birikimli')]")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for tr in soup.find_all("tr"):
            if "Birikimli" in tr.get_text(): return tr.find_all("td")[-1].get_text(strip=True)
    except: return None

def gist_islem(islem, veri=None):
    if not GIST_ID or not GIST_TOKEN: return {} if islem == "cek" else None
    h = {"Authorization": f"token {GIST_TOKEN}"}
    if islem == "cek":
        try: return json.loads(requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=h).json()["files"]["notlar.json"]["content"])
        except: return {}
    elif islem == "yaz" and veri:
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=h, json={"files": {"notlar.json": {"content": json.dumps(veri, indent=4)}}})

def metni_temizle(ders, ham):
    yasak = ["Ders", "Kredi", "AKTS", "Durum", "Başarı"]; notlar = []
    bulunan = re.findall(r'([a-zA-Zçğıöşü0-9\s\.\-]+)\s*[:|]\s*([\d,]+)', ham)
    vize_notu = None; final_var = False
    for i, d in bulunan:
        if any(y in i for y in yasak) or i.lower() in ders.lower(): continue
        ikon = "📄" if "vize" in i.lower() else "🏁" if "final" in i.lower() else "📝"
        if "vize" in i.lower(): vize_notu = d
        if "final" in i.lower(): final_var = True
        notlar.append(f"{ikon} *{i.strip()}:* `{d}`")
    msj = f"📚 *{ders}*\n" + " | ".join(notlar)
    if vize_notu and not final_var:
        analiz = final_ihtiyac_hesapla(vize_notu)
        if analiz: msj += f"\n\n🧠 *Hedef:*\n{analiz}"
    harf = re.search(r'\b(AA|BA|BB|CB|CC|DC|DD|FD|FF)\b', ham)
    if harf: msj += f"\n🔠 *Harf:* `{harf.group(1)}`"
    return msj if notlar or harf else None

def main():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    bulunan_bise_var_mi = False
    try:
        takvim = akademik_takvim_sayaci(driver)
        if takvim: telegram_gonder(takvim); bulunan_bise_var_mi = True
        yemek = yemek_menusunu_getir(driver)
        if yemek: telegram_gonder(yemek); bulunan_bise_var_mi = True
        print("🌍 UBYS..."); driver.get(UBYS_URL)
        wait = WebDriverWait(driver, 30)
        wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_KULLANICI_ADI))).send_keys(OGRENCI_NO)
        driver.find_element(By.XPATH, XPATH_SIFRE).send_keys(SIFRE)
        driver.find_element(By.XPATH, XPATH_GIRIS_BUTONU).click()
        time.sleep(5); driver.get("https://ubys.kastamonu.edu.tr/AIS/Student/Class/Index"); time.sleep(5)
        ifr = driver.find_elements(By.TAG_NAME, "iframe")
        if ifr: driver.switch_to.frame(ifr[0])
        html = driver.page_source; driver.switch_to.default_content() if ifr else None
        if html:
            soup = BeautifulSoup(html, "html.parser"); yeni = {}; son = "Genel"
            for tr in soup.find_all("tr"):
                cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"]) if c.get_text(strip=True)]
                if not cols or "Ders Kodu" in cols[0]: continue
                if len(cols) > 1 and len(cols[1]) > 3 and not any(c.isdigit() for c in cols[1]): son = cols[1]
                else: yeni[son] = yeni.get(son, "") + " | " + " | ".join(cols)
            eski = gist_islem("cek"); yano = None; gano = gano_cek(driver)
            for d, icerik in yeni.items():
                if icerik != eski.get(d, "") and len(icerik) > 5:
                    msj = metni_temizle(d, icerik)
                    if msj:
                        alt = f" | 🎓 GANO: {gano}" if gano else ""
                        telegram_gonder(f"📢 *YENİ NOT!* \n\n{msj}\n{alt}")
                        bulunan_bise_var_mi = True
            if yeni: gist_islem("yaz", yeni)
    except Exception as e:
        telegram_gonder(f"❌ HATA: {str(e)}"); bulunan_bise_var_mi = True
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
