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
