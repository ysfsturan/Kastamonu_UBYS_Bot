"""Telegram bildirim gönderme ve mesaj biçimlendirme modülü."""

from __future__ import annotations

import html
import logging
import time
from collections import OrderedDict
from datetime import date
from typing import Any, Iterable, Optional

import httpx

from .grade_calculator import analyze_course_grades
from .models import (
    AttendanceReport,
    CalendarEvent,
    CourseGrade,
    DailyMenu,
    GradeChange,
    GradeTargetAnalysis,
    TranscriptSummary,
)

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4000


def split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Uzun mesajları satır sınırlarından Telegram limitine uygun parçalara böler."""
    if len(text) <= max_length:
        return [text]

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

    def send_message(self, text: str) -> None:
        """Mesajı yapılandırılmış tüm Telegram sohbetlerine IPv4 ve yeniden denemeyle gönderir."""
        if not text.strip():
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        chunks = split_message(text)

        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout, connect=min(15.0, self.timeout)),
        }
        transport = _build_ipv4_transport()
        if transport is not None:
            client_kwargs["transport"] = transport

        with httpx.Client(**client_kwargs) as client:
            for chat_id in self.chat_ids:
                for chunk in chunks:
                    payload = {
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    }
                    self._post_chunk_with_retry(client, url, chat_id, payload)

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
        if course.status:
            extras.append(course.status)

        summary = " | ".join(extras) if extras else "Henüz açıklanmış not yok"
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


def format_daily_menu(menu: DailyMenu, is_next_preview: bool = False) -> str:
    """Günlük yemekhane menüsünü Telegram HTML mesajına dönüştürür."""
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


def format_transcript_summary(summary: TranscriptSummary, base_url: str) -> str:
    """Transkript ve GANO özetini Telegram HTML mesajına dönüştürür."""
    lines = ["🎓 <b>Kastamonu ÜBYS Transkript Özeti</b>", ""]
    if summary.gano is not None:
        lines.append(f"📊 <b>Genel Ortalama (GANO):</b> <code>{summary.gano:.2f}</code>")
    if summary.total_credit is not None:
        lines.append(f"📘 <b>Toplam Kredi:</b> <code>{summary.total_credit:g}</code>")
    if summary.total_ects is not None:
        lines.append(f"📗 <b>Toplam AKTS:</b> <code>{summary.total_ects:g}</code>")

    if summary.semesters:
        lines.append("")
        lines.append("📅 <b>Dönem Ortalamaları:</b>")
        for sem in summary.semesters:
            parts: list[str] = []
            if sem.semester_gpa is not None:
                parts.append(f"YANO: {sem.semester_gpa:.2f}")
            if sem.cumulative_gpa is not None:
                parts.append(f"GANO: {sem.cumulative_gpa:.2f}")
            if not parts and sem.courses:
                parts.append(f"{len(sem.courses)} ders")
            suffix = f" ({' | '.join(parts)})" if parts else ""
            lines.append(f"• <b>{html.escape(sem.name)}</b>{html.escape(suffix)}")

        latest = summary.semesters[-1]
        if latest.courses:
            lines.append("")
            lines.append(f"📚 <b>Son Dönem ({html.escape(latest.name)}):</b>")
            for c in latest.courses[:20]:
                grade_str = html.escape(c.letter_grade or "-")
                title = f"{c.code} - {c.name}" if c.code else c.name
                lines.append(f"• {html.escape(title)}: <code>{grade_str}</code>")
            if len(latest.courses) > 20:
                lines.append(f"<i>... ve {len(latest.courses) - 20} ders daha.</i>")
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


def _format_attendance_detail_line(report: AttendanceReport) -> str:
    parts: list[str] = [report.course_type]
    if report.max_theory_absent is not None and report.max_practice_absent is not None:
        t_part = f"Teorik: {_fmt_hours(report.used_theory_absent)}/{_fmt_hours(report.max_theory_absent)}"
        if report.remaining_theory is not None:
            t_part += f" (Kalan {_fmt_hours(report.remaining_theory)})"
        u_part = f"Uyg: {_fmt_hours(report.used_practice_absent)}/{_fmt_hours(report.max_practice_absent)}"
        if report.remaining_practice is not None:
            u_part += f" (Kalan {_fmt_hours(report.remaining_practice)})"
        parts.extend([t_part, u_part])
    elif report.max_total_absent is not None:
        if report.used_total_absent is not None and report.remaining_total is not None:
            parts.append(
                f"Devamsızlık: {_fmt_hours(report.used_total_absent)}/{_fmt_hours(report.max_total_absent)} saat "
                f"(Kalan: {_fmt_hours(report.remaining_total)} saat)"
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
            lines.append(f"   └ {html.escape(_format_attendance_detail_line(report))}")

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
            lines.append(
                f"   └ Kullanılan: <code>{_fmt_hours(old_hours)}</code> → <code>{_fmt_hours(report.used_total_absent)}</code> saat"
            )
        elif old_status and report.status != old_status:
            lines.append(f"   └ Durum: {html.escape(old_status)} → <b>{html.escape(report.status)}</b>")
        lines.append(f"   └ {html.escape(_format_attendance_detail_line(report))}")
        lines.append("")

    lines.append(f'🔗 <a href="{html.escape(base_url, quote=True)}">Kastamonu ÜBYS\'ye Git</a>')
    return "\n".join(lines)
