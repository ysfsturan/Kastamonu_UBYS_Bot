"""Kastamonu Üniversitesi SKS Yemekhane menüsü çekme ve ayrıştırma modülü."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .models import DailyMenu, DiningItem

_CATEGORY_LABELS = ("Çorba", "Ana Yemek", "Yardımcı", "Soğuk / Tatlı")
_TR_UPPER_MAP = {
    "i": "İ",
    "ı": "I",
    "ğ": "Ğ",
    "ü": "Ü",
    "ş": "Ş",
    "ö": "Ö",
    "ç": "Ç",
}
_CALORIE_RE = re.compile(r"(\d{1,4})\s*(?:kkal|kcal)", re.IGNORECASE)
_CALORIE_STRIP_RE = re.compile(r"\d{1,4}\s*(?:kkal|kcal)", re.IGNORECASE)


class DiningError(Exception):
    """Yemekhane menüsü alınırken veya ayrıştırılırken oluşan hata."""


def _tr_lower(text: str) -> str:
    return " ".join(text.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "").split())


def _tr_upper_char(ch: str) -> str:
    return _TR_UPPER_MAP.get(ch, ch.upper())


def tr_title(text: str) -> str:
    """Türkçe harf kurallarına uygun Başlık Düzeni uygular."""
    normalized = " ".join((text or "").split())
    if not normalized:
        return ""

    # KÖFTE(PATATES) -> KÖFTE (PATATES), MUSAKKA/ KÖRİLİ -> MUSAKKA / KÖRİLİ
    normalized = re.sub(r"([A-Za-zÇĞİÖŞÜçğıöşü0-9.])\(", r"\1 (", normalized)
    normalized = re.sub(r"\s*/\s*", " / ", normalized)
    lowered = normalized.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "")

    chars = list(lowered)
    capitalize_next = True
    for idx, ch in enumerate(chars):
        if ch.isalpha():
            if capitalize_next:
                chars[idx] = _tr_upper_char(ch)
                capitalize_next = False
        elif ch in {" ", "(", "/", "-", "\t"}:
            capitalize_next = True
        elif ch == ".":
            capitalize_next = idx + 1 < len(chars) and chars[idx + 1] == " "

    return " ".join("".join(chars).split())


def parse_turkish_date(raw: str) -> Optional[date]:
    """'2.11.2026' veya '19.11.2026' gibi tarih metinlerini date nesnesine çevirir."""
    match = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*$", raw or "")
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_calorie_range(raw: str) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """'185KKAL' veya '224KKAL/ 302KKAL' gibi kalori hücrelerini ayrıştırır."""
    matches = _CALORIE_RE.findall(raw or "")
    if not matches:
        return None, None, None

    values = [int(m) for m in matches]
    display = f"{values[0]} kkal" if len(values) == 1 else f"{'/'.join(str(v) for v in values)} kkal"
    return display, min(values), max(values)


def _is_pure_calorie_cell(raw: str) -> bool:
    cal_display, _, _ = parse_calorie_range(raw)
    if cal_display is None:
        return False
    leftover = _CALORIE_STRIP_RE.sub("", raw).strip(" /-,.")
    return leftover == ""


def extract_dining_sheet_url(sks_html: str) -> Optional[str]:
    """SKS ana sayfasından Google Sheets yemek listesi bağlantısını çıkarır."""
    soup = BeautifulSoup(sks_html, "html.parser")
    candidates: list[tuple[str, str]] = []
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        if "docs.google.com/spreadsheets" in href or "drive.google.com" in href:
            label = _tr_lower(link.get_text(" ", strip=True))
            candidates.append((label, href))

    if not candidates:
        return None

    for label, href in candidates:
        if "yemek" in label or "menü" in label or "menu" in label:
            return href
    return candidates[0][1]


def build_csv_export_url(sheet_url: str) -> str:
    """Google Sheets paylaşım bağlantısını doğrudan CSV export URL'sine dönüştürür."""
    cleaned = sheet_url.strip()
    if "/export" in cleaned and "format=csv" in cleaned:
        return cleaned

    id_match = re.search(r"/d/([a-zA-Z0-9_-]+)", cleaned)
    if not id_match:
        if "format=csv" in cleaned:
            return cleaned
        raise DiningError(f"Geçersiz yemekhane e-tablo adresi: {sheet_url}")

    sheet_id = id_match.group(1)
    gid_match = re.search(r"[#?&]gid=(\d+)", cleaned)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def parse_dining_csv(csv_text: str, source_url: Optional[str] = None) -> list[DailyMenu]:
    """Kastamonu SKS Google Sheets CSV çıktısından günlük menüleri ayrıştırır."""
    by_date: dict[date, DailyMenu] = {}

    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        date_idx: Optional[int] = None
        parsed_date: Optional[date] = None
        for idx, cell in enumerate(row):
            parsed = parse_turkish_date(cell)
            if parsed is not None:
                date_idx = idx
                parsed_date = parsed
                break

        if date_idx is None or parsed_date is None:
            continue

        items: list[DiningItem] = []
        total_min = 0
        total_max = 0
        has_calories = False

        idx = date_idx + 1
        while idx < len(row):
            raw_cell = " ".join(row[idx].split())
            if not raw_cell:
                idx += 1
                continue

            if _is_pure_calorie_cell(raw_cell):
                idx += 1
                continue

            cal_display: Optional[str] = None
            c_min: Optional[int] = None
            c_max: Optional[int] = None
            if idx + 1 < len(row):
                next_cell = " ".join(row[idx + 1].split())
                if _is_pure_calorie_cell(next_cell):
                    cal_display, c_min, c_max = parse_calorie_range(next_cell)
                    idx += 2
                else:
                    idx += 1
            else:
                idx += 1

            category = _CATEGORY_LABELS[len(items)] if len(items) < len(_CATEGORY_LABELS) else "Diğer"
            items.append(
                DiningItem(
                    name=tr_title(raw_cell),
                    calories=cal_display,
                    category=category,
                )
            )
            if c_min is not None and c_max is not None:
                has_calories = True
                total_min += c_min
                total_max += c_max

        if items:
            by_date[parsed_date] = DailyMenu(
                menu_date=parsed_date,
                items=items,
                total_calories_min=total_min if has_calories else None,
                total_calories_max=total_max if has_calories else None,
                source_url=source_url,
            )

    return sorted(by_date.values(), key=lambda m: m.menu_date)


