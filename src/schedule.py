"""ÜBYS haftalık ders programı ve sınav takvimi ayrıştırma ve hatırlatma modülü."""

from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from .models import ExamScheduleItem, ScheduleSlot

_TR_DAYS = (
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
)

_DAY_ALIASES: dict[str, int] = {
    "pazartesi": 0,
    "pzt": 0,
    "monday": 0,
    "mon": 0,
    "salı": 1,
    "sali": 1,
    "sal": 1,
    "tuesday": 1,
    "tue": 1,
    "çarşamba": 2,
    "carsamba": 2,
    "çrş": 2,
    "crs": 2,
    "wednesday": 2,
    "wed": 2,
    "perşembe": 3,
    "persembe": 3,
    "per": 3,
    "prs": 3,
    "thursday": 3,
    "thu": 3,
    "cuma": 4,
    "cum": 4,
    "friday": 4,
    "fri": 4,
    "cumartesi": 5,
    "cmt": 5,
    "cmts": 5,
    "saturday": 5,
    "sat": 5,
    "pazar": 6,
    "paz": 6,
    "sunday": 6,
    "sun": 6,
}

_TR_MONTHS: dict[str, int] = {
    "ocak": 1,
    "oca": 1,
    "şubat": 2,
    "subat": 2,
    "şub": 2,
    "sub": 2,
    "mart": 3,
    "mar": 3,
    "nisan": 4,
    "nis": 4,
    "mayıs": 5,
    "mayis": 5,
    "may": 5,
    "haziran": 6,
    "haz": 6,
    "temmuz": 7,
    "tem": 7,
    "ağustos": 8,
    "agustos": 8,
    "ağu": 8,
    "agu": 8,
    "eylül": 9,
    "eylul": 9,
    "eyl": 9,
    "ekim": 10,
    "eki": 10,
    "kasım": 11,
    "kasim": 11,
    "kas": 11,
    "aralık": 12,
    "aralik": 12,
    "ara": 12,
}

_JSM_DECODE_RE = re.compile(r'Base64\.decode\(\s*["\']([^"\']+)["\']\s*\)')
_TIME_RANGE_RE = re.compile(r"\b(\d{1,2}[:.]\d{2})\s*(?:[-–]\s*(\d{1,2}[:.]\d{2}))?\b")
_COURSE_CODE_RE = re.compile(r"\b([A-ZÇĞİÖŞÜ]{2,6}\s*-?\s*\d{3,4}[A-Z]?)\b")
_DMY_DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TEXT_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-ZÇĞİÖŞÜa-zçğıöşü]{3,10})(?:\s+(\d{4}))?\b")


def _clean_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return " ".join(raw.split())


def _tr_lower(text: str) -> str:
    return " ".join(text.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "").split())


def _parse_day_index(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, int):
        if 1 <= raw <= 7:
            return raw - 1
        if 0 <= raw <= 6:
            return raw
        return None
    text = _tr_lower(str(raw))
    if text.isdigit():
        num = int(text)
        if 1 <= num <= 7:
            return num - 1
        if 0 <= num <= 6:
            return num
    for alias, idx in _DAY_ALIASES.items():
        if text == alias or alias in text.split():
            return idx
    for alias, idx in _DAY_ALIASES.items():
        if len(alias) >= 4 and alias in text:
            return idx
    return None


def _norm_time(raw: Optional[str]) -> str:
    if not raw:
        return ""
    match = re.search(r"(\d{1,2})[:.](\d{2})", raw)
    if not match:
        return ""
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"


def _parse_time_range(raw: str) -> tuple[str, str]:
    match = _TIME_RANGE_RE.search(raw or "")
    if not match:
        return "", ""
    return _norm_time(match.group(1)), _norm_time(match.group(2) or "")


