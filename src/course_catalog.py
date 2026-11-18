"""Kastamonu Üniversitesi ÜBYS Eğitim Kataloğu (Bologna) istemci ve ayrıştırıcısı."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Optional

import httpx

from .models import CourseCatalogEntry, CourseGrade

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_STOPWORDS = {
    "ve",
    "ile",
    "veya",
    "icin",
    "giris",
    "temel",
    "genel",
    "uygulamali",
    "teorik",
    "ders",
    "dersi",
    "dersleri",
    "bolum",
    "bolumu",
    "programi",
    "program",
    "fakultesi",
    "yuksekokulu",
    "meslek",
    "mudurlugu",
    "enstitusu",
    "egitim",
    "bilimleri",
    "teknolojileri",
    "turk",
    "dili",
    "ataturk",
    "ilkeleri",
    "inkilap",
    "tarihi",
    "ingilizce",
    "yabanci",
    "dil",
    "secmeli",
    "zorunlu",
    "alan",
    "mesleki",
    "teknikleri",
    "ii",
    "iii",
    "iv",
}

_JSM_DECODE_RE = re.compile(r'Base64\.decode\(\s*["\']([^"\']+)["\']\s*\)')


class BolognaCatalogError(Exception):
    """Eğitim Kataloğu (Bologna) verisi çekilirken oluşan hata."""


def _fold_tr(text: str) -> str:
    """Türkçe karakterleri ASCII karşılıklarına katlar ve kısaltmaları açar."""
    if not text:
        return ""
    trans = str.maketrans(
        {
            "İ": "i",
            "I": "i",
            "ı": "i",
            "Ç": "c",
            "ç": "c",
            "Ğ": "g",
            "ğ": "g",
            "Ö": "o",
            "ö": "o",
            "Ş": "s",
            "ş": "s",
            "Ü": "u",
            "ü": "u",
        }
    )
    folded = text.translate(trans).lower()
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    folded = re.sub(r"\bmyo\b", "meslek yuksekokulu", folded)
    folded = re.sub(r"\bfak\b", "fakultesi", folded)
    return " ".join(folded.split())


def _norm_code(code: Optional[str]) -> str:
    return " ".join(str(code or "").split()).upper()


def _to_opt_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _classify_assessment_name(name: str) -> str:
    lowered = _fold_tr(name)
    if "butunleme" in lowered or "mazeret" in lowered:
        return "makeup"
    if "final" in lowered or "yariyil sonu" in lowered or "donem sonu" in lowered:
        return "final"
    if "vize" in lowered or "ara sinav" in lowered or "midterm" in lowered:
        return "midterm"
    return "other"


def _parse_assessment_list(raw_list: Any) -> tuple[list[dict[str, Any]], Optional[float], Optional[float]]:
    if not isinstance(raw_list, list):
        return [], None, None

    assessments: list[dict[str, Any]] = []
    midterm_pct = 0.0
    final_pct = 0.0
    other_pct = 0.0

    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("ExamName") or item.get("Name") or "").split())
        pct = _to_opt_float(item.get("PercentageContribution"))
        if pct is None or pct <= 0:
            continue
        weight = round(pct / 100.0, 4)
        assessments.append({"name": name or "Değerlendirme", "weight": weight})

        kind = _classify_assessment_name(name)
        if kind == "final":
            final_pct += pct
        elif kind == "midterm":
            midterm_pct += pct
        elif kind == "other":
            other_pct += pct

    midterm_weight: Optional[float] = None
    final_weight: Optional[float] = None
    in_term_pct = midterm_pct + other_pct
    if final_pct > 0 and in_term_pct > 0 and abs((final_pct + in_term_pct) - 100.0) <= 5.0:
        final_weight = round(final_pct / 100.0, 4)
        if midterm_pct > 0:
            midterm_weight = round(midterm_pct / 100.0, 4)

    return assessments, midterm_weight, final_weight


def parse_course_detail_jsm(html: str) -> dict[str, Any]:
    """Bologna CourseDetail sayfasındaki _jsm JSON verisinden ders saati ve değerlendirme oranlarını çıkarır."""
    result: dict[str, Any] = {
        "theoretical_hours": None,
        "practical_hours": None,
        "lab_hours": None,
        "credit": None,
        "ects": None,
        "midterm_weight": None,
        "final_weight": None,
        "assessments": [],
    }

    for match in _JSM_DECODE_RE.finditer(html or ""):
        try:
            decoded = base64.b64decode(match.group(1)).decode("utf-8")
            obj = json.loads(decoded)
        except Exception:
            continue

        if not isinstance(obj, dict):
            continue
        if "CourseDetail" not in obj and "AssessmentMethodDetailList" not in obj:
            continue

        detail = obj.get("CourseDetail")
        if isinstance(detail, dict):
            result["theoretical_hours"] = _to_opt_float(detail.get("TheoreticalCredit"))
            result["practical_hours"] = _to_opt_float(detail.get("PractiseCredit"))
            result["lab_hours"] = _to_opt_float(detail.get("LaboratoryCredit"))
            result["credit"] = _to_opt_float(detail.get("Credit"))
            result["ects"] = _to_opt_float(detail.get("Ects"))

        assessments, mw, fw = _parse_assessment_list(obj.get("AssessmentMethodDetailList"))
        if assessments:
            result["assessments"] = assessments
        if mw is not None:
            result["midterm_weight"] = mw
        if fw is not None:
            result["final_weight"] = fw
        break

    return result


def extract_curriculum_courses(curriculum_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """SearchCurriculumDetail veya GetCurriculumDetail JSON yanıtından dersleri kod bazlı çıkarır."""
    extracted: dict[str, dict[str, Any]] = {}

    def _record_course(
        raw: dict[str, Any],
        curriculum_enc_id: str,
        is_elective: bool,
        is_integrated: bool,
    ) -> None:
        code = _norm_code(raw.get("Code"))
        if not code:
            return

        candidate = {
            "code": code,
            "name": " ".join(str(raw.get("Name") or "").split()),
            "theoretical_hours": _to_opt_float(raw.get("TheoreticalCredit")),
            "practical_hours": _to_opt_float(raw.get("PractiseCredit")),
            "lab_hours": _to_opt_float(raw.get("LaboratoryCredit")),
            "credit": _to_opt_float(raw.get("Credit")),
            "ects": _to_opt_float(raw.get("Ects")),
            "encrypted_id": str(raw.get("EncryptedId") or ""),
            "curriculum_encrypted_id": curriculum_enc_id,
            "is_elective": bool(is_elective),
            "is_integrated": bool(is_integrated),
            "_approved": bool(raw.get("IsApproved", True)) and bool(raw.get("IsActiveForBologna", True)),
        }

        existing = extracted.get(code)
        if existing is None:
            extracted[code] = candidate
        elif candidate["_approved"] and not existing.get("_approved"):
            extracted[code] = candidate
        elif not existing.get("encrypted_id") and candidate.get("encrypted_id"):
            extracted[code] = candidate

    details = curriculum_json.get("CurriculumDetails") or []
    for cd in details:
        if not isinstance(cd, dict):
            continue
        curriculum_enc_id = str(cd.get("EncryptedId") or "")
        for cc in cd.get("CurriculumCources") or []:
            if not isinstance(cc, dict):
                continue
            course = cc.get("Course")
            if isinstance(course, dict):
                is_int = course.get("CourseType") == 12308
                _record_course(
                    course,
                    curriculum_enc_id=curriculum_enc_id,
                    is_elective=False,
                    is_integrated=is_int,
                )

            pool = cc.get("ElectivePool")
            if isinstance(pool, dict):
                for ec in pool.get("ElectivePoolCourses") or []:
                    if isinstance(ec, dict):
                        _record_course(
                            ec,
                            curriculum_enc_id=curriculum_enc_id,
                            is_elective=True,
                            is_integrated=False,
                        )

    default_cur_id = ""
    if details and isinstance(details[0], dict):
        default_cur_id = str(details[0].get("EncryptedId") or "")
    for sub in curriculum_json.get("SubCourses") or []:
        if isinstance(sub, dict):
            _record_course(
                sub,
                curriculum_enc_id=default_cur_id,
                is_elective=False,
                is_integrated=True,
            )

    return extracted


def _distinctive_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for tok in _fold_tr(text).split():
        if len(tok) < 3 or tok in _STOPWORDS:
            continue
        tokens.append(tok)
    return tokens


def _program_initials(unit: dict[str, Any]) -> set[str]:
    initials: set[str] = set()
    full_name = str(unit.get("FullAcademicProgramName") or "")
    short_name = str(unit.get("Name") or "")
    for raw_text in (short_name, full_name):
        words = [w for w in _fold_tr(raw_text).split() if len(w) >= 2 and w not in {"ve", "ile", "veya"}]
        if len(words) >= 2:
            for k in (2, 3):
                if len(words) >= k:
                    initials.add("".join(w[0] for w in words[-k:]))
                    initials.add("".join(w[0] for w in words[:k]))
        if "/" in raw_text:
            tail = raw_text.split("/")[-1]
            tail_words = [w for w in _fold_tr(tail).split() if len(w) >= 2 and w not in {"ve", "ile"}]
            if len(tail_words) >= 2:
                initials.add("".join(w[0] for w in tail_words[:3]))
                initials.add("".join(w[0] for w in tail_words[:2]))
    return {ini for ini in initials if len(ini) >= 2}


def rank_program_candidates(
    units: list[dict[str, Any]],
    program_hints: list[str],
    courses: list[CourseGrade],
    program_override: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Öğrencinin kayıtlı olma olasılığı en yüksek akademik programları sıralar."""
    academic_programs = [
        u
        for u in units
        if isinstance(u, dict)
        and u.get("IsAcademicProgram")
        and u.get("AcademicProgramId")
        and u.get("CurriculumId")
    ]
    if not academic_programs:
        return []

    override_clean = " ".join((program_override or "").split())
    if override_clean.isdigit():
        target_id = int(override_clean)
        exact = [u for u in academic_programs if int(u["AcademicProgramId"]) == target_id]
        if exact:
            return exact

    override_folded = _fold_tr(override_clean)
    override_tokens = _distinctive_tokens(override_clean)

    hint_folded_list = [_fold_tr(h) for h in program_hints if h and h.strip()]
    hint_token_sets = [_distinctive_tokens(h) for h in program_hints if h and h.strip()]

    course_tokens: set[str] = set()
    code_prefixes: set[str] = set()
    for c in courses:
        for tok in _distinctive_tokens(c.name):
            course_tokens.add(tok)
        code = _norm_code(c.code)
        prefix_match = re.match(r"^([A-Z]{2,4})", code)
        if prefix_match:
            raw_pref = prefix_match.group(1).lower()
            code_prefixes.add(raw_pref[:2])
            if len(raw_pref) >= 3:
                code_prefixes.add(raw_pref[:3])

    scored: list[tuple[int, dict[str, Any]]] = []
    for unit in academic_programs:
        prog_text = _fold_tr(
            f"{unit.get('FullAcademicProgramName') or ''} {unit.get('Name') or ''}"
        )
        prog_words = set(prog_text.split())
        score = 0

        if override_folded:
            if override_folded in prog_text:
                score += 80
            for tok in override_tokens:
                if tok in prog_words or (len(tok) >= 4 and tok in prog_text):
                    score += 30

        for h_folded, h_tokens in zip(hint_folded_list, hint_token_sets):
            if h_folded and h_folded in prog_text:
                score += 40
            if h_tokens:
                matched_toks = sum(
                    1
                    for tok in h_tokens
                    if tok in prog_words or (len(tok) >= 4 and tok in prog_text)
                )
                score += matched_toks * 15
                if matched_toks == len(h_tokens) and len(h_tokens) >= 2:
                    score += 40

        for tok in course_tokens:
            if tok in prog_words or (len(tok) >= 5 and tok[:5] in prog_text):
                score += 4

        if code_prefixes:
            initials = _program_initials(unit)
            if code_prefixes & initials:
                score += 12

        if score > 0:
            scored.append((score, unit))

    scored.sort(key=lambda pair: (-pair[0], int(pair[1].get("AcademicProgramId") or 0)))
    return [unit for _, unit in scored]


