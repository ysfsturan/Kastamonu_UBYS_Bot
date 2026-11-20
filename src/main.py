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

from .announcements import fetch_all_announcements, filter_new_announcements
from .attendance import (
    build_attendance_snapshot,
    diff_attendance,
    evaluate_all_attendance,
)
from .bot_commands import process_telegram_commands
from .calendar_tracker import (
    CalendarError,
    fetch_calendar_events,
    filter_events_by_categories,
    find_milestone_reminders,
    find_ongoing_and_upcoming,
    milestone_key_for,
)
from .config import Config, ConfigError, load_config, parse_weight_pair
from .course_catalog import enrich_courses_with_catalog, fetch_catalog_for_courses
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
from .grade_calculator import (
    analyze_course_grades,
    calculate_final_targets,
    project_semester_gpa,
    resolve_course_weights,
)
from .models import (
    Announcement,
    AttendanceReport,
    CalendarEvent,
    CourseCatalogEntry,
    CourseGrade,
    CourseMaterial,
    DailyMenu,
    ExamScheduleItem,
    GpaProjection,
    GradeTargetAnalysis,
    ScheduleSlot,
    TranscriptSummary,
    WeatherForecast,
)
from .notifier import (
    TelegramNotifier,
    format_announcements,
    format_attendance_alerts,
    format_attendance_detail_line,
    format_attendance_report,
    format_baseline_summary,
    format_calendar_digest,
    format_calendar_reminders,
    format_daily_menu,
    format_daily_schedule,
    format_error_alert,
    format_exam_reminders,
    format_exam_schedule,
    format_gano_change,
    format_gpa_projection,
    format_grade_calculator,
    format_grade_changes,
    format_material_alerts,
    format_test_summary,
    format_tr_date,
    format_transcript_summary,
    format_weather_report,
    format_weekly_briefing,
    format_weekly_schedule,
)
from .schedule import exam_reminder_key, find_exam_reminders, get_slots_for_day
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
from .weather import fetch_weather_forecast

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
        if course.theoretical_hours is not None or course.practical_hours is not None:
            t_h = course.theoretical_hours or 0.0
            u_h = course.practical_hours or 0.0
            summary_parts.append(f"Saat: {t_h:g}T+{u_h:g}U")
        def_mw = config.midterm_weight if config is not None else 0.40
        def_fw = config.final_weight if config is not None else 0.60
        mw, fw, w_src = resolve_course_weights(
            course,
            default_midterm_weight=def_mw,
            default_final_weight=def_fw,
        )
        if w_src != "default":
            summary_parts.append(f"Vize/Final: %{round(mw * 100)}/%{round(fw * 100)}")
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
                    mw_pct = round(analysis.midterm_weight * 100)
                    fw_pct = round(analysis.final_weight * 100)
                    print(f"  Final Hedefleri (%{mw_pct}/%{fw_pct}): {targets_txt} (Maks: {analysis.max_possible_total:.2f})")
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
        print(f"• [{report.risk_level.upper()}] {title}")
        print(f"  {format_attendance_detail_line(report)}")


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


def _print_dining_menu(
    menu: Optional[DailyMenu],
    is_next_preview: bool = False,
    weather: Optional[WeatherForecast] = None,
) -> None:
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
    if weather is not None:
        temp_rng = (
            f"{weather.temp_min:.0f}/{weather.temp_max:.0f}°C"
            if (weather.temp_min is not None and weather.temp_max is not None)
            else "-"
        )
        print(f"  Hava ({weather.location_name}): {weather.condition_text}, {temp_rng} | {weather.advice}")


def _print_weather_report(weather: WeatherForecast) -> None:
    print(f"\n=== Hava Durumu ({weather.location_name} | {format_tr_date(weather.forecast_date)}) ===")
    print(f"  Durum: {weather.condition_text}")
    if weather.current_temp is not None:
        print(f"  Şu an: {weather.current_temp:.1f}°C")
    if weather.temp_min is not None and weather.temp_max is not None:
        print(f"  En Düşük / Yüksek: {weather.temp_min:.0f}° / {weather.temp_max:.0f}°C")
    if weather.precip_probability is not None:
        print(f"  Yağış İhtimali: %{weather.precip_probability}")
    print(f"  Tavsiye: {weather.advice}")
    for line in weather.daily_summaries:
        print(f"  • {line}")


def _print_announcements(announcements: list[Announcement]) -> None:
    print("\n=== Güncel Duyurular ===")
    if not announcements:
        print("Gösterilecek duyuru bulunamadı.")
        return
    for item in announcements[:20]:
        d_str = f" ({item.published_date})" if item.published_date else ""
        print(f"• [{item.source}]{d_str} {item.title}")
        print(f"  {item.url}")


def _print_gpa_projection(projection: GpaProjection) -> None:
    print("\n=== Dönem Sonu YANO / GANO Projeksiyonu ===")
    if projection.projected_yano is None:
        print("Hesaplama için henüz geçme harfi veya vize+final notu yok.")
        return
    print(f"Tahmini YANO: {projection.projected_yano:.2f} (Kredi: {projection.total_term_credit:g})")
    if projection.projected_gano is not None:
        print(f"Tahmini GANO: {projection.projected_gano:.2f}")
    print(f"Durum: {projection.honor_status}")
    for c in projection.counted_courses:
        print(f"  • {c['code']} {c['name']} ({c['credit']:g} kr): {c['letter']} ({c['source']})")


def _print_weekly_schedule(slots: list[ScheduleSlot]) -> None:
    print("\n=== Haftalık Ders Programı ===")
    if not slots:
        print("ÜBYS üzerinde ders programı verisi bulunamadı.")
        return
    for s in sorted(slots, key=lambda x: (x.day_of_week, x.start_time, x.course_code)):
        t_str = f"{s.start_time}-{s.end_time}" if s.end_time else s.start_time
        room = f" | {s.classroom}" if s.classroom else ""
        print(f"• {s.day_name} {t_str}: {s.course_code} {s.course_name}{room}")


