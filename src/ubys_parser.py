"""Kastamonu Üniversitesi ÜBYS HTML ayrıştırma (parser) modülü."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from .models import (
    CourseGrade,
    ExamGrade,
    TranscriptCourse,
    TranscriptSemester,
    TranscriptSummary,
)


class UBYSError(Exception):
    """ÜBYS işlemlerinde oluşan temel hata sınıfı."""


class SessionExpiredError(UBYSError):
    """Oturum süresi dolduğunda veya giriş sayfasına düşüldüğünde fırlatılır."""


class ParseError(UBYSError):
    """Beklenen HTML veya veri yapısı bulunamadığında fırlatılır."""


_EMPTY_MARKERS = {
    "",
    "-",
    "--",
    "---",
    "girmedi",
    "girilmedi",
    "aciklanmadi",
    "açıklanmadı",
    "belirlenmedi",
    "netlesmemis",
    "netleşmemiş",
    "durumu netlesmemis",
    "durumu netleşmemiş",
    "n/a",
    "yok",
    "bekleniyor",
}

_EXAM_INLINE_PATTERN = re.compile(
    r"\b("
    r"Ara\s*Sınav(?:\s*\d+)?|"
    r"Vize(?:\s*\d+)?|"
    r"Yarıyıl\s*Sonu(?:\s*\d+)?|"
    r"Final(?:\s*\d+)?|"
    r"Bütünleme(?:\s*\d+)?|"
    r"Kısa\s*Sınav(?:\s*\d+)?|"
    r"Quiz(?:\s*\d+)?|"
    r"Ödev(?:\s*\d+)?|"
    r"Lab(?:oratuvar)?(?:\s*\d+)?|"
    r"Proje(?:\s*\d+)?|"
    r"Uygulama(?:\s*\d+)?|"
    r"Mazeret(?:\s*\d+)?|"
    r"Telafi(?:\s*\d+)?"
    r")\s*[:\-]\s*([^\s|,;/()]+)",
    re.IGNORECASE,
)

_CLASS_ID_PATTERN = re.compile(r"classId=([^&'\"\s)]+)", re.IGNORECASE)
_LETTER_GRADE_PATTERN = re.compile(
    r"\b(AA|BA|BB|CB|CC|DC|DD|FD|FF|YT|YZ|DZ|GR|M|G)\b"
)


def _clean_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return " ".join(raw.split())


def _tr_lower(text: str) -> str:
    """Türkçe büyük/küçük harf dönüşümünü güvenli şekilde yapar."""
    replaced = text.replace("İ", "i").replace("I", "ı")
    lowered = replaced.lower().replace("\u0307", "")
    return " ".join(lowered.split())


def normalize_score(raw: Optional[str]) -> Optional[str]:
    """Sınav/geçme notu metnini karşılaştırılabilir standart biçime çevirir."""
    cleaned = _clean_text(raw)
    if _tr_lower(cleaned) in _EMPTY_MARKERS:
        return None

    numeric_match = re.match(r"^[+-]?\d+(?:[.,]\d+)?$", cleaned)
    if numeric_match:
        num = cleaned.lstrip("+").replace(",", ".")
        if "." in num:
            num = num.rstrip("0").rstrip(".")
        if num in {"", "-0"}:
            num = "0"
        return num

    return cleaned


def normalize_letter_grade(raw: Optional[str]) -> Optional[str]:
    """Harf notu değerini temizler; henüz netleşmemişse None döner."""
    cleaned = _clean_text(raw)
    lowered = _tr_lower(cleaned)
    if lowered in _EMPTY_MARKERS or "netleşmemiş" in lowered or "netlesmemis" in lowered:
        return None
    if len(cleaned) <= 4 and cleaned.isascii():
        return cleaned.upper()
    return cleaned


def normalize_status(raw: Optional[str]) -> Optional[str]:
    """Başarı durumu değerini temizler; henüz netleşmemişse None döner."""
    cleaned = _clean_text(raw)
    lowered = _tr_lower(cleaned)
    if lowered in _EMPTY_MARKERS or "netleşmemiş" in lowered or "netlesmemis" in lowered:
        return None
    return cleaned


def _normalize_optional_text(raw: Optional[str]) -> Optional[str]:
    cleaned = _clean_text(raw)
    if _tr_lower(cleaned) in {"", "-", "--", "---", "n/a"}:
        return None
    return cleaned


def is_login_page(html: str, url: str = "") -> bool:
    """Yanıtın oturumun düştüğü giriş sayfası olup olmadığını kontrol eder."""
    if "account/login" in url.lower():
        return True
    soup = BeautifulSoup(html, "html.parser")
    login_form = soup.find("form", id="loginForm")
    username_input = soup.find("input", attrs={"name": "username"})
    return login_form is not None and username_input is not None


def has_active_captcha(html: str) -> bool:
    """ÜBYS giriş sayfasında aktif reCAPTCHA olup olmadığını kontrol eder."""
    match = re.search(
        r"""_verifiedreCaptcha\s*=\s*JSON\.parse\(\s*Base64\.decode\(\s*["']([^"']+)["']\s*\)\s*\)""",
        html,
    )
    if match:
        try:
            decoded = base64.b64decode(match.group(1)).decode("utf-8")
            return json.loads(decoded) is True
        except Exception:
            return False

    literal_match = re.search(r"_verifiedreCaptcha\s*=\s*(true|false)\b", html, re.IGNORECASE)
    if literal_match:
        return literal_match.group(1).lower() == "true"

    return False


def extract_login_csrf_token(html: str) -> str:
    """Giriş formu (#loginForm) içinden __RequestVerificationToken değerini çıkarır."""
    soup = BeautifulSoup(html, "html.parser")
    login_form = soup.find("form", id="loginForm")
    if login_form:
        token_input = login_form.find("input", attrs={"name": "__RequestVerificationToken"})
        if token_input and token_input.get("value"):
            return str(token_input["value"])

    any_token = soup.find("input", attrs={"name": "__RequestVerificationToken"})
    if any_token and any_token.get("value"):
        return str(any_token["value"])

    raise ParseError("Giriş sayfasında __RequestVerificationToken (CSRF) bulunamadı.")


def extract_ajax_csrf_token(html: str) -> Optional[str]:
    """AJAX istekleri için #__AjaxAntiForgeryForm içindeki CSRF token'ını çıkarır."""
    soup = BeautifulSoup(html, "html.parser")
    ajax_form = soup.find("form", id="__AjaxAntiForgeryForm")
    if ajax_form:
        token_input = ajax_form.find("input", attrs={"name": "__RequestVerificationToken"})
        if token_input and token_input.get("value"):
            return str(token_input["value"])

    try:
        return extract_login_csrf_token(html)
    except ParseError:
        return None


def parse_sap_id(home_html: str) -> Optional[str]:
    """Öğrenci ana sayfasından (/AIS/Student/Home/Index) sapId değerini bulur."""
    match = re.search(r"""selectAcademicProgram\(\s*['"]([^'"]+)['"]\s*\)""", home_html)
    if match:
        return match.group(1).strip()

    soup = BeautifulSoup(home_html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if "/AIS/Student/Class/Index" in href or "sapid=" in href.lower():
            sap_match = re.search(r"[?&]sapid=([^&'\"\s]+)", href, re.IGNORECASE)
            if sap_match:
                return unquote(sap_match.group(1).strip())

    generic_match = re.search(r"[?&]sapid=([^&'\"\s]+)", home_html, re.IGNORECASE)
    if generic_match:
        return unquote(generic_match.group(1).strip())

    return None


def _extract_class_id_from_cells(cells: list[Tag], preferred_indices: list[int]) -> Optional[str]:
    seen: set[int] = set()
    ordered_indices = [idx for idx in preferred_indices if 0 <= idx < len(cells)]
    ordered_indices.extend(idx for idx in range(len(cells)) if idx not in ordered_indices)

    for idx in ordered_indices:
        if idx in seen:
            continue
        seen.add(idx)
        cell = cells[idx]
        for tag in cell.find_all(["a", "button", "tr", "span"]):
            for attr in ("href", "onclick", "data-url"):
                val = tag.get(attr)
                if not val:
                    continue
                match = _CLASS_ID_PATTERN.search(str(val))
                if match:
                    return unquote(match.group(1))
    return None


def _find_header_row(table: Tag) -> Optional[Tag]:
    thead = table.find("thead")
    if thead:
        row = thead.find("tr")
        if row:
            return row
    first_row = table.find("tr")
    if first_row and first_row.find("th"):
        return first_row
    return None


def _map_grade_table_columns(table: Tag) -> dict[str, int]:
    """Tablo başlıklarından sütun indekslerini dinamik olarak eşler."""
    defaults = {
        "code": 0,
        "name": 1,
        "credit": 2,
        "passing_grade": 6,
        "letter_grade": 7,
        "status": 8,
    }
    header_row = _find_header_row(table)
    if header_row is None:
        return defaults

    headers = [_tr_lower(th.get_text(" ", strip=True)) for th in header_row.find_all(["th", "td"], recursive=False)]
    if not headers:
        return defaults

    mapped: dict[str, int] = {}
    for idx, title in enumerate(headers):
        compact = title.replace(" ", "")
        if "ders kodu" in title or title == "kodu" or title == "kod":
            mapped.setdefault("code", idx)
        elif "ders adı" in title or "dersin adı" in title or title == "ders":
            mapped.setdefault("name", idx)
        elif "t+u" in compact or "t/u" in compact or "ders saati" in title or title == "saat":
            mapped.setdefault("tu_hours", idx)
        elif title == "t" or "teorik" in title:
            mapped.setdefault("theory", idx)
        elif title == "u" or "uygulama" in title or "lab" in title:
            mapped.setdefault("practice", idx)
        elif "kredi" in title or "ul. kr" in title:
            mapped.setdefault("credit", idx)
        elif "devam durumu" in title:
            mapped.setdefault("attendance_status", idx)
        elif "devamsızlık" in title or "devamsizlik" in title:
            mapped.setdefault("absence", idx)
        elif "geçme" in title or "başarı notu" in title:
            mapped.setdefault("passing_grade", idx)
        elif "hbn" in title or "harf" in title:
            mapped.setdefault("letter_grade", idx)
        elif "durum" in title:
            mapped.setdefault("status", idx)

    return {**defaults, **mapped}


def _parse_inline_exam_row(exam_row: Tag) -> list[ExamGrade]:
    """Ana ders satırının hemen altındaki satırdan özet sınav notlarını ayrıştırır."""
    exams: list[ExamGrade] = []
    seen: set[str] = set()
    non_blank_empty_markers = _EMPTY_MARKERS - {""}

    def _add_exam(raw_label: str, raw_val: str, exam_type_override: Optional[str] = None) -> None:
        label = _clean_text(raw_label).rstrip(" :-").strip()
        norm_key = _tr_lower(label)
        if not norm_key or norm_key in seen:
            return
        score = normalize_score(raw_val)
        if score is None and _tr_lower(_clean_text(raw_val)) not in non_blank_empty_markers:
            return
        seen.add(norm_key)
        exam_type = _clean_text(exam_type_override).rstrip(" :-").strip() if exam_type_override else label
        exams.append(ExamGrade(exam_type=exam_type, name=label, score=score))

    # İç içe tablo varsa önce yapılandırılmış satırları dene
    for nested_table in exam_row.find_all("table"):
        thead = nested_table.find("thead")
        tbody = nested_table.find("tbody")
        if thead and tbody:
            headers = [_clean_text(c.get_text(" ", strip=True)) for c in thead.find_all(["th", "td"])]
            first_body_row = tbody.find("tr")
            if headers and first_body_row:
                values = [_clean_text(c.get_text(" ", strip=True)) for c in first_body_row.find_all(["td", "th"])]
                if len(headers) == len(values) and not any(
                    _tr_lower(h) in {"sınav adı", "sınav tipi", "sınav notu"} for h in headers
                ):
                    for label, raw_val in zip(headers, values):
                        _add_exam(label, raw_val)
                    continue

        nested_rows = nested_table.find_all("tr")
        for n_row in nested_rows:
            n_cells = [_clean_text(c.get_text(" ", strip=True)) for c in n_row.find_all(["td", "th"], recursive=False)]
            if len(n_cells) >= 2 and not any(_tr_lower(c) in {"sınav adı", "sınav tipi"} for c in n_cells):
                label = n_cells[0]
                if re.match(r"^[+-]?\d+(?:[.,]\d+)?$", label):
                    continue
                _add_exam(label, n_cells[-1])

    # Metin bazlı kalıpları tara (örn. "Vize: 75", "Final: 80")
    segments: list[str] = []
    for cell in exam_row.find_all("td", recursive=False):
        text = _clean_text(cell.get_text(" ", strip=True))
        if text:
            segments.append(text)
    if not segments:
        full_text = _clean_text(exam_row.get_text(" ", strip=True))
        if full_text:
            segments.append(full_text)

    for segment in segments:
        for match in _EXAM_INLINE_PATTERN.finditer(segment):
            exam_name = _clean_text(match.group(1))
            exam_type = exam_name.split()[0] if exam_name else exam_name
            _add_exam(exam_name, match.group(2), exam_type_override=exam_type)

    return exams


def _cell_text(cells: list[Tag], index: int) -> str:
    if 0 <= index < len(cells):
        return _clean_text(cells[index].get_text(" ", strip=True))
    return ""


def _parse_float_value(raw: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[.,]\d+)?)", raw or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_tu_hours(raw: str) -> tuple[Optional[float], Optional[float]]:
    match = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*[+/]\s*(\d+(?:[.,]\d+)?)\s*$", raw or "")
    if not match:
        return None, None
    try:
        return float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", "."))
    except ValueError:
        return None, None


def _parse_absence_text(raw: str) -> dict[str, Optional[float]]:
    result: dict[str, Optional[float]] = {
        "absent_theoretical_hours": None,
        "absent_practical_hours": None,
        "absent_total_hours": None,
        "absent_percent": None,
    }
    cleaned = _clean_text(raw)
    if not cleaned or _tr_lower(cleaned) in _EMPTY_MARKERS:
        return result

    pct_match = re.search(r"(?:%\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*%)", cleaned)
    if pct_match:
        pct_str = pct_match.group(1) or pct_match.group(2)
        try:
            result["absent_percent"] = float(pct_str.replace(",", "."))
        except ValueError:
            pass

    t_match = re.search(r"\bT(?:eorik)?\s*[:\-]\s*(\d+(?:[.,]\d+)?)", cleaned, re.IGNORECASE)
    u_match = re.search(r"\bU(?:ygulama)?\s*[:\-]\s*(\d+(?:[.,]\d+)?)", cleaned, re.IGNORECASE)
    if t_match:
        result["absent_theoretical_hours"] = float(t_match.group(1).replace(",", "."))
    if u_match:
        result["absent_practical_hours"] = float(u_match.group(1).replace(",", "."))

    if not t_match and not u_match:
        without_pct = re.sub(r"(?:%\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*%)", "", cleaned)
        hour_match = re.search(r"(\d+(?:[.,]\d+)?)", without_pct)
        if hour_match:
            result["absent_total_hours"] = float(hour_match.group(1).replace(",", "."))

    return result


def _parse_course_from_cells(
    cells: list[Tag],
    semester_name: str,
    col_map: dict[str, int],
) -> CourseGrade:
    code = _cell_text(cells, col_map["code"])
    name = _cell_text(cells, col_map["name"])
    credit = _normalize_optional_text(_cell_text(cells, col_map["credit"]))
    passing_grade = normalize_score(_cell_text(cells, col_map["passing_grade"]))
    letter_grade = normalize_letter_grade(_cell_text(cells, col_map["letter_grade"]))
    status = normalize_status(_cell_text(cells, col_map["status"]))
    class_id = _extract_class_id_from_cells(cells, [col_map["code"], col_map["name"]])

    theory_hours: Optional[float] = None
    practice_hours: Optional[float] = None
    if "tu_hours" in col_map:
        theory_hours, practice_hours = _parse_tu_hours(_cell_text(cells, col_map["tu_hours"]))
    if "theory" in col_map and theory_hours is None:
        theory_hours = _parse_float_value(_cell_text(cells, col_map["theory"]))
    if "practice" in col_map and practice_hours is None:
        practice_hours = _parse_float_value(_cell_text(cells, col_map["practice"]))

    absence_data = (
        _parse_absence_text(_cell_text(cells, col_map["absence"]))
        if "absence" in col_map
        else {}
    )
    att_status: Optional[str] = None
    if "attendance_status" in col_map:
        att_status = _normalize_optional_text(_cell_text(cells, col_map["attendance_status"]))
    if att_status is None and status:
        low_status = _tr_lower(status)
        if "devam" in low_status or "muaf" in low_status:
            att_status = status

    return CourseGrade(
        semester=semester_name,
        code=code,
        name=name,
        credit=credit,
        passing_grade=passing_grade,
        letter_grade=letter_grade,
        status=status,
        class_id=class_id,
        theoretical_hours=theory_hours,
        practical_hours=practice_hours,
        absent_theoretical_hours=absence_data.get("absent_theoretical_hours"),
        absent_practical_hours=absence_data.get("absent_practical_hours"),
        absent_total_hours=absence_data.get("absent_total_hours"),
        absent_percent=absence_data.get("absent_percent"),
        attendance_status=att_status,
    )


def _iter_panel_tables(html: str) -> list[tuple[str, Tag]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, Tag]] = []

    panels = soup.find_all("div", class_="panel-default")
    for panel in panels:
        heading = panel.find("div", class_="panel-heading")
        semester_name = _clean_text(heading.get_text(" ", strip=True)) if heading else "Güncel Dönem"
        for table in panel.find_all("table"):
            results.append((semester_name, table))

    if results:
        return results

    # Fallback: panel-default olmayan sayfa düzeni için başlığında Ders Kodu/Adı geçen tabloları bul
    for table in soup.find_all("table"):
        thead = table.find("thead")
        header_text = _tr_lower(thead.get_text(" ", strip=True)) if thead else ""
        if "ders kodu" in header_text or "ders adı" in header_text:
            results.append(("Güncel Dönem", table))

    return results


