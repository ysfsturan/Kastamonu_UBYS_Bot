"""Telegram bildirim gönderme ve mesaj biçimlendirme modülü."""

from __future__ import annotations

import html
import logging
import re
import time
from collections import OrderedDict
from datetime import date
from typing import Any, Iterable, Optional

import httpx

from .grade_calculator import analyze_course_grades, resolve_course_weights
from .models import (
    Announcement,
    AttendanceReport,
    CalendarEvent,
    CourseGrade,
    CourseMaterial,
    DailyMenu,
    ExamScheduleItem,
    GpaProjection,
    GradeChange,
    GradeTargetAnalysis,
    ScheduleSlot,
    TranscriptSemester,
    TranscriptSummary,
    WeatherForecast,
)

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4000


def _split_lines_fallback(text: str, max_length: int) -> list[str]:
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in text.splitlines():
        line_len = len(line) + 1
        if len(line) > max_length:
            if current_lines:
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_len = 0
            for start in range(0, len(line), max_length):
                chunks.append(line[start : start + max_length])
            continue

        if current_len + line_len > max_length and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_len = line_len
        else:
            current_lines.append(line)
            current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks


def split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Uzun mesajları önce blok (\n\n), gerekirse satır sınırlarından Telegram limitine uygun parçalara böler."""
    if len(text) <= max_length:
        return [text]

    if "\n\n" not in text:
        return _split_lines_fallback(text, max_length)

    chunks: list[str] = []
    current_blocks: list[str] = []
    current_len = 0

    for block in text.split("\n\n"):
        if len(block) > max_length:
            if current_blocks:
                chunks.append("\n\n".join(current_blocks))
                current_blocks = []
                current_len = 0
            chunks.extend(_split_lines_fallback(block, max_length))
            continue

        added_len = len(block) if not current_blocks else len(block) + 2
        if current_len + added_len > max_length and current_blocks:
            chunks.append("\n\n".join(current_blocks))
            current_blocks = [block]
            current_len = len(block)
        else:
            current_blocks.append(block)
            current_len += added_len

    if current_blocks:
        chunks.append("\n\n".join(current_blocks))

    return chunks


def _build_ipv4_transport() -> Optional[httpx.HTTPTransport]:
    try:
        return httpx.HTTPTransport(local_address="0.0.0.0")
    except OSError:
        return None


def _extract_telegram_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("description"):
            return str(data["description"])
    except Exception:
        pass
    return response.text[:200] or f"HTTP {response.status_code}"


class TelegramNotifier:
    """Telegram Bot API üzerinden HTML formatlı bildirim gönderir."""

    def __init__(
        self,
        bot_token: str,
        chat_ids: Iterable[str],
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self.bot_token = bot_token
        self.chat_ids = [str(cid).strip() for cid in chat_ids if str(cid).strip()]
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.retry_delay = max(0.0, retry_delay)

    def _build_client(self, timeout_override: Optional[float] = None) -> httpx.Client:
        eff_timeout = timeout_override if timeout_override is not None else self.timeout
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(eff_timeout, connect=min(15.0, eff_timeout)),
        }
        transport = _build_ipv4_transport()
        if transport is not None:
            client_kwargs["transport"] = transport
        return httpx.Client(**client_kwargs)

    def send_message(
        self,
        text: str,
        chat_ids_override: Optional[Iterable[str]] = None,
    ) -> None:
        """Mesajı yapılandırılmış veya belirtilen Telegram sohbetlerine IPv4 ve yeniden denemeyle gönderir."""
        if not text.strip():
            return

        targets = (
            [str(cid).strip() for cid in chat_ids_override if str(cid).strip()]
            if chat_ids_override is not None
            else self.chat_ids
        )
        if not targets:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        chunks = split_message(text)

        with self._build_client() as client:
            for chat_id in targets:
                for chunk in chunks:
                    payload = {
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    }
                    self._post_chunk_with_retry(client, url, chat_id, payload)

    def get_updates(
        self,
        offset: Optional[int] = None,
        timeout_seconds: int = 0,
    ) -> list[dict[str, Any]]:
        """Bot hesabına gelen güncellemeleri (getUpdates) IPv4 üzerinden çeker."""
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params: dict[str, Any] = {
            "timeout": max(0, int(timeout_seconds)),
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = int(offset)

        req_timeout = max(self.timeout, float(timeout_seconds) + 15.0)
        with self._build_client(timeout_override=req_timeout) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.post(url, json=params)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self.max_retries:
                        raise
                    wait_seconds = self.retry_delay * attempt
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
                    continue

                if response.status_code >= 400:
                    desc = _extract_telegram_error(response)
                    raise RuntimeError(f"Telegram getUpdates hatası (HTTP {response.status_code}): {desc}")

                data = response.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Telegram getUpdates hatası: {data.get('description', data)}")
                raw_results = data.get("result") or []
                return [u for u in raw_results if isinstance(u, dict)]
        return []

    def set_my_commands(self, commands: list[dict[str, str]]) -> bool:
        """Telegram sohbet menüsü için bot komut listesini (setMyCommands) kaydeder."""
        url = f"https://api.telegram.org/bot{self.bot_token}/setMyCommands"
        try:
            with self._build_client() as client:
                resp = client.post(url, json={"commands": commands})
                if resp.status_code >= 400:
                    return False
                data = resp.json()
                return bool(data.get("ok"))
        except Exception as exc:
            logger.debug("Telegram komut menüsü kaydedilemedi: %s", exc)
            return False

    def _post_chunk_with_retry(
        self,
        client: httpx.Client,
        url: str,
        chat_id: str,
        payload: dict[str, Any],
    ) -> None:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = client.post(url, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.max_retries:
                    raise
                wait_seconds = self.retry_delay * attempt
                logger.warning(
                    "Telegram isteği başarısız (%d/%d), %.1f sn sonra yeniden denenecek: %s",
                    attempt,
                    self.max_retries,
                    wait_seconds,
                    exc,
                )
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                continue

            if response.status_code >= 400:
                desc = _extract_telegram_error(response)
                raise RuntimeError(
                    f"Telegram API hatası (HTTP {response.status_code}, chat_id={chat_id}): {desc}"
                )

            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(
                    f"Telegram API hatası (chat_id={chat_id}): {data.get('description', data)}"
                )
            return


def _format_target_lines(analysis: GradeTargetAnalysis, include_impossible: bool = False) -> list[str]:
    mw_pct = round(analysis.midterm_weight * 100)
    fw_pct = round(analysis.final_weight * 100)
    lines: list[str] = [f"🎯 <b>Final Hedefleri (%{mw_pct}/%{fw_pct}):</b>"]

    has_impossible = False
    for target in analysis.targets:
        tag = " (Şartlı)" if target.letter == "DC" else ""
        if target.status == "guaranteed":
            lines.append(f"   ✅ <b>{target.letter}{tag}</b> (≥{target.min_total}): Garantili")
        elif target.status == "achievable":
            lines.append(
                f"   • <b>{target.letter}{tag}</b> (≥{target.min_total}): Finalden <code>{target.required_final}</code>+"
            )
        else:
            has_impossible = True
            if include_impossible:
                lines.append(f"   ❌ <b>{target.letter}</b> (≥{target.min_total}): İmkansız (100+)")

    if has_impossible:
        lines.append(
            f"   ℹ️ <i>Maks. olası ortalama: {analysis.max_possible_total:.2f} ({analysis.max_possible_letter})</i>"
        )
    return lines


def format_grade_changes(
    changes: list[GradeChange],
    base_url: str,
    courses: Optional[list[CourseGrade]] = None,
    midterm_weight: float = 0.40,
    final_weight: float = 0.60,
    final_min_score: int = 0,
) -> str:
    """Tespit edilen not değişikliklerini okunaklı Türkçe Telegram mesajına dönüştürür."""
    grouped: OrderedDict[tuple[str, str, str], list[GradeChange]] = OrderedDict()
    for change in changes:
        key = (change.semester, change.course_code, change.course_name)
        grouped.setdefault(key, []).append(change)

    course_map = {
        (c.semester, c.code, c.name): c
        for c in (courses or [])
    }

    lines: list[str] = ["🔔 <b>ÜBYS Not Bildirimi</b>", ""]

    emoji_map = {
        "new_exam_score": "🆕",
        "updated_exam_score": "✏️",
        "new_letter_grade": "🏅",
        "updated_letter_grade": "✏️",
        "new_passing_grade": "📊",
        "updated_passing_grade": "✏️",
        "status_changed": "📌",
    }

    for (semester, code, name), course_changes in grouped.items():
        title_text = f"{code} - {name}" if code and name else (code or name)
        lines.append(f"📚 <b>{html.escape(title_text)}</b>")
        if semester:
            lines.append(f"<i>{html.escape(semester)}</i>")

        for ch in course_changes:
            emoji = emoji_map.get(ch.change_type, "📌")
            label = html.escape(ch.label)
            new_val = html.escape(ch.new_value or "-")

            if ch.old_value is not None and ch.change_type != "status_changed":
                old_val = html.escape(ch.old_value)
                lines.append(f"{emoji} <b>{label}:</b> <code>{old_val}</code> → <code>{new_val}</code>")
            elif ch.change_type == "status_changed":
                if ch.old_value:
                    old_val = html.escape(ch.old_value)
                    lines.append(f"{emoji} <b>{label}:</b> {old_val} → <b>{new_val}</b>")
                else:
                    lines.append(f"{emoji} <b>{label}:</b> <b>{new_val}</b>")
            else:
                lines.append(f"{emoji} <b>{label}:</b> <code>{new_val}</code>")

            meta_parts: list[str] = []
            if ch.class_average:
                meta_parts.append(f"Sınıf Ort: {html.escape(ch.class_average)}")
            if ch.ranking:
                meta_parts.append(f"Sıralama: {html.escape(ch.ranking)}")
            if ch.announcement_date:
                meta_parts.append(f"İlan: {html.escape(ch.announcement_date)}")
            if meta_parts:
                lines.append(f"   └ {' | '.join(meta_parts)}")

        course_obj = course_map.get((semester, code, name))
        if course_obj is not None:
            analysis, estimate = analyze_course_grades(
                course_obj,
                default_midterm_weight=midterm_weight,
                default_final_weight=final_weight,
                final_min_score=final_min_score,
            )
            if analysis is not None:
                lines.extend(_format_target_lines(analysis, include_impossible=False))
            elif estimate is not None:
                lines.append(
                    f"🧮 <b>Tahmini Ortalama:</b> <code>{estimate.weighted_total:.2f}</code> "
                    f"→ <b>{estimate.letter_grade}</b> ({estimate.coefficient:.2f})"
                )

        lines.append("")

    escaped_url = html.escape(base_url, quote=True)
    lines.append(f'🔗 <a href="{escaped_url}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def _format_course_summary_lines(courses: list[CourseGrade], max_courses: int = 25) -> list[str]:
    lines: list[str] = []
    semesters = list(OrderedDict.fromkeys(c.semester for c in courses if c.semester))
    if semesters:
        lines.append(f"📅 <b>Takip edilen dönem:</b> {html.escape(', '.join(semesters))}")
    lines.append(f"📚 <b>Toplam ders sayısı:</b> {len(courses)}")
    lines.append("")

    for course in courses[:max_courses]:
        title = f"{course.code} - {course.name}" if course.code and course.name else (course.code or course.name)
        scored_exams = [f"{e.name}: {e.score}" for e in course.exams if e.score is not None]
        extras: list[str] = []
        if scored_exams:
            extras.append(", ".join(scored_exams))
        if course.letter_grade:
            extras.append(f"Harf: {course.letter_grade}")
        if not scored_exams and not course.letter_grade:
            extras.append("Henüz not yok")

        mw, fw, _ = resolve_course_weights(course)
        extras.append(f"Vize/Final: %{round(mw * 100)}/%{round(fw * 100)}")

        durum = course.status or course.attendance_status
        if durum:
            extras.append(durum)

        summary = " | ".join(extras)
        lines.append(f"• <b>{html.escape(title)}</b>\n  {html.escape(summary)}")

    if len(courses) > max_courses:
        lines.append(f"\n<i>... ve {len(courses) - max_courses} ders daha takip ediliyor.</i>")

    return lines


def format_baseline_summary(courses: list[CourseGrade]) -> str:
    """İlk çalıştırmada oluşturulan başlangıç not özetini biçimlendirir."""
    lines = [
        "✅ <b>Kastamonu ÜBYS Not Takibi Başlatıldı!</b>",
        "Mevcut notlarınız başlangıç durumu olarak kaydedildi. Yeni bir not girildiğinde veya güncellendiğinde buradan anlık bildirim alacaksınız.",
        "",
    ]
    lines.extend(_format_course_summary_lines(courses))
    return "\n".join(lines)


def format_test_summary(courses: list[CourseGrade]) -> str:
    """--test --notify-test komutu için bağlantı testi özeti üretir."""
    lines = [
        "🧪 <b>ÜBYS Bağlantı Testi Başarılı</b>",
        "Bu bir test mesajıdır; kayıtlı not durumu dosyası değiştirilmedi.",
        "",
    ]
    lines.extend(_format_course_summary_lines(courses))
    return "\n".join(lines)


def format_error_alert(title: str, detail: str) -> str:
    """Hata uyarı mesajını Telegram HTML formatında hazırlar."""
    return f"⚠️ <b>{html.escape(title)}</b>\n\n{html.escape(detail)}"


_TR_MONTHS = (
    "",
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
_TR_WEEKDAYS = (
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
)
_DINING_CATEGORY_ICONS = {
    "Çorba": "🥣",
    "Ana Yemek": "🍖",
    "Yardımcı": "🍝",
    "Soğuk / Tatlı": "🥗",
}
_CALENDAR_ICON_RULES = (
    (("ara sınav", "vize"), "📝"),
    (("yarıyıl sonu", "final"), "🏁"),
    (("bütünleme", "mazeret", "ek sınav", "tek ders"), "🆘"),
    (("kayıt", "danışman", "ders ekleme"), "📋"),
    (("tatil", "bayram", "yılbaşı"), "🎉"),
    (("kuzem", "uzaktan"), "💻"),
)


def format_tr_date(d: date, with_weekday: bool = True) -> str:
    base = f"{d.day} {_TR_MONTHS[d.month]} {d.year}"
    if with_weekday:
        return f"{base}, {_TR_WEEKDAYS[d.weekday()]}"
    return base


def _format_event_date_range(event: CalendarEvent) -> str:
    if event.start_date == event.end_date:
        return format_tr_date(event.start_date, with_weekday=False)
    return (
        f"{format_tr_date(event.start_date, with_weekday=False)} – "
        f"{format_tr_date(event.end_date, with_weekday=False)}"
    )


def _calendar_event_icon(event: CalendarEvent) -> str:
    haystack = f"{event.title} {event.category}".replace("İ", "i").replace("I", "ı").lower()
    for keywords, icon in _CALENDAR_ICON_RULES:
        if any(kw in haystack for kw in keywords):
            return icon
    return "📅"


def _format_weather_inline_lines(weather: WeatherForecast) -> list[str]:
    temp_range = (
        f"{weather.temp_min:.0f}° / {weather.temp_max:.0f}°C"
        if (weather.temp_min is not None and weather.temp_max is not None)
        else (f"{weather.current_temp:.0f}°C" if weather.current_temp is not None else "-")
    )
    extra_parts: list[str] = []
    if weather.precip_probability is not None:
        extra_parts.append(f"Yağış %{weather.precip_probability}")
    if weather.wind_speed is not None:
        extra_parts.append(f"Rüzgâr {weather.wind_speed:.0f} km/sa")
    extra_txt = f" ({', '.join(extra_parts)})" if extra_parts else ""
    return [
        f"{weather.condition_icon} <b>{html.escape(weather.location_name)}:</b> {html.escape(weather.condition_text)}, <code>{html.escape(temp_range)}</code>{html.escape(extra_txt)}",
        f"🧥 <i>{html.escape(weather.advice)}</i>",
    ]


def format_daily_menu(
    menu: DailyMenu,
    is_next_preview: bool = False,
    weather: Optional[WeatherForecast] = None,
) -> str:
    """Günlük yemekhane menüsünü (varsa hava durumu özetiyle) Telegram HTML mesajına dönüştürür."""
    header = "🍽️ <b>Yaklaşan İlk Yemekhane Menüsü</b>" if is_next_preview else "🍽️ <b>Günün Yemekhane Menüsü</b>"
    lines: list[str] = [
        header,
        f"📅 <i>{html.escape(format_tr_date(menu.menu_date))}</i>",
        "",
    ]

    for item in menu.items:
        icon = _DINING_CATEGORY_ICONS.get(item.category, "🍴")
        cal_suffix = f" <i>({html.escape(item.calories)})</i>" if item.calories else ""
        lines.append(f"{icon} <b>{html.escape(item.name)}</b>{cal_suffix}")

    if menu.total_calories_min is not None and menu.total_calories_max is not None:
        lines.append("")
        if menu.total_calories_min == menu.total_calories_max:
            lines.append(f"🔥 <b>Toplam Kalori:</b> ~<code>{menu.total_calories_min} kkal</code>")
        else:
            lines.append(
                f"🔥 <b>Toplam Kalori:</b> ~<code>{menu.total_calories_min}–{menu.total_calories_max} kkal</code>"
            )

    if weather is not None:
        lines.append("")
        lines.extend(_format_weather_inline_lines(weather))

    source_url = menu.source_url or "https://sks.kastamonu.edu.tr/"
    lines.append("")
    lines.append(f'🔗 <a href="{html.escape(source_url, quote=True)}">Yemek Listesini Aç</a>')
    return "\n".join(lines)


def format_calendar_reminders(
    reminders: list[tuple[CalendarEvent, int]],
    faculty: str,
    calendar_url: str,
) -> str:
    """Eşik günlerine giren akademik takvim etkinlikleri için hatırlatma mesajı üretir."""
    lines: list[str] = [
        "📣 <b>Akademik Takvim Hatırlatması</b>",
        f"🏛️ <i>Birim: {html.escape(faculty)}</i>",
        "",
    ]

    for event, days_until in reminders:
        if days_until == 0:
            badge = "🚨 <b>BUGÜN BAŞLIYOR</b>"
        elif days_until == 1:
            badge = "⏰ <b>YARIN BAŞLIYOR</b>"
        else:
            badge = f"⏳ <b>{days_until} GÜN KALDI</b>"

        icon = _calendar_event_icon(event)
        lines.append(f"{badge} • {icon} <b>{html.escape(event.title)}</b>")

        meta = [_format_event_date_range(event)]
        if event.category:
            meta.append(event.category)
        lines.append(f"   └ {html.escape(' | '.join(meta))}")
        if event.google_calendar_url:
            gcal_href = html.escape(event.google_calendar_url, quote=True)
            lines.append(f'   └ <a href="{gcal_href}">Google Takvime Ekle</a>')
        lines.append("")

    lines.append(f'🔗 <a href="{html.escape(calendar_url, quote=True)}">Akademik Takvim\'e Git</a>')
    return "\n".join(lines)


def format_calendar_digest(
    ongoing: list[CalendarEvent],
    upcoming: list[CalendarEvent],
    today: date,
    faculty: str,
    term: str,
    lookahead_days: int,
    calendar_url: str,
    max_items: int = 12,
) -> str:
    """Haftalık veya isteğe bağlı akademik takvim özet mesajı oluşturur."""
    lines: list[str] = [
        "📅 <b>Akademik Takvim Özeti</b>",
        f"🏛️ <i>{html.escape(faculty)} ({html.escape(term)})</i>",
        "",
    ]

    if ongoing:
        lines.append("⏳ <b>Şu An Devam Edenler</b>")
        for event in ongoing[:max_items]:
            icon = _calendar_event_icon(event)
            days_left = (event.end_date - today).days
            left_text = "Bugün son gün" if days_left == 0 else f"Bitime {days_left} gün"
            lines.append(
                f"• {icon} <b>{html.escape(event.title)}</b>\n"
                f"  {html.escape(_format_event_date_range(event))} ({left_text})"
            )
        lines.append("")

    if upcoming:
        lines.append(f"🗓️ <b>Yaklaşan Etkinlikler (Önümüzdeki {lookahead_days} Gün)</b>")
        for event in upcoming[:max_items]:
            icon = _calendar_event_icon(event)
            days_until = (event.start_date - today).days
            lines.append(
                f"• {icon} <b>{html.escape(event.title)}</b>\n"
                f"  {html.escape(_format_event_date_range(event))} (<b>{days_until} gün kaldı</b>)"
            )
        if len(upcoming) > max_items:
            lines.append(f"<i>... ve {len(upcoming) - max_items} etkinlik daha.</i>")
        lines.append("")

    if not ongoing and not upcoming:
        lines.append(f"Önümüzdeki {lookahead_days} gün için kayıtlı etkinlik bulunmuyor.")
        lines.append("")

    lines.append(f'🔗 <a href="{html.escape(calendar_url, quote=True)}">Akademik Takvim\'e Git</a>')
    return "\n".join(lines)


def format_grade_calculator(analysis: GradeTargetAnalysis) -> str:
    """Bağımsız final hedef hesaplama sonucunu HTML biçiminde döndürür."""
    lines = [
        "🧮 <b>Kastamonu ÜBYS Final Hedef Hesaplayıcı</b>",
        f"📝 <b>Vize Notunuz:</b> <code>{analysis.midterm_score:g}</code>",
    ]
    if analysis.final_min_score > 0:
        lines.append(f"🚧 <b>Final Alt Barajı:</b> <code>{analysis.final_min_score}</code>")
    lines.append("")
    lines.extend(_format_target_lines(analysis, include_impossible=True))
    return "\n".join(lines)


def _norm_tr_code(code: Optional[str]) -> str:
    if not code:
        return ""
    return re.sub(r"[\s\-_]+", "", re.sub(r"\.\d+$", "", str(code).strip())).upper()


def select_transcript_semesters(
    summary: TranscriptSummary,
    active_courses: Optional[list[CourseGrade]] = None,
) -> tuple[Optional[TranscriptSemester], Optional[TranscriptSemester], int]:
    """Transkriptten aktif dönemi, son notlu dönemi ve aktif dönem indeksini bulur."""
    semesters = summary.semesters
    if not semesters:
        return None, None, -1

    last_graded_idx: Optional[int] = None
    for idx, sem in enumerate(semesters):
        if any(bool(c.letter_grade) for c in sem.courses) or (
            sem.semester_gpa is not None and sem.semester_gpa > 0.0
        ):
            last_graded_idx = idx

    active_idx: Optional[int] = None
    if active_courses:
        active_codes = {_norm_tr_code(c.code) for c in active_courses if _norm_tr_code(c.code)}
        if active_codes:
            best_overlap = 0
            for idx, sem in enumerate(semesters):
                sem_codes = {_norm_tr_code(c.code) for c in sem.courses if _norm_tr_code(c.code)}
                overlap = len(active_codes & sem_codes)
                if overlap > best_overlap:
                    best_overlap = overlap
                    active_idx = idx

    if active_idx is None:
        if last_graded_idx is not None and last_graded_idx + 1 < len(semesters) and semesters[last_graded_idx + 1].courses:
            active_idx = last_graded_idx + 1
        elif last_graded_idx is not None:
            active_idx = last_graded_idx
        else:
            first_with_courses = next((i for i, s in enumerate(semesters) if s.courses), None)
            active_idx = first_with_courses if first_with_courses is not None else len(semesters) - 1

    active_sem = semesters[active_idx]
    last_graded_sem = semesters[last_graded_idx] if last_graded_idx is not None else None
    return active_sem, last_graded_sem, active_idx


def format_transcript_summary(
    summary: TranscriptSummary,
    base_url: str,
    active_courses: Optional[list[CourseGrade]] = None,
) -> str:
    """Transkript ve GANO özetini Telegram HTML mesajına dönüştürür."""
    lines = ["🎓 <b>Kastamonu ÜBYS Transkript Özeti</b>", ""]
    if summary.gano is not None:
        lines.append(f"📊 <b>Genel Ortalama (GANO):</b> <code>{summary.gano:.2f}</code>")
    if summary.total_credit is not None:
        lines.append(f"📘 <b>Toplam Kredi:</b> <code>{summary.total_credit:g}</code>")
    if summary.total_ects is not None:
        lines.append(f"📗 <b>Toplam AKTS:</b> <code>{summary.total_ects:g}</code>")

    if summary.semesters:
        active_sem, last_graded_sem, active_idx = select_transcript_semesters(
            summary,
            active_courses=active_courses,
        )
        lines.append("")
        lines.append("📅 <b>Dönem Ortalamaları:</b>")
        for idx, sem in enumerate(summary.semesters):
            clean_name = re.sub(r"\s+\.", ".", sem.name).strip()
            sem_has_grades = any(bool(c.letter_grade) for c in sem.courses) or (
                sem.semester_gpa is not None and sem.semester_gpa > 0.0
            )
            parts: list[str] = []
            if not sem_has_grades and (sem.semester_gpa is None or sem.semester_gpa == 0.0):
                if idx == active_idx:
                    parts.append("Aktif Dönem — Henüz not girilmedi")
                elif active_idx >= 0 and idx > active_idx:
                    parts.append("Gelecek Dönem")
                else:
                    parts.append("Henüz not girilmedi")
            else:
                if sem.semester_gpa is not None:
                    parts.append(f"YANO: {sem.semester_gpa:.2f}")
                if sem.cumulative_gpa is not None:
                    parts.append(f"GANO: {sem.cumulative_gpa:.2f}")
            if not parts and sem.courses:
                parts.append(f"{len(sem.courses)} ders")
            suffix = f" ({' | '.join(parts)})" if parts else ""
            lines.append(f"• <b>{html.escape(clean_name)}</b>{html.escape(suffix)}")

        if active_sem is not None and active_sem.courses:
            active_name = re.sub(r"\s+\.", ".", active_sem.name).strip()
            active_has_grades = any(bool(c.letter_grade) for c in active_sem.courses)
            lines.append("")
            if active_has_grades:
                lines.append(f"📚 <b>Son Notlu Dönem ({html.escape(active_name)}):</b>")
            else:
                lines.append(f"📌 <b>Aktif Dönem ({html.escape(active_name)}):</b>")
            for c in active_sem.courses[:15]:
                grade_str = html.escape(c.letter_grade or "Devam Ediyor")
                title = f"{c.code} - {c.name}" if c.code else c.name
                lines.append(f"• {html.escape(title)}: <code>{grade_str}</code>")
            if len(active_sem.courses) > 15:
                lines.append(f"<i>... ve {len(active_sem.courses) - 15} ders daha.</i>")

        if (
            last_graded_sem is not None
            and last_graded_sem is not active_sem
            and last_graded_sem.courses
        ):
            graded_name = re.sub(r"\s+\.", ".", last_graded_sem.name).strip()
            lines.append("")
            lines.append(f"📚 <b>Son Notlu Dönem ({html.escape(graded_name)}):</b>")
            for c in last_graded_sem.courses[:15]:
                grade_str = html.escape(c.letter_grade or "-")
                title = f"{c.code} - {c.name}" if c.code else c.name
                lines.append(f"• {html.escape(title)}: <code>{grade_str}</code>")
            if len(last_graded_sem.courses) > 15:
                lines.append(f"<i>... ve {len(last_graded_sem.courses) - 15} ders daha.</i>")
    elif summary.gano is None:
        lines.append("Transkript verisi bulunamadı.")

    lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_gano_change(old_gano: float, new_gano: float, base_url: str) -> str:
    """GANO değişikliği bildirimi hazırlar."""
    delta = new_gano - old_gano
    icon = "📈" if delta >= 0 else "📉"
    sign = "+" if delta >= 0 else ""
    lines = [
        f"🎓 <b>GANO Güncellendi!</b>",
        "",
        f"{icon} <b>Genel Ortalama:</b> <code>{old_gano:.2f}</code> → <code>{new_gano:.2f}</code> (<code>{sign}{delta:.2f}</code>)",
        "",
        f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>',
    ]
    return "\n".join(lines)


_ATTENDANCE_ICONS = {
    "safe": "🟢",
    "warning": "🟡",
    "critical": "🔴",
    "failed": "⛔",
    "unknown": "⚪",
}


def _fmt_hours(val: Optional[float]) -> str:
    if val is None:
        return "-"
    return f"{val:g}"


def _fmt_days(val: Optional[float | int]) -> str:
    if val is None:
        return "-"
    if isinstance(val, int):
        return str(val)
    if abs(val - round(val)) < 1e-6:
        return str(int(round(val)))
    return f"{val:g}"


def _format_weekly_hours_tag(report: AttendanceReport) -> str:
    t = report.weekly_theory or 0.0
    u = report.weekly_practice or 0.0
    if t > 0 and u > 0:
        return f"{t:g}T+{u:g}U"
    if t > 0:
        return f"{t:g}T"
    if u > 0:
        return f"{u:g}U"
    return ""


def format_attendance_detail_line(report: AttendanceReport) -> str:
    """Devamsızlık raporunun tek satırlık gün ve saat özetini üretir."""
    weekly_tag = _format_weekly_hours_tag(report)
    if weekly_tag and report.course_type.endswith(")"):
        type_label = f"{report.course_type[:-1]} | {weekly_tag})"
    else:
        type_label = report.course_type

    parts: list[str] = [type_label]
    if (
        report.max_theory_absent is not None
        and report.max_practice_absent is not None
        and (report.weekly_practice or 0.0) > 0
    ):
        if (
            report.used_theory_absent is not None
            and report.used_practice_absent is not None
            and report.remaining_theory_days is not None
            and report.remaining_practice_days is not None
        ):
            t_rem_txt = (
                f"Kalan: {_fmt_days(report.remaining_theory_days)} gün"
                if report.remaining_theory_days > 0
                else "Kalan: 0 tam gün"
            )
            u_rem_txt = (
                f"Kalan: {_fmt_days(report.remaining_practice_days)} gün"
                if report.remaining_practice_days > 0
                else "Kalan: 0 tam gün"
            )
            t_part = (
                f"Teorik: {_fmt_days(report.used_theory_days)}/{_fmt_days(report.max_theory_days)} gün "
                f"({t_rem_txt} / {_fmt_hours(report.remaining_theory)}s)"
            )
            u_part = (
                f"Uyg: {_fmt_days(report.used_practice_days)}/{_fmt_days(report.max_practice_days)} gün "
                f"({u_rem_txt} / {_fmt_hours(report.remaining_practice)}s)"
            )
            parts.extend([t_part, u_part])
        elif report.used_total_absent is not None:
            rem_days_txt = (
                f"{_fmt_days(report.remaining_total_days)} gün"
                if report.remaining_total_days is not None
                else "-"
            )
            parts.append(
                f"Kullanılan: {_fmt_hours(report.used_total_absent)} saat | Kalan tam gün: {rem_days_txt} • "
                f"Limit: Teorik {_fmt_days(report.max_theory_days)} gün ({_fmt_hours(report.max_theory_absent)}s), "
                f"Uyg {_fmt_days(report.max_practice_days)} gün ({_fmt_hours(report.max_practice_absent)}s)"
            )
        else:
            full_days_txt = (
                f" • Tam gün: {_fmt_days(report.max_total_days)} gün hakkın var"
                if report.max_total_days is not None
                else ""
            )
            parts.append(
                f"Hak: Teorik {_fmt_days(report.max_theory_days)} gün ({_fmt_hours(report.max_theory_absent)} saat), "
                f"Uyg {_fmt_days(report.max_practice_days)} gün ({_fmt_hours(report.max_practice_absent)} saat)"
                f"{full_days_txt}"
            )
    elif report.max_total_absent is not None:
        if report.used_total_absent is not None and report.remaining_total is not None:
            if report.max_total_days is not None and report.remaining_total_days is not None:
                if report.remaining_total_days > 0:
                    rem_desc = (
                        f"Kalan: {_fmt_days(report.remaining_total_days)} gün hakkın var "
                        f"({_fmt_hours(report.remaining_total)} saat)"
                    )
                else:
                    rem_desc = f"Kalan: 0 tam gün ({_fmt_hours(report.remaining_total)} saat)"
                parts.append(
                    f"Kullanılan: {_fmt_days(report.used_total_days)}/{_fmt_days(report.max_total_days)} gün "
                    f"({_fmt_hours(report.used_total_absent)}/{_fmt_hours(report.max_total_absent)} saat) | {rem_desc}"
                )
            else:
                parts.append(
                    f"Devamsızlık: {_fmt_hours(report.used_total_absent)}/{_fmt_hours(report.max_total_absent)} saat "
                    f"(Kalan: {_fmt_hours(report.remaining_total)} saat)"
                )
        elif report.max_total_days is not None:
            parts.append(
                f"{_fmt_days(report.max_total_days)} gün hakkın var ({_fmt_hours(report.max_total_absent)} saat)"
            )
        else:
            parts.append(f"Maks. Hak: {_fmt_hours(report.max_total_absent)} saat")

    if report.absent_percent is not None:
        parts.append(f"Oran: %{report.absent_percent:g}")
    if report.status and report.status != "Bilinmiyor":
        parts.append(report.status)
    return " | ".join(parts)


def format_attendance_report(reports: list[AttendanceReport], base_url: str) -> str:
    """Tüm derslerin devamsızlık hakkı ve risk özetini Telegram HTML mesajına dönüştürür."""
    lines = ["📋 <b>Devamsızlık Takip Raporu</b>", ""]
    if not reports:
        lines.append("Değerlendirilecek ders bulunamadı.")
    else:
        for report in reports:
            icon = _ATTENDANCE_ICONS.get(report.risk_level, "⚪")
            title = f"{report.course_code} - {report.course_name}" if report.course_code else report.course_name
            lines.append(f"{icon} <b>{html.escape(title)}</b>")
            lines.append(f"   └ {html.escape(format_attendance_detail_line(report))}")

    lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_attendance_alerts(
    alerts: list[tuple[AttendanceReport, Optional[float], Optional[str]]],
    base_url: str,
) -> str:
    """Devamsızlık artışı veya kritik sınır uyarısı için Telegram HTML mesajı üretir."""
    lines = ["⚠️ <b>Devamsızlık Uyarısı</b>", ""]
    for report, old_hours, old_status in alerts:
        icon = _ATTENDANCE_ICONS.get(report.risk_level, "⚠️")
        title = f"{report.course_code} - {report.course_name}" if report.course_code else report.course_name
        lines.append(f"{icon} <b>{html.escape(title)}</b>")
        if old_hours is not None and report.used_total_absent is not None and report.used_total_absent > old_hours:
            weekly_sum = (report.weekly_theory or 0.0) + (report.weekly_practice or 0.0)
            if weekly_sum > 0:
                old_d = _fmt_days(round(old_hours / weekly_sum, 2))
                new_d = _fmt_days(round(report.used_total_absent / weekly_sum, 2))
                lines.append(
                    f"   └ Kullanılan: <code>{old_d}</code> → <code>{new_d}</code> gün "
                    f"(<code>{_fmt_hours(old_hours)}</code> → <code>{_fmt_hours(report.used_total_absent)}</code> saat)"
                )
            else:
                lines.append(
                    f"   └ Kullanılan: <code>{_fmt_hours(old_hours)}</code> → <code>{_fmt_hours(report.used_total_absent)}</code> saat"
                )
        elif old_status and report.status != old_status:
            lines.append(f"   └ Durum: {html.escape(old_status)} → <b>{html.escape(report.status)}</b>")
        lines.append(f"   └ {html.escape(format_attendance_detail_line(report))}")
        lines.append("")

    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_weather_report(weather: WeatherForecast) -> str:
    """Kastamonu / Kuzeykent hava durumu raporunu Telegram HTML formatında üretir."""
    lines = [
        f"{weather.condition_icon} <b>{html.escape(weather.location_name)} Hava Durumu</b>",
        f"📅 <i>{html.escape(format_tr_date(weather.forecast_date))}</i>",
        "",
        f"🌡️ <b>Durum:</b> {html.escape(weather.condition_text)}",
    ]
    if weather.current_temp is not None:
        app_txt = f" (Hissedilen: {weather.apparent_temp:.0f}°C)" if weather.apparent_temp is not None else ""
        lines.append(f"🌡️ <b>Şu An:</b> <code>{weather.current_temp:.1f}°C</code>{html.escape(app_txt)}")
    if weather.temp_min is not None and weather.temp_max is not None:
        lines.append(f"↕️ <b>Günlük En Düşük / Yüksek:</b> <code>{weather.temp_min:.0f}° / {weather.temp_max:.0f}°C</code>")
    if weather.precip_probability is not None:
        lines.append(f"☔ <b>Yağış İhtimali:</b> <code>%{weather.precip_probability}</code>")
    if weather.wind_speed is not None:
        lines.append(f"💨 <b>Rüzgâr:</b> <code>{weather.wind_speed:.0f} km/sa</code>")
    lines.append(f"🧥 <b>Tavsiye:</b> <i>{html.escape(weather.advice)}</i>")

    if weather.daily_summaries:
        lines.append("")
        lines.append("📆 <b>3 Günlük Görünüm:</b>")
        for s in weather.daily_summaries:
            lines.append(f"• {html.escape(s)}")

    return "\n".join(lines)


def _trim_announcement_summary(raw: str, limit: int = 110) -> str:
    cleaned = " ".join((raw or "").split())
    cleaned = re.sub(r"\s+([’'])", r"\1", cleaned)
    cleaned = re.sub(r"([A-Za-zÇĞİÖŞÜçğıöşü0-9][’'])\s+(?=[a-zçğıöşü])", r"\1", cleaned)
    if len(re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+", "", cleaned)) < 4:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;: ")
    return f"{clipped}..."


def _select_balanced_announcements(items: list[Announcement], max_items: int = 8) -> list[Announcement]:
    if len(items) <= max_items:
        return items
    buckets: OrderedDict[str, list[Announcement]] = OrderedDict()
    for item in items:
        buckets.setdefault(item.source, []).append(item)
    selected: list[Announcement] = []
    idx = 0
    while len(selected) < max_items:
        added_any = False
        for src_list in buckets.values():
            if idx < len(src_list):
                selected.append(src_list[idx])
                added_any = True
                if len(selected) >= max_items:
                    break
        if not added_any:
            break
        idx += 1
    return selected


def format_announcements(announcements: list[Announcement], is_preview: bool = False) -> str:
    """Üniversite / OİDB / SKS / Fakülte / ÜBYS duyurularını Telegram HTML mesajına çevirir."""
    header = "📢 <b>Kastamonu Üniversitesi Güncel Duyurular</b>" if is_preview else "📢 <b>Yeni Duyuru Bildirimi</b>"
    lines = [header, ""]
    if not announcements:
        lines.append("Gösterilecek duyuru bulunamadı.")
        return "\n".join(lines)

    to_show = _select_balanced_announcements(announcements, max_items=8) if is_preview else announcements[:15]
    for item in to_show:
        date_tag = f" ({html.escape(item.published_date)})" if item.published_date else ""
        lines.append(f"🏷️ <b>[{html.escape(item.source)}]</b>{date_tag}")
        lines.append(f'• <a href="{html.escape(item.url, quote=True)}">{html.escape(item.title)}</a>')
        trimmed_sum = _trim_announcement_summary(item.summary)
        if trimmed_sum:
            lines.append(f"  <i>{html.escape(trimmed_sum)}</i>")
        lines.append("")

    if is_preview and len(announcements) > len(to_show):
        lines.append(f"<i>... toplam {len(announcements)} duyurunun en güncel {len(to_show)} tanesi gösterildi.</i>")
    return "\n".join(lines).rstrip()


def format_gpa_projection(projection: GpaProjection, base_url: str) -> str:
    """Tahmini YANO/GANO ve onur belgesi projeksiyonunu Telegram HTML mesajına çevirir."""
    lines = ["📊 <b>Dönem Sonu YANO / GANO Projeksiyonu</b>", ""]
    if projection.projected_yano is None:
        lines.append("Henüz YANO/GANO hesabı için girilmiş geçme harfi veya vize+final notu yok.")
        lines.append("")
        lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
        return "\n".join(lines)

    lines.append(f"📈 <b>Tahmini Dönem Ortalaması (YANO):</b> <code>{projection.projected_yano:.2f}</code> (Kredi: <code>{projection.total_term_credit:g}</code>)")
    if projection.projected_gano is not None:
        prev_txt = f" (Önceki: <code>{projection.current_gano:.2f}</code>)" if projection.current_gano is not None else ""
        lines.append(f"🎓 <b>Tahmini Genel Ortalama (GANO):</b> <code>{projection.projected_gano:.2f}</code>{prev_txt}")

    status_map = {
        "yuksek_onur": "🏆 <b>Yüksek Onur Belgesi (≥3.50)</b> bandındasın!",
        "onur": "🏅 <b>Onur Belgesi (≥3.00)</b> bandındasın!",
        "risk": "⚠️ <b>Dikkat:</b> GANO 2.00 sınırının altında görünüyor.",
        "normal": "📘 Normal başarı bandındasın.",
    }
    lines.append(status_map.get(projection.honor_status, ""))

    if projection.has_conditional_grade and projection.dc_pass_safe is not None:
        if projection.dc_pass_safe:
            lines.append("✅ <b>DC/DD Koşullu Ders:</b> GANO ≥ 2.00 olduğu için geçme güvenli görünüyor.")
        else:
            lines.append("🚨 <b>DC/DD Koşullu Ders Uyarısı:</b> GANO < 2.00 olursa koşullu dersler kalabilir.")

    if not projection.has_failing_grade:
        if projection.points_to_honor and projection.points_to_honor > 0:
            lines.append(f"ℹ️ Onur Belgesi (3.00) için dönem ortalamana <code>+{projection.points_to_honor:.2f}</code> puan gerekiyor.")
        elif projection.points_to_high_honor and projection.points_to_high_honor > 0:
            lines.append(f"ℹ️ Yüksek Onur (3.50) için dönem ortalamana <code>+{projection.points_to_high_honor:.2f}</code> puan gerekiyor.")

    if projection.counted_courses:
        lines.append("")
        lines.append("📚 <b>Hesaba Katılan Dersler:</b>")
        for c in projection.counted_courses:
            tag = "tahmini" if c.get("source") == "tahmini" else "resmî"
            title = f"{c['code']} - {c['name']}" if c.get("code") else str(c.get("name") or "")
            lines.append(
                f"• {html.escape(title)} ({c['credit']:g} kr): <b>{html.escape(c['letter'])}</b> <i>({tag})</i>"
            )

    lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def _format_slot_line(slot: ScheduleSlot) -> str:
    time_txt = f"{slot.start_time}-{slot.end_time}" if slot.end_time else slot.start_time
    title = f"{slot.course_code} - {slot.course_name}" if slot.course_code else slot.course_name
    extras = [x for x in (slot.classroom, slot.instructor) if x]
    suffix = f" <i>({' | '.join(extras)})</i>" if extras else ""
    return f"⏰ <code>{html.escape(time_txt)}</code> • <b>{html.escape(title)}</b>{suffix}"


def format_daily_schedule(slots: list[ScheduleSlot], target_date: date, base_url: str) -> str:
    """Belirli bir günün ders programını Telegram HTML mesajına çevirir."""
    lines = [
        "🗓️ <b>Günün Ders Programı</b>",
        f"📅 <i>{html.escape(format_tr_date(target_date))}</i>",
        "",
    ]
    if not slots:
        lines.append("Bugün için kayıtlı ders bulunmuyor 🎉")
    else:
        for s in slots:
            lines.append(_format_slot_line(s))
    lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_weekly_schedule(slots: list[ScheduleSlot], base_url: str) -> str:
    """Tüm haftalık ders programını Telegram HTML mesajına çevirir."""
    lines = ["🗓️ <b>Haftalık Ders Programı</b>", ""]
    if not slots:
        lines.append("ÜBYS üzerinde ders programı verisi bulunamadı.")
    else:
        grouped: OrderedDict[int, list[ScheduleSlot]] = OrderedDict()
        for s in sorted(slots, key=lambda x: (x.day_of_week, x.start_time, x.course_code)):
            grouped.setdefault(s.day_of_week, []).append(s)
        for day_slots in grouped.values():
            lines.append(f"📌 <b>{html.escape(day_slots[0].day_name)}</b>")
            for s in day_slots:
                lines.append(f"  {_format_slot_line(s)}")
            lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_exam_schedule(
    exams: list[ExamScheduleItem],
    today: date,
    base_url: str,
    exam_announcements: Optional[list[Announcement]] = None,
) -> str:
    """Yaklaşan sınav programını ve bölüm/fakülte sınav duyuru PDF'lerini Telegram HTML mesajına çevirir."""
    lines = ["📝 <b>ÜBYS Sınav Takvimi</b>", ""]
    if not exams and not exam_announcements:
        lines.append("ÜBYS üzerinde yayınlanmış sınav takvimi bulunamadı.")
    else:
        if exams:
            upcoming = [e for e in exams if e.exam_date >= today]
            to_show = upcoming if upcoming else exams
            for ex in to_show[:25]:
                days_left = (ex.exam_date - today).days
                day_tag = "BUGÜN" if days_left == 0 else (f"{days_left} gün kaldı" if days_left > 0 else "Geçti")
                title = f"{ex.course_code} - {ex.course_name}" if ex.course_code else ex.course_name
                time_part = f" | {ex.exam_time}" if ex.exam_time else ""
                room_part = f" | Salon: {ex.classroom}" if ex.classroom else ""
                seat_part = f" (Sıra: {ex.seat})" if ex.seat else ""
                lines.append(f"• <b>{html.escape(title)}</b> — <i>{html.escape(ex.exam_type)}</i>")
                lines.append(
                    f"  📅 {html.escape(format_tr_date(ex.exam_date, with_weekday=True))}{html.escape(time_part + room_part + seat_part)} (<b>{html.escape(day_tag)}</b>)"
                )
        if exam_announcements:
            if exams:
                lines.append("")
            lines.append("📢 <b>Bölüm / Fakülte Sınav Programı &amp; PDF'ler:</b>")
            for ann in exam_announcements[:6]:
                d_tag = f" ({html.escape(ann.published_date)})" if ann.published_date else ""
                lines.append(
                    f'• <b>[{html.escape(ann.source)}]</b>{d_tag} '
                    f'<a href="{html.escape(ann.url, quote=True)}">{html.escape(ann.title)}</a>'
                )
    lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_exam_reminders(reminders: list[tuple[ExamScheduleItem, int]], base_url: str) -> str:
    """Sınav günü yaklaşan dersler için hatırlatma mesajı üretir."""
    lines = ["📝 <b>Yaklaşan Sınav Hatırlatması</b>", ""]
    for ex, days_until in reminders:
        badge = "🚨 <b>BUGÜN SINAV VAR</b>" if days_until == 0 else ("⏰ <b>YARIN SINAV VAR</b>" if days_until == 1 else f"⏳ <b>{days_until} GÜN KALDI</b>")
        title = f"{ex.course_code} - {ex.course_name}" if ex.course_code else ex.course_name
        lines.append(f"{badge} • <b>{html.escape(title)}</b> ({html.escape(ex.exam_type)})")
        meta = [format_tr_date(ex.exam_date)]
        if ex.exam_time:
            meta.append(f"Saat {ex.exam_time}")
        if ex.classroom:
            meta.append(f"Salon: {ex.classroom}")
        if ex.seat:
            meta.append(f"Sıra: {ex.seat}")
        lines.append(f"   └ {html.escape(' | '.join(meta))}")
        lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_material_alerts(materials: list[CourseMaterial], base_url: str) -> str:
    """Ders içine yüklenen yeni materyal, ödev veya duyuru bildirimi üretir."""
    icon_map = {"ödev": "📝", "duyuru": "📢", "dosya": "📄"}
    lines = ["📚 <b>Ders Materyali / Ödev Bildirimi</b>", ""]
    for mat in materials[:20]:
        icon = icon_map.get(mat.category, "📄")
        course_title = f"{mat.course_code} - {mat.course_name}" if mat.course_code else mat.course_name
        lines.append(f"{icon} <b>[{html.escape(mat.category.upper())}]</b> {html.escape(course_title)}")
        if mat.url:
            lines.append(f'   └ <a href="{html.escape(mat.url, quote=True)}">{html.escape(mat.title)}</a>')
        else:
            lines.append(f"   └ <b>{html.escape(mat.title)}</b>")
        if mat.due_date:
            lines.append(f"   └ ⏳ Son Teslim: <code>{html.escape(mat.due_date)}</code>")
        lines.append("")
    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_weekly_briefing(
    today: date,
    ongoing_cal: list[CalendarEvent],
    upcoming_cal: list[CalendarEvent],
    exams: list[ExamScheduleItem],
    attendance_reports: list[AttendanceReport],
    gpa_projection: Optional[GpaProjection],
    weather: Optional[WeatherForecast],
    base_url: str,
) -> str:
    """Haftalık öğrenci özet brifingi mesajını oluşturur."""
    lines = [
        "📆 <b>Haftalık Kastamonu ÜBYS Öğrenci Özeti</b>",
        f"📅 <i>{html.escape(format_tr_date(today))}</i>",
        "",
    ]

    if weather is not None:
        lines.extend(_format_weather_inline_lines(weather))
        if weather.tomorrow_summary:
            lines.append(f"   └ Yarın: {html.escape(weather.tomorrow_summary)}")
        lines.append("")

    upcoming_exams = [e for e in exams if 0 <= (e.exam_date - today).days <= 14]
    if upcoming_exams:
        lines.append("📝 <b>Önümüzdeki 14 Günün Sınavları:</b>")
        for ex in upcoming_exams[:8]:
            days_left = (ex.exam_date - today).days
            t_str = f" {ex.exam_time}" if ex.exam_time else ""
            r_str = f" | {ex.classroom}" if ex.classroom else ""
            lines.append(
                f"• <b>{html.escape(ex.course_code or ex.course_name)}</b> ({html.escape(ex.exam_type)}): "
                f"{html.escape(format_tr_date(ex.exam_date, with_weekday=False))}{html.escape(t_str + r_str)} ({days_left} gün)"
            )
        lines.append("")

    risky_att = [r for r in attendance_reports if r.risk_level in {"warning", "critical", "failed"}]
    if risky_att:
        lines.append("⚠️ <b>Devamsızlık Uyarısı Olan Dersler:</b>")
        for r in risky_att:
            ico = _ATTENDANCE_ICONS.get(r.risk_level, "⚠️")
            lines.append(f"{ico} <b>{html.escape(r.course_code or r.course_name)}</b>: {html.escape(format_attendance_detail_line(r))}")
        lines.append("")

    if gpa_projection is not None and gpa_projection.projected_yano is not None:
        gano_part = f" | GANO: <code>{gpa_projection.projected_gano:.2f}</code>" if gpa_projection.projected_gano is not None else ""
        lines.append(f"📊 <b>Tahmini YANO:</b> <code>{gpa_projection.projected_yano:.2f}</code>{gano_part}")
        lines.append("")

    week_cal = [e for e in upcoming_cal if 0 <= (e.start_date - today).days <= 10]
    if ongoing_cal or week_cal:
        lines.append("🗓️ <b>Akademik Takvim (Yakın Tarihler):</b>")
        for ev in ongoing_cal[:4]:
            lines.append(f"• ⏳ <b>{html.escape(ev.title)}</b> (Devam ediyor)")
        for ev in week_cal[:5]:
            days_left = (ev.start_date - today).days
            lines.append(f"• 📅 <b>{html.escape(ev.title)}</b> ({days_left} gün kaldı)")
        lines.append("")

    if len(lines) <= 4:
        lines.append("Bu hafta için kritik sınav, devamsızlık uyarısı veya takvim etkinliği görünmüyor. İyi haftalar! 💪")
        lines.append("")

    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)


