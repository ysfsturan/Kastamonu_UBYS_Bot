"""Kastamonu Üniversitesi Akademik Takvim takip ve hatırlatma modülü."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from .dining import parse_turkish_date
from .models import CalendarEvent

FACULTY_ALIASES = {
    "GENEL": "Genel",
    "TIP": "Tıp Fakültesi",
    "TIP FAKULTESI": "Tıp Fakültesi",
    "VET": "Veteriner Fakültesi",
    "VETERINER": "Veteriner Fakültesi",
    "VETERINER FAKULTESI": "Veteriner Fakültesi",
    "DIS": "Diş Hekimliği Fakültesi",
    "DIS HEKIMLIGI": "Diş Hekimliği Fakültesi",
    "DIS HEKIMLIGI FAKULTESI": "Diş Hekimliği Fakültesi",
    "LISANSUSTU": "Lisansüstü Eğitim Enstitüsü",
    "LISANSUSTU EGITIM ENSTITUSU": "Lisansüstü Eğitim Enstitüsü",
    "TURIZM": "Turizm Fakültesi",
    "TURIZM FAKULTESI": "Turizm Fakültesi",
}

STUDENT_CORE_CATEGORIES = {
    "ders ve sınav",
    "kayıt (ilk / yenileme)",
    "resmi tatil",
    "kuzem",
    "osd",
}

_LONG_SPAN_KEYWORDS = ("sınav", "not giriş", "kayıt", "başvuru", "bütünleme", "mazeret")


class CalendarError(Exception):
    """Akademik takvim verisi alınırken veya ayrıştırılırken oluşan hata."""


def _tr_lower(text: str) -> str:
    return " ".join(text.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "").split())


def _ascii_upper(text: str) -> str:
    trans = str.maketrans("İIıŞşĞğÜüÖöÇç", "IIISSGGUUOOCC")
    return " ".join(text.translate(trans).upper().split())


def resolve_faculty_name(raw: Optional[str]) -> str:
    """Kısa kod veya fakülte adını akademik takvim API'sinin beklediği ada çevirir."""
    cleaned = " ".join((raw or "").split())
    if not cleaned:
        return "Genel"
    key = _ascii_upper(cleaned)
    return FACULTY_ALIASES.get(key, cleaned)


def extract_active_term(home_html: str, today: Optional[date] = None) -> str:
    """Akademik takvim ana sayfasından aktif eğitim-öğretim dönemini çıkarır."""
    soup = BeautifulSoup(home_html, "html.parser")
    active_item = soup.select_one(".timeline-item.active[data-donem]")
    if active_item and active_item.get("data-donem"):
        return str(active_item["data-donem"]).strip()

    any_item = soup.select_one(".timeline-item[data-donem]")
    if any_item and any_item.get("data-donem"):
        return str(any_item["data-donem"]).strip()

    ref = today or date.today()
    start_year = ref.year if ref.month >= 7 else ref.year - 1
    return f"{start_year}-{start_year + 1}"


def parse_calendar_api_json(
    groups: list[dict[str, Any]],
    default_faculty: str = "Genel",
    default_term: str = "",
) -> list[CalendarEvent]:
    """/Home/FiltreliEtkinlikler JSON yanıtından CalendarEvent listesi oluşturur."""
    events: list[CalendarEvent] = []
    seen: set[tuple[str, date, str]] = set()

    for group in groups:
        if not isinstance(group, dict):
            continue
        raw_events = group.get("etkinlikler") or []
        for item in raw_events:
            if not isinstance(item, dict):
                continue

            title = " ".join(str(item.get("etkinlikAdi") or "").split())
            start_date = parse_turkish_date(str(item.get("baslamaTarihi") or ""))
            if not title or start_date is None:
                continue

            end_date = (
                parse_turkish_date(str(item.get("bitisTarihi") or ""))
                or parse_turkish_date(str(item.get("sonTarih") or ""))
                or start_date
            )
            if end_date < start_date:
                end_date = start_date

            event_id = str(item.get("id") or "").strip()
            dedup_key = (event_id, start_date, _tr_lower(title))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            events.append(
                CalendarEvent(
                    event_id=event_id,
                    title=title,
                    start_date=start_date,
                    end_date=end_date,
                    category=" ".join(str(item.get("kategori") or "").split()),
                    faculty=" ".join(str(item.get("fakulte") or default_faculty).split()),
                    term=" ".join(str(item.get("donem") or default_term).split()),
                    description=" ".join(str(item.get("aciklama") or "").split()),
                    google_calendar_url=(str(item.get("googleCalendarUrl") or "").strip() or None),
                )
            )

    return sorted(events, key=lambda e: (e.start_date, e.end_date, e.title))


def _parse_date_range_text(text: str) -> tuple[Optional[date], Optional[date]]:
    matches = re.findall(r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})", text or "")
    if not matches:
        return None, None
    start_date = parse_turkish_date(matches[0])
    end_date = parse_turkish_date(matches[1]) if len(matches) > 1 else start_date
    if start_date and end_date and end_date < start_date:
        end_date = start_date
    return start_date, end_date