def parse_grades_index(html: str) -> list[CourseGrade]:
    """/AIS/Student/Class/Index HTML sayfasından dönem ve ders notlarını ayrıştırır."""
    if is_login_page(html):
        raise SessionExpiredError("Oturum süresi doldu veya giriş sayfasına yönlendirildi.")

    courses: list[CourseGrade] = []
    for semester_name, table in _iter_panel_tables(html):
        col_map = _map_grade_table_columns(table)
        tbody = table.find("tbody")
        rows = tbody.find_all("tr", recursive=False) if tbody else table.find_all("tr", recursive=False)

        idx = 0
        while idx < len(rows):
            row = rows[idx]
            cells = row.find_all("td", recursive=False)
            if not cells:
                idx += 1
                continue

            has_rowspan_2 = any(str(c.get("rowspan") or "") == "2" for c in cells)
            if has_rowspan_2:
                course = _parse_course_from_cells(cells, semester_name, col_map)
                if idx + 1 < len(rows):
                    next_row = rows[idx + 1]
                    next_cells = next_row.find_all("td", recursive=False)
                    is_next_main = any(str(c.get("rowspan") or "") == "2" for c in next_cells)
                    if not is_next_main:
                        course.exams = _parse_inline_exam_row(next_row)
                        idx += 1
                if course.code or course.name:
                    courses.append(course)
            elif len(cells) >= 4 and not cells[0].has_attr("colspan"):
                course = _parse_course_from_cells(cells, semester_name, col_map)
                if course.code or course.name:
                    courses.append(course)

            idx += 1

    return courses


