"""Ders, sınav ve not değişikliği veri modelleri."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExamGrade:
    """Bir derse ait tekil sınav veya değerlendirme kaydı."""

    exam_type: str
    name: str
    score: Optional[str] = None
    announcement_date: Optional[str] = None
    class_average: Optional[str] = None
    ranking: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exam_type": self.exam_type,
            "name": self.name,
            "score": self.score,
            "announcement_date": self.announcement_date,
            "class_average": self.class_average,
            "ranking": self.ranking,
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
        )


@dataclass
class CourseGrade:
    """Bir döneme ait ders ve not bilgileri."""

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