def _print_exam_schedule(exams: list[ExamScheduleItem]) -> None:
    print("\n=== ÜBYS Sınav Takvimi ===")
    if not exams:
        print("ÜBYS üzerinde sınav takvimi verisi bulunamadı.")
        return
    for ex in exams:
        t_str = f" {ex.exam_time}" if ex.exam_time else ""
        r_str = f" | Salon: {ex.classroom}" if ex.classroom else ""
        print(f"• {ex.exam_date.strftime('%d.%m.%Y')}{t_str} - {ex.course_code} {ex.course_name} ({ex.exam_type}){r_str}")


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


CATALOG_CACHE_TTL_DAYS = 14


def _norm_course_code(code: Optional[str]) -> str:
    return " ".join(str(code or "").split()).upper()


def _enrich_courses_with_catalog_cached(
    config: Config,
    courses: list[CourseGrade],
    program_hints: Optional[list[str]] = None,
    swiss_state: Optional[dict[str, Any]] = None,
    current_dt: Optional[datetime] = None,
) -> bool:
    """Dersleri Eğitim Kataloğu (14 günlük Gist önbellekli) ve manuel oranlarla zenginleştirir."""
    if not courses:
        return False

    enrolled_codes = {_norm_course_code(c.code) for c in courses if _norm_course_code(c.code)}
    today = (current_dt or now_tr()).date()
    today_str = today.isoformat()
    desired_override = config.ubys_program or None

    catalog_entries: dict[str, CourseCatalogEntry] = {}
    cache_dirty = False

    if config.enable_catalog and enrolled_codes:
        cache = swiss_state.get("course_catalog") if isinstance(swiss_state, dict) else None
        cached_entries: dict[str, CourseCatalogEntry] = {}
        cache_is_valid = False

        if isinstance(cache, dict):
            raw_entries = cache.get("entries") or {}
            if isinstance(raw_entries, dict):
                for k, v in raw_entries.items():
                    if isinstance(v, dict):
                        norm_k = _norm_course_code(k)
                        if norm_k:
                            cached_entries[norm_k] = CourseCatalogEntry.from_dict(v)

            not_found = {
                _norm_course_code(x)
                for x in (cache.get("not_found") or [])
                if _norm_course_code(x)
            }
            updated_date_str = str(cache.get("updated_date") or "")
            cached_override = cache.get("program_override") or None

            try:
                cached_date = date.fromisoformat(updated_date_str)
                age_days = (today - cached_date).days
            except ValueError:
                age_days = CATALOG_CACHE_TTL_DAYS + 1

            covered_codes = set(cached_entries) | not_found
            if (
                age_days <= CATALOG_CACHE_TTL_DAYS
                and cached_override == desired_override
                and enrolled_codes.issubset(covered_codes)
            ):
                cache_is_valid = True

        if cache_is_valid:
            catalog_entries = cached_entries
        else:
            try:
                fetched_entries, prog_id, _ = fetch_catalog_for_courses(
                    courses=courses,
                    base_url=config.ubys_base_url,
                    program_hints=program_hints or [],
                    program_override=desired_override,
                )
                catalog_entries = fetched_entries
                logger.info(
                    "Eğitim Kataloğu verileri güncellendi (%d/%d ders eşleşti).",
                    len(fetched_entries),
                    len(enrolled_codes),
                )
                if swiss_state is not None:
                    swiss_state["course_catalog"] = {
                        "updated_date": today_str,
                        "program_id": prog_id,
                        "program_override": desired_override,
                        "entries": {k: v.to_dict() for k, v in fetched_entries.items()},
                        "not_found": sorted(enrolled_codes - set(fetched_entries)),
                    }
                    cache_dirty = True
            except Exception as exc:
                logger.warning(
                    "Eğitim Kataloğu verisi çekilemedi (ÜBYS/varsayılan değerler kullanılacak): %s",
                    exc,
                )
                catalog_entries = cached_entries

    enrich_courses_with_catalog(
        courses=courses,
        catalog_entries=catalog_entries,
        course_weights_overrides=config.course_weights,
        course_hours_overrides=config.course_hours,
    )
    return cache_dirty


def _run_grades_module(
    config: Config,
    state: dict[str, Any],
    dump_html: bool = False,
    extra_context: Optional[dict[str, Any]] = None,
) -> tuple[bool, bool, dict[str, Any], list[CourseGrade], Optional[float]]:
    """ÜBYS not kontrolünü çalıştırır -> (başarılı_mı, durum_değişti_mi, güncel_state, dersler, gano)."""
    dump_dir = Path("debug_html") if dump_html else None
    last_home_gano: Optional[float] = None
    program_hints: list[str] = []
    prev_swiss = state.get("swiss_tool") or {}
    today_date = now_tr().date()

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
                fetch_materials=config.enable_materials,
            )
            raw_gano = client.last_home_gano
            last_home_gano = float(raw_gano) if isinstance(raw_gano, (int, float)) else None
            program_hints = client.student_program_hints
            logger.info("Toplam %d ders çekildi.", len(courses))

            if extra_context is not None:
                home_ann = client.home_announcements
                if isinstance(home_ann, list):
                    extra_context["home_announcements"] = home_ann

                if config.enable_transcript and prev_swiss.get("last_total_credit") is None:
                    try:
                        tr_summary = client.fetch_transcript(dump_dir=dump_dir)
                        raw_credit = tr_summary.total_credit
                        if isinstance(raw_credit, (int, float)) and not isinstance(raw_credit, bool):
                            extra_context["total_credit"] = float(raw_credit)
                    except Exception:
                        pass

                if config.enable_schedule and not _is_date_cache_fresh(prev_swiss.get("schedule_cache"), today_date, 7):
                    try:
                        sched_items = client.fetch_weekly_schedule(dump_dir=dump_dir)
                        if isinstance(sched_items, list):
                            extra_context["schedule"] = sched_items
                    except Exception as s_exc:
                        logger.debug("Ders programı çekilemedi: %s", s_exc)

                if config.enable_exam_schedule and not _is_date_cache_fresh(prev_swiss.get("exam_schedule_cache"), today_date, 1):
                    try:
                        exam_items = client.fetch_exam_schedule(dump_dir=dump_dir)
                        if isinstance(exam_items, list):
                            extra_context["exams"] = exam_items
                    except Exception as ex_exc:
                        logger.debug("Sınav takvimi çekilemedi: %s", ex_exc)

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
    swiss_state = dict(updated.get("swiss_tool") or {})
    if _enrich_courses_with_catalog_cached(
        config=config,
        courses=courses,
        program_hints=program_hints,
        swiss_state=swiss_state,
    ):
        updated["swiss_tool"] = swiss_state

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