def _map_detail_exam_columns(table: Tag) -> dict[str, int]:
    defaults = {
        "exam_type": 0,
        "exam_name": 1,
        "date": 2,
        "score": 3,
        "ranking": 5,
        "average": 6,
    }
    header_row = _find_header_row(table)
    if header_row is None:
        return defaults

    headers = [_tr_lower(th.get_text(" ", strip=True)) for th in header_row.find_all(["th", "td"], recursive=False)]
    if not headers:
        return defaults

    mapped: dict[str, int] = {}
    for idx, title in enumerate(headers):
        if "sınav tipi" in title or title == "tip":
            mapped.setdefault("exam_type", idx)
        elif "sınav adı" in title or title == "sınav":
            mapped.setdefault("exam_name", idx)
        elif "tarih" in title:
            mapped.setdefault("date", idx)
        elif "sınav notu" in title or title == "not" or "puan" in title:
            mapped.setdefault("score", idx)
        elif (
            "etki" in title
            or "ağırlık" in title
            or "agirlik" in title
            or "oran" in title
            or "katkı" in title
            or "katki" in title
            or "yüzde" in title
            or "yuzde" in title
            or "%" in title
        ):
            mapped.setdefault("weight", idx)
        elif "sıralama" in title:
            mapped.setdefault("ranking", idx)
        elif "ortalama" in title:
            mapped.setdefault("average", idx)

    return {**defaults, **mapped}