def _parse_exam_date(raw: Any, default_year: Optional[int] = None) -> Optional[date]:
    if not raw:
        return None
    text = str(raw).strip()
    if text.startswith("/Date("):
        ms_match = re.search(r"/Date\((\d+)", text)
        if ms_match:
            return datetime.fromtimestamp(int(ms_match.group(1)) / 1000.0).date()

    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            pass

    dmy_match = _DMY_DATE_RE.search(text)
    if dmy_match:
        try:
            return date(int(dmy_match.group(3)), int(dmy_match.group(2)), int(dmy_match.group(1)))
        except ValueError:
            pass

    txt_match = _TEXT_DATE_RE.search(_tr_lower(text))
    if txt_match:
        month = _TR_MONTHS.get(txt_match.group(2))
        if month:
            year = int(txt_match.group(3)) if txt_match.group(3) else (default_year or date.today().year)
            try:
                return date(year, month, int(txt_match.group(1)))
            except ValueError:
                pass
    return None


def _extract_jsm_objects(html: str) -> list[Any]:
    objs: list[Any] = []
    for match in _JSM_DECODE_RE.finditer(html or ""):
        try:
            decoded = base64.b64decode(match.group(1)).decode("utf-8")
            objs.append(json.loads(decoded))
        except Exception:
            continue
    return objs


def _extract_cell_lines(cell: Tag) -> list[str]:
    html_fragment = str(cell)
    html_fragment = re.sub(r"<br\s*/?>", "\n", html_fragment, flags=re.IGNORECASE)
    frag_soup = BeautifulSoup(html_fragment, "html.parser")
    text = frag_soup.get_text("\n")
    return [_clean_text(line) for line in text.splitlines() if _clean_text(line)]


def _parse_grid_cell_slot(
    cell: Tag,
    day_idx: int,
    row_start: str,
    row_end: str,
) -> Optional[ScheduleSlot]:
    lines = _extract_cell_lines(cell)
    if not lines:
        return None
    full_text = " ".join(lines)
    if _tr_lower(full_text) in {"", "-", "--", "boş", "bos"}:
        return None

    classroom: Optional[str] = None
    instructor: Optional[str] = None
    course_code = ""
    course_name = ""

    remaining_lines: list[str] = []
    for line in lines:
        low = _tr_lower(line)
        labeled_room_match = re.search(r"(?:derslik|salon|oda)\s*[:\-]\s*(.+)$", line, re.IGNORECASE)
        if labeled_room_match:
            classroom = _clean_text(labeled_room_match.group(1))
            continue
        if re.match(r"^(?:amfi|lab|laboratuvar|derslik|salon)\b", low):
            classroom = _clean_text(line)
            continue
        inst_match = re.search(r"(?:öğretim|ogretim|hoca|elemanı|elemani)\s*[:\-]\s*(.+)$", line, re.IGNORECASE)
        if inst_match:
            instructor = _clean_text(inst_match.group(1))
            continue
        if not row_start and _TIME_RANGE_RE.search(line):
            row_start, row_end = _parse_time_range(line)
            cleaned_line = _clean_text(_TIME_RANGE_RE.sub("", line))
            if cleaned_line:
                remaining_lines.append(cleaned_line)
            continue
        if any(title in low for title in ("dr.", "öğr.", "prof.", "doç.", "arş.")) and len(lines) >= 2:
            instructor = line
            continue
        remaining_lines.append(line)

    for line in remaining_lines:
        if not course_code:
            code_m = _COURSE_CODE_RE.search(line)
            if code_m:
                course_code = _clean_text(code_m.group(1)).replace(" ", "")
                leftover = _clean_text(line.replace(code_m.group(1), "")).strip("-:| ")
                if leftover and not course_name:
                    course_name = leftover
                continue
        if not course_name:
            # Parantez içinde derslik varsa ayır: "İnternet Programcılığı (Lab-2)"
            paren_m = re.match(r"^(.+?)\s*\(([^()]{2,25})\)\s*$", line)
            if paren_m and classroom is None:
                course_name = _clean_text(paren_m.group(1))
                classroom = _clean_text(paren_m.group(2))
            else:
                course_name = line
        elif classroom is None:
            classroom = line

    if not course_name and not course_code:
        return None

    return ScheduleSlot(
        day_of_week=day_idx,
        day_name=_TR_DAYS[day_idx],
        start_time=row_start or "00:00",
        end_time=row_end,
        course_code=course_code,
        course_name=course_name or course_code,
        classroom=classroom,
        instructor=instructor,
    )


