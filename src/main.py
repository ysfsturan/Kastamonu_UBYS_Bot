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

from .attendance import (
    build_attendance_snapshot,
    diff_attendance,
    evaluate_all_attendance,
)
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
from .grade_calculator import analyze_course_grades, calculate_final_targets
from .models import (
    AttendanceReport,
    CalendarEvent,
    CourseGrade,
    DailyMenu,
    GradeTargetAnalysis,
    TranscriptSummary,
)
from .notifier import (
    TelegramNotifier,
    format_attendance_alerts,
    format_attendance_report,
    format_baseline_summary,
    format_calendar_digest,
    format_calendar_reminders,
    format_daily_menu,
    format_error_alert,
    format_gano_change,
    format_grade_calculator,
    format_grade_changes,
    format_test_summary,
    format_tr_date,
    format_transcript_summary,
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


def _print_courses_table(courses: list[CourseGrade], config: Optional[Config] = None) -> None:
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
                if exam.weight is not None:
                    extras.append(f"Etki: %{round(exam.weight * 100)}")
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

        if config is not None:
            analysis, estimate = analyze_course_grades(
                course,
                default_midterm_weight=config.midterm_weight,
                default_final_weight=config.final_weight,
                final_min_score=config.final_min_score,
            )
            if analysis is not None:
                targets_txt = ", ".join(
                    f"{t.letter}:{'Garanti' if t.status == 'guaranteed' else str(t.required_final) + '+'}"
                    for t in analysis.targets
                    if t.status != "impossible"
                )
                if targets_txt:
                    print(f"  Final Hedefleri: {targets_txt} (Maks: {analysis.max_possible_total:.2f})")
            elif estimate is not None:
                print(
                    f"  Tahmini Ortalama: {estimate.weighted_total:.2f} -> {estimate.letter_grade} ({estimate.coefficient:.2f})"
                )


def _print_grade_calculator(analysis: GradeTargetAnalysis) -> None:
    mw_pct = round(analysis.midterm_weight * 100)
    fw_pct = round(analysis.final_weight * 100)
    print(f"\n=== Final Hedef Hesaplayıcı (Vize: {analysis.midterm_score:g} | %{mw_pct}/%{fw_pct}) ===")
    if analysis.final_min_score > 0:
        print(f"Final alt barajı: {analysis.final_min_score}")
    for target in analysis.targets:
        tag = " (Şartlı)" if target.letter == "DC" else ""
        if target.status == "guaranteed":
            req_str = "Garantili (0+)"
        elif target.status == "achievable":
            req_str = f"Finalden en az {target.required_final}"
        else:
            req_str = "İmkansız (100 üzeri gerekir)"
        print(f"  • {target.letter}{tag} (≥{target.min_total} | {target.coefficient:.2f}): {req_str}")
    print(f"  Maksimum olası ortalama: {analysis.max_possible_total:.2f} ({analysis.max_possible_letter})")


def _print_attendance_reports(reports: list[AttendanceReport]) -> None:
    print("\n=== Devamsızlık Takip Raporu ===")
    if not reports:
        print("Değerlendirilecek ders bulunamadı.")
        return
    for report in reports:
        title = f"{report.course_code} - {report.course_name}" if report.course_code else report.course_name
        print(f"• [{report.risk_level.upper()}] {title} ({report.course_type})")
        if report.max_theory_absent is not None and report.max_practice_absent is not None:
            print(
                f"  Teorik: {report.used_theory_absent if report.used_theory_absent is not None else '-'}/{report.max_theory_absent:g}"
                f" (Kalan: {report.remaining_theory if report.remaining_theory is not None else '-'}) | "
                f"Uygulama: {report.used_practice_absent if report.used_practice_absent is not None else '-'}/{report.max_practice_absent:g}"
                f" (Kalan: {report.remaining_practice if report.remaining_practice is not None else '-'})"
            )
        elif report.max_total_absent is not None:
            used_str = f"{report.used_total_absent:g}" if report.used_total_absent is not None else "-"
            rem_str = f"{report.remaining_total:g}" if report.remaining_total is not None else "-"
            print(f"  Devamsızlık: {used_str}/{report.max_total_absent:g} saat (Kalan: {rem_str} saat)")
        if report.absent_percent is not None or report.status != "Bilinmiyor":
            pct_str = f" | Oran: %{report.absent_percent:g}" if report.absent_percent is not None else ""
            print(f"  Durum: {report.status}{pct_str}")


def _print_transcript_summary(summary: TranscriptSummary) -> None:
    print("\n=== Transkript Özeti ===")
    if summary.gano is not None:
        print(f"GANO: {summary.gano:.2f}")
    if summary.total_credit is not None:
        print(f"Toplam Kredi: {summary.total_credit:g}")
    if summary.total_ects is not None:
        print(f"Toplam AKTS: {summary.total_ects:g}")
    for sem in summary.semesters:
        gpa_str = f" | YANO: {sem.semester_gpa:.2f}" if sem.semester_gpa is not None else ""
        cum_str = f" | GANO: {sem.cumulative_gpa:.2f}" if sem.cumulative_gpa is not None else ""
        print(f"\n• {sem.name}{gpa_str}{cum_str}")
        for c in sem.courses:
            print(f"  - {c.code} {c.name}: {c.letter_grade or '-'}")


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
) -> tuple[bool, bool, dict[str, Any], list[CourseGrade], Optional[float]]:
    """ÜBYS not kontrolünü çalıştırır -> (başarılı_mı, durum_değişti_mi, güncel_state, dersler, gano)."""
    dump_dir = Path("debug_html") if dump_html else None
    last_home_gano: Optional[float] = None

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
            raw_gano = client.last_home_gano
            last_home_gano = float(raw_gano) if isinstance(raw_gano, (int, float)) else None
            logger.info("Toplam %d ders çekildi.", len(courses))

    except (LoginError, TwoFactorRequiredError, CaptchaRequiredError) as exc:
        logger.error("Kimlik doğrulama / güvenlik hatası: %s", exc)
        return (
            False,
            True,
            _apply_error_to_state(
                config, state, exc, immediate_alert_title="ÜBYS Giriş / Doğrulama Hatası"
            ),
            [],
            None,
        )

    except (NetworkError, ParseError, SessionExpiredError, UBYSError) as exc:
        logger.error("ÜBYS veri çekme hatası: %s", exc)
        return False, True, _apply_error_to_state(config, state, exc), [], None

    except Exception as exc:
        logger.exception("ÜBYS kontrolünde beklenmeyen hata: %s", exc)
        return False, True, _apply_error_to_state(config, state, exc), [], None

    updated = copy.deepcopy(state)
    is_first_run = not updated.get("baseline_initialized", False)

    if is_first_run:
        logger.info("İlk çalıştırma: %d ders başlangıç durumu olarak kaydediliyor.", len(courses))
        if config.notify_on_first_run:
            if not _send_telegram_safe(config, format_baseline_summary(courses)):
                logger.error("Başlangıç özeti Telegram'a gönderilemedi; not durumu güncellenmedi.")
                return False, False, state, courses, last_home_gano
            logger.info("Başlangıç özeti Telegram'a gönderildi.")

        updated["baseline_initialized"] = True
        updated["updated_at"] = _utc_now_iso()
        updated["consecutive_errors"] = 0
        updated["last_error_alert"] = None
        updated["courses"] = build_course_snapshot(courses)
        return True, True, updated, courses, last_home_gano

    prev_courses = updated.get("courses") or {}
    changes = diff_courses(prev_courses, courses)
    if changes:
        logger.info("%d adet yeni not/durum değişikliği tespit edildi!", len(changes))
        msg = format_grade_changes(
            changes,
            config.ubys_base_url,
            courses=courses,
            midterm_weight=config.midterm_weight,
            final_weight=config.final_weight,
            final_min_score=config.final_min_score,
        )
        if not _send_telegram_safe(config, msg):
            logger.error("Not bildirimi Telegram'a gönderilemedi; bir sonraki kontrolde tekrar denenecek.")
            return False, False, state, courses, last_home_gano
        logger.info("Not bildirimi Telegram'a gönderildi.")
    else:
        logger.info("Yeni not değişikliği bulunamadı.")

    updated["baseline_initialized"] = True
    updated["updated_at"] = _utc_now_iso()
    updated["consecutive_errors"] = 0
    updated["last_error_alert"] = None
    updated["courses"] = build_course_snapshot(courses, previous_courses=prev_courses)
    return True, True, updated, courses, last_home_gano


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


