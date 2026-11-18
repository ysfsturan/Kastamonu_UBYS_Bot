"""Telegram bildirim gönderme ve mesaj biçimlendirme modülü."""

from __future__ import annotations

import html
from collections import OrderedDict
from typing import Iterable

import httpx

from .models import CourseGrade, GradeChange

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


class TelegramNotifier:
    """Telegram Bot API üzerinden HTML formatlı bildirim gönderir."""

    def __init__(self, bot_token: str, chat_ids: Iterable[str], timeout: float = 20.0) -> None:
        self.bot_token = bot_token
        self.chat_ids = [str(cid).strip() for cid in chat_ids if str(cid).strip()]
        self.timeout = timeout

    def send_message(self, text: str) -> None:
        """Mesajı yapılandırılmış tüm Telegram sohbetlerine gönderir."""
        if not text.strip():
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        chunks = split_message(text)

        with httpx.Client(timeout=self.timeout) as client:
            for chat_id in self.chat_ids:
                for chunk in chunks:
                    payload = {
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    }
                    response = client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    if not data.get("ok"):
                        raise RuntimeError(
                            f"Telegram API hatası (chat_id={chat_id}): {data.get('description', data)}"
                        )


def format_grade_changes(changes: list[GradeChange], base_url: str) -> str:
    """Tespit edilen not değişikliklerini okunaklı Türkçe Telegram mesajına dönüştürür."""
    grouped: OrderedDict[tuple[str, str, str], list[GradeChange]] = OrderedDict()
    for change in changes:
        key = (change.semester, change.course_code, change.course_name)
        grouped.setdefault(key, []).append(change)

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