def _is_date_cache_fresh(cache: Any, today: date, ttl_days: int) -> bool:
    if not isinstance(cache, dict):
        return False
    raw_date = str(cache.get("updated_date") or "")
    try:
        cached_dt = date.fromisoformat(raw_date)
    except ValueError:
        return False
    return (today - cached_dt).days <= ttl_days


def _get_weather_safe(config: Config) -> Optional[WeatherForecast]:
    if not config.enable_weather:
        return None
    try:
        return fetch_weather_forecast(
            lat=config.weather_lat,
            lon=config.weather_lon,
            location_name=config.weather_location,
        )
    except Exception as exc:
        logger.warning("Hava durumu alınamadı (atlandı): %s", exc)
        return None


def _run_dining_module(
    config: Config,
    swiss_state: dict[str, Any],
    current_dt: datetime,
    force_daily: bool = False,
) -> tuple[bool, bool, Optional[WeatherForecast]]:
    """Hafta içi günde bir kez yemekhane menüsünü (+ hava durumu) gönderir."""
    today = current_dt.date()
    today_str = today.isoformat()

    is_due = force_daily or (
        today.weekday() < 5
        and current_dt.hour >= config.dining_notify_hour
        and swiss_state.get("last_dining_date") != today_str
    )
    if not is_due:
        return True, False, None

    try:
        menus = fetch_dining_menus(
            sks_url=config.sks_url,
            sheet_url_override=config.dining_sheet_url,
        )
    except DiningError as exc:
        logger.warning("Yemekhane menüsü alınamadı: %s", exc)
        return False, False, None
    except Exception as exc:
        logger.warning("Yemekhane modülünde beklenmeyen hata: %s", exc)
        return False, False, None

    menu = get_menu_for_date(menus, today)
    is_next_preview = False
    if menu is None and force_daily:
        menu = get_next_menu(menus, today)
        is_next_preview = menu is not None

    if menu is None:
        logger.info("Bugün (%s) için yemekhane menüsü bulunamadı.", today_str)
        return True, False, None

    weather = _get_weather_safe(config)
    if not _send_telegram_safe(
        config,
        format_daily_menu(menu, is_next_preview=is_next_preview, weather=weather),
    ):
        return False, False, weather

    logger.info("Yemekhane menüsü Telegram'a gönderildi (%s).", menu.menu_date.isoformat())
    if not is_next_preview:
        swiss_state["last_dining_date"] = today_str
        return True, True, weather
    return True, False, weather


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


def _run_announcements_module(
    config: Config,
    swiss_state: dict[str, Any],
    home_announcements: Optional[list[Announcement]] = None,
) -> tuple[bool, list[Announcement]]:
    """Kastamonu Üniversitesi + OİDB + SKS + ÜBYS duyurularını tarar -> (state_dirty, çekilenler)."""
    try:
        combined = fetch_all_announcements(extra_sources=config.announcement_urls)
    except Exception as exc:
        logger.warning("Duyuru modülünde hata: %s", exc)
        combined = []

    seen_combined_ids = {a.announcement_id for a in combined}
    for ha in home_announcements or []:
        if ha.announcement_id not in seen_combined_ids:
            seen_combined_ids.add(ha.announcement_id)
            combined.append(ha)

    if not combined:
        return False, []

    prev_ids = swiss_state.get("seen_announcement_ids")
    if not isinstance(prev_ids, list):
        swiss_state["seen_announcement_ids"] = [a.announcement_id for a in combined][:150]
        logger.info("Duyuru başlangıç durumu kaydedildi (%d duyuru).", len(combined))
        return True, combined

    seen_set = {str(x) for x in prev_ids}
    new_items = filter_new_announcements(
        combined,
        seen_ids=seen_set,
        keywords=config.announcement_keywords,
    )
    if new_items:
        if _send_telegram_safe(config, format_announcements(new_items, is_preview=False)):
            updated_ids = [a.announcement_id for a in new_items] + [str(x) for x in prev_ids]
            swiss_state["seen_announcement_ids"] = list(dict.fromkeys(updated_ids))[:200]
            logger.info("%d yeni duyuru Telegram'a gönderildi.", len(new_items))
            return True, combined
        return False, combined

    # Yeni bildirim olmasa bile filtre dışında kalan ID'leri işaretle
    unseen_all = [a.announcement_id for a in combined if a.announcement_id not in seen_set]
    if unseen_all:
        swiss_state["seen_announcement_ids"] = list(dict.fromkeys(unseen_all + [str(x) for x in prev_ids]))[:200]
        return True, combined
    return False, combined


