"""Ortam değişkenlerinden yapılandırma yükleme modülü."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv isteğe bağlı
    load_dotenv = None


class ConfigError(Exception):
    """Eksik veya geçersiz yapılandırma hatası."""


def _parse_bool(raw: Optional[str], default: bool, name: str) -> bool:
    if raw is None or raw.strip() == "":
        return default
    val = raw.strip().lower()
    if val in {"1", "true", "evet", "yes", "on"}:
        return True
    if val in {"0", "false", "hayir", "hayır", "no", "off"}:
        return False
    raise ConfigError(f"'{name}' için geçersiz mantıksal değer: {raw!r} (true/false olmalı).")


def _parse_int(
    raw: Optional[str],
    default: int,
    name: str,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"'{name}' geçerli bir tam sayı olmalıdır: {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"'{name}' en az {minimum} olmalıdır (verilen: {value}).")
    if maximum is not None and value > maximum:
        raise ConfigError(f"'{name}' en fazla {maximum} olmalıdır (verilen: {value}).")
    return value


def _parse_float(raw: Optional[str], default: float, name: str, minimum: float = 0.0) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip().replace(",", "."))
    except ValueError as exc:
        raise ConfigError(f"'{name}' geçerli bir sayı olmalıdır: {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"'{name}' en az {minimum} olmalıdır (verilen: {value}).")
    return value


def _parse_int_list(raw: Optional[str], default: list[int], name: str) -> list[int]:
    if raw is None or raw.strip() == "":
        return list(default)
    result: list[int] = []
    seen: set[int] = set()
    for part in raw.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        try:
            value = int(cleaned)
        except ValueError as exc:
            raise ConfigError(f"'{name}' virgülle ayrılmış tam sayılar içermelidir: {raw!r}") from exc
        if value < 0:
            raise ConfigError(f"'{name}' negatif sayı içeremez: {value}")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result or list(default)


def _validate_http_url(raw: str, name: str) -> str:
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"{name} geçerli bir HTTP(S) adresi olmalıdır: {url!r}")
    return url


def _parse_weight(raw: Optional[str], default: float, name: str) -> float:
    if raw is None or raw.strip() == "":
        return default
    val = _parse_float(raw, default, name, minimum=0.0)
    if val > 1.0:
        val = val / 100.0
    if val <= 0.0 or val >= 1.0:
        raise ConfigError(f"'{name}' 0 ile 1 (veya 1 ile 99) arasında olmalıdır: {raw!r}")
    return round(val, 4)


def parse_weight_pair(raw: str, name: str = "WEIGHTS") -> tuple[float, float]:
    """'30/70', '30-70', '0.3/0.7' veya tek başına '30'/'0.3' ağırlık çiftini ayrıştırır."""
    cleaned = raw.strip()
    if not cleaned:
        raise ConfigError(f"'{name}' boş olamaz.")

    parts = [p.strip() for p in re.split(r"[/\-]", cleaned) if p.strip()]
    if len(parts) == 1:
        mw = _parse_weight(parts[0], 0.40, name)
        fw = round(1.0 - mw, 4)
    elif len(parts) == 2:
        mw = _parse_weight(parts[0], 0.40, f"{name}[vize]")
        fw = _parse_weight(parts[1], 0.60, f"{name}[final]")
    else:
        raise ConfigError(
            f"'{name}' için geçersiz ağırlık biçimi: {raw!r} (örnek: 30/70 veya 30)."
        )

    if abs((mw + fw) - 1.0) > 0.01:
        raise ConfigError(
            f"'{name}' vize ({mw}) ve final ({fw}) ağırlıkları toplamı 1.0 (veya %100) olmalıdır."
        )
    return mw, fw


def _parse_course_weights(raw: Optional[str]) -> dict[str, tuple[float, float]]:
    """'BPBZ201:30/70, BPBZ207:40/60' biçimindeki ders bazlı vize/final oranlarını okur."""
    if raw is None or raw.strip() == "":
        return {}
    result: dict[str, tuple[float, float]] = {}
    for entry in re.split(r"[,;\n]+", raw):
        cleaned = entry.strip()
        if not cleaned:
            continue
        match = re.split(r"[:=]", cleaned, maxsplit=1)
        if len(match) != 2 or not match[0].strip() or not match[1].strip():
            raise ConfigError(
                f"'COURSE_WEIGHTS' için geçersiz kayıt: {cleaned!r} (örnek: BPBZ201:30/70)."
            )
        code = " ".join(match[0].split()).upper()
        result[code] = parse_weight_pair(match[1], f"COURSE_WEIGHTS[{code}]")
    return result


def _parse_course_hours(raw: Optional[str]) -> dict[str, tuple[float, float]]:
    """'BPBZ201:3+1, BPBZ207:4+0' biçimindeki ders bazlı haftalık T+U saatlerini okur."""
    if raw is None or raw.strip() == "":
        return {}
    result: dict[str, tuple[float, float]] = {}
    for entry in re.split(r"[,;\n]+", raw):
        cleaned = entry.strip()
        if not cleaned:
            continue
        match = re.split(r"[:=]", cleaned, maxsplit=1)
        if len(match) != 2 or not match[0].strip() or not match[1].strip():
            raise ConfigError(
                f"'COURSE_HOURS' için geçersiz kayıt: {cleaned!r} (örnek: BPBZ201:3+1)."
            )
        code = " ".join(match[0].split()).upper()
        val_parts = [p.strip() for p in re.split(r"[+/]", match[1].strip())]
        if len(val_parts) == 1 and val_parts[0]:
            t_hours = _parse_float(val_parts[0], 0.0, f"COURSE_HOURS[{code}][T]", minimum=0.0)
            u_hours = 0.0
        elif len(val_parts) == 2 and val_parts[0] and val_parts[1]:
            t_hours = _parse_float(val_parts[0], 0.0, f"COURSE_HOURS[{code}][T]", minimum=0.0)
            u_hours = _parse_float(val_parts[1], 0.0, f"COURSE_HOURS[{code}][U]", minimum=0.0)
        else:
            raise ConfigError(
                f"'COURSE_HOURS[{code}]' için geçersiz saat biçimi: {match[1]!r} (örnek: 3+1)."
            )
        if t_hours + u_hours <= 0:
            raise ConfigError(f"'COURSE_HOURS[{code}]' toplam saati 0'dan büyük olmalıdır.")
        result[code] = (t_hours, u_hours)
    return result


def _derive_announcement_label(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "Duyuru"
    sub = host.split(".")[0]
    if sub in {"kastamonu", "ubys", "sks", "oidb"}:
        return {
            "kastamonu": "Kastamonu Üni",
            "ubys": "ÜBYS",
            "sks": "SKS",
            "oidb": "OİDB",
        }[sub]
    return sub.replace("i", "İ").upper()


def _parse_announcement_urls(raw: Optional[str]) -> list[tuple[str, str]]:
    """'KMYO|https://kmyo.kastamonu.edu.tr/, https://mf.kastamonu.edu.tr/' adreslerini okur."""
    if raw is None or raw.strip() == "":
        return []
    result: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for entry in re.split(r"[,;\n]+", raw):
        cleaned = entry.strip()
        if not cleaned:
            continue
        if "|" in cleaned:
            label_part, url_part = cleaned.split("|", 1)
            label = label_part.strip()
            url = _validate_http_url(url_part, "ANNOUNCEMENT_URLS")
            if not label:
                label = _derive_announcement_label(url)
        else:
            url = _validate_http_url(cleaned, "ANNOUNCEMENT_URLS")
            label = _derive_announcement_label(url)
        if url not in seen_urls:
            seen_urls.add(url)
            result.append((label, url))
    return result


def _parse_str_list(raw: Optional[str]) -> list[str]:
    if raw is None or raw.strip() == "":
        return []
    return [part.strip() for part in re.split(r"[,;\n]+", raw) if part.strip()]


@dataclass(frozen=True)
class Config:
    """Uygulama yapılandırma ayarları."""

    ubys_username: str
    ubys_password: str
    telegram_bot_token: str
    telegram_chat_ids: list[str]
    ubys_base_url: str = "https://ubys.kastamonu.edu.tr"
    ubys_user_group_id: Optional[str] = None
    state_file: Path = Path("data/grades_state.json")
    gist_id: Optional[str] = None
    gist_token: Optional[str] = None
    gist_filename: str = "grades_state.json"
    all_semesters: bool = False
    fetch_class_details: bool = True
    request_delay_seconds: float = 0.7
    check_interval_minutes: int = 20
    notify_on_first_run: bool = True
    alert_after_consecutive_errors: int = 3
    enable_grades: bool = True
    enable_dining: bool = True
    enable_calendar: bool = True
    enable_attendance: bool = True
    enable_transcript: bool = True
    enable_catalog: bool = True
    ubys_program: Optional[str] = None
    midterm_weight: float = 0.40
    final_weight: float = 0.60
    final_min_score: int = 0
    course_weights: dict[str, tuple[float, float]] = field(default_factory=dict)
    semester_weeks: int = 14
    theory_min_attendance: int = 70
    practice_min_attendance: int = 80
    course_hours: dict[str, tuple[float, float]] = field(default_factory=dict)
    sks_url: str = "https://sks.kastamonu.edu.tr/"
    dining_sheet_url: Optional[str] = None
    dining_notify_hour: int = 8
    calendar_url: str = "https://akademiktakvim.kastamonu.edu.tr/"
    calendar_faculty: str = "GENEL"
    calendar_categories: str = "STUDENT"
    calendar_reminder_days: list[int] = field(default_factory=lambda: [7, 3, 1, 0])
    calendar_lookahead_days: int = 30
    calendar_notify_hour: int = 8
    calendar_weekly_summary: bool = True
    enable_weather: bool = True
    weather_lat: float = 41.4307
    weather_lon: float = 33.7764
    weather_location: str = "Kastamonu (Kuzeykent)"
    enable_announcements: bool = True
    announcement_urls: list[tuple[str, str]] = field(default_factory=list)
    announcement_keywords: list[str] = field(default_factory=list)
    enable_schedule: bool = True
    enable_exam_schedule: bool = True
    schedule_notify_hour: int = 8
    exam_reminder_days: list[int] = field(default_factory=lambda: [7, 3, 1, 0])
    enable_materials: bool = True
    enable_weekly_briefing: bool = True
    weekly_briefing_hour: int = 20
    enable_commands: bool = True


def load_config(
    require_telegram: bool = True,
    require_ubys: Optional[bool] = None,
) -> Config:
    """Ortam değişkenlerinden ve .env dosyasından Config nesnesi oluşturur."""
    if load_dotenv is not None:
        load_dotenv()

    enable_grades = _parse_bool(os.getenv("ENABLE_GRADES"), True, "ENABLE_GRADES")
    enable_dining = _parse_bool(os.getenv("ENABLE_DINING"), True, "ENABLE_DINING")
    enable_calendar = _parse_bool(os.getenv("ENABLE_CALENDAR"), True, "ENABLE_CALENDAR")
    enable_attendance = _parse_bool(os.getenv("ENABLE_ATTENDANCE"), True, "ENABLE_ATTENDANCE")
    enable_transcript = _parse_bool(os.getenv("ENABLE_TRANSCRIPT"), True, "ENABLE_TRANSCRIPT")
    enable_catalog = _parse_bool(os.getenv("ENABLE_CATALOG"), True, "ENABLE_CATALOG")
    needs_ubys = enable_grades if require_ubys is None else require_ubys

    midterm_weight = _parse_weight(os.getenv("MIDTERM_WEIGHT"), 0.40, "MIDTERM_WEIGHT")
    final_weight = _parse_weight(os.getenv("FINAL_WEIGHT"), 0.60, "FINAL_WEIGHT")
    if abs((midterm_weight + final_weight) - 1.0) > 0.01:
        raise ConfigError(
            f"MIDTERM_WEIGHT ({midterm_weight}) + FINAL_WEIGHT ({final_weight}) toplamı 1.0 (veya %100) olmalıdır."
        )
    course_weights = _parse_course_weights(os.getenv("COURSE_WEIGHTS"))
    course_hours = _parse_course_hours(os.getenv("COURSE_HOURS"))
    ubys_program = os.getenv("UBYS_PROGRAM", "").strip() or None

    ubys_username = (os.getenv("UBYS_USERNAME") or os.getenv("OGRENCI_NO") or "").strip()
    ubys_password = (os.getenv("UBYS_PASSWORD") or os.getenv("SIFRE") or "").strip()
    telegram_bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    raw_chat_ids = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
    telegram_chat_ids = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]

    missing: list[str] = []
    if needs_ubys:
        if not ubys_username:
            missing.append("UBYS_USERNAME")
        if not ubys_password:
            missing.append("UBYS_PASSWORD")
    if require_telegram:
        if not telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not telegram_chat_ids:
            missing.append("TELEGRAM_CHAT_ID")

    if missing:
        joined = ", ".join(missing)
        raise ConfigError(
            f"Eksik ortam değişkeni/değişkenleri: {joined}. "
            "Lütfen .env dosyanızı veya GitHub Secrets ayarlarınızı kontrol edin."
        )

    gist_id = os.getenv("GIST_ID", "").strip() or None
    gist_token = os.getenv("GIST_TOKEN", "").strip() or None
    if bool(gist_id) != bool(gist_token):
        raise ConfigError("GIST_ID ve GIST_TOKEN birlikte tanımlanmalıdır.")
    gist_filename = os.getenv("GIST_FILENAME", "grades_state.json").strip() or "grades_state.json"

    base_url = _validate_http_url(
        os.getenv("UBYS_BASE_URL", "https://ubys.kastamonu.edu.tr"),
        "UBYS_BASE_URL",
    )
    sks_url = _validate_http_url(
        os.getenv("SKS_URL", "https://sks.kastamonu.edu.tr"),
        "SKS_URL",
    ) + "/"
    calendar_url = _validate_http_url(
        os.getenv("CALENDAR_URL", "https://akademiktakvim.kastamonu.edu.tr"),
        "CALENDAR_URL",
    ) + "/"

    dining_sheet_url = os.getenv("DINING_SHEET_URL", "").strip() or None
    if dining_sheet_url:
        _validate_http_url(dining_sheet_url, "DINING_SHEET_URL")

    user_group_id = os.getenv("UBYS_USER_GROUP_ID", "").strip() or None
    state_file_str = os.getenv("STATE_FILE", "data/grades_state.json").strip() or "data/grades_state.json"
    calendar_faculty = (
        os.getenv("CALENDAR_FACULTY") or os.getenv("BOLUM_TIPI") or "GENEL"
    ).strip() or "GENEL"
    calendar_categories = os.getenv("CALENDAR_CATEGORIES", "STUDENT").strip() or "STUDENT"

    return Config(
        ubys_username=ubys_username,
        ubys_password=ubys_password,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_ids=telegram_chat_ids,
        ubys_base_url=base_url,
        ubys_user_group_id=user_group_id,
        state_file=Path(state_file_str),
        gist_id=gist_id,
        gist_token=gist_token,
        gist_filename=gist_filename,
        all_semesters=_parse_bool(os.getenv("ALL_SEMESTERS"), False, "ALL_SEMESTERS"),
        fetch_class_details=_parse_bool(os.getenv("FETCH_CLASS_DETAILS"), True, "FETCH_CLASS_DETAILS"),
        request_delay_seconds=_parse_float(
            os.getenv("REQUEST_DELAY_SECONDS"), 0.7, "REQUEST_DELAY_SECONDS", minimum=0.0
        ),
        check_interval_minutes=_parse_int(
            os.getenv("CHECK_INTERVAL_MINUTES"), 20, "CHECK_INTERVAL_MINUTES", minimum=1
        ),
        notify_on_first_run=_parse_bool(os.getenv("NOTIFY_ON_FIRST_RUN"), True, "NOTIFY_ON_FIRST_RUN"),
        alert_after_consecutive_errors=_parse_int(
            os.getenv("ALERT_AFTER_CONSECUTIVE_ERRORS"), 3, "ALERT_AFTER_CONSECUTIVE_ERRORS", minimum=1
        ),
        enable_grades=enable_grades,
        enable_dining=enable_dining,
        enable_calendar=enable_calendar,
        enable_attendance=enable_attendance,
        enable_transcript=enable_transcript,
        enable_catalog=enable_catalog,
        ubys_program=ubys_program,
        midterm_weight=midterm_weight,
        final_weight=final_weight,
        final_min_score=_parse_int(
            os.getenv("FINAL_MIN_SCORE"), 0, "FINAL_MIN_SCORE", minimum=0, maximum=100
        ),
        course_weights=course_weights,
        semester_weeks=_parse_int(
            os.getenv("SEMESTER_WEEKS"), 14, "SEMESTER_WEEKS", minimum=1, maximum=52
        ),
        theory_min_attendance=_parse_int(
            os.getenv("THEORY_MIN_ATTENDANCE"), 70, "THEORY_MIN_ATTENDANCE", minimum=1, maximum=100
        ),
        practice_min_attendance=_parse_int(
            os.getenv("PRACTICE_MIN_ATTENDANCE"), 80, "PRACTICE_MIN_ATTENDANCE", minimum=1, maximum=100
        ),
        course_hours=course_hours,
        sks_url=sks_url,
        dining_sheet_url=dining_sheet_url,
        dining_notify_hour=_parse_int(
            os.getenv("DINING_NOTIFY_HOUR"), 8, "DINING_NOTIFY_HOUR", minimum=0, maximum=23
        ),
        calendar_url=calendar_url,
        calendar_faculty=calendar_faculty,
        calendar_categories=calendar_categories,
        calendar_reminder_days=_parse_int_list(
            os.getenv("CALENDAR_REMINDER_DAYS"), [7, 3, 1, 0], "CALENDAR_REMINDER_DAYS"
        ),
        calendar_lookahead_days=_parse_int(
            os.getenv("CALENDAR_LOOKAHEAD_DAYS"), 30, "CALENDAR_LOOKAHEAD_DAYS", minimum=1
        ),
        calendar_notify_hour=_parse_int(
            os.getenv("CALENDAR_NOTIFY_HOUR"), 8, "CALENDAR_NOTIFY_HOUR", minimum=0, maximum=23
        ),
        calendar_weekly_summary=_parse_bool(
            os.getenv("CALENDAR_WEEKLY_SUMMARY"), True, "CALENDAR_WEEKLY_SUMMARY"
        ),
        enable_weather=_parse_bool(os.getenv("ENABLE_WEATHER"), True, "ENABLE_WEATHER"),
        weather_lat=_parse_float(
            os.getenv("WEATHER_LAT"), 41.4307, "WEATHER_LAT", minimum=-90.0
        ),
        weather_lon=_parse_float(
            os.getenv("WEATHER_LON"), 33.7764, "WEATHER_LON", minimum=-180.0
        ),
        weather_location=os.getenv("WEATHER_LOCATION", "Kastamonu (Kuzeykent)").strip()
        or "Kastamonu (Kuzeykent)",
        enable_announcements=_parse_bool(
            os.getenv("ENABLE_ANNOUNCEMENTS"), True, "ENABLE_ANNOUNCEMENTS"
        ),
        announcement_urls=_parse_announcement_urls(os.getenv("ANNOUNCEMENT_URLS")),
        announcement_keywords=_parse_str_list(os.getenv("ANNOUNCEMENT_KEYWORDS")),
        enable_schedule=_parse_bool(os.getenv("ENABLE_SCHEDULE"), True, "ENABLE_SCHEDULE"),
        enable_exam_schedule=_parse_bool(
            os.getenv("ENABLE_EXAM_SCHEDULE"), True, "ENABLE_EXAM_SCHEDULE"
        ),
        schedule_notify_hour=_parse_int(
            os.getenv("SCHEDULE_NOTIFY_HOUR"), 8, "SCHEDULE_NOTIFY_HOUR", minimum=0, maximum=23
        ),
        exam_reminder_days=_parse_int_list(
            os.getenv("EXAM_REMINDER_DAYS"), [7, 3, 1, 0], "EXAM_REMINDER_DAYS"
        ),
        enable_materials=_parse_bool(
            os.getenv("ENABLE_MATERIALS"), True, "ENABLE_MATERIALS"
        ),
        enable_weekly_briefing=_parse_bool(
            os.getenv("ENABLE_WEEKLY_BRIEFING"), True, "ENABLE_WEEKLY_BRIEFING"
        ),
        weekly_briefing_hour=_parse_int(
            os.getenv("WEEKLY_BRIEFING_HOUR"), 20, "WEEKLY_BRIEFING_HOUR", minimum=0, maximum=23
        ),
        enable_commands=_parse_bool(os.getenv("ENABLE_COMMANDS"), True, "ENABLE_COMMANDS"),
    )
