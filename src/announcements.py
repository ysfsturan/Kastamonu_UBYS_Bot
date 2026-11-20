"""Kastamonu Üniversitesi (OİDB, SKS, Fakülte/MYO) duyuru takip modülü."""

from __future__ import annotations

from collections import Counter
import hashlib
import logging
import re
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from .models import Announcement

logger = logging.getLogger(__name__)

DEFAULT_ANNOUNCEMENT_SOURCES: list[tuple[str, str]] = [
    ("OİDB", "https://oidb.kastamonu.edu.tr/"),
    ("SKS", "https://sks.kastamonu.edu.tr/"),
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_LEADING_DATE_RE = re.compile(
    r"^(?:\d{1,2}\s+[A-ZÇĞİÖŞÜa-zçğıöşü]{3,10}(?:\s+\d{4})?|[A-ZÇĞİÖŞÜa-zçğıöşü]{3,10}\s+\d{1,2})\s+(.+)$"
)


class AnnouncementError(Exception):
    """Duyuru sayfaları alınırken oluşan hata."""


def _clean_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    cleaned = " ".join(raw.split())
    cleaned = re.sub(r"\s+([’'])", r"\1", cleaned)
    return re.sub(r"([A-Za-zÇĞİÖŞÜçğıöşü0-9][’'])\s+(?=[a-zçğıöşü])", r"\1", cleaned)


def _fold_tr(text: str) -> str:
    trans = str.maketrans(
        {
            "İ": "i",
            "I": "i",
            "ı": "i",
            "Ç": "c",
            "ç": "c",
            "Ğ": "g",
            "ğ": "g",
            "Ö": "o",
            "ö": "o",
            "Ş": "s",
            "ş": "s",
            "Ü": "u",
            "ü": "u",
        }
    )
    return " ".join(text.translate(trans).lower().split())


def _canonicalize_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", parsed.query, ""))
    except Exception:
        return url.strip()


def make_announcement_id(source: str, url: str, title: str) -> str:
    """Duyuru için kararlı 16 karakterlik tekil kimlik üretir."""
    basis = _canonicalize_url(url) if url else f"{_fold_tr(source)}::{_fold_tr(title)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def parse_announcements_html(
    html: str,
    source_name: str,
    base_url: str,
    max_items: int = 15,
) -> list[Announcement]:
    """Kastamonu Üniversitesi Joomla / ana portal sayfalarından duyuruları ayrıştırır."""
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[Announcement] = []
    seen_urls: set[str] = set()

    def _add(title: str, href: str, pub_date: Optional[str] = None, summary: str = "") -> None:
        cleaned_title = _clean_text(title)
        if not cleaned_title or len(cleaned_title) < 6:
            return
        abs_url = urljoin(base_url, href.strip()) if href else base_url
        canon = _canonicalize_url(abs_url)
        if canon in seen_urls:
            return
        seen_urls.add(canon)
        cleaned_sum = _clean_text(summary)[:200]
        if len(re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+", "", cleaned_sum)) < 4:
            cleaned_sum = ""
        results.append(
            Announcement(
                announcement_id=make_announcement_id(source_name, abs_url, cleaned_title),
                source=source_name,
                title=cleaned_title,
                url=abs_url,
                published_date=_clean_text(pub_date) or None,
                summary=cleaned_sum,
            )
        )

    # 1. Joomla SP Page Builder duyuru kartları (oidb, sks, kmyo, fakülteler)
    for link in soup.select("a.sppb-articles-scroller-link"):
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        day_el = link.select_one("span.sppb-articles-scroller-day")
        month_el = link.select_one("span.sppb-articles-scroller-month")
        title_el = link.select_one("div.sppb-addon-articles-scroller-title")
        intro_el = link.select_one("div.sppb-articles-scroller-introtext")

        day_txt = _clean_text(day_el.get_text(" ", strip=True)) if day_el else ""
        month_txt = _clean_text(month_el.get_text(" ", strip=True)) if month_el else ""
        pub_date = f"{day_txt} {month_txt}".strip() or None
        title = (
            _clean_text(title_el.get_text(" ", strip=True))
            if title_el
            else _clean_text(link.get_text(" ", strip=True))
        )
        intro = _clean_text(intro_el.get_text(" ", strip=True)) if intro_el else ""
        _add(title, href, pub_date=pub_date, summary=intro)
        if len(results) >= max_items:
            return results

    if results:
        return results

    # 2. Ana portal (kastamonu.edu.tr/tr) gündem / duyuru / haber bağlantıları
    skip_titles = {"tümünü göster", "tumunu goster", "tüm gündemi göster", "tum gundemi goster", "tüm etkinlikler"}
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        low_href = href.lower()
        if not any(seg in low_href for seg in ("/tr/duyuru", "/tr/gundem/", "/tr/haberler/", "/tr/etkinlikler/")):
            continue
        raw_text = _clean_text(link.get_text(" ", strip=True))
        if not raw_text or len(raw_text) < 12 or _fold_tr(raw_text) in skip_titles:
            continue
        pub_date: Optional[str] = None
        date_match = _LEADING_DATE_RE.match(raw_text)
        title = raw_text
        if date_match:
            prefix_len = len(raw_text) - len(date_match.group(1))
            pub_date = raw_text[:prefix_len].strip()
            title = date_match.group(1).strip()
        _add(title, href, pub_date=pub_date)
        if len(results) >= max_items:
            return results

    if results:
        return results

    # 3. Genel Joomla catid=12 / duyuru fallback
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        low_href = href.lower()
        if "catid=12" not in low_href and "duyuru" not in low_href:
            continue
        title = _clean_text(link.get_text(" ", strip=True))
        if len(title) < 12:
            continue
        _add(title, href)
        if len(results) >= max_items:
            break

    return results


def fetch_all_announcements(
    extra_sources: Optional[list[tuple[str, str]]] = None,
    include_defaults: bool = True,
    timeout: float = 20.0,
) -> list[Announcement]:
    """Kastamonu Üniversitesi duyuru kaynaklarından duyuruları toplar (hata izolasyonlu)."""
    sources: list[tuple[str, str]] = []
    if include_defaults:
        sources.extend(DEFAULT_ANNOUNCEMENT_SOURCES)
    if extra_sources:
        sources.extend(extra_sources)

    dedup_sources: list[tuple[str, str]] = []
    seen_base_urls: set[str] = set()
    for label, url in sources:
        canon = _canonicalize_url(url).rstrip("/")
        if canon in seen_base_urls:
            continue
        seen_base_urls.add(canon)
        dedup_sources.append((label, url))

    all_items: list[Announcement] = []
    seen_ids: set[str] = set()

    with httpx.Client(
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9"},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for label, url in dedup_sources:
            try:
                resp = client.get(url)
                if resp.status_code >= 400:
                    logger.warning("Duyuru sayfası açılamadı (%s: HTTP %d).", label, resp.status_code)
                    continue
                parsed = parse_announcements_html(resp.text, source_name=label, base_url=str(resp.url))
                for item in parsed:
                    if item.announcement_id not in seen_ids:
                        seen_ids.add(item.announcement_id)
                        all_items.append(item)
            except httpx.HTTPError as exc:
                logger.warning("Duyuru çekme hatası (%s): %s", label, exc)
            except Exception as exc:
                logger.warning("Duyuru ayrıştırma hatası (%s): %s", label, exc)

    return all_items


def filter_new_announcements(
    announcements: list[Announcement],
    seen_ids: set[str],
    keywords: Optional[list[str]] = None,
) -> list[Announcement]:
    """Daha önce bildirilmemiş (ve varsa anahtar kelimeyle eşleşen) duyuruları döndürür."""
    folded_kws = [_fold_tr(kw) for kw in (keywords or []) if _fold_tr(kw)]
    new_items: list[Announcement] = []
    for item in announcements:
        if item.announcement_id in seen_ids:
            continue
        if folded_kws:
            haystack = _fold_tr(f"{item.title} {item.summary} {item.source}")
            if not any(kw in haystack for kw in folded_kws):
                continue
        new_items.append(item)
    return new_items


# (anahtar kelimeler (_fold_tr), kısa kaynak etiketi, duyuru/birim URL'si)
KASTAMONU_UNIT_SITES: list[tuple[tuple[str, ...], str, str]] = [
    (("kastamonu meslek yuksekokulu", "kmyo"), "KMYO", "https://kmyo.kastamonu.edu.tr/"),
    (("muhendislik ve mimarlik", "muhendislik fakultesi"), "MMF", "https://mmf.kastamonu.edu.tr/"),
    (("iktisadi ve idari", "iibf"), "İİBF", "https://iibf.kastamonu.edu.tr/"),
    (("fen fakultesi",), "Fen Fak.", "https://fen.kastamonu.edu.tr/"),
    (("insan ve toplum bilimleri", "itbf", "edebiyat fakultesi", "fen edebiyat"), "İTBF", "https://itbf.kastamonu.edu.tr/"),
    (("egitim fakultesi",), "Eğitim Fak.", "https://egitim.kastamonu.edu.tr/"),
    (("orman fakultesi",), "Orman Fak.", "https://orman.kastamonu.edu.tr/"),
    (("saglik bilimleri fakultesi",), "SBF", "https://sbf.kastamonu.edu.tr/"),
    (("tip fakultesi",), "Tıp Fak.", "https://tip.kastamonu.edu.tr/"),
    (("dis hekimligi",), "Diş Hekimliği", "https://dis.kastamonu.edu.tr/"),
    (("eczacilik",), "Eczacılık", "https://eczacilik.kastamonu.edu.tr/"),
    (("veteriner fakultesi",), "Veteriner", "https://veteriner.kastamonu.edu.tr/"),
    (("iletisim fakultesi",), "İletişim", "https://iletisim.kastamonu.edu.tr/"),
    (("ilahiyat fakultesi",), "İlahiyat", "https://ilahiyat.kastamonu.edu.tr/"),
    (("turizm fakultesi",), "Turizm", "https://turizm.kastamonu.edu.tr/"),
    (("spor bilimleri",), "Spor Bil.", "https://sporbilimleri.kastamonu.edu.tr/"),
    (("guzel sanatlar",), "GSTF", "https://gstf.kastamonu.edu.tr/"),
    (("su urunleri",), "Su Ürünleri", "https://suurunleri.kastamonu.edu.tr/"),
    (("sivil havacilik", "shyo"), "SHYO", "https://shyo.kastamonu.edu.tr/"),
    (("yabanci diller yuksekokulu", "ydyo"), "YDYO", "https://ydyo.kastamonu.edu.tr/"),
    (("fen bilimleri enstitusu",), "Fen Bilimleri Enst.", "https://fbe.kastamonu.edu.tr/"),
    (("sosyal bilimler enstitusu",), "Sosyal Bilimler Enst.", "https://sbe.kastamonu.edu.tr/"),
    (("saglik bilimleri enstitusu",), "Sağlık Bilimleri Enst.", "https://saglikbilimleri.kastamonu.edu.tr/"),
    (("arac rafet vergili", "arac meslek"), "Araç MYO", "https://aracmyo.kastamonu.edu.tr/"),
    (("taskopru meslek",), "Taşköprü MYO", "https://taskoprumyo.kastamonu.edu.tr/"),
    (("tosya meslek",), "Tosya MYO", "https://tosyamyo.kastamonu.edu.tr/"),
    (("inebolu meslek",), "İnebolu MYO", "https://inebolumyo.kastamonu.edu.tr/"),
    (("devrekani",), "Devrekani MYO", "https://devrekanimyo.kastamonu.edu.tr/"),
    (("cide rifat ilgaz", "cide meslek"), "Cide MYO", "https://cidemyo.kastamonu.edu.tr/"),
    (("abana sabahat", "abana meslek"), "Abana MYO", "https://abanamyo.kastamonu.edu.tr/"),
    (("bozkurt meslek",), "Bozkurt MYO", "https://bozkurtmyo.kastamonu.edu.tr/"),
    (("catalzeytin",), "Çatalzeytin MYO", "https://catalzeytinmyo.kastamonu.edu.tr/"),
    (("daday nafi", "daday meslek"), "Daday MYO", "https://dadaymyo.kastamonu.edu.tr/"),
    (("ihsangazi",), "İhsangazi MYO", "https://ihsangazimyo.kastamonu.edu.tr/"),
    (("kure meslek",), "Küre MYO", "https://kuremyo.kastamonu.edu.tr/"),
]

_EXAM_ANNOUNCE_KWS = (
    "sinav program",
    "sinav takvim",
    "vize sinav",
    "vize takvim",
    "ara sinav",
    "final sinav",
    "final takvim",
    "butunleme",
    "mazeret sinav",
    "sinav yerleri",
    "merkezi sinav",
)

_EXAM_FILE_EXTS = (".pdf", ".xlsx", ".xls", ".docx")
_IGNORE_PDF_KWS = ("yonetmelik", "yonerge", "kilavuz", "dilekce", "formu", "takvim_form")


def infer_faculty_sources(
    program_hints: list[str],
    extra_text: str = "",
) -> list[tuple[str, str]]:
    """Öğrencinin fakülte/MYO adından Kastamonu Üniversitesi birim duyuru adresini otomatik türetir."""
    haystack = _fold_tr(" ".join([*program_hints, extra_text]))
    if not haystack:
        return []
    matched: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for keywords, label, url in KASTAMONU_UNIT_SITES:
        if any(kw in haystack for kw in keywords):
            canon = _canonicalize_url(url).rstrip("/")
            if canon not in seen_urls:
                seen_urls.add(canon)
                matched.append((label, url))
    return matched


def is_exam_announcement(ann: Announcement) -> bool:
    """Duyurunun sınav programı / sınav takvimi / sınav yeri bildirimi olup olmadığını kontrol eder."""
    haystack = _fold_tr(f"{ann.source} {ann.title} {ann.summary}")
    return any(kw in haystack for kw in _EXAM_ANNOUNCE_KWS)


def infer_student_class_year(courses: Iterable[Any]) -> Optional[int]:
    """Aktif ders kodlarındaki yüzlük basamaktan (örn. BPBZ201 -> 2) öğrencinin sınıf düzeyini tahmin eder."""
    votes: Counter[int] = Counter()
    for course in courses:
        code = str(getattr(course, "code", "") or "")
        match = re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2,6}\s*-?\s*([1-6])\d{2}", code)
        if match:
            yr = int(match.group(1))
            if 1 <= yr <= 6:
                votes[yr] += 1
    if not votes:
        return None
    return votes.most_common(1)[0][0]


def _extract_program_terms(program_hints: list[str]) -> list[str]:
    stop = {"fakultesi", "yuksekokulu", "meslek", "enstitusu", "bolumu", "programi", "program", "kastamonu", "universitesi"}
    terms: list[str] = []
    for raw in program_hints:
        folded = _fold_tr(raw)
        if not folded:
            continue
        for part in re.split(r"[-/|(),]+", folded):
            cleaned = re.sub(r"\b(?:fakultesi|yuksekokulu|bolumu|programi|pr\.?)\b", "", part).strip()
            if len(cleaned) >= 5 and cleaned not in stop and cleaned not in terms:
                terms.append(cleaned)
    return terms


def _find_unit_exam_menu_url(unit_html: str, unit_base_url: str) -> Optional[str]:
    soup = BeautifulSoup(unit_html or "", "html.parser")
    best_url: Optional[str] = None
    best_score = 0
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        txt = _fold_tr(a.get_text(" ", strip=True))
        low_href = _fold_tr(href)
        if "sinav program" in txt or "sinav takvim" in txt:
            score = 100
        elif "sinav-program" in low_href or "sinav-takvim" in low_href or "sinav_program" in low_href:
            score = 80
        else:
            continue
        if score > best_score:
            best_score = score
            best_url = urljoin(unit_base_url, href)
    return best_url


def parse_department_program_url(
    unit_html: str,
    unit_base_url: str,
    program_hints: list[str],
) -> Optional[str]:
    """Birim ana sayfası menüsünden öğrencinin bölüm/program sayfası linkini bulur."""
    soup = BeautifulSoup(unit_html or "", "html.parser")
    folded_hints = [_fold_tr(h) for h in program_hints if _fold_tr(h)]
    program_terms = _extract_program_terms(program_hints)
    if not folded_hints and not program_terms:
        return None

    best_score = 0
    best_url: Optional[str] = None
    generic_skip = {"fakulte", "fakultesi", "bolum", "bolumler", "program", "programlar", "yuksekokul"}
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href == "#" or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        link_txt = _fold_tr(a.get_text(" ", strip=True))
        if not link_txt or len(link_txt) < 5 or link_txt in generic_skip:
            continue
        href_bonus = 50 if any(seg in href.lower() for seg in ("/boeluemler/", "/bolumler/", "/bolum", "/program", "/anabilim")) else 0
        for hint in folded_hints:
            if link_txt in hint or any(part.strip() == link_txt for part in re.split(r"[-/|]", hint)):
                score = len(link_txt) + href_bonus + 20
                if score > best_score:
                    best_score = score
                    best_url = urljoin(unit_base_url, href)
        for term in program_terms:
            if term in link_txt:
                score = len(term) + href_bonus
                if score > best_score:
                    best_score = score
                    best_url = urljoin(unit_base_url, href)
    return best_url


def _score_exam_pdf_candidate(
    title: str,
    abs_url: str,
    program_terms: list[str],
    class_year: Optional[int],
) -> int:
    hay = _fold_tr(f"{title} {abs_url.rsplit('/', 1)[-1]}")
    score = 0
    for term in program_terms:
        if term in hay:
            score += 200
        else:
            words = [w for w in term.split() if len(w) >= 4]
            if words and all(w in hay for w in words):
                score += 140
    if any(kw in hay for kw in ("2026", "2027", "guz", "bahar", "vize", "ara sinav", "final", "butunleme")):
        score += 30
    if class_year in (1, 2, 3, 4):
        if re.search(rf"\b{class_year}\s*[.\-_ ]*\s*sinif\b", hay):
            score += 120
        for other in (1, 2, 3, 4):
            if other != class_year and re.search(rf"\b{other}\s*[.\-_ ]*\s*sinif\b", hay):
                score -= 80
    return score


def parse_department_exam_pdfs(
    dept_html: str,
    dept_base_url: str,
    source_label: str,
    max_items: int = 2,
    program_hints: Optional[list[str]] = None,
    class_year: Optional[int] = None,
    allow_general_page: bool = False,
) -> list[Announcement]:
    """Bölüm sayfasındaki 'Sınav Programları' sekmesinden veya sınav duyurusu gövdesinden aktif PDF/Excel takvimlerini çıkarır."""
    soup = BeautifulSoup(dept_html or "", "html.parser")
    target_pane_ids: list[str] = []
    for tab_a in soup.find_all("a", href=True):
        href = str(tab_a["href"]).strip()
        txt = _fold_tr(tab_a.get_text(" ", strip=True))
        if href.startswith("#") and len(href) > 2 and ("sinav program" in txt or "sinav takvim" in txt):
            target_pane_ids.append(href[1:])

    containers = []
    is_tab_mode = False
    for pid in target_pane_ids:
        pane = soup.find(id=pid)
        if pane is not None:
            containers.append(pane)
    if containers:
        is_tab_mode = True
    elif allow_general_page:
        for sel in ('div[itemprop="articleBody"]', "div.item-page", "article", "main"):
            node = soup.select_one(sel)
            if node is not None:
                containers.append(node)
                break
        if not containers and soup.body is not None:
            containers.append(soup.body)
    else:
        return []

    program_terms = _extract_program_terms(program_hints or [])
    scored_results: list[tuple[int, int, Announcement]] = []
    seen_urls: set[str] = set()
    order_idx = 0

    for pane in containers:
        # "Önceki Dönem..." başlığından sonraki arşiv bağlantılarını atla
        for tag in pane.find_all(["p", "li", "h1", "h2", "h3", "h4", "strong", "span", "a"], recursive=True):
            if tag.name != "a" and not tag.find("a"):
                txt_fold = _fold_tr(tag.get_text(" ", strip=True))
                if "onceki donem" in txt_fold or "arsiv" in txt_fold:
                    break
            if tag.name != "a" or not tag.get("href"):
                continue
            href = str(tag["href"]).strip()
            low_h = href.lower().split("?")[0]
            if not any(low_h.endswith(ext) for ext in _EXAM_FILE_EXTS):
                continue
            abs_url = urljoin(dept_base_url, href)
            canon = _canonicalize_url(abs_url)
            if canon in seen_urls:
                continue

            parent_blk = tag.find_parent(["p", "li", "tr"]) or tag.parent
            blk_text = _clean_text(parent_blk.get_text(" ", strip=True)) if parent_blk else ""
            link_txt = _clean_text(tag.get_text(" ", strip=True))
            if link_txt and link_txt in blk_text:
                before = blk_text.split(link_txt, 1)[0]
            else:
                before = blk_text
            cleaned_title = re.sub(r"\s+i[çc]in\s*$", "", before.strip(" .:;-"), flags=re.IGNORECASE).strip()
            if len(cleaned_title) < 8:
                cleaned_title = link_txt if len(link_txt) >= 8 and _fold_tr(link_txt) not in {"tiklayiniz", "indir"} else abs_url.rsplit("/", 1)[-1]
            folded_all = _fold_tr(f"{cleaned_title} {link_txt} {abs_url}")
            if re.search(r"\b20(?:20|21|22|23|24)\b", folded_all):
                continue
            if any(bad in folded_all for bad in _IGNORE_PDF_KWS):
                continue
            if not is_tab_mode and not any(
                kw in folded_all
                for kw in ("sinav", "vize", "final", "butunleme", "program", "takvim", *program_terms)
            ):
                continue

            seen_urls.add(canon)
            ann = Announcement(
                announcement_id=make_announcement_id(f"{source_label} Sınav PDF", abs_url, cleaned_title),
                source=f"{source_label} Sınav PDF",
                title=cleaned_title[:180],
                url=abs_url,
            )
            score = _score_exam_pdf_candidate(cleaned_title, abs_url, program_terms, class_year)
            scored_results.append((score, order_idx, ann))
            order_idx += 1

    if not scored_results:
        return []
    scored_results.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored_results[:max_items]]