def _fmt_hour_minute(hour_val: Any, min_val: Any) -> str:
    if hour_val is None or hour_val == "":
        return ""
    try:
        return f"{int(hour_val):02d}:{int(min_val or 0):02d}"
    except (TypeError, ValueError):
        return ""


def _split_code_and_name(raw_code: str, raw_name: str) -> tuple[str, str]:
    c_code = _clean_text(raw_code)
    c_name = _clean_text(raw_name)
    if not c_code and c_name:
        m = re.match(
            r"^([A-ZÇĞİÖŞÜ]{2,6}\s*-?\s*\d{3,4}[A-Z]?)(?:\.\d+)?(?:\s+[-–:]?\s*(.+))?$",
            c_name,
        )
        if m:
            c_code = m.group(1).replace(" ", "")
            c_name = _clean_text(m.group(2)) or c_code
    elif c_code:
        c_code = re.sub(r"\.\d+$", "", c_code)
    return c_code, c_name


def parse_weekly_schedule(html: str) -> list[ScheduleSlot]:
    """ÜBYS haftalık ders programı sayfasından (_weeklySchedulle/_jsm, grid tablo veya liste tablo) ders saatlerini çıkarır."""
    slots: list[ScheduleSlot] = []
    seen: set[tuple[int, str, str, str, str]] = set()

    def _add(slot: Optional[ScheduleSlot]) -> None:
        if slot is None:
            return
        key = (
            slot.day_of_week,
            slot.start_time,
            slot.end_time,
            slot.course_code,
            _tr_lower(slot.course_name),
        )
        if key in seen:
            return
        seen.add(key)
        slots.append(slot)

    # 1. Base64 JSON (_weeklySchedulle / _jsm)
    def _walk_jsm(obj: Any) -> None:
        if isinstance(obj, dict):
            day_idx = _parse_day_index(
                obj.get("DayOfWeek") if obj.get("DayOfWeek") is not None else obj.get("Day") or obj.get("DayName")
            )
            raw_name = str(obj.get("CourseName") or obj.get("LessonName") or "")
            raw_code = str(obj.get("CourseCode") or "")
            c_code, c_name = _split_code_and_name(raw_code, raw_name)
            start = _norm_time(str(obj.get("StartTime") or obj.get("Start") or ""))
            if not start:
                start = _fmt_hour_minute(obj.get("StartHour"), obj.get("StartMinute"))
            if day_idx is not None and (c_name or c_code):
                end = _norm_time(str(obj.get("EndTime") or obj.get("End") or ""))
                if not end:
                    end = _fmt_hour_minute(
                        obj.get("FinishHour") if obj.get("FinishHour") is not None else obj.get("EndHour"),
                        obj.get("FinishMinute") if obj.get("FinishMinute") is not None else obj.get("EndMinute"),
                    )
                room = (
                    _clean_text(
                        str(
                            obj.get("WorkCenterName")
                            or obj.get("Classroom")
                            or obj.get("ClassRoomName")
                            or obj.get("RoomName")
                            or ""
                        )
                    )
                    or None
                )
                inst = _clean_text(str(obj.get("InstructorName") or obj.get("Instructor") or "")) or None
                _add(
                    ScheduleSlot(
                        day_of_week=day_idx,
                        day_name=_TR_DAYS[day_idx],
                        start_time=start or "00:00",
                        end_time=end,
                        course_code=c_code,
                        course_name=c_name or c_code,
                        classroom=room,
                        instructor=inst,
                    )
                )
            for val in obj.values():
                if isinstance(val, (dict, list)):
                    _walk_jsm(val)
        elif isinstance(obj, list):
            for item in obj:
                _walk_jsm(item)

    for jsm_obj in _extract_jsm_objects(html):
        _walk_jsm(jsm_obj)

    if slots:
        return sorted(slots, key=lambda s: (s.day_of_week, s.start_time, s.course_code, s.course_name))

    # 2. HTML Grid veya Liste Tabloları
    soup = BeautifulSoup(html or "", "html.parser")
    for table in soup.find_all("table"):
        thead = table.find("thead")
        first_tr = thead.find("tr") if thead else table.find("tr")
        if first_tr is None:
            continue
        headers = [_clean_text(th.get_text(" ", strip=True)) for th in first_tr.find_all(["th", "td"], recursive=False)]
        if not headers:
            continue

        day_col_map: dict[int, int] = {}
        for idx, h_text in enumerate(headers):
            d_idx = _parse_day_index(h_text)
            if d_idx is not None:
                day_col_map[idx] = d_idx

        tbody = table.find("tbody") or table
        rows = tbody.find_all("tr", recursive=False)

        # 2a. Grid Tablo (En az 3 gün sütunu veya ilk sütunu saat olan >=2 gün sütunu varsa)
        if len(day_col_map) >= 3 or (len(day_col_map) >= 2 and 0 not in day_col_map):
            for row in rows:
                cells = row.find_all(["td", "th"], recursive=False)
                if not cells or cells[0].name == "th" and row == first_tr:
                    continue
                if row == first_tr:
                    continue
                time_txt = _clean_text(cells[0].get_text(" ", strip=True))
                start_t, end_t = _parse_time_range(time_txt)
                if not start_t and all(_parse_day_index(c.get_text(" ", strip=True)) is not None for c in cells[1:4] if len(cells) >= 4):
                    continue
                for col_idx, day_idx in day_col_map.items():
                    if col_idx < len(cells):
                        _add(_parse_grid_cell_slot(cells[col_idx], day_idx, start_t, end_t))
            continue

        # 2b. Liste Tablosu (Gün | Saat | Ders Kodu | Ders Adı | Derslik)
        lower_headers = [_tr_lower(h) for h in headers]
        if any("gün" in h or "gun" in h for h in lower_headers) and any(
            "ders" in h or "saat" in h for h in lower_headers
        ):
            col_map: dict[str, int] = {}
            for idx, title in enumerate(lower_headers):
                if "gün" in title or "gun" in title:
                    col_map.setdefault("day", idx)
                elif "saat" in title or "zaman" in title or "başla" in title:
                    col_map.setdefault("time", idx)
                elif "kod" in title:
                    col_map.setdefault("code", idx)
                elif "derslik" in title or "salon" in title or "sınıf" in title:
                    col_map.setdefault("room", idx)
                elif "öğretim" in title or "ogretim" in title or "hoca" in title:
                    col_map.setdefault("instructor", idx)
                elif "ders" in title:
                    col_map.setdefault("name", idx)

            for row in rows:
                if row == first_tr:
                    continue
                cells = row.find_all("td", recursive=False)
                if len(cells) < 2:
                    continue
                day_idx = _parse_day_index(
                    _clean_text(cells[col_map["day"]].get_text(" ", strip=True))
                ) if "day" in col_map and col_map["day"] < len(cells) else None
                if day_idx is None:
                    continue
                time_raw = _clean_text(cells[col_map["time"]].get_text(" ", strip=True)) if "time" in col_map and col_map["time"] < len(cells) else ""
                start_t, end_t = _parse_time_range(time_raw)
                code = _clean_text(cells[col_map["code"]].get_text(" ", strip=True)) if "code" in col_map and col_map["code"] < len(cells) else ""
                name = _clean_text(cells[col_map["name"]].get_text(" ", strip=True)) if "name" in col_map and col_map["name"] < len(cells) else ""
                room = _clean_text(cells[col_map["room"]].get_text(" ", strip=True)) if "room" in col_map and col_map["room"] < len(cells) else ""
                inst = _clean_text(cells[col_map["instructor"]].get_text(" ", strip=True)) if "instructor" in col_map and col_map["instructor"] < len(cells) else ""
                if not name and not code:
                    continue
                _add(
                    ScheduleSlot(
                        day_of_week=day_idx,
                        day_name=_TR_DAYS[day_idx],
                        start_time=start_t or "00:00",
                        end_time=end_t,
                        course_code=code,
                        course_name=name or code,
                        classroom=room if room not in {"-", ""} else None,
                        instructor=inst if inst not in {"-", ""} else None,
                    )
                )

    return sorted(slots, key=lambda s: (s.day_of_week, s.start_time, s.course_code, s.course_name))