def fetch_catalog_for_courses(
    courses: list[CourseGrade],
    base_url: str = "https://ubys.kastamonu.edu.tr",
    program_hints: Optional[list[str]] = None,
    program_override: Optional[str] = None,
    timeout: float = 25.0,
    max_candidate_programs: int = 8,
    request_delay: float = 0.15,
    fetch_weights: bool = True,
) -> tuple[dict[str, CourseCatalogEntry], Optional[int], Optional[str]]:
    """Kastamonu Eğitim Kataloğu'ndan derslerin T/U/L saatlerini ve vize/final oranlarını çeker."""
    target_codes = {_norm_code(c.code) for c in courses if _norm_code(c.code)}
    if not target_codes:
        return {}, None, None

    root = base_url.rstrip("/")
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout) as client:
            warmup = client.get(f"{root}/AIS/OutcomeBasedLearning/Home/Index?culture=tr-TR")
            if warmup.status_code >= 400:
                raise BolognaCatalogError(f"Eğitim Kataloğu açılamadı: HTTP {warmup.status_code}")

            units_resp = client.post(
                f"{root}/AIS/Common/Helper/GetUnitProgramDataSource",
                json={
                    "criter": {
                        "DontUsePrivilage": True,
                        "GetOnlyActiveForBologna": True,
                        "ShowOnlyUnitSingleProgram": True,
                    }
                },
            )
            if units_resp.status_code >= 400:
                raise BolognaCatalogError(
                    f"Birim/program listesi alınamadı: HTTP {units_resp.status_code}"
                )
            units = units_resp.json()
            if not isinstance(units, list):
                raise BolognaCatalogError("Birim/program listesi beklenen formatta değil.")

            candidates = rank_program_candidates(
                units=units,
                program_hints=program_hints or [],
                courses=courses,
                program_override=program_override,
            )
            if not candidates:
                return {}, None, None

            best_prog: Optional[dict[str, Any]] = None
            best_cur_data: Optional[dict[str, Any]] = None
            best_extracted: dict[str, dict[str, Any]] = {}
            best_match_count = 0

            for idx, prog in enumerate(candidates[:max_candidate_programs]):
                if idx > 0 and request_delay > 0:
                    time.sleep(min(0.2, request_delay))
                cur_resp = client.post(
                    f"{root}/AIS/OutcomeBasedLearning/Home/SearchCurriculumDetail",
                    json={
                        "apid": prog["AcademicProgramId"],
                        "apIdStr": prog["EncryptedAcademicProgramId"],
                        "curId": prog["CurriculumId"],
                        "curIdStr": prog["EncryptedCurriculumId"],
                    },
                )
                if cur_resp.status_code >= 400:
                    continue
                cur_data = cur_resp.json()
                if not isinstance(cur_data, dict):
                    continue

                extracted = extract_curriculum_courses(cur_data)
                match_count = len(target_codes & set(extracted))
                if match_count > best_match_count:
                    best_match_count = match_count
                    best_prog = prog
                    best_cur_data = cur_data
                    best_extracted = extracted

                if best_match_count == len(target_codes):
                    break

            if best_prog is None or best_match_count == 0:
                return {}, None, None

            # Eksik ders varsa aynı programın önceki/alternatif müfredat versiyonlarını kontrol et
            missing_codes = target_codes - set(best_extracted)
            if missing_codes and best_cur_data is not None:
                alt_curriculums = best_cur_data.get("Curriculums") or []
                seen_cur_ids = {str(best_prog.get("EncryptedCurriculumId") or "")}
                alt_checked = 0
                for cur_opt in alt_curriculums:
                    if not missing_codes or alt_checked >= 2:
                        break
                    if not isinstance(cur_opt, dict):
                        continue
                    enc_cur = str(cur_opt.get("EncryptId") or cur_opt.get("EncryptedId") or "")
                    if not enc_cur or enc_cur in seen_cur_ids:
                        continue
                    seen_cur_ids.add(enc_cur)
                    alt_checked += 1
                    try:
                        alt_resp = client.get(
                            f"{root}/AIS/OutcomeBasedLearning/Home/GetCurriculumDetail",
                            params={"curriculumIdStr": enc_cur},
                        )
                        if alt_resp.status_code >= 400:
                            continue
                        alt_extracted = extract_curriculum_courses(alt_resp.json())
                        for m_code in list(missing_codes):
                            if m_code in alt_extracted:
                                best_extracted[m_code] = alt_extracted[m_code]
                                missing_codes.discard(m_code)
                    except Exception:
                        continue

            prog_id = int(best_prog["AcademicProgramId"])
            prog_name = " ".join(
                str(best_prog.get("FullAcademicProgramName") or best_prog.get("Name") or "").split()
            )
            entries: dict[str, CourseCatalogEntry] = {}

            matched_codes = sorted(target_codes & set(best_extracted))
            for idx, code in enumerate(matched_codes):
                raw = best_extracted[code]
                entry = CourseCatalogEntry(
                    code=code,
                    name=raw["name"],
                    theoretical_hours=raw["theoretical_hours"],
                    practical_hours=raw["practical_hours"],
                    lab_hours=raw["lab_hours"],
                    credit=raw["credit"],
                    ects=raw["ects"],
                    program_id=prog_id,
                    program_name=prog_name or None,
                )

                if fetch_weights and raw.get("encrypted_id") and raw.get("curriculum_encrypted_id"):
                    if idx > 0 and request_delay > 0:
                        time.sleep(request_delay)
                    try:
                        det_resp = client.get(
                            f"{root}/AIS/OutcomeBasedLearning/Home/CourseDetail",
                            params={
                                "isElectiveCourse": str(raw["is_elective"]).lower(),
                                "isIntegratedCourse": str(raw["is_integrated"]).lower(),
                                "courseId": raw["encrypted_id"],
                                "curriculumId": raw["curriculum_encrypted_id"],
                                "apid": best_prog["EncryptedAcademicProgramId"],
                                "eqd": best_prog.get("EducationQualificatinDegree", ""),
                            },
                        )
                        if det_resp.status_code < 400:
                            parsed = parse_course_detail_jsm(det_resp.text)
                            if entry.theoretical_hours is None and parsed["theoretical_hours"] is not None:
                                entry.theoretical_hours = parsed["theoretical_hours"]
                            if entry.practical_hours is None and parsed["practical_hours"] is not None:
                                entry.practical_hours = parsed["practical_hours"]
                            if entry.lab_hours is None and parsed["lab_hours"] is not None:
                                entry.lab_hours = parsed["lab_hours"]
                            if parsed["assessments"]:
                                entry.assessments = parsed["assessments"]
                            if parsed["midterm_weight"] is not None:
                                entry.midterm_weight = parsed["midterm_weight"]
                            if parsed["final_weight"] is not None:
                                entry.final_weight = parsed["final_weight"]
                    except Exception as det_exc:
                        logger.debug("CourseDetail alınamadı (%s): %s", code, det_exc)

                entries[code] = entry

            logger.debug("Bologna programı eşleşti (program_id=%s, %d/%d ders).", prog_id, len(entries), len(target_codes))
            return entries, prog_id, prog_name or None

    except BolognaCatalogError:
        raise
    except httpx.HTTPError as exc:
        raise BolognaCatalogError(f"Eğitim Kataloğu bağlantısı başarısız: {exc}") from exc