def _run_materials_module(
    config: Config,
    swiss_state: dict[str, Any],
    courses: list[CourseGrade],
) -> bool:
    """Ders içine yüklenen yeni dosya/ödev/duyuruları algılar -> state_dirty."""
    all_mats: list[CourseMaterial] = [m for c in courses for m in c.materials]
    if not all_mats:
        return False

    prev_ids = swiss_state.get("seen_material_ids")
    if not isinstance(prev_ids, list):
        swiss_state["seen_material_ids"] = [m.material_id for m in all_mats][:300]
        return True

    seen_set = {str(x) for x in prev_ids}
    new_mats = [m for m in all_mats if m.material_id not in seen_set]
    if not new_mats:
        return False

    if _send_telegram_safe(config, format_material_alerts(new_mats, config.ubys_base_url)):
        merged = [m.material_id for m in new_mats] + [str(x) for x in prev_ids]
        swiss_state["seen_material_ids"] = list(dict.fromkeys(merged))[:300]
        logger.info("%d yeni ders materyali/ödevi bildirildi.", len(new_mats))
        return True
    return False


def _run_schedule_and_exams_module(
    config: Config,
    swiss_state: dict[str, Any],
    current_dt: datetime,
    ubys_extras: dict[str, Any],
    force_daily: bool = False,
) -> tuple[bool, list[ScheduleSlot], list[ExamScheduleItem]]:
    """Ders programı (7 gün cache) ve sınav takvimi (1 gün cache) hatırlatmalarını çalıştırır."""
    today = current_dt.date()
    today_str = today.isoformat()
    dirty = False

    slots: list[ScheduleSlot] = []
    if "schedule" in ubys_extras and isinstance(ubys_extras["schedule"], list):
        slots = ubys_extras["schedule"]
        swiss_state["schedule_cache"] = {
            "updated_date": today_str,
            "slots": [s.to_dict() for s in slots],
        }
        dirty = True
    elif isinstance(swiss_state.get("schedule_cache"), dict):
        raw_slots = swiss_state["schedule_cache"].get("slots") or []
        slots = [ScheduleSlot.from_dict(s) for s in raw_slots if isinstance(s, dict)]

    if config.enable_schedule and slots:
        due_schedule = force_daily or (
            today.weekday() < 5
            and current_dt.hour >= config.schedule_notify_hour
            and swiss_state.get("last_schedule_date") != today_str
        )
        if due_schedule:
            today_slots = get_slots_for_day(slots, today)
            if today_slots or force_daily:
                if _send_telegram_safe(config, format_daily_schedule(today_slots, today, config.ubys_base_url)):
                    swiss_state["last_schedule_date"] = today_str
                    dirty = True

    exams: list[ExamScheduleItem] = []
    if "exams" in ubys_extras and isinstance(ubys_extras["exams"], list):
        exams = ubys_extras["exams"]
        swiss_state["exam_schedule_cache"] = {
            "updated_date": today_str,
            "exams": [e.to_dict() for e in exams],
        }
        dirty = True
    elif isinstance(swiss_state.get("exam_schedule_cache"), dict):
        raw_exams = swiss_state["exam_schedule_cache"].get("exams") or []
        exams = [ExamScheduleItem.from_dict(e) for e in raw_exams if isinstance(e, dict)]

    if config.enable_exam_schedule and exams:
        sent_ex = _prune_old_milestones(dict(swiss_state.get("sent_exam_reminders") or {}), today)
        reminders = find_exam_reminders(exams, today, config.exam_reminder_days, sent_ex)
        if reminders:
            if _send_telegram_safe(config, format_exam_reminders(reminders, config.ubys_base_url)):
                for ex, days_until in reminders:
                    sent_ex[exam_reminder_key(ex, days_until)] = today_str
                swiss_state["sent_exam_reminders"] = sent_ex
                dirty = True

    return dirty, slots, exams


def _run_weekly_briefing_module(
    config: Config,
    swiss_state: dict[str, Any],
    current_dt: datetime,
    courses: list[CourseGrade],
    last_home_gano: Optional[float],
    attendance_reports: list[AttendanceReport],
    exams: list[ExamScheduleItem],
    weather: Optional[WeatherForecast],
    force_daily: bool = False,
) -> bool:
    """Pazar akşamı haftalık toplu öğrenci brifingi gönderir -> state_dirty."""
    today = current_dt.date()
    iso_year, iso_week, _ = today.isocalendar()
    iso_week_str = f"{iso_year}-W{iso_week:02d}"

    is_due = force_daily or (
        today.weekday() == 6
        and current_dt.hour >= config.weekly_briefing_hour
        and swiss_state.get("last_weekly_briefing") != iso_week_str
    )
    if not is_due:
        return False

    if weather is None and config.enable_weather:
        weather = _get_weather_safe(config)

    ongoing_cal: list[CalendarEvent] = []
    upcoming_cal: list[CalendarEvent] = []
    if config.enable_calendar:
        try:
            _, _, all_events = fetch_calendar_events(config.calendar_url, config.calendar_faculty)
            ev_filtered = filter_events_by_categories(all_events, config.calendar_categories)
            ongoing_cal, upcoming_cal = find_ongoing_and_upcoming(ev_filtered, today, config.calendar_lookahead_days)
        except Exception:
            pass

    reports = attendance_reports
    if not reports and courses and config.enable_attendance:
        reports = evaluate_all_attendance(
            courses,
            semester_weeks=config.semester_weeks,
            theory_min_pct=config.theory_min_attendance,
            practice_min_pct=config.practice_min_attendance,
        )

    gpa_proj: Optional[GpaProjection] = None
    if courses:
        base_gano = last_home_gano if last_home_gano is not None else swiss_state.get("last_gano")
        base_cred = swiss_state.get("last_total_credit")
        gpa_proj = project_semester_gpa(
            courses,
            base_gano=float(base_gano) if base_gano is not None else None,
            base_credits=float(base_cred) if base_cred is not None else None,
            default_midterm_weight=config.midterm_weight,
            default_final_weight=config.final_weight,
            final_min_score=config.final_min_score,
        )

    msg = format_weekly_briefing(
        today=today,
        ongoing_cal=ongoing_cal,
        upcoming_cal=upcoming_cal,
        exams=exams,
        attendance_reports=reports,
        gpa_projection=gpa_proj,
        weather=weather,
        base_url=config.ubys_base_url,
    )
    if _send_telegram_safe(config, msg):
        swiss_state["last_weekly_briefing"] = iso_week_str
        logger.info("Haftalık öğrenci brifingi gönderildi (%s).", iso_week_str)
        return True
    return False


