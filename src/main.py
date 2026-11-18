"""Kastamonu Üniversitesi Öğrenci Asistanı (ÜBYS Not + Yemekhane + Akademik Takvim) CLI."""

from __future__ import annotations

import argparse
import copy
import logging
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .calendar_tracker import (
    CalendarError,
    fetch_calendar_events,
    filter_events_by_categories,
    find_milestone_reminders,
    find_ongoing_and_upcoming,
    milestone_key_for,
)
from .config import Config, ConfigError, load_config
from .differ import (
    STATE_SCHEMA_VERSION,
    StateStorageError,
    build_course_snapshot,
    create_state_store,
    diff_courses,
)
from .dining import (
    DiningError,
    fetch_dining_menus,
    get_menu_for_date,
    get_next_menu,
)
from .models import CalendarEvent, CourseGrade, DailyMenu
from .notifier import (
    TelegramNotifier,
    format_baseline_summary,
    format_calendar_digest,
    format_calendar_reminders,
    format_daily_menu,
    format_error_alert,
    format_grade_changes,
    format_test_summary,
    format_tr_date,
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

TR_TZ = timezone(timedelta(hours=3))


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
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_tr() -> datetime:
    """Türkiye saat diliminde (UTC+3) güncel zamanı döndürür."""
    return datetime.now(TR_TZ)


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


def _print_dining_menu(menu: Optional[DailyMenu], is_next_preview: bool = False) -> None:
    if menu is None:
        print("\n=== Yemekhane Menüsü ===\nGüncel yemekhane menüsü bulunamadı.")
        return

    label = "Yaklaşan İlk Yemekhane Menüsü" if is_next_preview else "Günün Yemekhane Menüsü"
    print(f"\n=== {label} ({format_tr_date(menu.menu_date)}) ===")
    for item in menu.items:
        cal = f" ({item.calories})" if item.calories else ""
        prefix = f"[{item.category}] " if item.category else ""
        print(f"  • {prefix}{item.name}{cal}")
    if menu.total_calories_min is not None and menu.total_calories_max is not None:
        if menu.total_calories_min == menu.total_calories_max:
            print(f"  Toplam Kalori: ~{menu.total_calories_min} kkal")
        else:
            print(f"  Toplam Kalori: ~{menu.total_calories_min}-{menu.total_calories_max} kkal")


def _print_calendar_digest(
    ongoing: list[CalendarEvent],
    upcoming: list[CalendarEvent],
    today: date,
    faculty: str,
    term: str,
    lookahead_days: int,
) -> None:
    print(f"\n=== Akademik Takvim ({faculty} | {term}) ===")
    if ongoing:
        print("Devam Edenler:")
        for ev in ongoing:
            left = (ev.end_date - today).days
            print(f"  • {ev.title} ({ev.start_date.strftime('%d.%m.%Y')} - {ev.end_date.strftime('%d.%m.%Y')}, bitime {left} gün)")
    if upcoming:
        print(f"Yaklaşanlar (Önümüzdeki {lookahead_days} Gün):")
        for ev in upcoming:
            days_until = (ev.start_date - today).days
            print(f"  • {ev.title} ({ev.start_date.strftime('%d.%m.%Y')}, {days_until} gün kaldı)")
    if not ongoing and not upcoming:
        print(f"Önümüzdeki {lookahead_days} gün için kayıtlı etkinlik yok.")


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


def _apply_error_to_state(
    config: Config,
    state: dict[str, Any],
    exc: Exception,
    immediate_alert_title: Optional[str] = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    consecutive_errors = int(updated.get("consecutive_errors") or 0) + 1
    last_error_alert = updated.get("last_error_alert")

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

    updated["updated_at"] = _utc_now_iso()
    updated["consecutive_errors"] = consecutive_errors
    updated["last_error_alert"] = last_error_alert
    return updated


def _run_grades_module(
    config: Config,
    state: dict[str, Any],
    dump_html: bool = False,
) -> tuple[bool, bool, dict[str, Any]]:
    """ÜBYS not kontrolünü çalıştırır -> (başarılı_mı, durum_değişti_mi, güncel_state)."""
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
        return False, True, _apply_error_to_state(
            config, state, exc, immediate_alert_title="ÜBYS Giriş / Doğrulama Hatası"
        )

    except (NetworkError, ParseError, SessionExpiredError, UBYSError) as exc:
        logger.error("ÜBYS veri çekme hatası: %s", exc)
        return False, True, _apply_error_to_state(config, state, exc)

    except Exception as exc:
        logger.exception("ÜBYS kontrolünde beklenmeyen hata: %s", exc)
        return False, True, _apply_error_to_state(config, state, exc)

    updated = copy.deepcopy(state)
    is_first_run = not updated.get("baseline_initialized", False)

    if is_first_run:
        logger.info("İlk çalıştırma: %d ders başlangıç durumu olarak kaydediliyor.", len(courses))
        if config.notify_on_first_run:
            if not _send_telegram_safe(config, format_baseline_summary(courses)):
                logger.error("Başlangıç özeti Telegram'a gönderilemedi; not durumu güncellenmedi.")
                return False, False, state
            logger.info("Başlangıç özeti Telegram'a gönderildi.")

        updated["baseline_initialized"] = True
        updated["updated_at"] = _utc_now_iso()
        updated["consecutive_errors"] = 0
        updated["last_error_alert"] = None
        updated["courses"] = build_course_snapshot(courses)
        return True, True, updated

    prev_courses = updated.get("courses") or {}
    changes = diff_courses(prev_courses, courses)
    if changes:
        logger.info("%d adet yeni not/durum değişikliği tespit edildi!", len(changes))
        if not _send_telegram_safe(config, format_grade_changes(changes, config.ubys_base_url)):
            logger.error("Not bildirimi Telegram'a gönderilemedi; bir sonraki kontrolde tekrar denenecek.")
            return False, False, state
        logger.info("Not bildirimi Telegram'a gönderildi.")
    else:
        logger.info("Yeni not değişikliği bulunamadı.")

    updated["baseline_initialized"] = True
    updated["updated_at"] = _utc_now_iso()
    updated["consecutive_errors"] = 0
    updated["last_error_alert"] = None
    updated["courses"] = build_course_snapshot(courses, previous_courses=prev_courses)
    return True, True, updated


def _run_dining_module(
    config: Config,
    swiss_state: dict[str, Any],
    current_dt: datetime,
    force_daily: bool = False,
) -> tuple[bool, bool]:
    """Hafta içi günde bir kez yemekhane menüsünü gönderir -> (başarılı_mı, state_değişti_mi)."""
    today = current_dt.date()
    today_str = today.isoformat()

    is_due = force_daily or (
        today.weekday() < 5
        and current_dt.hour >= config.dining_notify_hour
        and swiss_state.get("last_dining_date") != today_str
    )
    if not is_due:
        return True, False

    try:
        menus = fetch_dining_menus(
            sks_url=config.sks_url,
            sheet_url_override=config.dining_sheet_url,
        )
    except DiningError as exc:
        logger.warning("Yemekhane menüsü alınamadı: %s", exc)
        return False, False
    except Exception as exc:
        logger.warning("Yemekhane modülünde beklenmeyen hata: %s", exc)
        return False, False

    menu = get_menu_for_date(menus, today)
    is_next_preview = False
    if menu is None and force_daily:
        menu = get_next_menu(menus, today)
        is_next_preview = menu is not None

    if menu is None:
        logger.info("Bugün (%s) için yemekhane menüsü bulunamadı.", today_str)
        return True, False

    if not _send_telegram_safe(config, format_daily_menu(menu, is_next_preview=is_next_preview)):
        return False, False

    logger.info("Yemekhane menüsü Telegram'a gönderildi (%s).", menu.menu_date.isoformat())
    if not is_next_preview:
        swiss_state["last_dining_date"] = today_str
        return True, True
    return True, False


def _prune_old_milestones(sent_milestones: dict[str, str], today: date) -> dict[str, str]:
    pruned: dict[str, str] = {}
    for key, date_str in sent_milestones.items():
        try:
            recorded_date = date.fromisoformat(str(date_str))
            if (today - recorded_date).days <= 120:
                pruned[key] = str(date_str)
        except ValueError:
            continue
    return pruned


def _run_calendar_module(
    config: Config,
    swiss_state: dict[str, Any],
    current_dt: datetime,
    force_daily: bool = False,
) -> tuple[bool, bool]:
    """Akademik takvim hatırlatmalarını ve haftalık özeti kontrol eder -> (başarılı_mı, state_değişti_mi)."""
    today = current_dt.date()
    today_str = today.isoformat()

    is_due = force_daily or (
        current_dt.hour >= config.calendar_notify_hour
        and swiss_state.get("last_calendar_check_date") != today_str
    )
    if not is_due:
        return True, False

    try:
        faculty, term, all_events = fetch_calendar_events(
            calendar_url=config.calendar_url,
            faculty=config.calendar_faculty,
        )
    except CalendarError as exc:
        logger.warning("Akademik takvim verisi alınamadı: %s", exc)
        return False, False
    except Exception as exc:
        logger.warning("Akademik takvim modülünde beklenmeyen hata: %s", exc)
        return False, False

    events = filter_events_by_categories(all_events, config.calendar_categories)
    sent_milestones = _prune_old_milestones(
        dict(swiss_state.get("sent_calendar_milestones") or {}),
        today,
    )

    delivery_failed = False

    reminders = find_milestone_reminders(
        events=events,
        today=today,
        reminder_days=config.calendar_reminder_days,
        sent_milestones=sent_milestones,
    )
    if reminders:
        msg = format_calendar_reminders(reminders, faculty, config.calendar_url)
        if _send_telegram_safe(config, msg):
            for ev, days_until in reminders:
                sent_milestones[milestone_key_for(ev, days_until)] = today_str
            logger.info("%d akademik takvim hatırlatması gönderildi.", len(reminders))
        else:
            delivery_failed = True

    iso_year, iso_week, _ = today.isocalendar()
    iso_week_str = f"{iso_year}-W{iso_week:02d}"
    weekly_due = force_daily or (
        config.calendar_weekly_summary
        and today.weekday() == 0
        and swiss_state.get("last_calendar_weekly") != iso_week_str
    )
    if weekly_due:
        ongoing, upcoming = find_ongoing_and_upcoming(
            events=events,
            today=today,
            lookahead_days=config.calendar_lookahead_days,
        )
        if ongoing or upcoming or force_daily:
            digest_msg = format_calendar_digest(
                ongoing=ongoing,
                upcoming=upcoming,
                today=today,
                faculty=faculty,
                term=term,
                lookahead_days=config.calendar_lookahead_days,
                calendar_url=config.calendar_url,
            )
            if _send_telegram_safe(config, digest_msg):
                swiss_state["last_calendar_weekly"] = iso_week_str
                logger.info("Haftalık akademik takvim özeti gönderildi (%s).", iso_week_str)
            else:
                delivery_failed = True

    swiss_state["sent_calendar_milestones"] = sent_milestones
    if not delivery_failed:
        swiss_state["last_calendar_check_date"] = today_str
    return (not delivery_failed), True


def run_dining_preview(config: Config, notify_test: bool = False) -> int:
    """Sadece yemekhane menüsünü çekip ekrana (ve isteğe bağlı Telegram'a) yazdırır."""
    today = now_tr().date()
    try:
        menus = fetch_dining_menus(
            sks_url=config.sks_url,
            sheet_url_override=config.dining_sheet_url,
        )
    except DiningError as exc:
        logger.error("Yemekhane hatası: %s", exc)
        return 1

    menu = get_menu_for_date(menus, today)
    is_next_preview = False
    if menu is None:
        menu = get_next_menu(menus, today)
        is_next_preview = menu is not None

    _print_dining_menu(menu, is_next_preview=is_next_preview)
    if notify_test and menu is not None:
        if not _send_telegram_safe(config, format_daily_menu(menu, is_next_preview=is_next_preview)):
            return 1
        logger.info("Yemekhane menüsü Telegram'a gönderildi.")
    return 0


def run_calendar_preview(config: Config, notify_test: bool = False) -> int:
    """Sadece akademik takvim özetini çekip ekrana (ve isteğe bağlı Telegram'a) yazdırır."""
    today = now_tr().date()
    try:
        faculty, term, all_events = fetch_calendar_events(
            calendar_url=config.calendar_url,
            faculty=config.calendar_faculty,
        )
    except CalendarError as exc:
        logger.error("Akademik takvim hatası: %s", exc)
        return 1

    events = filter_events_by_categories(all_events, config.calendar_categories)
    ongoing, upcoming = find_ongoing_and_upcoming(
        events=events,
        today=today,
        lookahead_days=config.calendar_lookahead_days,
    )
    _print_calendar_digest(ongoing, upcoming, today, faculty, term, config.calendar_lookahead_days)

    if notify_test:
        msg = format_calendar_digest(
            ongoing=ongoing,
            upcoming=upcoming,
            today=today,
            faculty=faculty,
            term=term,
            lookahead_days=config.calendar_lookahead_days,
            calendar_url=config.calendar_url,
        )
        if not _send_telegram_safe(config, msg):
            return 1
        logger.info("Akademik takvim özeti Telegram'a gönderildi.")
    return 0


def _run_test_all(config: Config, notify_test: bool = False, dump_html: bool = False) -> int:
    overall_ok = True
    dump_dir = Path("debug_html") if dump_html else None

    if config.enable_grades:
        try:
            with UBYSClient(base_url=config.ubys_base_url) as client:
                logger.info("Kastamonu ÜBYS'ye giriş yapılıyor (%s)...", config.ubys_base_url)
                client.login(
                    username=config.ubys_username,
                    password=config.ubys_password,
                    user_group_id=config.ubys_user_group_id,
                )
                courses = client.fetch_grades(
                    all_semesters=config.all_semesters,
                    fetch_details=config.fetch_class_details,
                    request_delay=config.request_delay_seconds,
                    dump_dir=dump_dir,
                )
            _print_courses_table(courses)
            if notify_test:
                if not _send_telegram_safe(config, format_test_summary(courses)):
                    overall_ok = False
        except Exception as exc:
            logger.error("ÜBYS testi başarısız: %s", exc)
            overall_ok = False

    if config.enable_dining:
        if run_dining_preview(config, notify_test=notify_test) != 0:
            overall_ok = False

    if config.enable_calendar:
        if run_calendar_preview(config, notify_test=notify_test) != 0:
            overall_ok = False

    return 0 if overall_ok else 1


def run_once(
    config: Config,
    test_mode: bool = False,
    notify_test: bool = False,
    dump_html: bool = False,
    force_daily: bool = False,
) -> int:
    """Etkinleştirilmiş tüm modülleri çalıştırır; çıkış kodu döner (0 başarılı, 1 hatalı)."""
    if test_mode:
        return _run_test_all(config, notify_test=notify_test, dump_html=dump_html)

    state_store = create_state_store(
        state_file=config.state_file,
        gist_id=config.gist_id,
        gist_token=config.gist_token,
        gist_filename=config.gist_filename,
    )
    logger.info("Durum deposu: %s", state_store.description)
    try:
        loaded_state = state_store.load()
    except StateStorageError as exc:
        logger.error("Durum okunamadı: %s", exc)
        _send_telegram_safe(config, format_error_alert("GitHub Gist / Durum Okuma Hatası", str(exc)))
        return 1

    working_state: dict[str, Any] = (
        copy.deepcopy(loaded_state)
        if isinstance(loaded_state, dict)
        else {
            "schema_version": STATE_SCHEMA_VERSION,
            "baseline_initialized": False,
            "courses": {},
        }
    )

    grades_ok = True
    state_dirty = False

    if config.enable_grades:
        grades_ok, grades_dirty, working_state = _run_grades_module(
            config,
            working_state,
            dump_html=dump_html,
        )
        if grades_dirty:
            state_dirty = True

    current_dt = now_tr()
    swiss_state = dict(working_state.get("swiss_tool") or {})

    dining_ok = True
    if config.enable_dining:
        dining_ok, dining_dirty = _run_dining_module(
            config,
            swiss_state,
            current_dt,
            force_daily=force_daily,
        )
        if dining_dirty:
            working_state["swiss_tool"] = swiss_state
            state_dirty = True

    calendar_ok = True
    if config.enable_calendar:
        calendar_ok, calendar_dirty = _run_calendar_module(
            config,
            swiss_state,
            current_dt,
            force_daily=force_daily,
        )
        if calendar_dirty:
            working_state["swiss_tool"] = swiss_state
            state_dirty = True

    if state_dirty:
        working_state["updated_at"] = _utc_now_iso()
        if not _save_state_safe(config, state_store, working_state):
            return 1

    if config.enable_grades:
        return 0 if grades_ok else 1
    return 0 if (dining_ok and calendar_ok) else 1


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
        description="Kastamonu Üniversitesi Öğrenci Asistanı (Not + Yemekhane + Akademik Takvim)",
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
        help="Etkin modülleri test edip ekrana yazdırır, durum dosyasını güncellemez.",
    )
    mode_group.add_argument(
        "--dining",
        action="store_true",
        help="Yalnızca güncel yemekhane menüsünü gösterir (ÜBYS şifresi gerektirmez).",
    )
    mode_group.add_argument(
        "--calendar",
        action="store_true",
        help="Yalnızca akademik takvim özetini gösterir (ÜBYS şifresi gerektirmez).",
    )
    parser.add_argument(
        "--notify-test",
        action="store_true",
        help="--test, --dining veya --calendar ile Telegram'a test mesajı gönderir.",
    )
    parser.add_argument(
        "--force-daily",
        action="store_true",
        help="--once ile kullanıldığında günlük yemekhane ve takvim özetini saat/tekrar kontrolünü aşarak gönderir.",
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

    is_preview_cmd = args.test or args.dining or args.calendar
    require_telegram = bool(args.notify_test or not is_preview_cmd)
    require_ubys = False if (args.dining or args.calendar) else None

    try:
        config = load_config(
            require_telegram=require_telegram,
            require_ubys=require_ubys,
        )
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    if args.dining:
        return run_dining_preview(config, notify_test=args.notify_test)
    if args.calendar:
        return run_calendar_preview(config, notify_test=args.notify_test)
    if args.test:
        return run_once(
            config,
            test_mode=True,
            notify_test=args.notify_test,
            dump_html=args.dump_html,
        )
    if args.loop:
        return run_loop(config, dump_html=args.dump_html)

    return run_once(
        config,
        dump_html=args.dump_html,
        force_daily=args.force_daily,
    )


if __name__ == "__main__":
    raise SystemExit(main())