def parse_exam_schedule(
    html: str,
    default_year: Optional[int] = None,
) -> list[ExamScheduleItem]:
    """ÜBYS sınav takvimi sayfasından sınav tarihi, saati ve salon bilgisini ayrıştırır."""
    exams: list[ExamScheduleItem] = []
    seen: set[str] = set()

    def _add(item: Optional[ExamScheduleItem]) -> None:
        if item is None:
            return
        k = item.exam_key()
        if k in seen:
            return
        seen.add(k)
        exams.append(item)

    # 1. Base64 JSON (_jsm / _weeklySchedulle)
    def _walk_jsm(obj: Any) -> None:
        if isinstance(obj, dict):
            raw_date = obj.get("ExamDate") or obj.get("ExamStartDate")
            if not raw_date:
                ev_marker = _tr_lower(f"{obj.get('EventType') or ''} {obj.get('CourseName') or ''}")
                if obj.get("IsExam") or any(k in ev_marker for k in ("sınav", "sinav", "vize", "final", "bütünleme", "butunleme")):
                    raw_date = obj.get("Date") or obj.get("StartDate") or obj.get("EventDate")
            else:
                raw_date = raw_date or obj.get("Date")
            ex_date = _parse_exam_date(raw_date, default_year=default_year)
            c_code, c_name = _split_code_and_name(
                str(obj.get("CourseCode") or ""),
                str(obj.get("CourseName") or ""),
            )
            if ex_date is not None and (c_name or c_code):
                ex_type = _clean_text(
                    str(obj.get("ExamTypeName") or obj.get("ExamName") or obj.get("ExamType") or obj.get("EventType") or "Sınav")
                )
                ex_time = (
                    _norm_time(str(obj.get("ExamTime") or obj.get("StartTime") or obj.get("ExamHour") or raw_date or ""))
                    or _fmt_hour_minute(obj.get("StartHour"), obj.get("StartMinute"))
                    or None
                )
                room = (
                    _clean_text(
                        str(
                            obj.get("WorkCenterName")
                            or obj.get("Classroom")
                            or obj.get("HallName")
                            or obj.get("RoomName")
                            or ""
                        )
                    )
                    or None
                )
                seat = _clean_text(str(obj.get("SeatNo") or obj.get("DeskNo") or obj.get("SiraNo") or "")) or None
                _add(
                    ExamScheduleItem(
                        course_code=c_code,
                        course_name=c_name or c_code,
                        exam_type=ex_type,
                        exam_date=ex_date,
                        exam_time=ex_time,
                        classroom=room,
                        seat=seat,
                    )
                )
            for val in obj.values():
                if isinstance(val, (dict, list)):
                    _walk_jsm(val)
        elif isinstance(obj, list):
            for item in obj:
                _walk_jsm(item)

    for jsm_obj in _extract_jsm_objects(html):
        _walk_jsm(jsm_obj)

    if exams:
        return sorted(exams, key=lambda e: (e.exam_date, e.exam_time or "", e.course_code))

    # 2. HTML Sınav Takvimi Tabloları
    soup = BeautifulSoup(html or "", "html.parser")
    for table in soup.find_all("table"):
        thead = table.find("thead")
        header_row = thead.find("tr") if thead else table.find("tr")
        if header_row is None:
            continue
        headers = [_tr_lower(th.get_text(" ", strip=True)) for th in header_row.find_all(["th", "td"], recursive=False)]
        if not headers or not any("tarih" in h for h in headers):
            continue
        if not any(kw in " ".join(headers) for kw in ("sınav", "sinav", "ders", "salon", "derslik")):
            continue

        col_map: dict[str, int] = {}
        for idx, title in enumerate(headers):
            if "kod" in title:
                col_map.setdefault("code", idx)
            elif "ders" in title and "derslik" not in title:
                col_map.setdefault("name", idx)
            elif "sınav" in title or "sinav" in title or "tür" in title or "tur" in title:
                col_map.setdefault("exam_type", idx)
            elif "tarih" in title:
                col_map.setdefault("date", idx)
            elif "saat" in title:
                col_map.setdefault("time", idx)
            elif "derslik" in title or "salon" in title or "bina" in title or "yer" in title:
                col_map.setdefault("room", idx)
            elif "sıra" in title or "sira" in title or "koltuk" in title:
                col_map.setdefault("seat", idx)

        tbody = table.find("tbody") or table
        for row in tbody.find_all("tr", recursive=False):
            if row == header_row:
                continue
            cells = row.find_all("td", recursive=False)
            if len(cells) < 3 or "date" not in col_map or col_map["date"] >= len(cells):
                continue
            date_raw = _clean_text(cells[col_map["date"]].get_text(" ", strip=True))
            ex_date = _parse_exam_date(date_raw, default_year=default_year)
            if ex_date is None:
                continue
            time_raw = (
                _clean_text(cells[col_map["time"]].get_text(" ", strip=True))
                if "time" in col_map and col_map["time"] < len(cells)
                else date_raw
            )
            ex_time = _norm_time(time_raw) or None
            code = _clean_text(cells[col_map["code"]].get_text(" ", strip=True)) if "code" in col_map and col_map["code"] < len(cells) else ""
            name = _clean_text(cells[col_map["name"]].get_text(" ", strip=True)) if "name" in col_map and col_map["name"] < len(cells) else ""
            ex_type = _clean_text(cells[col_map["exam_type"]].get_text(" ", strip=True)) if "exam_type" in col_map and col_map["exam_type"] < len(cells) else "Sınav"
            room = _clean_text(cells[col_map["room"]].get_text(" ", strip=True)) if "room" in col_map and col_map["room"] < len(cells) else ""
            seat = _clean_text(cells[col_map["seat"]].get_text(" ", strip=True)) if "seat" in col_map and col_map["seat"] < len(cells) else ""
            if not (code or name):
                continue
            _add(
                ExamScheduleItem(
                    course_code=code,
                    course_name=name or code,
                    exam_type=ex_type or "Sınav",
                    exam_date=ex_date,
                    exam_time=ex_time,
                    classroom=room if room not in {"-", ""} else None,
                    seat=seat if seat not in {"-", ""} else None,
                )
            )

    return sorted(exams, key=lambda e: (e.exam_date, e.exam_time or "", e.course_code))


