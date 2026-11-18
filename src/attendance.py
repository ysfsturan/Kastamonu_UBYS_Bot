"""Kastamonu Üniversitesi %70 teorik / %80 uygulamalı devamsızlık takibi."""

from __future__ import annotations

import math
from typing import Any, Optional

from .models import AttendanceReport, CourseGrade

_RISK_RANK = {
    "unknown": 0,
    "safe": 1,
    "warning": 2,
    "critical": 3,
    "failed": 4,
}


def _tr_lower(text: str) -> str:
    return " ".join(text.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "").split())


def _try_float(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        return float(str(raw).strip().replace(",", "."))
    except ValueError:
        return None


def _max_absent_hours(weekly_hours: Optional[float], semester_weeks: int, allowed_ratio: float) -> Optional[float]:
    if weekly_hours is None or weekly_hours <= 0:
        return None
    return float(math.floor((weekly_hours * semester_weeks * allowed_ratio) + 1e-9))


def evaluate_course_attendance(
    course: CourseGrade,
    semester_weeks: int = 14,
    theory_min_pct: int = 70,
    practice_min_pct: int = 80,
) -> AttendanceReport:
    """Dersin haftalık teorik/uygulama saatine göre devamsızlık limitini ve kalan hakkı hesaplar."""
    theory_absent_ratio = max(0.0, (100 - theory_min_pct) / 100.0)
    practice_absent_ratio = max(0.0, (100 - practice_min_pct) / 100.0)

    weekly_theory = course.theoretical_hours
    weekly_practice = course.practical_hours
    estimated_from_credit = False

    if weekly_theory is None and weekly_practice is None:
        credit_val = _try_float(course.credit)
        if credit_val is not None and credit_val > 0:
            weekly_theory = credit_val
            weekly_practice = 0.0
            estimated_from_credit = True

    has_theory = (weekly_theory or 0.0) > 0
    has_practice = (weekly_practice or 0.0) > 0

    if estimated_from_credit:
        course_type = f"Teorik (%{theory_min_pct}, Tahmini)"
    elif has_theory and has_practice:
        course_type = f"Karma (%{theory_min_pct} T / %{practice_min_pct} U)"
    elif has_practice:
        course_type = f"Uygulamalı (%{practice_min_pct})"
    elif has_theory:
        course_type = f"Teorik (%{theory_min_pct})"
    else:
        course_type = "Belirsiz"

    max_theory = _max_absent_hours(weekly_theory, semester_weeks, theory_absent_ratio)
    max_practice = _max_absent_hours(weekly_practice, semester_weeks, practice_absent_ratio)
    max_total = (
        (max_theory or 0.0) + (max_practice or 0.0)
        if (max_theory is not None or max_practice is not None)
        else None
    )

    used_theory = course.absent_theoretical_hours
    used_practice = course.absent_practical_hours
    used_total = course.absent_total_hours

    if used_total is None and (used_theory is not None or used_practice is not None):
        used_total = (used_theory or 0.0) + (used_practice or 0.0)

    if has_theory and not has_practice and used_theory is None and used_total is not None:
        used_theory = used_total
    if has_practice and not has_theory and used_practice is None and used_total is not None:
        used_practice = used_total

    rem_theory = max(0.0, max_theory - used_theory) if (max_theory is not None and used_theory is not None) else None
    rem_practice = (
        max(0.0, max_practice - used_practice) if (max_practice is not None and used_practice is not None) else None
    )
    rem_total = max(0.0, max_total - used_total) if (max_total is not None and used_total is not None) else None

    status_text = course.attendance_status or ""
    if not status_text and course.status:
        lower_course_status = _tr_lower(course.status)
        if "devam" in lower_course_status or "muaf" in lower_course_status:
            status_text = course.status
    if not status_text:
        status_text = "Bilinmiyor"

    lower_status = _tr_lower(status_text)
    absent_pct = course.absent_percent

    # Yüzde bazlı sınır kontrolü (saat bilgisi eksik olduğunda da çalışır)
    allowed_pct_limit: Optional[float] = None
    if has_practice and not has_theory:
        allowed_pct_limit = float(100 - practice_min_pct)
    elif has_theory and not has_practice:
        allowed_pct_limit = float(100 - theory_min_pct)
    elif has_theory and has_practice:
        allowed_pct_limit = float(100 - practice_min_pct)

    failed_by_hours = any(
        u is not None and m is not None and u > m
        for u, m in (
            (used_theory, max_theory),
            (used_practice, max_practice),
            (used_total, max_total),
        )
    )
    failed_by_pct = (
        absent_pct is not None and allowed_pct_limit is not None and absent_pct > allowed_pct_limit
    )

    known_pairs = [
        (m, r)
        for m, r in (
            (max_theory, rem_theory),
            (max_practice, rem_practice),
            (max_total, rem_total),
        )
        if m is not None and r is not None
    ]

    if "devamsız" in lower_status or "devamsiz" in lower_status or failed_by_hours or failed_by_pct:
        risk_level = "failed"
    elif any(r <= 1.0 + 1e-9 for _, r in known_pairs):
        risk_level = "critical"
    elif any(r <= 2.0 + 1e-9 or (m > 0 and (r / m) <= 0.25) for m, r in known_pairs) or (
        absent_pct is not None and allowed_pct_limit is not None and absent_pct >= (allowed_pct_limit * 0.75)
    ):
        risk_level = "warning"
    elif "devamlı" in lower_status or "devamli" in lower_status or "muaf" in lower_status or known_pairs or absent_pct is not None:
        risk_level = "safe"
    else:
        risk_level = "unknown"

    return AttendanceReport(
        course_code=course.code,
        course_name=course.name,
        course_type=course_type,
        weekly_theory=weekly_theory,
        weekly_practice=weekly_practice,
        semester_weeks=semester_weeks,
        max_theory_absent=max_theory,
        used_theory_absent=used_theory,
        remaining_theory=rem_theory,
        max_practice_absent=max_practice,
        used_practice_absent=used_practice,
        remaining_practice=rem_practice,
        max_total_absent=max_total,
        used_total_absent=used_total,
        remaining_total=rem_total,
        absent_percent=absent_pct,
        status=status_text,
        risk_level=risk_level,
    )


def evaluate_all_attendance(
    courses: list[CourseGrade],
    semester_weeks: int = 14,
    theory_min_pct: int = 70,
    practice_min_pct: int = 80,
) -> list[AttendanceReport]:
    return [
        evaluate_course_attendance(
            course,
            semester_weeks=semester_weeks,
            theory_min_pct=theory_min_pct,
            practice_min_pct=practice_min_pct,
        )
        for course in courses
    ]


def _report_key(report: AttendanceReport) -> str:
    return " ".join((report.course_code or report.course_name).split())


def build_attendance_snapshot(reports: list[AttendanceReport]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for report in reports:
        snapshot[_report_key(report)] = {
            "course_code": report.course_code,
            "course_name": report.course_name,
            "used_theory_absent": report.used_theory_absent,
            "used_practice_absent": report.used_practice_absent,
            "used_total_absent": report.used_total_absent,
            "absent_percent": report.absent_percent,
            "status": report.status,
            "risk_level": report.risk_level,
        }
    return snapshot


def diff_attendance(
    previous_snapshot: dict[str, Any],
    reports: list[AttendanceReport],
) -> list[tuple[AttendanceReport, Optional[float], Optional[str]]]:
    """Devamsızlık artışı veya kritik eşik geçişlerinde uyarı listesi döndürür."""
    alerts: list[tuple[AttendanceReport, Optional[float], Optional[str]]] = []

    for report in reports:
        prev = previous_snapshot.get(_report_key(report))
        if not isinstance(prev, dict):
            continue

        old_used_total = prev.get("used_total_absent")
        old_used_theory = prev.get("used_theory_absent")
        old_used_practice = prev.get("used_practice_absent")
        old_pct = prev.get("absent_percent")
        old_status = prev.get("status")
        old_risk = str(prev.get("risk_level") or "unknown")

        hours_increased = any(
            curr is not None and old is not None and float(curr) > float(old)
            for curr, old in (
                (report.used_total_absent, old_used_total),
                (report.used_theory_absent, old_used_theory),
                (report.used_practice_absent, old_used_practice),
            )
        )
        hours_newly_recorded = (
            report.used_total_absent is not None
            and report.used_total_absent > 0
            and old_used_total is None
        )
        pct_increased = (
            report.absent_percent is not None
            and (
                (old_pct is not None and float(report.absent_percent) > float(old_pct))
                or (old_pct is None and float(report.absent_percent) > 0)
            )
        )
        status_became_failed = (
            ("devamsız" in _tr_lower(report.status) or "devamsiz" in _tr_lower(report.status))
            and report.status != old_status
        )
        risk_worsened = (
            _RISK_RANK.get(report.risk_level, 0) > _RISK_RANK.get(old_risk, 0)
            and report.risk_level in {"warning", "critical", "failed"}
        )

        if hours_increased or hours_newly_recorded or pct_increased or status_became_failed or risk_worsened:
            prev_hours_val = float(old_used_total) if old_used_total is not None else None
            alerts.append((report, prev_hours_val, str(old_status) if old_status else None))

    return alerts