def run_dining_preview(config: Config, notify_test: bool = False) -> int:
    """Sadece yemekhane menüsünü (+ hava durumunu) çekip ekrana (ve isteğe bağlı Telegram'a) yazdırır."""
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

    weather = _get_weather_safe(config)
    _print_dining_menu(menu, is_next_preview=is_next_preview, weather=weather)
    if notify_test and menu is not None:
        if not _send_telegram_safe(
            config,
            format_daily_menu(menu, is_next_preview=is_next_preview, weather=weather),
        ):
            return 1
        logger.info("Yemekhane menüsü Telegram'a gönderildi.")
    return 0


def run_weather_preview(config: Config, notify_test: bool = False) -> int:
    """Kastamonu / Kuzeykent hava durumunu çekip ekrana (ve Telegram'a) yazdırır."""
    try:
        weather = fetch_weather_forecast(
            lat=config.weather_lat,
            lon=config.weather_lon,
            location_name=config.weather_location,
        )
    except Exception as exc:
        logger.error("Hava durumu hatası: %s", exc)
        return 1

    _print_weather_report(weather)
    if notify_test:
        if not _send_telegram_safe(config, format_weather_report(weather)):
            return 1
        logger.info("Hava durumu raporu Telegram'a gönderildi.")
    return 0


def run_announcements_preview(config: Config, notify_test: bool = False) -> int:
    """Kastamonu Üniversitesi, OİDB, SKS ve yapılandırılmış duyuruları gösterir."""
    items = fetch_all_announcements(extra_sources=config.announcement_urls)
    if config.announcement_keywords:
        items = filter_new_announcements(items, seen_ids=set(), keywords=config.announcement_keywords)
    _print_announcements(items)
    if notify_test:
        if not _send_telegram_safe(config, format_announcements(items, is_preview=True)):
            return 1
        logger.info("Duyuru özeti Telegram'a gönderildi.")
    return 0


def run_gpa_preview(
    config: Config,
    notify_test: bool = False,
    dump_html: bool = False,
) -> int:
    """Tahmini dönem YANO/GANO ve Onur belgesi durumunu hesaplar."""
    dump_dir = Path("debug_html") if dump_html else None
    program_hints: list[str] = []
    base_gano: Optional[float] = None
    base_credits: Optional[float] = None
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
                fetch_materials=False,
            )
            base_gano = client.last_home_gano
            program_hints = client.student_program_hints
            try:
                tr_sum = client.fetch_transcript(dump_dir=dump_dir)
                if tr_sum.gano is not None:
                    base_gano = tr_sum.gano
                base_credits = tr_sum.total_credit
            except Exception:
                pass
    except Exception as exc:
        logger.error("YANO/GANO projeksiyonu için ÜBYS verisi çekilemedi: %s", exc)
        return 1

    _enrich_courses_with_catalog_cached(config=config, courses=courses, program_hints=program_hints)
    projection = project_semester_gpa(
        courses=courses,
        base_gano=base_gano,
        base_credits=base_credits,
        default_midterm_weight=config.midterm_weight,
        default_final_weight=config.final_weight,
        final_min_score=config.final_min_score,
    )
    _print_gpa_projection(projection)
    if notify_test:
        if not _send_telegram_safe(config, format_gpa_projection(projection, config.ubys_base_url)):
            return 1
        logger.info("YANO/GANO projeksiyonu Telegram'a gönderildi.")
    return 0


def run_schedule_preview(
    config: Config,
    notify_test: bool = False,
    dump_html: bool = False,
) -> int:
    """ÜBYS haftalık ders programını çekip ekrana (ve Telegram'a) yazdırır."""
    dump_dir = Path("debug_html") if dump_html else None
    try:
        with UBYSClient(base_url=config.ubys_base_url) as client:
            client.login(
                username=config.ubys_username,
                password=config.ubys_password,
                user_group_id=config.ubys_user_group_id,
            )
            slots = client.fetch_weekly_schedule(dump_dir=dump_dir)
    except Exception as exc:
        logger.error("Ders programı çekilemedi: %s", exc)
        return 1

    _print_weekly_schedule(slots)
    if notify_test:
        if not _send_telegram_safe(config, format_weekly_schedule(slots, config.ubys_base_url)):
            return 1
        logger.info("Ders programı Telegram'a gönderildi.")
    return 0


def run_exams_preview(
    config: Config,
    notify_test: bool = False,
    dump_html: bool = False,
) -> int:
    """ÜBYS sınav takvimini çekip ekrana (ve Telegram'a) yazdırır."""
    dump_dir = Path("debug_html") if dump_html else None
    today = now_tr().date()
    try:
        with UBYSClient(base_url=config.ubys_base_url) as client:
            client.login(
                username=config.ubys_username,
                password=config.ubys_password,
                user_group_id=config.ubys_user_group_id,
            )
            exams = client.fetch_exam_schedule(dump_dir=dump_dir)
    except Exception as exc:
        logger.error("Sınav takvimi çekilemedi: %s", exc)
        return 1

    _print_exam_schedule(exams)
    if notify_test:
        if not _send_telegram_safe(config, format_exam_schedule(exams, today, config.ubys_base_url)):
            return 1
        logger.info("Sınav takvimi Telegram'a gönderildi.")
    return 0


