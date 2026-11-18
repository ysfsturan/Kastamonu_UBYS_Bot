"""Kastamonu Üniversitesi ÜBYS Not Bildirim Botu giriş noktası (CLI)."""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config, ConfigError, load_config
from .differ import (
    STATE_SCHEMA_VERSION,
    StateStorageError,
    build_course_snapshot,
    create_state_store,
    diff_courses,
)
from .models import CourseGrade
from .notifier import (
    TelegramNotifier,
    format_baseline_summary,
    format_error_alert,
    format_grade_changes,
    format_test_summary,
)
from .ubys_client import (
    CaptchaRequiredError,
    LoginError,
    NetworkError,
    ParseError,
    SessionExpiredError,
    TwoFactorRequiredError,
    UBYSClient,
    UBYSError,
)

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _print_courses_table(courses: list[CourseGrade]) -> None:
    if not courses:
        print("Hiç ders bulunamadı.")
        return

    current_semester: Optional[str] = None
    for course in courses:
        if course.semester != current_semester:
            current_semester = course.semester
            print(f"\n=== {current_semester} ===")

        title = f"{course.code} - {course.name}" if course.code else course.name
        print(f"• {title}")
        if course.instructor:
            print(f"  Öğretim Elemanı: {course.instructor}")
        if course.exams:
            for exam in course.exams:
                score_str = exam.score if exam.score is not None else "-"
                extras: list[str] = []
                if exam.class_average:
                    extras.append(f"Sınıf Ort: {exam.class_average}")
                if exam.ranking:
                    extras.append(f"Sıra: {exam.ranking}")
                if exam.announcement_date:
                    extras.append(f"Tarih: {exam.announcement_date}")
                extra_txt = f" ({', '.join(extras)})" if extras else ""
                print(f"    - {exam.name}: {score_str}{extra_txt}")
        else:
            print("    - Sınav kaydı yok")

        summary_parts: list[str] = []
        if course.passing_grade:
            summary_parts.append(f"Geçme Notu: {course.passing_grade}")
        if course.letter_grade:
            summary_parts.append(f"Harf: {course.letter_grade}")
        if course.status:
            summary_parts.append(f"Durum: {course.status}")
        if course.class_average:
            summary_parts.append(f"Genel Ort: {course.class_average}")
        if summary_parts:
            print(f"  [{' | '.join(summary_parts)}]")


def _send_telegram_safe(config: Config, text: str) -> bool:
    if not config.telegram_bot_token or not config.telegram_chat_ids:
        logger.warning("Telegram ayarları eksik olduğu için bildirim gönderilemedi.")
        return False
    try:
        notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_ids)
        notifier.send_message(text)
        return True
    except Exception as exc:
        logger.error("Telegram mesajı gönderilirken hata oluştu: %s", exc)
        return False


def _save_state_safe(
    config: Config,
    state_store: Any,
    state: dict[str, Any],
) -> bool:
    try:
        state_store.save(state)
        return True
    except StateStorageError as exc:
        logger.error("Durum kaydedilemedi: %s", exc)
        _send_telegram_safe(config, format_error_alert("GitHub Gist / Durum Kaydetme Hatası", str(exc)))
        return False


def _record_error_state(
    config: Config,
    state_store: Any,
    state: Optional[dict[str, Any]],
    exc: Exception,
    immediate_alert_title: Optional[str] = None,
) -> None:
    base_state: dict[str, Any] = (
        dict(state)
        if isinstance(state, dict)
        else {
            "schema_version": STATE_SCHEMA_VERSION,
            "baseline_initialized": False,
            "courses": {},
        }
    )
    consecutive_errors = int(base_state.get("consecutive_errors") or 0) + 1
    last_error_alert = base_state.get("last_error_alert")

    if immediate_alert_title is not None:
        alert_key = f"{type(exc).__name__}:{str(exc)[:120]}"
        if last_error_alert != alert_key:
            msg = format_error_alert(immediate_alert_title, str(exc))
            if _send_telegram_safe(config, msg):
                last_error_alert = alert_key
    elif consecutive_errors == config.alert_after_consecutive_errors:
        msg = format_error_alert(
            f"ÜBYS Kontrolü Üst Üste {consecutive_errors} Kez Başarısız",
            f"Son hata: {exc}",
        )
        if _send_telegram_safe(config, msg):
            last_error_alert = f"consecutive:{type(exc).__name__}"

    base_state["updated_at"] = _utc_now_iso()
    base_state["consecutive_errors"] = consecutive_errors
    base_state["last_error_alert"] = last_error_alert
    try:
        state_store.save(base_state)
    except StateStorageError as save_exc:
        logger.error("Hata durumu kaydedilemedi: %s", save_exc)


