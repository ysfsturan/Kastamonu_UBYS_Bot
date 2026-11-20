"""Ders, sınav ve not değişikliği veri modelleri."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


def _opt_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


@dataclass
class ExamGrade:
    """Bir derse ait tekil sınav veya değerlendirme kaydı."""

    exam_type: str
    name: str
    score: Optional[str] = None
    announcement_date: Optional[str] = None
    class_average: Optional[str] = None
    ranking: Optional[str] = None
    weight: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exam_type": self.exam_type,
            "name": self.name,
            "score": self.score,
            "announcement_date": self.announcement_date,
            "class_average": self.class_average,
            "ranking": self.ranking,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExamGrade:
        return cls(
            exam_type=str(data.get("exam_type") or ""),
            name=str(data.get("name") or ""),
            score=data.get("score"),
            announcement_date=data.get("announcement_date"),
            class_average=data.get("class_average"),
            ranking=data.get("ranking"),
            weight=_opt_float(data.get("weight")),
        )


@dataclass
class CourseGrade:
    """Bir döneme ait ders, not ve devamsızlık bilgileri."""

    semester: str
    code: str
    name: str
    credit: Optional[str] = None
    passing_grade: Optional[str] = None
    letter_grade: Optional[str] = None
    status: Optional[str] = None
    class_id: Optional[str] = None
    instructor: Optional[str] = None
    class_average: Optional[str] = None
    exams: list[ExamGrade] = field(default_factory=list)
    detail_fetched: bool = True
    theoretical_hours: Optional[float] = None
    practical_hours: Optional[float] = None
    absent_theoretical_hours: Optional[float] = None
    absent_practical_hours: Optional[float] = None
    absent_total_hours: Optional[float] = None
    absent_percent: Optional[float] = None
    attendance_status: Optional[str] = None
    midterm_weight: Optional[float] = None
    final_weight: Optional[float] = None
    weight_source: Optional[str] = None
    hours_source: Optional[str] = None
    catalog_assessments: list[dict[str, Any]] = field(default_factory=list)
    materials: list[CourseMaterial] = field(default_factory=list)

    def course_key(self) -> str:
        """Dersi dönem ve kod/ad bazında benzersiz olarak tanımlar."""
        semester = " ".join(self.semester.split())
        identifier = " ".join((self.code or self.name).split())
        return f"{semester}::{identifier}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "semester": self.semester,
            "code": self.code,
            "name": self.name,
            "credit": self.credit,
            "passing_grade": self.passing_grade,
            "letter_grade": self.letter_grade,
            "status": self.status,
            "class_id": self.class_id,
            "instructor": self.instructor,
            "class_average": self.class_average,
            "exams": [exam.to_dict() for exam in self.exams],
            "theoretical_hours": self.theoretical_hours,
            "practical_hours": self.practical_hours,
            "absent_theoretical_hours": self.absent_theoretical_hours,
            "absent_practical_hours": self.absent_practical_hours,
            "absent_total_hours": self.absent_total_hours,
            "absent_percent": self.absent_percent,
            "attendance_status": self.attendance_status,
            "midterm_weight": self.midterm_weight,
            "final_weight": self.final_weight,
            "weight_source": self.weight_source,
            "hours_source": self.hours_source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CourseGrade:
        raw_exams = data.get("exams") or []
        return cls(
            semester=str(data.get("semester") or ""),
            code=str(data.get("code") or ""),
            name=str(data.get("name") or ""),
            credit=data.get("credit"),
            passing_grade=data.get("passing_grade"),
            letter_grade=data.get("letter_grade"),
            status=data.get("status"),
            class_id=data.get("class_id"),
            instructor=data.get("instructor"),
            class_average=data.get("class_average"),
            exams=[ExamGrade.from_dict(e) for e in raw_exams if isinstance(e, dict)],
            detail_fetched=bool(data.get("detail_fetched", True)),
            theoretical_hours=_opt_float(data.get("theoretical_hours")),
            practical_hours=_opt_float(data.get("practical_hours")),
            absent_theoretical_hours=_opt_float(data.get("absent_theoretical_hours")),
            absent_practical_hours=_opt_float(data.get("absent_practical_hours")),
            absent_total_hours=_opt_float(data.get("absent_total_hours")),
            absent_percent=_opt_float(data.get("absent_percent")),
            attendance_status=data.get("attendance_status"),
            midterm_weight=_opt_float(data.get("midterm_weight")),
            final_weight=_opt_float(data.get("final_weight")),
            weight_source=data.get("weight_source"),
            hours_source=data.get("hours_source"),
        )


@dataclass
class CourseCatalogEntry:
    """Eğitim Kataloğu (Bologna) üzerinden alınan ders saat ve değerlendirme kaydı."""

    code: str
    name: str
    theoretical_hours: Optional[float] = None
    practical_hours: Optional[float] = None
    lab_hours: Optional[float] = None
    credit: Optional[float] = None
    ects: Optional[float] = None
    midterm_weight: Optional[float] = None
    final_weight: Optional[float] = None
    assessments: list[dict[str, Any]] = field(default_factory=list)
    program_id: Optional[int] = None
    program_name: Optional[str] = None

    @property
    def total_practical_hours(self) -> Optional[float]:
        """Uygulama + laboratuvar haftalık saat toplamını döndürür."""
        if self.practical_hours is None and self.lab_hours is None:
            return None
        return (self.practical_hours or 0.0) + (self.lab_hours or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "theoretical_hours": self.theoretical_hours,
            "practical_hours": self.practical_hours,
            "lab_hours": self.lab_hours,
            "credit": self.credit,
            "ects": self.ects,
            "midterm_weight": self.midterm_weight,
            "final_weight": self.final_weight,
            "assessments": list(self.assessments),
            "program_id": self.program_id,
            "program_name": self.program_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CourseCatalogEntry:
        raw_prog_id = data.get("program_id")
        try:
            prog_id = int(raw_prog_id) if raw_prog_id is not None else None
        except (TypeError, ValueError):
            prog_id = None
        raw_assessments = data.get("assessments") or []
        return cls(
            code=str(data.get("code") or ""),
            name=str(data.get("name") or ""),
            theoretical_hours=_opt_float(data.get("theoretical_hours")),
            practical_hours=_opt_float(data.get("practical_hours")),
            lab_hours=_opt_float(data.get("lab_hours")),
            credit=_opt_float(data.get("credit")),
            ects=_opt_float(data.get("ects")),
            midterm_weight=_opt_float(data.get("midterm_weight")),
            final_weight=_opt_float(data.get("final_weight")),
            assessments=[a for a in raw_assessments if isinstance(a, dict)],
            program_id=prog_id,
            program_name=data.get("program_name"),
        )


@dataclass
class GradeChange:
    """İki kontrol arasında tespit edilen tekil not/durum değişikliği."""

    change_type: str
    semester: str
    course_code: str
    course_name: str
    label: str
    old_value: Optional[str]
    new_value: Optional[str]
    class_average: Optional[str] = None
    ranking: Optional[str] = None
    announcement_date: Optional[str] = None


@dataclass
class DiningItem:
    """Yemekhane menüsündeki tekil yemek/çeşit öğesi."""

    name: str
    calories: Optional[str] = None
    category: str = ""


@dataclass
class DailyMenu:
    """Belirli bir güne ait yemekhane menüsü."""

    menu_date: date
    items: list[DiningItem]
    total_calories_min: Optional[int] = None
    total_calories_max: Optional[int] = None
    source_url: Optional[str] = None


@dataclass
class CalendarEvent:
    """Kastamonu Üniversitesi Akademik Takvim etkinliği."""

    event_id: str
    title: str
    start_date: date
    end_date: date
    category: str
    faculty: str
    term: str
    description: str = ""
    google_calendar_url: Optional[str] = None


@dataclass
class FinalTarget:
    """Belirli bir harf notu için finalden gereken minimum puan hedefi."""

    letter: str
    min_total: int
    coefficient: float
    required_final: Optional[int]
    status: str  # "guaranteed", "achievable", "impossible"


@dataclass
class GradeTargetAnalysis:
    """Vize notuna göre final hedef tablosu analizi."""

    midterm_score: float
    midterm_weight: float
    final_weight: float
    final_min_score: int
    targets: list[FinalTarget]
    max_possible_total: float
    max_possible_letter: str
    weight_source: str = "default"


@dataclass
class GradeEstimate:
    """Vize ve final notlarına göre tahmini başarı notu ve harf karşılığı."""

    weighted_total: float
    letter_grade: str
    coefficient: float
    is_passing: bool
    is_conditional: bool


@dataclass
class TranscriptCourse:
    """Transkript dönem tablosundaki tekil ders kaydı."""

    code: str
    name: str
    credit: Optional[float] = None
    ects: Optional[float] = None
    letter_grade: Optional[str] = None


@dataclass
class TranscriptSemester:
    """Transkript üzerindeki tekil yarıyıl verisi."""

    name: str
    semester_gpa: Optional[float] = None
    cumulative_gpa: Optional[float] = None
    courses: list[TranscriptCourse] = field(default_factory=list)


@dataclass
class TranscriptSummary:
    """Öğrenci transkript ve GANO özeti."""

    gano: Optional[float] = None
    total_credit: Optional[float] = None
    total_ects: Optional[float] = None
    semesters: list[TranscriptSemester] = field(default_factory=list)


@dataclass
class AttendanceReport:
    """Bir derse ait devamsızlık limiti ve kalan hak raporu."""

    course_code: str
    course_name: str
    course_type: str
    weekly_theory: Optional[float]
    weekly_practice: Optional[float]
    semester_weeks: int
    max_theory_absent: Optional[float]
    used_theory_absent: Optional[float]
    remaining_theory: Optional[float]
    max_practice_absent: Optional[float]
    used_practice_absent: Optional[float]
    remaining_practice: Optional[float]
    max_total_absent: Optional[float]
    used_total_absent: Optional[float]
    remaining_total: Optional[float]
    absent_percent: Optional[float]
    status: str
    risk_level: str  # "safe", "warning", "critical", "failed", "unknown"
    hours_source: str = "unknown"
    max_theory_days: Optional[int] = None
    used_theory_days: Optional[float] = None
    remaining_theory_days: Optional[int] = None
    max_practice_days: Optional[int] = None
    used_practice_days: Optional[float] = None
    remaining_practice_days: Optional[int] = None
    max_total_days: Optional[int] = None
    used_total_days: Optional[float] = None
    remaining_total_days: Optional[int] = None


@dataclass
class WeatherForecast:
    """Kastamonu / Kuzeykent kampüs hava durumu tahmini."""

    location_name: str
    forecast_date: date
    current_temp: Optional[float]
    apparent_temp: Optional[float]
    temp_min: Optional[float]
    temp_max: Optional[float]
    precip_probability: Optional[int]
    wind_speed: Optional[float]
    weather_code: int
    condition_text: str
    condition_icon: str
    advice: str
    tomorrow_summary: Optional[str] = None
    daily_summaries: list[str] = field(default_factory=list)


@dataclass
class Announcement:
    """Üniversite, OİDB, SKS, Fakülte/MYO veya ÜBYS duyuru kaydı."""

    announcement_id: str
    source: str
    title: str
    url: str
    published_date: Optional[str] = None
    summary: str = ""


@dataclass
class GpaProjection:
    """Dönem sonu YANO/GANO ve onur belgesi projeksiyonu."""

    projected_yano: Optional[float]
    projected_gano: Optional[float]
    current_gano: Optional[float]
    total_term_credit: float
    counted_courses: list[dict[str, Any]] = field(default_factory=list)
    has_failing_grade: bool = False
    has_conditional_grade: bool = False
    honor_status: str = "normal"  # "yuksek_onur", "onur", "normal", "risk"
    dc_pass_safe: Optional[bool] = None
    points_to_honor: Optional[float] = None
    points_to_high_honor: Optional[float] = None


@dataclass
class ScheduleSlot:
    """Haftalık ders programı satırı."""

    day_of_week: int
    day_name: str
    start_time: str
    end_time: str = ""
    course_code: str = ""
    course_name: str = ""
    classroom: Optional[str] = None
    instructor: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "day_of_week": self.day_of_week,
            "day_name": self.day_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "course_code": self.course_code,
            "course_name": self.course_name,
            "classroom": self.classroom,
            "instructor": self.instructor,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleSlot:
        return cls(
            day_of_week=int(data.get("day_of_week") or 0),
            day_name=str(data.get("day_name") or ""),
            start_time=str(data.get("start_time") or ""),
            end_time=str(data.get("end_time") or ""),
            course_code=str(data.get("course_code") or ""),
            course_name=str(data.get("course_name") or ""),
            classroom=data.get("classroom"),
            instructor=data.get("instructor"),
        )


@dataclass
class ExamScheduleItem:
    """ÜBYS sınav programı kaydı."""

    course_code: str
    course_name: str
    exam_type: str
    exam_date: date
    exam_time: Optional[str] = None
    classroom: Optional[str] = None
    seat: Optional[str] = None

    def exam_key(self) -> str:
        ident = " ".join((self.course_code or self.course_name).split()).upper()
        etype = " ".join(self.exam_type.split()).lower()
        return f"{ident}::{etype}::{self.exam_date.isoformat()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_code": self.course_code,
            "course_name": self.course_name,
            "exam_type": self.exam_type,
            "exam_date": self.exam_date.isoformat(),
            "exam_time": self.exam_time,
            "classroom": self.classroom,
            "seat": self.seat,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExamScheduleItem:
        return cls(
            course_code=str(data.get("course_code") or ""),
            course_name=str(data.get("course_name") or ""),
            exam_type=str(data.get("exam_type") or ""),
            exam_date=date.fromisoformat(str(data["exam_date"])),
            exam_time=data.get("exam_time"),
            classroom=data.get("classroom"),
            seat=data.get("seat"),
        )


@dataclass
class CourseMaterial:
    """Ders içi yüklenen dosya/materyal, ödev veya ders duyurusu kaydı."""

    material_id: str
    course_code: str
    course_name: str
    category: str  # "dosya", "ödev", "duyuru"
    title: str
    url: Optional[str] = None
    due_date: Optional[str] = None
    published_date: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "course_code": self.course_code,
            "course_name": self.course_name,
            "category": self.category,
            "title": self.title,
            "url": self.url,
            "due_date": self.due_date,
            "published_date": self.published_date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CourseMaterial:
        return cls(
            material_id=str(data.get("material_id") or ""),
            course_code=str(data.get("course_code") or ""),
            course_name=str(data.get("course_name") or ""),
            category=str(data.get("category") or "dosya"),
            title=str(data.get("title") or ""),
            url=data.get("url"),
            due_date=data.get("due_date"),
            published_date=data.get("published_date"),
        )