def run_briefing_preview(
    config: Config,
    notify_test: bool = False,
    dump_html: bool = False,
) -> int:
    """Haftalık toplu öğrenci özet brifingini oluşturur."""
    today = now_tr().date()
    dump_dir = Path("debug_html") if dump_html else None
    courses: list[CourseGrade] = []
    exams: list[ExamScheduleItem] = []
    base_gano: Optional[float] = None
    base_credit: Optional[float] = None
    hints: list[str] = []

    if config.enable_grades:
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
                    fetch_materials=False,
                )
                base_gano = client.last_home_gano
                hints = client.student_program_hints
                try:
                    tr_sum = client.fetch_transcript(dump_dir=dump_dir)
                    base_credit = tr_sum.total_credit
                    if tr_sum.gano is not None:
                        base_gano = tr_sum.gano
                except Exception:
                    pass
                if config.enable_exam_schedule:
                    try:
                        exams = client.fetch_exam_schedule(dump_dir=dump_dir)
                    except Exception:
                        pass
            _enrich_courses_with_catalog_cached(config=config, courses=courses, program_hints=hints)
        except Exception as exc:
            logger.warning("Brifing için ÜBYS verileri alınamadı: %s", exc)

    reports = evaluate_all_attendance(
        courses,
        semester_weeks=config.semester_weeks,
        theory_min_pct=config.theory_min_attendance,
        practice_min_pct=config.practice_min_attendance,
    ) if courses else []
    proj = project_semester_gpa(
        courses=courses,
        base_gano=base_gano,
        base_credits=base_credit,
        default_midterm_weight=config.midterm_weight,
        default_final_weight=config.final_weight,
        final_min_score=config.final_min_score,
    ) if courses else None

    ongoing_cal: list[CalendarEvent] = []
    upcoming_cal: list[CalendarEvent] = []
    if config.enable_calendar:
        try:
            _, _, all_ev = fetch_calendar_events(config.calendar_url, config.calendar_faculty)
            ev_f = filter_events_by_categories(all_ev, config.calendar_categories)
            ongoing_cal, upcoming_cal = find_ongoing_and_upcoming(ev_f, today, config.calendar_lookahead_days)
        except Exception:
            pass

    weather = _get_weather_safe(config)
    msg = format_weekly_briefing(
        today=today,
        ongoing_cal=ongoing_cal,
        upcoming_cal=upcoming_cal,
        exams=exams,
        attendance_reports=reports,
        gpa_projection=proj,
        weather=weather,
        base_url=config.ubys_base_url,
    )
    print("\n=== Haftalık Öğrenci Özeti ===\n" + msg)
    if notify_test:
        if not _send_telegram_safe(config, msg):
            return 1
        logger.info("Haftalık özet Telegram'a gönderildi.")
    return 0


def run_commands_once(config: Config) -> int:
    """Sadece bekleyen Telegram bot komutlarını okuyup yanıtlar."""
    state_store = create_state_store(
        state_file=config.state_file,
        gist_id=config.gist_id,
        gist_token=config.gist_token,
        gist_filename=config.gist_filename,
    )
    try:
        loaded_state = state_store.load()
    except StateStorageError as exc:
        logger.error("Durum okunamadı: %s", exc)
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
    swiss_state = dict(working_state.get("swiss_tool") or {})
    ctx: dict[str, Any] = {"today": now_tr().date(), "swiss_state": swiss_state}
    _, dirty = process_telegram_commands(config, swiss_state, ctx, poll_timeout=0)
    if dirty:
        working_state["swiss_tool"] = swiss_state
        working_state["updated_at"] = _utc_now_iso()
        if not _save_state_safe(config, state_store, working_state):
            return 1
    return 0


def run_listen_loop(config: Config) -> int:
    """VPS/Docker/PC için anlık Telegram komut dinleyicisi (long polling)."""
    logger.info("Telegram anlık komut dinleyicisi başlatıldı (Çıkmak için Ctrl+C)...")
    state_store = create_state_store(
        state_file=config.state_file,
        gist_id=config.gist_id,
        gist_token=config.gist_token,
        gist_filename=config.gist_filename,
    )
    try:
        while True:
            try:
                loaded_state = state_store.load()
                working_state: dict[str, Any] = (
                    copy.deepcopy(loaded_state)
                    if isinstance(loaded_state, dict)
                    else {
                        "schema_version": STATE_SCHEMA_VERSION,
                        "baseline_initialized": False,
                        "courses": {},
                    }
                )
                swiss_state = dict(working_state.get("swiss_tool") or {})
                ctx: dict[str, Any] = {"today": now_tr().date(), "swiss_state": swiss_state}
                _, dirty = process_telegram_commands(config, swiss_state, ctx, poll_timeout=25)
                if dirty:
                    working_state["swiss_tool"] = swiss_state
                    working_state["updated_at"] = _utc_now_iso()
                    state_store.save(working_state)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.warning("Komut dinleyicide geçici hata: %s", exc)
                time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Dinleyici durduruldu.")
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
    program_hints: list[str] = []
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
            program_hints = client.student_program_hints
    except Exception as exc:
        logger.error("Devamsızlık verileri çekilemedi: %s", exc)
        return 1

    _enrich_courses_with_catalog_cached(config=config, courses=courses, program_hints=program_hints)
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


