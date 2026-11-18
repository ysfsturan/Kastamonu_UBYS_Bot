"""Ortam değişkenlerinden yapılandırma yükleme modülü."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    return val


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
    midterm_weight: float = 0.40
    final_weight: float = 0.60
    final_min_score: int = 0
    semester_weeks: int = 14
    theory_min_attendance: int = 70
    practice_min_attendance: int = 80
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
    needs_ubys = enable_grades if require_ubys is None else require_ubys

    midterm_weight = _parse_weight(os.getenv("MIDTERM_WEIGHT"), 0.40, "MIDTERM_WEIGHT")
    final_weight = _parse_weight(os.getenv("FINAL_WEIGHT"), 0.60, "FINAL_WEIGHT")
    if abs((midterm_weight + final_weight) - 1.0) > 0.01:
        raise ConfigError(
            f"MIDTERM_WEIGHT ({midterm_weight}) + FINAL_WEIGHT ({final_weight}) toplamı 1.0 (veya %100) olmalıdır."
        )

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
        midterm_weight=midterm_weight,
        final_weight=final_weight,
        final_min_score=_parse_int(
            os.getenv("FINAL_MIN_SCORE"), 0, "FINAL_MIN_SCORE", minimum=0, maximum=100
        ),
        semester_weeks=_parse_int(
            os.getenv("SEMESTER_WEEKS"), 14, "SEMESTER_WEEKS", minimum=1, maximum=52
        ),
        theory_min_attendance=_parse_int(
            os.getenv("THEORY_MIN_ATTENDANCE"), 70, "THEORY_MIN_ATTENDANCE", minimum=1, maximum=100
        ),
        practice_min_attendance=_parse_int(
            os.getenv("PRACTICE_MIN_ATTENDANCE"), 80, "PRACTICE_MIN_ATTENDANCE", minimum=1, maximum=100
        ),
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
    )
