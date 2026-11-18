"""Not durumu saklama (state) ve değişiklik karşılaştırma (diff) modülü."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

import httpx

from .models import CourseGrade, ExamGrade, GradeChange

logger = logging.getLogger(__name__)

STATE_SCHEMA_VERSION = 1


class StateStorageError(Exception):
    """Not durumu okunurken veya kaydedilirken oluşan hata."""


def _parse_state_json(raw: str, source: str) -> Optional[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Durum verisi bozuk (%s), sıfırdan başlatılacak: %s", source, exc)
        return None

    if not isinstance(data, dict) or not isinstance(data.get("courses"), dict):
        return None
    return data


def load_state(path: Path) -> Optional[dict[str, Any]]:
    """Kayıtlı JSON durum dosyasını okur; yoksa veya boşsa None döner."""
    if not path.exists():
        return None
    return _parse_state_json(path.read_text(encoding="utf-8"), str(path))


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Durum sözlüğünü UTF-8 JSON olarak diske güvenli şekilde yazar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(path)


class LocalFileStateStore:
    """Durum verisini yerel JSON dosyasında saklar."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.description = f"Yerel dosya ({path})"

    def load(self) -> Optional[dict[str, Any]]:
        return load_state(self.path)

    def save(self, state: dict[str, Any]) -> None:
        save_state(self.path, state)


class GistStateStore:
    """Durum verisini gizli (Secret) GitHub Gist içinde saklar."""

    def __init__(
        self,
        gist_id: str,
        gist_token: str,
        filename: str = "grades_state.json",
        timeout: float = 20.0,
    ) -> None:
        self.gist_id = gist_id.strip()
        self.gist_token = gist_token.strip()
        self.filename = filename.strip() or "grades_state.json"
        self.timeout = timeout
        self.description = f"GitHub Gist ({self.filename})"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.gist_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "kastamonu-ubys-not-bot",
        }

    def load(self) -> Optional[dict[str, Any]]:
        url = f"https://api.github.com/gists/{self.gist_id}"
        try:
            with httpx.Client(
                headers=self._headers(),
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                resp = client.get(url)
                if resp.status_code >= 400:
                    raise StateStorageError(
                        f"GitHub Gist okunamadı (HTTP {resp.status_code}). "
                        "GIST_ID ve 'gist' yetkisine sahip GIST_TOKEN ayarlarını kontrol edin."
                    )
                payload = resp.json()
                files = payload.get("files") or {}
                entry = files.get(self.filename)
                if not isinstance(entry, dict):
                    return None

                if entry.get("truncated") and entry.get("raw_url"):
                    raw_resp = client.get(str(entry["raw_url"]))
                    if raw_resp.status_code >= 400:
                        raise StateStorageError(
                            f"GitHub Gist ham dosyası okunamadı (HTTP {raw_resp.status_code})."
                        )
                    raw_text = raw_resp.text
                else:
                    raw_text = str(entry.get("content") or "")
        except httpx.HTTPError as exc:
            raise StateStorageError(f"GitHub Gist bağlantısı başarısız: {exc}") from exc

        return _parse_state_json(raw_text, f"gist:{self.gist_id}/{self.filename}")

    def save(self, state: dict[str, Any]) -> None:
        url = f"https://api.github.com/gists/{self.gist_id}"
        content = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        body = {"files": {self.filename: {"content": content}}}
        try:
            with httpx.Client(headers=self._headers(), timeout=self.timeout) as client:
                resp = client.patch(url, json=body)
                if resp.status_code >= 400:
                    raise StateStorageError(
                        f"GitHub Gist güncellenemedi (HTTP {resp.status_code}). "
                        "GIST_ID ve 'gist' yetkisine sahip GIST_TOKEN ayarlarını kontrol edin."
                    )
        except httpx.HTTPError as exc:
            raise StateStorageError(f"GitHub Gist kaydedilirken bağlantı hatası: {exc}") from exc


def create_state_store(
    state_file: Path,
    gist_id: Optional[str] = None,
    gist_token: Optional[str] = None,
    gist_filename: str = "grades_state.json",
) -> Union[GistStateStore, LocalFileStateStore]:
    """Yapılandırmaya göre Gist veya yerel dosya durum deposu döndürür."""
    if gist_id and gist_token:
        return GistStateStore(
            gist_id=gist_id,
            gist_token=gist_token,
            filename=gist_filename,
        )
    return LocalFileStateStore(state_file)


def build_course_snapshot(
    courses: list[CourseGrade],
    previous_courses: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, Any]]:
    """Mevcut ders listesini state JSON'una uygun sözlük yapısına dönüştürür."""
    snapshot: dict[str, dict[str, Any]] = {}
    prev_map = previous_courses or {}

    for course in courses:
        key = course.course_key()
        course_dict = course.to_dict()

        if not course.detail_fetched and key in prev_map and isinstance(prev_map[key], dict):
            prev_entry = prev_map[key]
            course_dict["exams"] = list(prev_entry.get("exams") or [])
            if not course_dict.get("instructor") and prev_entry.get("instructor"):
                course_dict["instructor"] = prev_entry["instructor"]
            if not course_dict.get("class_average") and prev_entry.get("class_average"):
                course_dict["class_average"] = prev_entry["class_average"]

        snapshot[key] = course_dict

    return snapshot