def run_calc_preview(
    config: Config,
    midterm_score: float,
    notify_test: bool = False,
    weights_raw: Optional[str] = None,
) -> int:
    """Verilen vize notuna göre final hedeflerini hesaplar ve yazdırır."""
    if midterm_score < 0 or midterm_score > 100:
        logger.error("Vize notu 0 ile 100 arasında olmalıdır (verilen: %s).", midterm_score)
        return 2

    mw, fw = config.midterm_weight, config.final_weight
    weight_src = "default"
    if weights_raw:
        try:
            mw, fw = parse_weight_pair(weights_raw, "--weights")
            weight_src = "manual"
        except ConfigError as exc:
            logger.error("%s", exc)
            return 2

    analysis = calculate_final_targets(
        midterm_score=midterm_score,
        midterm_weight=mw,
        final_weight=fw,
        final_min_score=config.final_min_score,
        weight_source=weight_src,
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
    home_anns: list[Announcement] = []

    if config.enable_grades:
        transcript_summary: Optional[TranscriptSummary] = None
        slots: list[ScheduleSlot] = []
        exams: list[ExamScheduleItem] = []
        program_hints: list[str] = []
        base_gano: Optional[float] = None
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
                    fetch_materials=config.enable_materials,
                )
                base_gano = client.last_home_gano
                program_hints = client.student_program_hints
                home_anns = client.home_announcements
                if config.enable_transcript:
                    try:
                        transcript_summary = client.fetch_transcript(dump_dir=dump_dir)
                    except Exception as t_exc:
                        logger.warning("Transkript alınamadı: %s", t_exc)
                if config.enable_schedule:
                    try:
                        slots = client.fetch_weekly_schedule(dump_dir=dump_dir)
                    except Exception:
                        pass
                if config.enable_exam_schedule:
                    try:
                        exams = client.fetch_exam_schedule(dump_dir=dump_dir)
                    except Exception:
                        pass

            _enrich_courses_with_catalog_cached(
                config=config,
                courses=courses,
                program_hints=program_hints,
            )
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

            if courses:
                proj = project_semester_gpa(
                    courses=courses,
                    base_gano=(
                        transcript_summary.gano
                        if transcript_summary and transcript_summary.gano is not None
                        else base_gano
                    ),
                    base_credits=(transcript_summary.total_credit if transcript_summary else None),
                    default_midterm_weight=config.midterm_weight,
                    default_final_weight=config.final_weight,
                    final_min_score=config.final_min_score,
                )
                if proj.projected_yano is not None:
                    _print_gpa_projection(proj)
                    if notify_test:
                        if not _send_telegram_safe(config, format_gpa_projection(proj, config.ubys_base_url)):
                            overall_ok = False

            if transcript_summary is not None:
                _print_transcript_summary(transcript_summary)
                if notify_test:
                    if not _send_telegram_safe(
                        config, format_transcript_summary(transcript_summary, config.ubys_base_url)
                    ):
                        overall_ok = False

            if slots:
                _print_weekly_schedule(slots)
                if notify_test:
                    if not _send_telegram_safe(config, format_weekly_schedule(slots, config.ubys_base_url)):
                        overall_ok = False

            if exams:
                _print_exam_schedule(exams)
                if notify_test:
                    if not _send_telegram_safe(
                        config, format_exam_schedule(exams, now_tr().date(), config.ubys_base_url)
                    ):
                        overall_ok = False
        except Exception as exc:
            logger.error("ÜBYS testi başarısız: %s", exc)
            overall_ok = False

    if config.enable_dining:
        if run_dining_preview(config, notify_test=notify_test) != 0:
            overall_ok = False

    if config.enable_weather and not config.enable_dining:
        if run_weather_preview(config, notify_test=notify_test) != 0:
            overall_ok = False

    if config.enable_calendar:
        if run_calendar_preview(config, notify_test=notify_test) != 0:
            overall_ok = False

    if config.enable_announcements:
        anns = fetch_all_announcements(extra_sources=config.announcement_urls)
        seen_a = {a.announcement_id for a in anns}
        for ha in home_anns:
            if ha.announcement_id not in seen_a:
                anns.append(ha)
        if config.announcement_keywords:
            anns = filter_new_announcements(anns, seen_ids=set(), keywords=config.announcement_keywords)
        _print_announcements(anns)
        if notify_test and anns:
            if not _send_telegram_safe(config, format_announcements(anns, is_preview=True)):
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
    ubys_extras: dict[str, Any] = {}

    if config.enable_grades:
        grades_ok, grades_dirty, working_state, courses, last_home_gano = _run_grades_module(
            config,
            working_state,
            dump_html=dump_html,
            extra_context=ubys_extras,
        )
        if grades_dirty:
            state_dirty = True

    current_dt = now_tr()
    swiss_state = dict(working_state.get("swiss_tool") or {})
    if "total_credit" in ubys_extras and ubys_extras["total_credit"] is not None:
        swiss_state["last_total_credit"] = float(ubys_extras["total_credit"])
        working_state["swiss_tool"] = swiss_state
        state_dirty = True

    attendance_reports: list[AttendanceReport] = []
    if grades_ok and courses and config.enable_attendance:
        attendance_reports = evaluate_all_attendance(
            courses,
            semester_weeks=config.semester_weeks,
            theory_min_pct=config.theory_min_attendance,
            practice_min_pct=config.practice_min_attendance,
        )
        prev_attendance = swiss_state.get("attendance")
        if isinstance(prev_attendance, dict):
            alerts = diff_attendance(prev_attendance, attendance_reports)
            if alerts:
                _send_telegram_safe(config, format_attendance_alerts(alerts, config.ubys_base_url))
        swiss_state["attendance"] = build_attendance_snapshot(attendance_reports)
        working_state["swiss_tool"] = swiss_state
        state_dirty = True

    if grades_ok and courses and config.enable_materials:
        if _run_materials_module(config, swiss_state, courses):
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
    weather: Optional[WeatherForecast] = None
    if config.enable_dining:
        dining_ok, dining_dirty, weather = _run_dining_module(
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

    fetched_announcements: list[Announcement] = []
    if config.enable_announcements:
        ann_dirty, fetched_announcements = _run_announcements_module(
            config,
            swiss_state,
            home_announcements=ubys_extras.get("home_announcements"),
        )
        if ann_dirty:
            working_state["swiss_tool"] = swiss_state
            state_dirty = True

    schedule_slots: list[ScheduleSlot] = []
    exam_items: list[ExamScheduleItem] = []
    if grades_ok and (config.enable_schedule or config.enable_exam_schedule):
        sched_dirty, schedule_slots, exam_items = _run_schedule_and_exams_module(
            config,
            swiss_state,
            current_dt,
            ubys_extras,
            force_daily=force_daily,
        )
        if sched_dirty:
            working_state["swiss_tool"] = swiss_state
            state_dirty = True

    if config.enable_weekly_briefing:
        if _run_weekly_briefing_module(
            config=config,
            swiss_state=swiss_state,
            current_dt=current_dt,
            courses=courses,
            last_home_gano=last_home_gano,
            attendance_reports=attendance_reports,
            exams=exam_items,
            weather=weather,
            force_daily=force_daily,
        ):
            working_state["swiss_tool"] = swiss_state
            state_dirty = True

    if config.enable_commands and config.telegram_bot_token and config.telegram_chat_ids:
        try:
            cmd_ctx: dict[str, Any] = {
                "today": current_dt.date(),
                "swiss_state": swiss_state,
            }
            if courses:
                cmd_ctx["courses"] = courses
            if last_home_gano is not None:
                cmd_ctx["home_gano"] = last_home_gano
            if weather is not None:
                cmd_ctx["weather"] = weather
            if fetched_announcements:
                cmd_ctx["announcements"] = fetched_announcements
            if schedule_slots:
                cmd_ctx["schedule"] = schedule_slots
            if exam_items:
                cmd_ctx["exams"] = exam_items
            _, cmd_dirty = process_telegram_commands(config, swiss_state, cmd_ctx, poll_timeout=0)
            if cmd_dirty:
                working_state["swiss_tool"] = swiss_state
                state_dirty = True
        except Exception as cmd_exc:
            logger.warning("Telegram komut kontrolü geçici hata verdi: %s", cmd_exc)

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
    mode_group.add_argument(
        "--weather",
        action="store_true",
        help="Kastamonu / Kuzeykent hava durumunu gösterir (ÜBYS şifresi gerektirmez).",
    )
    mode_group.add_argument(
        "--announcements",
        action="store_true",
        help="Kastamonu Üniversitesi, OİDB ve SKS güncel duyurularını gösterir (ÜBYS şifresi gerektirmez).",
    )
    mode_group.add_argument(
        "--gpa",
        action="store_true",
        help="Tahmini dönem YANO/GANO ve Onur belgesi projeksiyonunu hesaplar (state değiştirmez).",
    )
    mode_group.add_argument(
        "--schedule",
        action="store_true",
        help="ÜBYS haftalık ders programını gösterir (state değiştirmez).",
    )
    mode_group.add_argument(
        "--exams",
        action="store_true",
        help="ÜBYS vize/final sınav takvimini gösterir (state değiştirmez).",
    )
    mode_group.add_argument(
        "--briefing",
        action="store_true",
        help="Haftalık toplu öğrenci özet brifingini oluşturur (state değiştirmez).",
    )
    mode_group.add_argument(
        "--commands",
        action="store_true",
        help="Telegram üzerinden gelen bot komutlarını tek seferlik yanıtlar.",
    )
    mode_group.add_argument(
        "--listen",
        action="store_true",
        help="VPS/Docker/PC için anlık Telegram bot komut dinleyicisini başlatır.",
    )
    parser.add_argument(
        "--weights",
        metavar="VIZE/FINAL",
        help="--calc ile vize/final yüzdelerini belirtir (örnek: --calc 80 --weights 30/70).",
    )
    parser.add_argument(
        "--notify-test",
        action="store_true",
        help="Önizleme komutlarıyla Telegram'a da mesaj gönderir.",
    )
    parser.add_argument(
        "--force-daily",
        action="store_true",
        help="--once ile kullanıldığında günlük yemekhane/takvim/program/brifing özetini zorla gönderir.",
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
        or args.weather
        or args.announcements
        or args.gpa
        or args.schedule
        or args.exams
        or args.briefing
        or (args.calc is not None)
    )
    require_telegram = bool(
        args.notify_test or args.commands or args.listen or not is_preview_cmd
    )
    if args.calc is not None or args.dining or args.calendar or args.weather or args.announcements:
        require_ubys: Optional[bool] = False
    elif args.transcript or args.attendance or args.gpa or args.schedule or args.exams:
        require_ubys = True
    elif args.commands or args.listen:
        require_ubys = False
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
        return run_calc_preview(
            config,
            args.calc,
            notify_test=args.notify_test,
            weights_raw=args.weights,
        )
    if args.weather:
        return run_weather_preview(config, notify_test=args.notify_test)
    if args.announcements:
        return run_announcements_preview(config, notify_test=args.notify_test)
    if args.gpa:
        return run_gpa_preview(config, notify_test=args.notify_test, dump_html=args.dump_html)
    if args.schedule:
        return run_schedule_preview(config, notify_test=args.notify_test, dump_html=args.dump_html)
    if args.exams:
        return run_exams_preview(config, notify_test=args.notify_test, dump_html=args.dump_html)
    if args.briefing:
        return run_briefing_preview(config, notify_test=args.notify_test, dump_html=args.dump_html)
    if args.commands:
        return run_commands_once(config)
    if args.listen:
        return run_listen_loop(config)
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