def run_transcript_preview(
    config: Config,
    notify_test: bool = False,
    dump_html: bool = False,
) -> int:
    """ÜBYS transkript ve GANO özetini çekip ekrana (ve isteğe bağlı Telegram'a) yazdırır."""
    dump_dir = Path("debug_html") if dump_html else None
    try:
        with UBYSClient(base_url=config.ubys_base_url) as client:
            client.login(
                username=config.ubys_username,
                password=config.ubys_password,
                user_group_id=config.ubys_user_group_id,
            )
            summary = client.fetch_transcript(dump_dir=dump_dir)
    except Exception as exc:
        logger.error("Transkript çekilemedi: %s", exc)
        return 1

    _print_transcript_summary(summary)
    if notify_test:
        if not _send_telegram_safe(config, format_transcript_summary(summary, config.ubys_base_url)):
            return 1
        logger.info("Transkript özeti Telegram'a gönderildi.")
    return 0


def run_attendance_preview(
    config: Config,
    notify_test: bool = False,
    dump_html: bool = False,
) -> int:
    """Aktif dönem derslerinin devamsızlık raporunu ekrana (ve isteğe bağlı Telegram'a) yazdırır."""
    dump_dir = Path("debug_html") if dump_html else None
    try:
        with UBYSClient(base_url=config.ubys_base_url) as client:
            client.login(
                username=config.ubys_username,
                password=config.ubys_password,
                user_group_id=config.ubys_user_group_id,
            )
            courses = client.fetch_grades(
                all_semesters=False,
                fetch_details=config.fetch_class_details,
                request_delay=config.request_delay_seconds,
                dump_dir=dump_dir,
            )
    except Exception as exc:
        logger.error("Devamsızlık verileri çekilemedi: %s", exc)
        return 1

    reports = evaluate_all_attendance(
        courses,
        semester_weeks=config.semester_weeks,
        theory_min_pct=config.theory_min_attendance,
        practice_min_pct=config.practice_min_attendance,
    )
    _print_attendance_reports(reports)
    if notify_test:
        if not _send_telegram_safe(config, format_attendance_report(reports, config.ubys_base_url)):
            return 1
        logger.info("Devamsızlık raporu Telegram'a gönderildi.")
    return 0