def _parse_weight_value(raw: str) -> Optional[float]:
    val = _parse_float_value(raw)
    if val is None or val <= 0:
        return None
    if val > 1.0:
        val = val / 100.0
    if val <= 0.0 or val > 1.0:
        return None
    return round(val, 4)


def _extract_attendance_from_soup(soup: BeautifulSoup) -> dict[str, Any]:
    """HTML içindeki tablo ve etiketlerden ders saati ve devamsızlık bilgisini çıkarır."""
    info: dict[str, Any] = {}

    pairs: list[tuple[str, str]] = []
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            pairs.append((_clean_text(cells[0].get_text(" ", strip=True)), _clean_text(cells[1].get_text(" ", strip=True))))
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            pairs.append((_clean_text(dt.get_text(" ", strip=True)), _clean_text(dd.get_text(" ", strip=True))))

    for raw_label, raw_val in pairs:
        label = _tr_lower(raw_label)
        if not raw_val or _tr_lower(raw_val) in _EMPTY_MARKERS:
            continue
        if ("t+u" in label.replace(" ", "") or "t/u" in label.replace(" ", "")) and "theoretical_hours" not in info:
            t_h, u_h = _parse_tu_hours(raw_val)
            if t_h is not None:
                info["theoretical_hours"] = t_h
            if u_h is not None:
                info["practical_hours"] = u_h
        elif ("teorik" in label and "saat" in label) and "theoretical_hours" not in info:
            val = _parse_float_value(raw_val)
            if val is not None:
                info["theoretical_hours"] = val
        elif ("uygulama" in label and "saat" in label) and "practical_hours" not in info:
            val = _parse_float_value(raw_val)
            if val is not None:
                info["practical_hours"] = val
        elif "teorik" in label and ("devams" in label or "yoklama" in label):
            parsed = _parse_absence_text(raw_val)
            if parsed["absent_total_hours"] is not None:
                info["absent_theoretical_hours"] = parsed["absent_total_hours"]
            if parsed["absent_percent"] is not None and "absent_percent" not in info:
                info["absent_percent"] = parsed["absent_percent"]
        elif ("uygulama" in label or "lab" in label) and ("devams" in label or "yoklama" in label):
            parsed = _parse_absence_text(raw_val)
            if parsed["absent_total_hours"] is not None:
                info["absent_practical_hours"] = parsed["absent_total_hours"]
            if parsed["absent_percent"] is not None and "absent_percent" not in info:
                info["absent_percent"] = parsed["absent_percent"]
        elif "devam durumu" in label:
            info.setdefault("attendance_status", raw_val)
        elif "devamsızlık" in label or "devamsizlik" in label:
            parsed = _parse_absence_text(raw_val)
            for k, v in parsed.items():
                if v is not None and k not in info:
                    info[k] = v

    return info


