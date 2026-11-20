"""Telegram etkileşimli bot komutları (/yemek, /hesapla, /devamsizlik vb.) modülü."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Callable, Optional

from .announcements import fetch_all_announcements
from .attendance import evaluate_all_attendance
from .calendar_tracker import fetch_calendar_events, filter_events_by_categories, find_ongoing_and_upcoming
from .config import Config, ConfigError, parse_weight_pair
from .course_catalog import enrich_courses_with_catalog, fetch_catalog_for_courses
from .dining import fetch_dining_menus, get_menu_for_date, get_next_menu
from .grade_calculator import calculate_final_targets, project_semester_gpa
from .models import (
    Announcement,
    CourseCatalogEntry,
    CourseGrade,
    ExamScheduleItem,
    ScheduleSlot,
    WeatherForecast,
)
from .notifier import (
    TelegramNotifier,
    format_announcements,
    format_attendance_report,
    format_calendar_digest,
    format_daily_menu,
    format_daily_schedule,
    format_exam_schedule,
    format_gpa_projection,
    format_grade_calculator,
    format_help_message,
    format_test_summary,
    format_transcript_summary,
    format_weather_report,
    format_weekly_briefing,
    format_weekly_schedule,
)
from .schedule import get_slots_for_day
from .ubys_client import UBYSClient
from .weather import fetch_weather_forecast

logger = logging.getLogger(__name__)

BOT_COMMANDS_VERSION = 1

BOT_COMMANDS_MENU: list[dict[str, str]] = [
    {"command": "yardim", "description": "Kullanılabilir tüm komutları gösterir"},
    {"command": "notlar", "description": "Güncel dönem notlarını listeler"},
    {"command": "devamsizlik", "description": "Gün ve saat bazlı devamsızlık haklarını gösterir"},
    {"command": "hesapla", "description": "Vize notuna göre final hedeflerini hesaplar (/hesapla 80 30/70)"},
    {"command": "yemek", "description": "Günün yemekhane menüsü ve hava durumu"},
    {"command": "hava", "description": "Kuzeykent kampüsü 3 günlük hava durumu"},
    {"command": "program", "description": "Haftalık ders programını gösterir (/program bugun)"},
    {"command": "sinav", "description": "Yaklaşan sınav tarih ve salonlarını listeler"},
    {"command": "duyuru", "description": "Kastamonu Üni., OİDB, SKS güncel duyuruları"},
    {"command": "takvim", "description": "Akademik takvimde yaklaşan önemli tarihler"},
    {"command": "transkript", "description": "Transkript ve dönem ortalamaları"},
    {"command": "gano", "description": "Tahmini dönem YANO/GANO ve Onur belgesi durumu"},
    {"command": "ozet", "description": "Haftalık toplu öğrenci brifingi"},
]

_COMMAND_ALIASES: dict[str, str] = {
    "start": "yardim",
    "help": "yardim",
    "yardim": "yardim",
    "yardım": "yardim",
    "notlar": "notlar",
    "not": "notlar",
    "devamsizlik": "devamsizlik",
    "devamsızlık": "devamsizlik",
    "devam": "devamsizlik",
    "hesapla": "hesapla",
    "hesap": "hesapla",
    "final": "hesapla",
    "yemek": "yemek",
    "yemekhane": "yemek",
    "menu": "yemek",
    "menü": "yemek",
    "hava": "hava",
    "havadurumu": "hava",
    "program": "program",
    "dersprogrami": "program",
    "dersprogramı": "program",
    "sinav": "sinav",
    "sınav": "sinav",
    "sinavlar": "sinav",
    "sınavlar": "sinav",
    "duyuru": "duyuru",
    "duyurular": "duyuru",
    "takvim": "takvim",
    "akademiktakvim": "takvim",
    "transkript": "transkript",
    "gano": "gano",
    "yano": "gano",
    "onur": "gano",
    "ozet": "ozet",
    "özet": "ozet",
}


def parse_bot_command(text: str) -> tuple[Optional[str], list[str]]:
    """Telegram mesaj metninden /komut adını ve argümanlarını ayrıştırır."""
    cleaned = (text or "").strip()
    if not cleaned.startswith("/"):
        return None, []
    parts = cleaned.split()
    raw_cmd = parts[0][1:]
    if "@" in raw_cmd:
        raw_cmd = raw_cmd.split("@", 1)[0]
    norm = raw_cmd.replace("İ", "i").replace("I", "ı").lower().strip()
    canonical = _COMMAND_ALIASES.get(norm)
    if not canonical:
        return None, parts[1:]
    return canonical, parts[1:]


def _get_or_fetch_weather(config: Config, context: dict[str, Any]) -> Optional[WeatherForecast]:
    if "weather" in context and isinstance(context["weather"], WeatherForecast):
        return context["weather"]
    try:
        forecast = fetch_weather_forecast(
            lat=config.weather_lat,
            lon=config.weather_lon,
            location_name=config.weather_location,
        )
        context["weather"] = forecast
        return forecast
    except Exception:
        return None


def _get_or_fetch_courses(config: Config, context: dict[str, Any]) -> list[CourseGrade]:
    existing = context.get("courses")
    if isinstance(existing, list) and existing:
        return existing

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
            fetch_materials=False,
        )
        context["courses"] = courses
        if client.last_home_gano is not None:
            context["home_gano"] = float(client.last_home_gano)
        hints = client.student_program_hints

    catalog_entries: dict[str, CourseCatalogEntry] = {}
    cache = (context.get("swiss_state") or {}).get("course_catalog")
    if isinstance(cache, dict) and isinstance(cache.get("entries"), dict):
        for k, v in cache["entries"].items():
            if isinstance(v, dict):
                catalog_entries[k] = CourseCatalogEntry.from_dict(v)

    if config.enable_catalog and courses and not catalog_entries:
        try:
            catalog_entries, _, _ = fetch_catalog_for_courses(
                courses=courses,
                base_url=config.ubys_base_url,
                program_hints=hints,
                program_override=config.ubys_program,
            )
        except Exception:
            pass

    enrich_courses_with_catalog(
        courses=courses,
        catalog_entries=catalog_entries,
        course_weights_overrides=config.course_weights,
        course_hours_overrides=config.course_hours,
    )
    return courses


def _get_or_fetch_schedule(config: Config, context: dict[str, Any]) -> list[ScheduleSlot]:
    existing = context.get("schedule")
    if isinstance(existing, list):
        return existing
    swiss_state = context.get("swiss_state") or {}
    cache = swiss_state.get("schedule_cache")
    if isinstance(cache, dict) and isinstance(cache.get("slots"), list):
        slots = [ScheduleSlot.from_dict(s) for s in cache["slots"] if isinstance(s, dict)]
        if slots:
            context["schedule"] = slots
            return slots
    with UBYSClient(base_url=config.ubys_base_url) as client:
        client.login(
            username=config.ubys_username,
            password=config.ubys_password,
            user_group_id=config.ubys_user_group_id,
        )
        slots = client.fetch_weekly_schedule()
    context["schedule"] = slots
    return slots


def _get_or_fetch_exams(config: Config, context: dict[str, Any]) -> list[ExamScheduleItem]:
    existing = context.get("exams")
    if isinstance(existing, list):
        return existing
    swiss_state = context.get("swiss_state") or {}
    cache = swiss_state.get("exam_schedule_cache")
    if isinstance(cache, dict) and isinstance(cache.get("exams"), list):
        exams = [ExamScheduleItem.from_dict(e) for e in cache["exams"] if isinstance(e, dict)]
        if exams:
            context["exams"] = exams
            return exams
    with UBYSClient(base_url=config.ubys_base_url) as client:
        client.login(
            username=config.ubys_username,
            password=config.ubys_password,
            user_group_id=config.ubys_user_group_id,
        )
        exams = client.fetch_exam_schedule()
    context["exams"] = exams
    return exams


def handle_command(
    command: str,
    args: list[str],
    config: Config,
    context: dict[str, Any],
) -> str:
    """Yetkili sohbetten gelen Telegram komutunu işleyip HTML yanıt metni üretir."""
    today: date = context.get("today") or date.today()

    if command == "yardim":
        return format_help_message()

    if command == "hesapla":
        if not args:
            return "ℹ️ Kullanım: <code>/hesapla 80</code> veya <code>/hesapla 80 30/70</code>"
        try:
            score = float(args[0].replace(",", "."))
        except ValueError:
            return "⚠️ Geçerli bir vize notu girin (örnek: <code>/hesapla 75 30/70</code>)."
        if score < 0 or score > 100:
            return "⚠️ Vize notu 0 ile 100 arasında olmalıdır."
        mw, fw = config.midterm_weight, config.final_weight
        w_src = "default"
        if len(args) >= 2:
            try:
                mw, fw = parse_weight_pair(args[1], "ORAN")
                w_src = "manual"
            except ConfigError as exc:
                return f"⚠️ {exc}"
        analysis = calculate_final_targets(
            midterm_score=score,
            midterm_weight=mw,
            final_weight=fw,
            final_min_score=config.final_min_score,
            weight_source=w_src,
        )
        return format_grade_calculator(analysis)

    if command == "hava":
        try:
            weather = fetch_weather_forecast(
                lat=config.weather_lat,
                lon=config.weather_lon,
                location_name=config.weather_location,
            )
            context["weather"] = weather
            return format_weather_report(weather)
        except Exception as exc:
            return f"⚠️ Hava durumu alınamadı: {exc}"

    if command == "yemek":
        try:
            menus = fetch_dining_menus(
                sks_url=config.sks_url,
                sheet_url_override=config.dining_sheet_url,
            )
            menu = get_menu_for_date(menus, today)
            is_next = False
            if menu is None:
                menu = get_next_menu(menus, today)
                is_next = menu is not None
            if menu is None:
                return "🍽️ Güncel yemekhane menüsü bulunamadı."
            weather = _get_or_fetch_weather(config, context) if config.enable_weather else None
            return format_daily_menu(menu, is_next_preview=is_next, weather=weather)
        except Exception as exc:
            return f"⚠️ Yemekhane menüsü alınamadı: {exc}"

    if command == "calendar" or command == "takvim":
        try:
            faculty, term, all_events = fetch_calendar_events(
                calendar_url=config.calendar_url,
                faculty=config.calendar_faculty,
            )
            events = filter_events_by_categories(all_events, config.calendar_categories)
            ongoing, upcoming = find_ongoing_and_upcoming(events, today, config.calendar_lookahead_days)
            return format_calendar_digest(
                ongoing=ongoing,
                upcoming=upcoming,
                today=today,
                faculty=faculty,
                term=term,
                lookahead_days=config.calendar_lookahead_days,
                calendar_url=config.calendar_url,
            )
        except Exception as exc:
            return f"⚠️ Akademik takvim alınamadı: {exc}"

    if command == "duyuru":
        anns = context.get("announcements")
        if not isinstance(anns, list) or not anns:
            anns = fetch_all_announcements(extra_sources=config.announcement_urls)
            context["announcements"] = anns
        return format_announcements(anns, is_preview=True)

    try:
        if command == "notlar":
            courses = _get_or_fetch_courses(config, context)
            return format_test_summary(courses)

        if command == "devamsizlik":
            courses = _get_or_fetch_courses(config, context)
            reports = evaluate_all_attendance(
                courses,
                semester_weeks=config.semester_weeks,
                theory_min_pct=config.theory_min_attendance,
                practice_min_pct=config.practice_min_attendance,
            )
            return format_attendance_report(reports, config.ubys_base_url)

        if command == "transkript":
            with UBYSClient(base_url=config.ubys_base_url) as client:
                client.login(
                    username=config.ubys_username,
                    password=config.ubys_password,
                    user_group_id=config.ubys_user_group_id,
                )
                summary = client.fetch_transcript()
            return format_transcript_summary(summary, config.ubys_base_url)

        if command == "gano":
            courses = _get_or_fetch_courses(config, context)
            swiss_state = context.get("swiss_state") or {}
            base_gano = context.get("home_gano") or swiss_state.get("last_gano")
            base_credit = swiss_state.get("last_total_credit")
            proj = project_semester_gpa(
                courses,
                base_gano=float(base_gano) if base_gano is not None else None,
                base_credits=float(base_credit) if base_credit is not None else None,
                default_midterm_weight=config.midterm_weight,
                default_final_weight=config.final_weight,
                final_min_score=config.final_min_score,
            )
            return format_gpa_projection(proj, config.ubys_base_url)

        if command == "program":
            slots = _get_or_fetch_schedule(config, context)
            if args and any(k in args[0].lower() for k in ("bugün", "bugun", "today")):
                return format_daily_schedule(get_slots_for_day(slots, today), today, config.ubys_base_url)
            return format_weekly_schedule(slots, config.ubys_base_url)

        if command == "sinav":
            exams = _get_or_fetch_exams(config, context)
            return format_exam_schedule(exams, today, config.ubys_base_url)

        if command == "ozet":
            courses = _get_or_fetch_courses(config, context)
            reports = evaluate_all_attendance(
                courses,
                semester_weeks=config.semester_weeks,
                theory_min_pct=config.theory_min_attendance,
                practice_min_pct=config.practice_min_attendance,
            )
            swiss_state = context.get("swiss_state") or {}
            base_gano = context.get("home_gano") or swiss_state.get("last_gano")
            base_credit = swiss_state.get("last_total_credit")
            proj = project_semester_gpa(
                courses,
                base_gano=float(base_gano) if base_gano is not None else None,
                base_credits=float(base_credit) if base_credit is not None else None,
                default_midterm_weight=config.midterm_weight,
                default_final_weight=config.final_weight,
                final_min_score=config.final_min_score,
            )
            weather = _get_or_fetch_weather(config, context) if config.enable_weather else None
            ongoing: list[Any] = []
            upcoming: list[Any] = []
            try:
                _, _, all_ev = fetch_calendar_events(config.calendar_url, config.calendar_faculty)
                ev_filtered = filter_events_by_categories(all_ev, config.calendar_categories)
                ongoing, upcoming = find_ongoing_and_upcoming(ev_filtered, today, config.calendar_lookahead_days)
            except Exception:
                pass
            exams: list[ExamScheduleItem] = []
            try:
                exams = _get_or_fetch_exams(config, context)
            except Exception:
                pass
            return format_weekly_briefing(
                today=today,
                ongoing_cal=ongoing,
                upcoming_cal=upcoming,
                exams=exams,
                attendance_reports=reports,
                gpa_projection=proj,
                weather=weather,
                base_url=config.ubys_base_url,
            )
    except Exception as exc:
        return f"⚠️ Komut işlenirken hata oluştu: {exc}"

    return format_help_message()


def process_telegram_commands(
    config: Config,
    swiss_state: dict[str, Any],
    context: dict[str, Any],
    poll_timeout: int = 0,
    notifier_factory: Optional[Callable[[], TelegramNotifier]] = None,
) -> tuple[int, bool]:
    """Telegram getUpdates kuyruğundaki yetkili kullanıcı komutlarını işler ve yanıtlar."""
    if not config.telegram_bot_token or not config.telegram_chat_ids:
        return 0, False

    notifier = (
        notifier_factory()
        if notifier_factory is not None
        else TelegramNotifier(config.telegram_bot_token, config.telegram_chat_ids)
    )
    allowed_ids = {str(cid).strip() for cid in config.telegram_chat_ids if str(cid).strip()}
    dirty = False

    if swiss_state.get("telegram_commands_version") != BOT_COMMANDS_VERSION:
        if notifier.set_my_commands(BOT_COMMANDS_MENU):
            swiss_state["telegram_commands_version"] = BOT_COMMANDS_VERSION
            dirty = True

    last_update_id = swiss_state.get("telegram_last_update_id")
    offset = (int(last_update_id) + 1) if isinstance(last_update_id, int) else None

    updates = notifier.get_updates(offset=offset, timeout_seconds=poll_timeout)
    if not updates:
        return 0, dirty

    max_update_id = int(last_update_id) if isinstance(last_update_id, int) else 0
    handled_count = 0

    for update in updates:
        raw_uid = update.get("update_id")
        if isinstance(raw_uid, int) and raw_uid > max_update_id:
            max_update_id = raw_uid

        msg = update.get("message")
        if not isinstance(msg, dict):
            continue
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        if not chat_id or chat_id not in allowed_ids:
            continue

        text = str(msg.get("text") or "")
        command, args = parse_bot_command(text)
        if not command:
            continue

        reply = handle_command(command, args, config, context)
        try:
            notifier.send_message(reply, chat_ids_override=[chat_id])
            handled_count += 1
        except Exception as exc:
            logger.warning("Telegram komut yanıtı gönderilemedi: %s", exc)

    if max_update_id and max_update_id != last_update_id:
        swiss_state["telegram_last_update_id"] = max_update_id
        dirty = True

    if handled_count > 0:
        logger.info("%d Telegram komutu yanıtlandı.", handled_count)

    return handled_count, dirty
