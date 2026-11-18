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
    weight_source: str = "default",
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
        weight_source=weight_source,
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


def _is_valid_weight_pair(mw: Optional[float], fw: Optional[float]) -> bool:
    return (
        mw is not None
        and fw is not None
        and 0.0 < mw < 1.0
        and 0.0 < fw < 1.0
        and abs((mw + fw) - 1.0) <= 0.05
    )


def resolve_course_weights(
    course: CourseGrade,
    default_midterm_weight: float = 0.40,
    default_final_weight: float = 0.60,
) -> tuple[float, float, str]:
    """Dersin vize/final ağırlıklarını öncelik sırasıyla belirler: manual > ubys > bologna > default."""
    if course.weight_source == "manual" and _is_valid_weight_pair(course.midterm_weight, course.final_weight):
        return float(course.midterm_weight), float(course.final_weight), "manual"

    in_term_total = 0.0
    midterm_only_total = 0.0
    final_weights: list[float] = []
    makeup_weights: list[float] = []

    for exam in course.exams:
        w = exam.weight
        if w is None or w <= 0.0 or w >= 1.0:
            continue
        kind = _classify_exam(exam)
        if kind == "midterm":
            midterm_only_total += w
            in_term_total += w
        elif kind == "other":
            in_term_total += w
        elif kind == "final":
            final_weights.append(w)
        elif kind == "makeup":
            makeup_weights.append(w)

    mw_exam = in_term_total if 0.0 < in_term_total < 1.0 else (midterm_only_total if 0.0 < midterm_only_total < 1.0 else None)
    fw_exam = final_weights[-1] if final_weights else (makeup_weights[-1] if makeup_weights else None)

    if _is_valid_weight_pair(mw_exam, fw_exam):
        return float(mw_exam), float(fw_exam), "ubys"
    if mw_exam is not None and 0.0 < mw_exam < 1.0 and fw_exam is None:
        return round(float(mw_exam), 4), round(1.0 - float(mw_exam), 4), "ubys"
    if fw_exam is not None and 0.0 < fw_exam < 1.0 and mw_exam is None:
        return round(1.0 - float(fw_exam), 4), round(float(fw_exam), 4), "ubys"

    if _is_valid_weight_pair(course.midterm_weight, course.final_weight):
        return (
            float(course.midterm_weight),
            float(course.final_weight),
            course.weight_source or "bologna",
        )

    return default_midterm_weight, default_final_weight, "default"


def analyze_course_grades(
    course: CourseGrade,
    default_midterm_weight: float = 0.40,
    default_final_weight: float = 0.60,
    final_min_score: int = 0,
) -> tuple[Optional[GradeTargetAnalysis], Optional[GradeEstimate]]:
    """Dersin mevcut sınav notlarına göre final hedef analizi veya tahmini harf notu üretir."""
    mw, fw, weight_source = resolve_course_weights(
        course,
        default_midterm_weight=default_midterm_weight,
        default_final_weight=default_final_weight,
    )

    midterms: list[tuple[float, Optional[float]]] = []
    others: list[tuple[float, Optional[float]]] = []
    finals: list[tuple[float, Optional[float]]] = []
    makeups: list[tuple[float, Optional[float]]] = []

    for exam in course.exams:
        num_score = _parse_numeric_score(exam.score)
        if num_score is None:
            continue
        kind = _classify_exam(exam)
        if kind == "midterm":
            midterms.append((num_score, exam.weight))
        elif kind == "other":
            others.append((num_score, exam.weight))
        elif kind == "final":
            finals.append((num_score, exam.weight))
        elif kind == "makeup":
            makeups.append((num_score, exam.weight))

    if not midterms:
        return None, None

    weighted_others = [(s, float(w)) for s, w in others if w is not None and 0.0 < w < 1.0]
    if all(w is not None and w > 0 for _, w in midterms):
        weighted_items = [(s, float(w)) for s, w in midterms if w is not None] + weighted_others
        total_mw = sum(w for _, w in weighted_items)
        midterm_score = sum(s * w for s, w in weighted_items) / total_mw
    else:
        midterm_score = sum(s for s, _ in midterms) / len(midterms)

    end_term_list = makeups if makeups else finals
    end_score: Optional[float] = None
    if end_term_list:
        end_score, _ = end_term_list[-1]

    if end_score is None:
        return (
            calculate_final_targets(
                midterm_score,
                mw,
                fw,
                final_min_score,
                weight_source=weight_source,
            ),
            None,
        )

    return None, estimate_course_grade(midterm_score, end_score, mw, fw, final_min_score)
