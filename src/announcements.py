"""Kastamonu Üniversitesi (OİDB, SKS, Fakülte/MYO) duyuru takip modülü."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional
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
