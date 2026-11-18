"""Kastamonu Üniversitesi geçme notu, harf aralığı ve final hedef hesaplayıcı."""

from __future__ import annotations

import math
from typing import Optional

from .models import (
    CourseGrade,
    ExamGrade,
    FinalTarget,
    GradeEstimate,
    GradeTargetAnalysis,
)

# Kastamonu Üniversitesi Eğitim-Öğretim ve Sınav Yönetmeliği harf notu tablosu
KU_GRADE_SCALE: tuple[tuple[int, str, float], ...] = (
    (90, "AA", 4.00),
    (85, "BA", 3.50),
    (75, "BB", 3.00),
    (65, "CB", 2.50),
    (60, "CC", 2.00),
    (55, "DC", 1.50),
    (50, "DD", 1.00),
    (40, "FD", 0.50),
    (0, "FF", 0.00),
)

TARGET_LETTERS: tuple[str, ...] = ("DC", "CC", "CB", "BB", "BA", "AA")


def _tr_lower(text: str) -> str:
    return " ".join(text.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "").split())


def score_to_letter(score: float) -> tuple[str, float]:
    """100'lük puanı Kastamonu Üniversitesi harf notu ve 4'lük katsayısına çevirir."""
    for threshold, letter, coeff in KU_GRADE_SCALE:
        if score >= threshold - 1e-9:
            return letter, coeff
    return "FF", 0.00


def calculate_final_targets(
    midterm_score: float,
    midterm_weight: float = 0.40,
    final_weight: float = 0.60,
    final_min_score: int = 0,
) -> GradeTargetAnalysis:
    """Vize puanına göre her harf notu için finalden alınması gereken minimum puanları hesaplar."""
    targets: list[FinalTarget] = []
    scale_by_letter = {letter: (threshold, coeff) for threshold, letter, coeff in KU_GRADE_SCALE}

    for letter in TARGET_LETTERS:
        min_total, coeff = scale_by_letter[letter]
        raw_req = (min_total - (midterm_score * midterm_weight)) / final_weight
        req = max(final_min_score, math.ceil(raw_req - 1e-9))

        if req > 100:
            targets.append(
                FinalTarget(
                    letter=letter,
                    min_total=min_total,
                    coefficient=coeff,
                    required_final=None,
                    status="impossible",
                )
            )
        elif req <= 0:
            targets.append(
                FinalTarget(
                    letter=letter,
                    min_total=min_total,
                    coefficient=coeff,
                    required_final=0,
                    status="guaranteed",
                )
            )
        else:
            targets.append(
                FinalTarget(
                    letter=letter,
                    min_total=min_total,
                    coefficient=coeff,
                    required_final=int(req),
                    status="achievable",
                )
            )

    max_possible = round((midterm_score * midterm_weight) + (100.0 * final_weight), 2)
    max_letter, _ = score_to_letter(max_possible)
    return GradeTargetAnalysis(
        midterm_score=round(midterm_score, 2),
        midterm_weight=midterm_weight,
        final_weight=final_weight,
        final_min_score=final_min_score,
        targets=targets,
        max_possible_total=max_possible,
        max_possible_letter=max_letter,
    )


def estimate_course_grade(
    midterm_score: float,
    final_score: float,
    midterm_weight: float = 0.40,
    final_weight: float = 0.60,
    final_min_score: int = 0,
) -> GradeEstimate:
    """Vize ve final notlarına göre ağırlıklı ortalamayı ve harf notunu tahmin eder."""
    weighted_total = round((midterm_score * midterm_weight) + (final_score * final_weight), 2)
    if final_min_score > 0 and final_score < final_min_score:
        letter, coeff = "FF", 0.00
    else:
        letter, coeff = score_to_letter(weighted_total)

    return GradeEstimate(
        weighted_total=weighted_total,
        letter_grade=letter,
        coefficient=coeff,
        is_passing=letter in {"AA", "BA", "BB", "CB", "CC"},
        is_conditional=letter == "DC",
    )


def _parse_numeric_score(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        return float(str(raw).strip().replace(",", "."))
    except ValueError:
        return None


def _classify_exam(exam: ExamGrade) -> str:
    label = _tr_lower(f"{exam.exam_type} {exam.name}")
    if "bütünleme" in label or "butunleme" in label:
        return "makeup"
    if "final" in label or "yarıyıl sonu" in label or "yariyil sonu" in label or "dönem sonu" in label:
        return "final"
    if "vize" in label or "ara sınav" in label or "ara sinav" in label:
        return "midterm"
    return "other"


def analyze_course_grades(
    course: CourseGrade,
    default_midterm_weight: float = 0.40,
    default_final_weight: float = 0.60,
    final_min_score: int = 0,
) -> tuple[Optional[GradeTargetAnalysis], Optional[GradeEstimate]]:
    """Dersin mevcut sınav notlarına göre final hedef analizi veya tahmini harf notu üretir."""
    midterms: list[tuple[float, Optional[float]]] = []
    finals: list[tuple[float, Optional[float]]] = []
    makeups: list[tuple[float, Optional[float]]] = []

    for exam in course.exams:
        num_score = _parse_numeric_score(exam.score)
        if num_score is None:
            continue
        kind = _classify_exam(exam)
        if kind == "midterm":
            midterms.append((num_score, exam.weight))
        elif kind == "final":
            finals.append((num_score, exam.weight))
        elif kind == "makeup":
            makeups.append((num_score, exam.weight))

    if not midterms:
        return None, None

    if all(w is not None and w > 0 for _, w in midterms):
        total_mw = sum(float(w) for _, w in midterms if w is not None)
        midterm_score = sum(s * float(w) for s, w in midterms if w is not None) / total_mw
        midterm_w_from_exam: Optional[float] = total_mw if 0 < total_mw < 1 else None
    else:
        midterm_score = sum(s for s, _ in midterms) / len(midterms)
        midterm_w_from_exam = None

    end_term_list = makeups if makeups else finals
    end_score: Optional[float] = None
    end_w_from_exam: Optional[float] = None
    if end_term_list:
        end_score, end_w_from_exam = end_term_list[-1]

    if (
        midterm_w_from_exam is not None
        and end_w_from_exam is not None
        and 0 < midterm_w_from_exam < 1
        and 0 < end_w_from_exam < 1
        and abs((midterm_w_from_exam + end_w_from_exam) - 1.0) <= 0.05
    ):
        mw, fw = midterm_w_from_exam, end_w_from_exam
    else:
        mw, fw = default_midterm_weight, default_final_weight

    if end_score is None:
        return calculate_final_targets(midterm_score, mw, fw, final_min_score), None

    return None, estimate_course_grade(midterm_score, end_score, mw, fw, final_min_score)