def _find_attendance_partial_url(soup: BeautifulSoup) -> Optional[str]:
    for tag in soup.find_all(["a", "button", "li"]):
        text = _tr_lower(tag.get_text(" ", strip=True))
        if not any(kw in text for kw in ("devamsız", "devamsiz", "yoklama", "devam durum")):
            continue
        for attr in ("data-url", "href", "onclick"):
            val = str(tag.get(attr) or "").strip()
            if not val or val == "#" or val.startswith("javascript:void"):
                continue
            if attr == "onclick":
                m = re.search(r"""['"]([^'"]*(?:ClassDetail|Attendance|RollCall|Devamsiz|Yoklama)[^'"]*)['"]""", val, re.IGNORECASE)
                if m:
                    return m.group(1)
            else:
                return val
    return None


def _find_exam_table(container: Tag) -> Optional[Tag]:
    for table in container.find_all("table"):
        header_row = _find_header_row(table)
        if header_row is None:
            continue
        header_text = _tr_lower(header_row.get_text(" ", strip=True))
        if "sınav tipi" in header_text or "sınav notu" in header_text or "sınav adı" in header_text:
            return table
    return None


def parse_class_detail(html: str) -> dict[str, Any]:
    """/AIS/Student/Class/ClassDetail HTML sayfasından sınav ve ortalama detaylarını ayrıştırır."""
    if is_login_page(html):
        raise SessionExpiredError("Detay sayfası alınırken oturum süresi doldu.")

    soup = BeautifulSoup(html, "html.parser")
    letter_grade: Optional[str] = None
    instructor: Optional[str] = None
    class_average: Optional[str] = None
    exams: list[ExamGrade] = []

    # 1. Başarı durumu / harf notu
    status_elem = soup.find("div", class_="success-status")
    if status_elem:
        status_text = _clean_text(status_elem.get_text(" ", strip=True))
        letter_match = _LETTER_GRADE_PATTERN.search(status_text)
        if letter_match:
            letter_grade = letter_match.group(1)
        else:
            letter_grade = normalize_letter_grade(status_text)

    # 2. Sınav tablosu
    tab_pane = soup.select_one("div.tab-pane.active") or soup
    exam_table = (
        _find_exam_table(tab_pane)
        or _find_exam_table(soup)
        or tab_pane.select_one(".table-responsive table")
    )

    if exam_table is not None:
        col_map = _map_detail_exam_columns(exam_table)
        tbody = exam_table.find("tbody")
        rows = tbody.find_all("tr", recursive=False) if tbody else exam_table.find_all("tr", recursive=False)
        for row in rows:
            cells = row.find_all("td", recursive=False)
            if len(cells) < 4:
                continue
            row_lower = _tr_lower(row.get_text(" ", strip=True))
            if "kayıt bulunamadı" in row_lower or "sınav bulunamadı" in row_lower:
                continue

            exam_type = _cell_text(cells, col_map["exam_type"])
            exam_name = _cell_text(cells, col_map["exam_name"]) or exam_type
            announcement_date = _normalize_optional_text(_cell_text(cells, col_map["date"]))
            score = normalize_score(_cell_text(cells, col_map["score"]))
            ranking = _normalize_optional_text(_cell_text(cells, col_map["ranking"]))
            exam_avg = normalize_score(_cell_text(cells, col_map["average"]))

            weight: Optional[float] = None
            if "weight" in col_map:
                weight = _parse_weight_value(_cell_text(cells, col_map["weight"]))
            if weight is None:
                inline_w = re.search(r"(?:%\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*%)", f"{exam_type} {exam_name}")
                if inline_w:
                    weight = _parse_weight_value(inline_w.group(1) or inline_w.group(2))

            if exam_type or exam_name:
                exams.append(
                    ExamGrade(
                        exam_type=exam_type,
                        name=exam_name,
                        score=score,
                        announcement_date=announcement_date,
                        class_average=exam_avg,
                        ranking=ranking,
                        weight=weight,
                    )
                )

    # 3. Öğretim elemanı ve sınıf ortalaması (ÜBYS CSS sınıfı gerçekte 'avarage' yazım hatası içerir)
    instructor_div = soup.find("div", class_="instructor")
    if instructor_div:
        name_div = instructor_div.find("div", class_="name")
        if name_div:
            name_link = name_div.find("a")
            raw_name = name_link.get_text(" ", strip=True) if name_link else name_div.get_text(" ", strip=True)
            instructor = _normalize_optional_text(raw_name)

        avg_div = instructor_div.find("div", class_="avarage") or instructor_div.find("div", class_="average")
        if avg_div:
            avg_text = _clean_text(avg_div.get_text(" ", strip=True))
            avg_match = re.search(r"Ortalamas[ıi]\s*:\s*([\d,]+(?:\.\d+)?)", avg_text, re.IGNORECASE)
            if avg_match:
                class_average = normalize_score(avg_match.group(1))

    attendance_info = _extract_attendance_from_soup(soup)
    attendance_partial_url = _find_attendance_partial_url(soup)

    return {
        "exams": exams,
        "letter_grade": letter_grade,
        "instructor": instructor,
        "class_average": class_average,
        "attendance": attendance_info,
        "attendance_partial_url": attendance_partial_url,
    }