def run_calc_preview(config: Config, midterm_score: float, notify_test: bool = False) -> int:
    """Verilen vize notuna göre final hedeflerini hesaplar ve yazdırır."""
    if midterm_score < 0 or midterm_score > 100:
        logger.error("Vize notu 0 ile 100 arasında olmalıdır (verilen: %s).", midterm_score)
        return 2

    analysis = calculate_final_targets(
        midterm_score=midterm_score,
        midterm_weight=config.midterm_weight,
        final_weight=config.final_weight,
        final_min_score=config.final_min_score,
    )
    _print_grade_calculator(analysis)
    if notify_test:
        if not _send_telegram_safe(config, format_grade_calculator(analysis)):
            return 1
        logger.info("Final hesaplama özeti Telegram'a gönderildi.")
    return 0


def _run_test_all(config: Config, notify_test: bool = False, dump_html: bool = False) -> int:
    overall_ok = True
    dump_dir = Path("debug_html") if dump_html else None

    if config.enable_grades:
        transcript_summary: Optional[TranscriptSummary] = None
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
                if config.enable_transcript:
                    try:
                        transcript_summary = client.fetch_transcript(dump_dir=dump_dir)
                    except Exception as t_exc:
                        logger.warning("Transkript alınamadı: %s", t_exc)

            _print_courses_table(courses, config=config)
            if notify_test:
                if not _send_telegram_safe(config, format_test_summary(courses)):
                    overall_ok = False

            if config.enable_attendance and courses:
                reports = evaluate_all_attendance(
                    courses,
                    semester_weeks=config.semester_weeks,
                    theory_min_pct=config.theory_min_attendance,
                    practice_min_pct=config.practice_min_attendance,
                )
                _print_attendance_reports(reports)
                if notify_test:
                    if not _send_telegram_safe(config, format_attendance_report(reports, config.ubys_base_url)):
                        overall_ok = False

            if transcript_summary is not None:
                _print_transcript_summary(transcript_summary)
                if notify_test:
                    if not _send_telegram_safe(
                        config, format_transcript_summary(transcript_summary, config.ubys_base_url)
                    ):
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
    courses: list[CourseGrade] = []
    last_home_gano: Optional[float] = None

    if config.enable_grades:
        grades_ok, grades_dirty, working_state, courses, last_home_gano = _run_grades_module(
            config,
            working_state,
            dump_html=dump_html,
        )
        if grades_dirty:
            state_dirty = True

    current_dt = now_tr()
    swiss_state = dict(working_state.get("swiss_tool") or {})

    if grades_ok and courses and config.enable_attendance:
        reports = evaluate_all_attendance(
            courses,
            semester_weeks=config.semester_weeks,
            theory_min_pct=config.theory_min_attendance,
            practice_min_pct=config.practice_min_attendance,
        )
        prev_attendance = swiss_state.get("attendance")
        if isinstance(prev_attendance, dict):
            alerts = diff_attendance(prev_attendance, reports)
            if alerts:
                _send_telegram_safe(config, format_attendance_alerts(alerts, config.ubys_base_url))
        swiss_state["attendance"] = build_attendance_snapshot(reports)
        working_state["swiss_tool"] = swiss_state
        state_dirty = True

    if grades_ok and config.enable_transcript and last_home_gano is not None:
        prev_gano = swiss_state.get("last_gano")
        if prev_gano is not None and abs(float(last_home_gano) - float(prev_gano)) >= 0.005:
            _send_telegram_safe(
                config,
                format_gano_change(float(prev_gano), float(last_home_gano), config.ubys_base_url),
            )
        swiss_state["last_gano"] = float(last_home_gano)
        working_state["swiss_tool"] = swiss_state
        state_dirty = True

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
    mode_group.add_argument(
        "--transcript",
        action="store_true",
        help="ÜBYS transkript ve GANO özetini gösterir (state dosyasını değiştirmez).",
    )
    mode_group.add_argument(
        "--attendance",
        action="store_true",
        help="Aktif derslerin devamsızlık haklarını ve kalan saatleri gösterir (state değiştirmez).",
    )
    mode_group.add_argument(
        "--calc",
        type=float,
        metavar="VIZE_NOTU",
        help="Girilen vize notuna göre finalden gereken puanları hesaplar (çevrimdışı çalışır).",
    )
    parser.add_argument(
        "--notify-test",
        action="store_true",
        help="--test, --dining, --calendar, --transcript, --attendance veya --calc ile Telegram'a gönderir.",
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

    is_preview_cmd = (
        args.test
        or args.dining
        or args.calendar
        or args.transcript
        or args.attendance
        or (args.calc is not None)
    )
    require_telegram = bool(args.notify_test or not is_preview_cmd)
    if args.calc is not None or args.dining or args.calendar:
        require_ubys: Optional[bool] = False
    elif args.transcript or args.attendance:
        require_ubys = True
    else:
        require_ubys = None

    try:
        config = load_config(
            require_telegram=require_telegram,
            require_ubys=require_ubys,
        )
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    if args.calc is not None:
        return run_calc_preview(config, args.calc, notify_test=args.notify_test)
    if args.dining:
        return run_dining_preview(config, notify_test=args.notify_test)
    if args.calendar:
        return run_calendar_preview(config, notify_test=args.notify_test)
    if args.transcript:
        return run_transcript_preview(config, notify_test=args.notify_test, dump_html=args.dump_html)
    if args.attendance:
        return run_attendance_preview(config, notify_test=args.notify_test, dump_html=args.dump_html)
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
