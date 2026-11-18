"""Kastamonu Üniversitesi ÜBYS HTTP istemcisi."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urljoin

import httpx

from .models import CourseGrade, TranscriptSummary
from .ubys_parser import (
    ParseError,
    SessionExpiredError,
    UBYSError,
    extract_ajax_csrf_token,
    extract_login_csrf_token,
    has_active_captcha,
    is_login_page,
    parse_attendance_partial,
    parse_class_detail,
    parse_grades_index,
    parse_sap_id,
    parse_student_gano,
    parse_transcript,
    parse_transcript_url,
)

logger = logging.getLogger(__name__)


class LoginError(UBYSError):
    """Kullanıcı adı/şifre hatalı veya giriş reddedildiğinde fırlatılır."""


class TwoFactorRequiredError(UBYSError):
    """Hesapta iki adımlı doğrulama aktif olduğunda fırlatılır."""


class CaptchaRequiredError(UBYSError):
    """Giriş sayfasında CAPTCHA koruması aktif olduğunda fırlatılır."""


class NetworkError(UBYSError):
    """Ağ veya sunucu bağlantı hatası oluştuğunda fırlatılır."""


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

EXCLUDED_USER_GROUP_IDS = {5001, 5002, 5003}


class UBYSClient:
    """Kastamonu Üniversitesi ÜBYS oturum ve not çekme istemcisi."""

    def __init__(
        self,
        base_url: str = "https://ubys.kastamonu.edu.tr",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=timeout,
        )
        self._logged_in = False
        self._sap_id: Optional[str] = None
        self._last_home_gano: Optional[float] = None
        self._transcript_url: Optional[str] = None

    @property
    def last_home_gano(self) -> Optional[float]:
        """Ana sayfadan okunan son GANO bilgisini döndürür."""
        return self._last_home_gano

    def __enter__(self) -> UBYSClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()
        self._logged_in = False
        self._sap_id = None
        self._last_home_gano = None
        self._transcript_url = None

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise NetworkError(f"ÜBYS bağlantısı başarısız ({url}): {exc}") from exc

    @staticmethod
    def _select_user_group(
        user_groups: list[dict[str, Any]],
        preferred_group_id: Optional[str],
    ) -> Optional[str]:
        valid_groups = [
            g for g in user_groups
            if str(g.get("id", "")).strip()
            and _safe_int(g.get("id")) not in EXCLUDED_USER_GROUP_IDS
        ]
        if not valid_groups:
            return None

        if preferred_group_id:
            for g in valid_groups:
                if str(g.get("id")).strip() == preferred_group_id.strip():
                    return str(g["id"]).strip()
            return preferred_group_id.strip()

        for g in valid_groups:
            name = str(g.get("name") or "").replace("İ", "i").replace("I", "ı").lower()
            if "öğrenci" in name or "ogrenci" in name:
                return str(g["id"]).strip()

        return str(valid_groups[0]["id"]).strip()

    def login(
        self,
        username: str,
        password: str,
        user_group_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """ÜBYS sistemine giriş yapar ve gerekirse öğrenci rolünü seçer."""
        home_resp = self._request("GET", f"{self.base_url}/")
        if home_resp.status_code >= 400:
            raise NetworkError(f"ÜBYS ana sayfası açılamadı: HTTP {home_resp.status_code}")

        if has_active_captcha(home_resp.text):
            raise CaptchaRequiredError(
                "ÜBYS giriş ekranında CAPTCHA doğrulaması aktif edilmiş. "
                "Otomatik giriş güvenlik nedeniyle durduruldu."
            )

        login_csrf = extract_login_csrf_token(home_resp.text)
        ajax_csrf = extract_ajax_csrf_token(home_resp.text)

        payload = {
            "__RequestVerificationToken": login_csrf,
            "username": username,
            "password": password,
            "X-Requested-With": "XMLHttpRequest",
        }
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        login_resp = self._request(
            "POST",
            f"{self.base_url}/Account/Login",
            data=payload,
            headers=headers,
        )

        try:
            data = login_resp.json()
        except Exception as exc:
            if login_resp.status_code >= 500:
                raise NetworkError(
                    f"ÜBYS giriş isteği sunucu hatası verdi: HTTP {login_resp.status_code}"
                ) from exc
            raise LoginError(
                "ÜBYS giriş yanıtı beklenmeyen formatta (JSON değil). "
                "Giriş ekranı değişmiş veya geçici bakım olabilir."
            ) from exc

        error_msg = data.get("errorMessage")
        if data.get("errorType") == "error" or error_msg:
            raise LoginError(f"ÜBYS girişi başarısız: {error_msg or 'Kullanıcı adı veya parola hatalı.'}")

        if login_resp.status_code >= 400:
            raise LoginError(f"ÜBYS girişi reddedildi: HTTP {login_resp.status_code}")

        if data.get("twoFactorAuthenticationIsActive"):
            raise TwoFactorRequiredError(
                "ÜBYS hesabınızda iki adımlı doğrulama (2FA) aktif görünüyor. "
                "Bu bot yalnızca şifreli doğrudan girişi destekler."
            )

        user_groups = data.get("userGroups") or []
        if not data.get("direct") and isinstance(user_groups, list) and user_groups:
            selected_group_id = self._select_user_group(user_groups, user_group_id)
            if selected_group_id:
                group_resp = self._request(
                    "POST",
                    f"{self.base_url}/Account/SetCurrentUsersGroup",
                    data={
                        "__RequestVerificationToken": ajax_csrf or login_csrf,
                        "userGroupId": selected_group_id,
                    },
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Referer": f"{self.base_url}/",
                    },
                )
                if group_resp.status_code >= 400:
                    raise LoginError(
                        f"Kullanıcı grubu seçimi başarısız (HTTP {group_resp.status_code})."
                    )

        self._logged_in = True
        return data

    @staticmethod
    def _merge_attendance_fields(course: CourseGrade, att: Optional[dict[str, Any]]) -> None:
        if not att:
            return
        for field_name in (
            "theoretical_hours",
            "practical_hours",
            "absent_theoretical_hours",
            "absent_practical_hours",
            "absent_total_hours",
            "absent_percent",
            "attendance_status",
        ):
            val = att.get(field_name)
            if val is not None and getattr(course, field_name) is None:
                setattr(course, field_name, val)

    def _fetch_home_metadata(self, dump_dir: Optional[Path] = None) -> str:
        home_resp = self._request("GET", f"{self.base_url}/AIS/Student/Home/Index")
        if is_login_page(home_resp.text, str(home_resp.url)):
            raise SessionExpiredError("Öğrenci ana sayfası alınırken oturum düştü.")
        if home_resp.status_code >= 400:
            raise NetworkError(f"Öğrenci ana sayfası açılamadı: HTTP {home_resp.status_code}")

        if dump_dir is not None:
            dump_dir.mkdir(parents=True, exist_ok=True)
            (dump_dir / "home_index.html").write_text(home_resp.text, encoding="utf-8")

        self._sap_id = parse_sap_id(home_resp.text)
        self._last_home_gano = parse_student_gano(home_resp.text)
        self._transcript_url = parse_transcript_url(home_resp.text)
        return home_resp.text

    def fetch_grades(
        self,
        all_semesters: bool = False,
        fetch_details: bool = True,
        request_delay: float = 0.7,
        dump_dir: Optional[Path] = None,
        fetch_attendance_partials: bool = True,
    ) -> list[CourseGrade]:
        """Öğrenci dönem derslerini, sınav detaylarını ve devamsızlık verilerini çeker."""
        if not self._logged_in:
            raise SessionExpiredError("Önce login() çağrılmalıdır.")

        if dump_dir is not None:
            dump_dir.mkdir(parents=True, exist_ok=True)

        self._fetch_home_metadata(dump_dir=dump_dir)
        sap_id = self._sap_id

        params: dict[str, str] = {"history": "true" if all_semesters else "false"}
        if sap_id:
            params["sapid"] = sap_id

        class_resp = self._request("GET", f"{self.base_url}/AIS/Student/Class/Index", params=params)
        if is_login_page(class_resp.text, str(class_resp.url)):
            raise SessionExpiredError("Not listesi alınırken oturum düştü.")
        if class_resp.status_code >= 400:
            raise NetworkError(f"Not listesi sayfası açılamadı: HTTP {class_resp.status_code}")

        if dump_dir is not None:
            (dump_dir / "class_index.html").write_text(class_resp.text, encoding="utf-8")

        courses = parse_grades_index(class_resp.text)

        # Bazı dönem geçişlerinde history=false boş dönerse history=true ile son dönemi al
        if not all_semesters and not courses:
            history_params = dict(params)
            history_params["history"] = "true"
            history_resp = self._request(
                "GET",
                f"{self.base_url}/AIS/Student/Class/Index",
                params=history_params,
            )
            if is_login_page(history_resp.text, str(history_resp.url)):
                raise SessionExpiredError("Geçmiş dönem not listesi alınırken oturum düştü.")
            if history_resp.status_code < 400:
                if dump_dir is not None:
                    (dump_dir / "class_index_history.html").write_text(history_resp.text, encoding="utf-8")
                all_courses = parse_grades_index(history_resp.text)
                if all_courses:
                    latest_semester = all_courses[0].semester
                    courses = [c for c in all_courses if c.semester == latest_semester]

        if fetch_details and courses:
            dumped_detail = False
            detail_calls = 0
            for course in courses:
                if not course.class_id:
                    continue

                if detail_calls > 0 and request_delay > 0:
                    time.sleep(request_delay)
                detail_calls += 1

                encoded_class_id = quote(course.class_id, safe="")
                detail_url = f"{self.base_url}/AIS/Student/Class/ClassDetail?classId={encoded_class_id}"

                try:
                    detail_resp = self._request("GET", detail_url)
                    if is_login_page(detail_resp.text, str(detail_resp.url)):
                        raise SessionExpiredError("Ders detayı alınırken oturum düştü.")
                    if detail_resp.status_code >= 400:
                        raise NetworkError(f"HTTP {detail_resp.status_code}")

                    if dump_dir is not None and not dumped_detail:
                        (dump_dir / "class_detail_sample.html").write_text(detail_resp.text, encoding="utf-8")
                        dumped_detail = True

                    detail = parse_class_detail(detail_resp.text)
                    if detail["exams"]:
                        course.exams = detail["exams"]
                    if not course.letter_grade and detail["letter_grade"]:
                        course.letter_grade = detail["letter_grade"]
                    if detail["instructor"]:
                        course.instructor = detail["instructor"]
                    if detail["class_average"]:
                        course.class_average = detail["class_average"]
                    self._merge_attendance_fields(course, detail.get("attendance"))

                    partial_url = detail.get("attendance_partial_url")
                    if (
                        fetch_attendance_partials
                        and partial_url
                        and course.absent_total_hours is None
                        and course.absent_theoretical_hours is None
                    ):
                        try:
                            if request_delay > 0:
                                time.sleep(min(0.3, request_delay))
                            resolved_partial = urljoin(f"{self.base_url}/", str(partial_url))
                            p_resp = self._request("GET", resolved_partial)
                            if p_resp.status_code < 400 and not is_login_page(p_resp.text, str(p_resp.url)):
                                self._merge_attendance_fields(course, parse_attendance_partial(p_resp.text))
                        except Exception as p_exc:
                            logger.debug("Devamsızlık alt sekmesi okunamadı (%s): %s", course.code, p_exc)
                except SessionExpiredError:
                    raise
                except Exception as exc:
                    course.detail_fetched = False
                    logger.warning(
                        "Ders detayı alınamadı (%s - %s): %s",
                        course.code,
                        course.name,
                        exc,
                    )

        return courses

    def fetch_transcript(self, dump_dir: Optional[Path] = None) -> TranscriptSummary:
        """Öğrenci transkriptini ve GANO özetini çeker."""
        if not self._logged_in:
            raise SessionExpiredError("Önce login() çağrılmalıdır.")

        if self._transcript_url is None and self._last_home_gano is None:
            self._fetch_home_metadata(dump_dir=dump_dir)

        candidates: list[str] = []
        if self._transcript_url:
            candidates.append(urljoin(f"{self.base_url}/", self._transcript_url))
        if self._sap_id:
            sap_q = quote(self._sap_id, safe="")
            candidates.append(f"{self.base_url}/AIS/Student/Transcript/Index?sapId={sap_q}")
            candidates.append(f"{self.base_url}/AIS/Student/Transkript/Index?sapId={sap_q}")
        candidates.append(f"{self.base_url}/AIS/Student/Transcript/Index")
        candidates.append(f"{self.base_url}/AIS/Student/Transkript/Index")

        seen_urls: set[str] = set()
        last_status: Optional[int] = None
        for url in candidates:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            resp = self._request("GET", url)
            if is_login_page(resp.text, str(resp.url)):
                raise SessionExpiredError("Transkript alınırken oturum düştü.")
            last_status = resp.status_code
            if resp.status_code >= 400:
                continue

            if dump_dir is not None:
                dump_dir.mkdir(parents=True, exist_ok=True)
                (dump_dir / "transcript.html").write_text(resp.text, encoding="utf-8")

            summary = parse_transcript(resp.text)
            if summary.gano is None and self._last_home_gano is not None:
                summary.gano = self._last_home_gano
            if summary.semesters or summary.gano is not None:
                return summary

        if last_status is not None and last_status >= 400:
            raise NetworkError(f"Transkript sayfası açılamadı: HTTP {last_status}")
        return TranscriptSummary(gano=self._last_home_gano)


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