def _index_exams(exams: list[ExamGrade]) -> dict[str, tuple[ExamGrade, int]]:
    counts: dict[tuple[str, str], int] = {}
    indexed: dict[str, tuple[ExamGrade, int]] = {}

    for exam in exams:
        norm_type = " ".join(exam.exam_type.split())
        norm_name = " ".join(exam.name.split())
        pair = (norm_type, norm_name)
        occurrence = counts.get(pair, 0) + 1
        counts[pair] = occurrence

        base_key = f"{norm_type}::{norm_name}"
        unique_key = base_key if occurrence == 1 else f"{base_key}#{occurrence}"
        indexed[unique_key] = (exam, occurrence)

    return indexed


def _exam_display_label(exam: ExamGrade, occurrence: int = 1) -> str:
    e_type = " ".join(exam.exam_type.split())
    e_name = " ".join(exam.name.split())

    if e_name and e_type:
        if e_type.lower() in e_name.lower():
            label = e_name
        elif e_name.lower() in e_type.lower():
            label = e_type
        else:
            label = f"{e_type} - {e_name}"
    else:
        label = e_name or e_type or "Sınav"

    if occurrence > 1:
        label = f"{label} #{occurrence}"
    return label


def _compare_optional_field(
    changes: list[GradeChange],
    course: CourseGrade,
    old_value: Optional[str],
    new_value: Optional[str],
    new_type: str,
    updated_type: str,
    label: str,
) -> None:
    if new_value is None:
        return
    if old_value is None:
        changes.append(
            GradeChange(
                change_type=new_type,
                semester=course.semester,
                course_code=course.code,
                course_name=course.name,
                label=label,
                old_value=None,
                new_value=new_value,
            )
        )
    elif old_value != new_value:
        changes.append(
            GradeChange(
                change_type=updated_type,
                semester=course.semester,
                course_code=course.code,
                course_name=course.name,
                label=label,
                old_value=old_value,
                new_value=new_value,
            )
        )


def diff_courses(
    previous_courses: dict[str, Any],
    current_courses: list[CourseGrade],
) -> list[GradeChange]:
    """Önceki durum ile güncel ders listesini karşılaştırıp not değişikliklerini döndürür."""
    changes: list[GradeChange] = []

    for course in current_courses:
        key = course.course_key()
        prev_raw = previous_courses.get(key)
        prev_course = CourseGrade.from_dict(prev_raw) if isinstance(prev_raw, dict) else None

        if course.detail_fetched:
            prev_exams = _index_exams(prev_course.exams if prev_course else [])
            curr_exams = _index_exams(course.exams)

            for exam_key, (exam, occurrence) in curr_exams.items():
                prev_entry = prev_exams.get(exam_key)
                old_score = prev_entry[0].score if prev_entry else None
                new_score = exam.score

                if new_score is None:
                    continue

                label = _exam_display_label(exam, occurrence)
                if old_score is None:
                    changes.append(
                        GradeChange(
                            change_type="new_exam_score",
                            semester=course.semester,
                            course_code=course.code,
                            course_name=course.name,
                            label=label,
                            old_value=None,
                            new_value=new_score,
                            class_average=exam.class_average or course.class_average,
                            ranking=exam.ranking,
                            announcement_date=exam.announcement_date,
                        )
                    )
                elif old_score != new_score:
                    changes.append(
                        GradeChange(
                            change_type="updated_exam_score",
                            semester=course.semester,
                            course_code=course.code,
                            course_name=course.name,
                            label=label,
                            old_value=old_score,
                            new_value=new_score,
                            class_average=exam.class_average or course.class_average,
                            ranking=exam.ranking,
                            announcement_date=exam.announcement_date,
                        )
                    )

        _compare_optional_field(
            changes=changes,
            course=course,
            old_value=prev_course.passing_grade if prev_course else None,
            new_value=course.passing_grade,
            new_type="new_passing_grade",
            updated_type="updated_passing_grade",
            label="Geçme Notu",
        )

        _compare_optional_field(
            changes=changes,
            course=course,
            old_value=prev_course.letter_grade if prev_course else None,
            new_value=course.letter_grade,
            new_type="new_letter_grade",
            updated_type="updated_letter_grade",
            label="Harf Notu (HBN)",
        )

        old_status = prev_course.status if prev_course else None
        new_status = course.status
        if new_status is not None and new_status != old_status:
            changes.append(
                GradeChange(
                    change_type="status_changed",
                    semester=course.semester,
                    course_code=course.code,
                    course_name=course.name,
                    label="Başarı Durumu",
                    old_value=old_status,
                    new_value=new_status,
                )
            )

    return changes