def run_once(
    config: Config,
    test_mode: bool = False,
    notify_test: bool = False,
    dump_html: bool = False,
) -> int:
    """Tek bir ÜBYS not kontrolü gerçekleştirir; çıkış kodu döner (0 başarılı, 1 hatalı)."""
    state_store = create_state_store(
        state_file=config.state_file,
        gist_id=config.gist_id,
        gist_token=config.gist_token,
        gist_filename=config.gist_filename,
    )
    state: Optional[dict[str, Any]] = None
    if not test_mode:
        logger.info("Durum deposu: %s", state_store.description)
        try:
            state = state_store.load()
        except StateStorageError as exc:
            logger.error("Durum okunamadı: %s", exc)
            _send_telegram_safe(config, format_error_alert("GitHub Gist / Durum Okuma Hatası", str(exc)))
            return 1

    dump_dir = Path("debug_html") if dump_html else None

    try:
        with UBYSClient(base_url=config.ubys_base_url) as client:
            logger.info("Kastamonu ÜBYS'ye giriş yapılıyor (%s)...", config.ubys_base_url)
            client.login(
                username=config.ubys_username,
                password=config.ubys_password,
                user_group_id=config.ubys_user_group_id,
            )
            logger.info("Giriş başarılı. Ders notları çekiliyor...")
            courses = client.fetch_grades(
                all_semesters=config.all_semesters,
                fetch_details=config.fetch_class_details,
                request_delay=config.request_delay_seconds,
                dump_dir=dump_dir,
            )
            logger.info("Toplam %d ders çekildi.", len(courses))

    except (LoginError, TwoFactorRequiredError, CaptchaRequiredError) as exc:
        logger.error("Kimlik doğrulama / güvenlik hatası: %s", exc)
        if not test_mode:
            _record_error_state(
                config,
                state_store,
                state,
                exc,
                immediate_alert_title="ÜBYS Giriş / Doğrulama Hatası",
            )
        return 1

    except (NetworkError, ParseError, SessionExpiredError, UBYSError) as exc:
        logger.error("ÜBYS veri çekme hatası: %s", exc)
        if not test_mode:
            _record_error_state(config, state_store, state, exc)
        return 1

    except Exception as exc:
        logger.exception("Beklenmeyen hata oluştu: %s", exc)
        if not test_mode:
            _record_error_state(config, state_store, state, exc)
        return 1

    if test_mode:
        _print_courses_table(courses)
        if notify_test:
            if not _send_telegram_safe(config, format_test_summary(courses)):
                return 1
            logger.info("Test özeti Telegram'a gönderildi.")
        return 0

    is_first_run = state is None or not state.get("baseline_initialized", True)
    if is_first_run:
        logger.info("İlk çalıştırma: %d ders başlangıç durumu olarak kaydediliyor.", len(courses))
        if config.notify_on_first_run:
            if not _send_telegram_safe(config, format_baseline_summary(courses)):
                logger.error("Başlangıç özeti Telegram'a gönderilemedi; durum güncellenmedi.")
                return 1
            logger.info("Başlangıç özeti Telegram'a gönderildi.")

        new_state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "baseline_initialized": True,
            "updated_at": _utc_now_iso(),
            "consecutive_errors": 0,
            "last_error_alert": None,
            "courses": build_course_snapshot(courses),
        }
        return 0 if _save_state_safe(config, state_store, new_state) else 1

    prev_courses = state.get("courses") or {}
    changes = diff_courses(prev_courses, courses)

    if changes:
        logger.info("%d adet yeni not/durum değişikliği tespit edildi!", len(changes))
        if not _send_telegram_safe(config, format_grade_changes(changes, config.ubys_base_url)):
            logger.error("Not bildirimi Telegram'a gönderilemedi; bir sonraki kontrolde tekrar denenecek.")
            return 1
        logger.info("Not bildirimi Telegram'a gönderildi.")
    else:
        logger.info("Yeni not değişikliği bulunamadı.")

    new_state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "baseline_initialized": True,
        "updated_at": _utc_now_iso(),
        "consecutive_errors": 0,
        "last_error_alert": None,
        "courses": build_course_snapshot(courses, previous_courses=prev_courses),
    }
    return 0 if _save_state_safe(config, state_store, new_state) else 1


def run_loop(config: Config, dump_html: bool = False) -> int:
    """Belirlenen aralıklarla sürekli kontrol döngüsü çalıştırır."""
    base_seconds = config.check_interval_minutes * 60
    logger.info(
        "Sürekli takip modu başlatıldı (yaklaşık her %d dakikada bir kontrol).",
        config.check_interval_minutes,
    )
    try:
        while True:
            run_once(config, dump_html=dump_html)
            sleep_seconds = random.uniform(base_seconds * 0.9, base_seconds * 1.1)
            logger.info("Sonraki kontrol için %.0f saniye bekleniyor...", sleep_seconds)
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        logger.info("Kullanıcı tarafından durduruldu.")
        return 0


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kastamonu Üniversitesi ÜBYS Not Bildirim Botu",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--once",
        action="store_true",
        help="Tek seferlik kontrol yapar ve çıkar (varsayılan; GitHub Actions/cron için).",
    )
    mode_group.add_argument(
        "--loop",
        action="store_true",
        help="Belirtilen aralıklarla sürekli kontrol döngüsü çalıştırır (VPS/Docker/PC için).",
    )
    mode_group.add_argument(
        "--test",
        action="store_true",
        help="Notları ekrana yazdırır, state dosyasını güncellemez.",
    )
    parser.add_argument(
        "--notify-test",
        action="store_true",
        help="--test ile birlikte kullanıldığında Telegram'a örnek özet mesajı gönderir.",
    )
    parser.add_argument(
        "--dump-html",
        action="store_true",
        help="Hata ayıklama için çekilen ÜBYS HTML sayfalarını debug_html/ klasörüne kaydeder.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    _configure_logging()
    args = parse_args(argv)

    require_telegram = not (args.test and not args.notify_test)
    try:
        config = load_config(require_telegram=require_telegram)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    if args.test:
        return run_once(
            config,
            test_mode=True,
            notify_test=args.notify_test,
            dump_html=args.dump_html,
        )
    if args.loop:
        return run_loop(config, dump_html=args.dump_html)

    return run_once(config, dump_html=args.dump_html)


if __name__ == "__main__":
    raise SystemExit(main())