def fetch_department_exam_links(
    unit_sources: list[tuple[str, str]],
    program_hints: list[str],
    timeout: float = 20.0,
    class_year: Optional[int] = None,
) -> list[Announcement]:
    """Birim sitesi, bölüm sayfası ve sınav duyuruları üzerinden aktif sınav programı PDF/Excel bağlantılarını toplar."""
    if not unit_sources or not program_hints:
        return []

    found: list[Announcement] = []
    seen_ids: set[str] = set()

    def _collect(items: list[Announcement]) -> None:
        for pdf_ann in items:
            if pdf_ann.announcement_id not in seen_ids:
                seen_ids.add(pdf_ann.announcement_id)
                found.append(pdf_ann)

    with httpx.Client(
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9"},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for label, unit_url in unit_sources:
            try:
                u_resp = client.get(unit_url)
                if u_resp.status_code >= 400:
                    continue
                unit_final_url = str(u_resp.url)

                # 1. Öncelik: Birim menüsündeki öğrencinin bölüm/program sayfası
                dept_url = parse_department_program_url(u_resp.text, unit_final_url, program_hints)
                unit_found_count = 0
                if dept_url:
                    d_resp = client.get(dept_url)
                    if d_resp.status_code < 400:
                        dept_pdfs = parse_department_exam_pdfs(
                            d_resp.text,
                            str(d_resp.url),
                            label,
                            program_hints=program_hints,
                            class_year=class_year,
                            allow_general_page=False,
                        )
                        _collect(dept_pdfs)
                        unit_found_count += len(dept_pdfs)

                # 2. Yedek (Fakülteler): Birim menüsündeki 'Sınav Programları' sayfası veya sınav duyurusu detay sayfası
                if unit_found_count == 0:
                    candidate_pages: list[str] = []
                    exam_menu_url = _find_unit_exam_menu_url(u_resp.text, unit_final_url)
                    if exam_menu_url:
                        candidate_pages.append(exam_menu_url)
                    unit_anns = parse_announcements_html(u_resp.text, source_name=label, base_url=unit_final_url)
                    for ann in unit_anns:
                        if is_exam_announcement(ann) and ann.url not in candidate_pages:
                            candidate_pages.append(ann.url)
                        if len(candidate_pages) >= 3:
                            break
                    for page_url in candidate_pages[:2]:
                        p_resp = client.get(page_url)
                        if p_resp.status_code >= 400:
                            continue
                        page_pdfs = parse_department_exam_pdfs(
                            p_resp.text,
                            str(p_resp.url),
                            label,
                            program_hints=program_hints,
                            class_year=class_year,
                            allow_general_page=True,
                        )
                        _collect(page_pdfs)
                        if page_pdfs:
                            break
            except Exception as exc:
                logger.debug("Bölüm sınav PDF'leri alınamadı (%s): %s", label, exc)
    return found