def format_help_message() -> str:
    """Telegram etkileşimli bot komut listesini HTML formatında döndürür."""
    return "\n".join(
        [
            "🤖 <b>Kastamonu ÜBYS Asistanı Komutları</b>",
            "",
            "• /notlar — Güncel ders notlarını listeler",
            "• /devamsizlik — Gün/saat bazlı devamsızlık haklarını gösterir",
            "• /hesapla <code>VIZE [ORAN]</code> — Final hedeflerini hesaplar <i>(ör. /hesapla 80 30/70)</i>",
            "• /yemek — Günün yemekhane menüsü ve hava durumunu gönderir",
            "• /hava — Kuzeykent Kampüsü güncel & 3 günlük hava tahmini",
            "• /program — Haftalık veya bugünkü ders programını gösterir",
            "• /sinav — Yaklaşan sınav tarih ve salonlarını listeler",
            "• /duyuru — OİDB, SKS ve okul güncel duyurularını getirir",
            "• /takvim — Yaklaşan akademik takvim tarihlerini gösterir",
            "• /transkript — Dönem ortalamalarını ve genel GANO özetini verir",
            "• /gano — Tahmini dönem sonu YANO/GANO & Onur belgesi durumu",
            "• /ozet — Haftalık toplu öğrenci özetini gösterir",
            "",
            "ℹ️ <i>Not: GitHub Actions modunda komutlar ~15 dakikalık kontrol döngüsünde yanıtlanır; VPS/Docker --listen kipinde anlık yanıt verir.</i>",
        ]
    )