def fetch_dining_menus(
    sks_url: str = "https://sks.kastamonu.edu.tr/",
    sheet_url_override: Optional[str] = None,
    timeout: float = 20.0,
) -> list[DailyMenu]:
    """SKS sayfasından güncel yemek listesi linkini bulup tüm günlük menüleri çeker."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    }
    try:
        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout, connect=min(15.0, timeout)),
        ) as client:
            sheet_url = sheet_url_override
            if not sheet_url:
                sks_resp = client.get(sks_url)
                if sks_resp.status_code >= 400:
                    raise DiningError(f"SKS sayfası açılamadı: HTTP {sks_resp.status_code}")
                sheet_url = extract_dining_sheet_url(sks_resp.text)
                if not sheet_url:
                    raise DiningError("SKS sayfasında yemekhane Google Sheets bağlantısı bulunamadı.")

            csv_url = build_csv_export_url(sheet_url)
            csv_resp = client.get(csv_url)
            if csv_resp.status_code >= 400:
                raise DiningError(f"Yemek listesi CSV verisi indirilemedi: HTTP {csv_resp.status_code}")

            csv_text = csv_resp.content.decode("utf-8-sig", errors="replace")
            if "<html" in csv_text[:400].lower():
                raise DiningError("Yemek listesi CSV yerine HTML sayfası döndürdü (erişim kısıtlı olabilir).")

            return parse_dining_csv(csv_text, source_url=sheet_url)
    except DiningError:
        raise
    except httpx.HTTPError as exc:
        raise DiningError(f"Yemekhane verisi alınırken ağ hatası: {exc}") from exc


def get_menu_for_date(menus: list[DailyMenu], target_date: date) -> Optional[DailyMenu]:
    for menu in menus:
        if menu.menu_date == target_date:
            return menu
    return None


def get_next_menu(menus: list[DailyMenu], from_date: date) -> Optional[DailyMenu]:
    for menu in sorted(menus, key=lambda m: m.menu_date):
        if menu.menu_date >= from_date:
            return menu
    return None
