"""Ortam değişkenlerinden yapılandırma yükleme modülü."""

from __future__ import annotations

import os
from dataclasses import dataclass
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


def _parse_int(raw: Optional[str], default: int, name: str, minimum: int = 1) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"'{name}' geçerli bir tam sayı olmalıdır: {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"'{name}' en az {minimum} olmalıdır (verilen: {value}).")
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


def load_config(require_telegram: bool = True) -> Config:
    """Ortam değişkenlerinden ve .env dosyasından Config nesnesi oluşturur."""
    if load_dotenv is not None:
        load_dotenv()

    ubys_username = (os.getenv("UBYS_USERNAME") or os.getenv("OGRENCI_NO") or "").strip()
    ubys_password = (os.getenv("UBYS_PASSWORD") or os.getenv("SIFRE") or "").strip()
    telegram_bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    raw_chat_ids = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
    telegram_chat_ids = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]

    missing: list[str] = []
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

    base_url = os.getenv("UBYS_BASE_URL", "https://ubys.kastamonu.edu.tr").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"UBYS_BASE_URL geçerli bir HTTP(S) adresi olmalıdır: {base_url!r}")

    user_group_id = os.getenv("UBYS_USER_GROUP_ID", "").strip() or None
    state_file_str = os.getenv("STATE_FILE", "data/grades_state.json").strip() or "data/grades_state.json"

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
    )