def parse_attendance_partial(html: str) -> dict[str, Any]:
    """ClassDetail içindeki devamsızlık / yoklama sekmesi (partial HTML) verisini ayrıştırır."""
    if is_login_page(html):
        raise SessionExpiredError("Devamsızlık detayı alınırken oturum süresi doldu.")

    soup = BeautifulSoup(html, "html.parser")
    info = _extract_attendance_from_soup(soup)

    if info.get("absent_total_hours") is None and info.get("absent_theoretical_hours") is None:
        # Satır bazlı yoklama tablosundan "Katılmadı / Gelmedi / Yok" kayıtlarını say
        for table in soup.find_all("table"):
            header_row = _find_header_row(table)
            header_text = _tr_lower(header_row.get_text(" ", strip=True)) if header_row else ""
            if not any(kw in header_text for kw in ("durum", "katılım", "yoklama", "tarih")):
                continue
            tbody = table.find("tbody") or table
            absent_count = 0.0
            found_status_rows = False
            for row in tbody.find_all("tr", recursive=False):
                row_text = _tr_lower(row.get_text(" ", strip=True))
                if any(kw in row_text for kw in ("katıldı", "geldi", "var", "katılmadı", "gelmedi", "yok")):
                    found_status_rows = True
                if any(kw in row_text for kw in ("katılmadı", "katilmadi", "gelmedi", "devamsız")):
                    absent_count += 1.0
            if found_status_rows:
                info["absent_total_hours"] = absent_count
                break

    return info