def get_slots_for_day(slots: list[ScheduleSlot], target_date: date) -> list[ScheduleSlot]:
    """Verilen tarihin haftanın gününe ait dersleri saate göre sıralı döndürür."""
    weekday = target_date.weekday()
    return sorted(
        [s for s in slots if s.day_of_week == weekday],
        key=lambda s: (s.start_time, s.course_code, s.course_name),
    )


def exam_reminder_key(item: ExamScheduleItem, days_until: int) -> str:
    return f"{item.exam_key()}::d{days_until}"


def find_exam_reminders(
    exams: list[ExamScheduleItem],
    today: date,
    reminder_days: list[int],
    sent_keys: dict[str, str],
) -> list[tuple[ExamScheduleItem, int]]:
    """Hatırlatma eşik günlerine giren ve daha önce gönderilmemiş sınavları döndürür."""
    thresholds = set(reminder_days)
    reminders: list[tuple[ExamScheduleItem, int]] = []
    for item in exams:
        days_until = (item.exam_date - today).days
        if days_until not in thresholds:
            continue
        if exam_reminder_key(item, days_until) in sent_keys:
            continue
        reminders.append((item, days_until))
    reminders.sort(key=lambda pair: (pair[1], pair[0].exam_date, pair[0].exam_time or ""))
    return reminders