def enrich_courses_with_catalog(
    courses: list[CourseGrade],
    catalog_entries: dict[str, CourseCatalogEntry],
    course_weights_overrides: Optional[dict[str, tuple[float, float]]] = None,
    course_hours_overrides: Optional[dict[str, tuple[float, float]]] = None,
) -> None:
    """Ders listesini Bologna katalog verileri ve manuel COURSE_WEIGHTS/COURSE_HOURS ayarlarıyla zenginleştirir."""
    weights_map = {_norm_code(k): v for k, v in (course_weights_overrides or {}).items()}
    hours_map = {_norm_code(k): v for k, v in (course_hours_overrides or {}).items()}

    for course in courses:
        code = _norm_code(course.code)

        if (course.theoretical_hours is not None or course.practical_hours is not None) and course.hours_source is None:
            course.hours_source = "ubys"

        entry = catalog_entries.get(code)
        if entry is not None:
            if course.theoretical_hours is None and course.practical_hours is None:
                has_cat_t = entry.theoretical_hours is not None
                cat_u = entry.total_practical_hours
                if has_cat_t or cat_u is not None:
                    course.theoretical_hours = entry.theoretical_hours if entry.theoretical_hours is not None else 0.0
                    course.practical_hours = cat_u if cat_u is not None else 0.0
                    course.hours_source = "bologna"

            if entry.assessments and not course.catalog_assessments:
                course.catalog_assessments = list(entry.assessments)

            if (
                course.midterm_weight is None
                and course.final_weight is None
                and entry.midterm_weight is not None
                and entry.final_weight is not None
            ):
                course.midterm_weight = entry.midterm_weight
                course.final_weight = entry.final_weight
                if course.weight_source is None:
                    course.weight_source = "bologna"

        if code in hours_map:
            t_override, u_override = hours_map[code]
            course.theoretical_hours = t_override
            course.practical_hours = u_override
            course.hours_source = "manual"

        if code in weights_map:
            mw_override, fw_override = weights_map[code]
            course.midterm_weight = mw_override
            course.final_weight = fw_override
            course.weight_source = "manual"