def parse_student_info_json(home_html: str) -> Optional[dict[str, Any]]:
    """/AIS/Student/Home/Index sayfasındaki Base64 kodlu StudentInfo JSON nesnesini çözer."""
    match = re.search(
        r"""StudentInfo\s*=\s*JSON\.parse\(\s*Base64\.decode\(\s*["']([^"']+)["']\s*\)\s*\)""",
        home_html,
    )
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group(1)).decode("utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _collect_program_strings_from_obj(obj: Any, hints: list[str]) -> None:
    target_keys = {
        "FullAcademicProgramName",
        "AcademicProgramName",
        "ProgramName",
        "DepartmentName",
        "UnitName",
        "FacultyName",
        "AcademicProgramId",
    }
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in target_keys and val is not None:
                text = _clean_text(str(val))
                if text and len(text) <= 200:
                    hints.append(text)
            elif isinstance(val, (dict, list)):
                _collect_program_strings_from_obj(val, hints)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _collect_program_strings_from_obj(item, hints)


def parse_student_program_hints(html: str) -> list[str]:
    """Öğrenci ana veya ders sayfasından fakülte/MYO/bölüm/program ipuçlarını çıkarır."""
    raw_hints: list[str] = []

    info = parse_student_info_json(html)
    if info:
        _collect_program_strings_from_obj(info, raw_hints)

    for jsm_match in re.finditer(
        r"""Base64\.decode\(\s*["']([^"']+)["']\s*\)""",
        html or "",
    ):
        try:
            decoded = base64.b64decode(jsm_match.group(1)).decode("utf-8")
            parsed = json.loads(decoded)
            if isinstance(parsed, (dict, list)):
                _collect_program_strings_from_obj(parsed, raw_hints)
        except Exception:
            continue

    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup.find_all(["a", "button", "li", "div", "tr"]):
        onclick = str(tag.get("onclick") or "")
        if "selectAcademicProgram" in onclick:
            text = _clean_text(tag.get_text(" ", strip=True))
            if text and len(text) <= 180:
                raw_hints.append(text)
            parent = tag.parent
            if parent is not None:
                parent_text = _clean_text(parent.get_text(" ", strip=True))
                if parent_text and len(parent_text) <= 180:
                    raw_hints.append(parent_text)

    label_pairs: list[tuple[str, str]] = []
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            label_pairs.append(
                (_clean_text(cells[0].get_text(" ", strip=True)), _clean_text(cells[1].get_text(" ", strip=True)))
            )
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            label_pairs.append(
                (_clean_text(dt.get_text(" ", strip=True)), _clean_text(dd.get_text(" ", strip=True)))
            )

    for raw_label, raw_val in label_pairs:
        low_label = _tr_lower(raw_label)
        if not raw_val or len(raw_val) > 200 or _tr_lower(raw_val) in _EMPTY_MARKERS:
            continue
        if "ders programı" in low_label or "ders programi" in low_label:
            continue
        if any(
            kw in low_label
            for kw in ("fakülte", "fakulte", "yüksekokul", "yuksekokul", "enstitü", "enstitu", "bölüm", "bolum", "program", "birim")
        ):
            raw_hints.append(raw_val)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in raw_hints:
        cleaned = _clean_text(item)
        if not cleaned or len(cleaned) > 200 or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def parse_student_gano(home_html: str) -> Optional[float]:
    """Öğrenci ana sayfasından birikimli GANO değerini çıkarır."""
    info = parse_student_info_json(home_html)
    if not info:
        return None
    for program in info.get("Programs") or []:
        if isinstance(program, dict) and program.get("GANO") is not None:
            try:
                return round(float(str(program["GANO"]).replace(",", ".")), 4)
            except ValueError:
                continue
    return None


def parse_transcript_url(home_html: str) -> Optional[str]:
    """Öğrenci ana sayfasından Transkript bağlantısını bulur."""
    soup = BeautifulSoup(home_html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        low = href.lower()
        if "/ais/student/transcript" in low or "/ais/student/transkript" in low:
            return href
    return None


def _opt_float_tr(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).strip().replace(",", "."))
    except ValueError:
        return None


def parse_transcript(html: str) -> TranscriptSummary:
    """ÜBYS transkript sayfasından (_jsm Base64 JSON veya HTML tablo fallback) özet çıkarır."""
    if is_login_page(html):
        raise SessionExpiredError("Transkript alınırken oturum süresi doldu.")

    # 1. Öncelik: ÜBYS _jsm = JSON.parse(Base64.decode("..."))
    jsm_match = re.search(
        r"""_jsm\s*=\s*JSON\.parse\(\s*Base64\.decode\(\s*["']([^"']+)["']\s*\)\s*\)""",
        html,
    )
    if jsm_match:
        try:
            decoded = base64.b64decode(jsm_match.group(1)).decode("utf-8")
            data = json.loads(decoded)
            transcripts = data.get("Transcripts") or []
            if transcripts and isinstance(transcripts[0], dict):
                t = transcripts[0]
                semesters: list[TranscriptSemester] = []
                last_cum_gpa: Optional[float] = None

                for sem_raw in t.get("Semesters") or []:
                    if not isinstance(sem_raw, dict):
                        continue
                    sem_name = _clean_text(str(sem_raw.get("SemesterName") or ""))
                    sem_gpa = _opt_float_tr(sem_raw.get("SemesterAverage"))
                    cum_gpa = _opt_float_tr(
                        sem_raw.get("CumulativeAverage")
                        or sem_raw.get("GeneralAverage")
                        or sem_raw.get("GANO")
                    )
                    if cum_gpa is not None:
                        last_cum_gpa = cum_gpa

                    courses: list[TranscriptCourse] = []
                    for c_raw in sem_raw.get("Courses") or []:
                        if not isinstance(c_raw, dict):
                            continue
                        code = _clean_text(str(c_raw.get("CourseCode") or ""))
                        name = _clean_text(str(c_raw.get("CourseName") or ""))
                        if not (code or name):
                            continue
                        courses.append(
                            TranscriptCourse(
                                code=code,
                                name=name,
                                credit=_opt_float_tr(c_raw.get("Credit")),
                                ects=_opt_float_tr(c_raw.get("Ects") or c_raw.get("AKTS")),
                                letter_grade=normalize_letter_grade(
                                    str(c_raw.get("Grade") or c_raw.get("LetterGrade") or "")
                                ),
                            )
                        )
                    if sem_name or courses:
                        semesters.append(
                            TranscriptSemester(
                                name=sem_name or f"{len(semesters) + 1}. Dönem",
                                semester_gpa=sem_gpa,
                                cumulative_gpa=cum_gpa,
                                courses=courses,
                            )
                        )

                gano = _opt_float_tr(
                    t.get("GANO")
                    or t.get("CumulativeAverage")
                    or t.get("GeneralAverage")
                    or t.get("Average")
                )
                if gano is None:
                    gano = last_cum_gpa

                return TranscriptSummary(
                    gano=gano,
                    total_credit=_opt_float_tr(t.get("TotalCredit")),
                    total_ects=_opt_float_tr(t.get("TotalEcts") or t.get("TotalAkts")),
                    semesters=semesters,
                )
        except Exception:
            pass

    # 2. Yedek: HTML tabloları (table#test veya <caption> içeren tablolar)
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table", id="test")
    if not tables:
        tables = [tbl for tbl in soup.find_all("table") if tbl.find("caption")]

    semesters_fb: list[TranscriptSemester] = []
    overall_gano: Optional[float] = None

    for tbl in tables:
        caption = tbl.find("caption")
        sem_name = _clean_text(caption.get_text(" ", strip=True)) if caption else ""
        if not sem_name:
            continue

        sem_gpa: Optional[float] = None
        cum_gpa: Optional[float] = None
        courses_fb: list[TranscriptCourse] = []

        tbody = tbl.find("tbody") or tbl
        for row in tbody.find_all("tr", recursive=False):
            cells = row.find_all("td", recursive=False)
            if not cells:
                continue
            row_text = _tr_lower(row.get_text(" ", strip=True))
            if any(kw in row_text for kw in ("ortalama", "birikimli", "gano", "gpa", "yano")):
                for cell in reversed(cells):
                    val = _opt_float_tr(cell.get_text(" ", strip=True))
                    if val is not None and 0.0 <= val <= 4.0:
                        if "birikimli" in row_text or "gano" in row_text or "genel" in row_text:
                            cum_gpa = val
                            overall_gano = val
                        else:
                            sem_gpa = val
                        break
                continue

            if len(cells) < 3:
                continue
            code = _clean_text(cells[0].get_text(" ", strip=True))
            name = _clean_text(cells[1].get_text(" ", strip=True))
            credit = _opt_float_tr(cells[2].get_text(" ", strip=True))
            ects: Optional[float] = None
            if len(cells) >= 5:
                ects = _opt_float_tr(cells[3].get_text(" ", strip=True))
                letter = normalize_letter_grade(cells[4].get_text(" ", strip=True))
            elif len(cells) == 4:
                letter = normalize_letter_grade(cells[3].get_text(" ", strip=True))
            else:
                letter = None

            if code or name:
                courses_fb.append(
                    TranscriptCourse(
                        code=code,
                        name=name,
                        credit=credit,
                        ects=ects,
                        letter_grade=letter,
                    )
                )

        if courses_fb or sem_gpa is not None:
            semesters_fb.append(
                TranscriptSemester(
                    name=sem_name,
                    semester_gpa=sem_gpa,
                    cumulative_gpa=cum_gpa,
                    courses=courses_fb,
                )
            )

    if overall_gano is None:
        for row in soup.find_all("tr"):
            row_text = _tr_lower(row.get_text(" ", strip=True))
            if "birikimli" in row_text or "gano" in row_text or "genel ortalama" in row_text:
                for cell in reversed(row.find_all(["td", "th"])):
                    val = _opt_float_tr(cell.get_text(" ", strip=True))
                    if val is not None and 0.0 <= val <= 4.0:
                        overall_gano = val
                        break
            if overall_gano is not None:
                break

    return TranscriptSummary(gano=overall_gano, semesters=semesters_fb)