def parse_calendar_html_fallback(html: str) -> list[CalendarEvent]:
    """JSON endpoint başarısız olursa ana sayfadaki akordeon HTML'inden etkinlikleri ayrıştırır."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[CalendarEvent] = []
    seen: set[tuple[str, date, str]] = set()

    for item in soup.select("#eventsAccordion .accordion-item"):
        raw_id = str(item.get("id") or "")
        event_id = raw_id.replace("etkinlik-", "").strip()
        category = " ".join(str(item.get("data-kategori") or "").split())
        term = " ".join(str(item.get("data-donem") or "").split())
        faculty = " ".join(str(item.get("data-fakulte") or "Genel").split())

        title_el = item.select_one(".accordion-button span.fw-semibold")
        date_el = item.select_one(".accordion-button span.text-muted")
        title = " ".join(title_el.get_text(" ", strip=True).split()) if title_el else ""
        date_text = date_el.get_text(" ", strip=True) if date_el else ""
        start_date, end_date = _parse_date_range_text(date_text)
        if not title or start_date is None or end_date is None:
            continue

        gcal_el = item.select_one("a[href*='calendar.google.com']")
        gcal_url = str(gcal_el["href"]).strip() if gcal_el and gcal_el.get("href") else None

        dedup_key = (event_id, start_date, _tr_lower(title))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        events.append(
            CalendarEvent(
                event_id=event_id,
                title=title,
                start_date=start_date,
                end_date=end_date,
                category=category,
                faculty=faculty,
                term=term,
                google_calendar_url=gcal_url,
            )
        )

    return sorted(events, key=lambda e: (e.start_date, e.end_date, e.title))


def fetch_calendar_events(
    calendar_url: str = "https://akademiktakvim.kastamonu.edu.tr/",
    faculty: str = "GENEL",
    timeout: float = 20.0,
) -> tuple[str, str, list[CalendarEvent]]:
    """Akademik takvimden aktif dönemi ve fakülte etkinliklerini çeker."""
    base_url = calendar_url.rstrip("/")
    resolved_faculty = resolve_faculty_name(faculty)
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
            home_resp = client.get(f"{base_url}/")
            if home_resp.status_code >= 400:
                raise CalendarError(f"Akademik takvim sayfası açılamadı: HTTP {home_resp.status_code}")

            active_term = extract_active_term(home_resp.text)

            try:
                api_resp = client.post(
                    f"{base_url}/Home/FiltreliEtkinlikler",
                    json={"donem": active_term, "fakulte": resolved_faculty},
                    headers={"Content-Type": "application/json"},
                )
                if api_resp.status_code >= 400:
                    raise CalendarError(f"Akademik takvim API hatası: HTTP {api_resp.status_code}")
                data = api_resp.json()
                if not isinstance(data, list):
                    raise CalendarError("Akademik takvim API yanıtı beklenen liste biçiminde değil.")
                events = parse_calendar_api_json(
                    data,
                    default_faculty=resolved_faculty,
                    default_term=active_term,
                )
                return resolved_faculty, active_term, events
            except Exception as api_exc:
                if resolved_faculty == "Genel":
                    fallback = parse_calendar_html_fallback(home_resp.text)
                    if fallback:
                        return resolved_faculty, active_term, fallback
                if isinstance(api_exc, CalendarError):
                    raise
                raise CalendarError(f"Akademik takvim verisi ayrıştırılamadı: {api_exc}") from api_exc
    except CalendarError:
        raise
    except httpx.HTTPError as exc:
        raise CalendarError(f"Akademik takvim bağlantısı başarısız: {exc}") from exc


def filter_events_by_categories(
    events: list[CalendarEvent],
    categories_setting: str,
) -> list[CalendarEvent]:
    """Etkinlikleri kategori ayarına (STUDENT, ALL veya özel virgüllü liste) göre süzer."""
    setting = (categories_setting or "STUDENT").strip()
    upper = setting.upper()
    if upper in {"ALL", "*"}:
        return list(events)

    if upper == "STUDENT":
        return [
            e for e in events
            if not e.category or _tr_lower(e.category) in STUDENT_CORE_CATEGORIES
        ]

    wanted = [_tr_lower(part) for part in setting.split(",") if part.strip()]
    if not wanted:
        return list(events)

    return [
        e for e in events
        if any(term in _tr_lower(e.category) for term in wanted)
    ]


def _milestone_key(event: CalendarEvent, days_until: int) -> str:
    ident = event.event_id or f"{event.start_date.isoformat()}:{_tr_lower(event.title)[:40]}"
    return f"{ident}:{days_until}"


def find_milestone_reminders(
    events: list[CalendarEvent],
    today: date,
    reminder_days: list[int],
    sent_milestones: dict[str, str],
) -> list[tuple[CalendarEvent, int]]:
    """Belirtilen gün eşiklerine (örn. 7, 3, 1, 0 gün) giren ve henüz bildirilmemiş etkinlikleri döndürür."""
    wanted_days = set(reminder_days)
    reminders: list[tuple[CalendarEvent, int]] = []

    for event in events:
        days_until = (event.start_date - today).days
        if days_until not in wanted_days:
            continue
        key = _milestone_key(event, days_until)
        if key in sent_milestones:
            continue
        reminders.append((event, days_until))

    return sorted(reminders, key=lambda pair: (pair[1], pair[0].start_date, pair[0].title))


def milestone_key_for(event: CalendarEvent, days_until: int) -> str:
    return _milestone_key(event, days_until)


def find_ongoing_and_upcoming(
    events: list[CalendarEvent],
    today: date,
    lookahead_days: int = 30,
) -> tuple[list[CalendarEvent], list[CalendarEvent]]:
    """Bugün devam eden önemli etkinlikleri ve önümüzdeki N günde başlayacakları döndürür."""
    cutoff = today + timedelta(days=lookahead_days)
    ongoing: list[CalendarEvent] = []
    upcoming: list[CalendarEvent] = []

    for event in events:
        if event.start_date <= today <= event.end_date:
            span_days = (event.end_date - event.start_date).days
            lower_title = _tr_lower(event.title)
            if span_days <= 60 or any(kw in lower_title for kw in _LONG_SPAN_KEYWORDS):
                ongoing.append(event)
        elif today < event.start_date <= cutoff:
            upcoming.append(event)

    return ongoing, upcoming
