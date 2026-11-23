"""Kastamonu ÜBYS Not Bildirim Botu birim testleri."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from src.announcements import (
    filter_new_announcements,
    infer_faculty_sources,
    infer_student_class_year,
    is_exam_announcement,
    make_announcement_id,
    parse_announcements_html,
    parse_department_exam_pdfs,
    parse_department_program_url,
)
from src.attendance import (
    build_attendance_snapshot,
    diff_attendance,
    evaluate_all_attendance,
    evaluate_course_attendance,
)
from src.bot_commands import (
    BOT_COMMANDS_VERSION,
    handle_command,
    parse_bot_command,
    process_telegram_commands,
)
from src.calendar_tracker import (
    CalendarError,
    extract_active_term,
    filter_events_by_categories,
    find_milestone_reminders,
    find_ongoing_and_upcoming,
    parse_calendar_api_json,
    resolve_faculty_name,
)
from src.config import Config, ConfigError, load_config, parse_weight_pair
from src.course_catalog import (
    BolognaCatalogError,
    enrich_courses_with_catalog,
    extract_curriculum_courses,
    parse_course_detail_jsm,
    rank_program_candidates,
)
from src.differ import (
    GistStateStore,
    StateStorageError,
    build_course_snapshot,
    diff_courses,
    load_state,
    save_state,
)
from src.dining import (
    DiningError,
    build_csv_export_url,
    extract_dining_sheet_url,
    get_next_menu,
    parse_dining_csv,
    tr_title,
)
from src.grade_calculator import (
    analyze_course_grades,
    calculate_final_targets,
    estimate_course_grade,
    project_semester_gpa,
    resolve_course_weights,
    score_to_letter,
)
from src.main import TR_TZ, main as cli_main, run_once
from src.models import (
    Announcement,
    CalendarEvent,
    CourseCatalogEntry,
    CourseGrade,
    CourseMaterial,
    DailyMenu,
    DiningItem,
    ExamGrade,
    ExamScheduleItem,
    GpaProjection,
    ScheduleSlot,
    TranscriptCourse,
    TranscriptSemester,
    TranscriptSummary,
    WeatherForecast,
)
from src.notifier import (
    TelegramNotifier,
    format_announcements,
    format_attendance_alerts,
    format_attendance_report,
    format_baseline_summary,
    format_calendar_digest,
    format_calendar_reminders,
    format_daily_menu,
    format_daily_schedule,
    format_exam_reminders,
    format_exam_schedule,
    format_gano_change,
    format_gpa_projection,
    format_grade_calculator,
    format_grade_changes,
    format_help_message,
    format_material_alerts,
    format_test_summary,
    format_transcript_summary,
    format_weather_report,
    format_weekly_briefing,
    format_weekly_schedule,
    select_transcript_semesters,
    split_message,
)
from src.schedule import (
    exam_reminder_key,
    filter_slots_for_active_courses,
    find_exam_reminders,
    get_slots_for_day,
    parse_exam_schedule,
    parse_weekly_schedule,
)
from src.ubys_client import LoginError, NetworkError, UBYSClient
from src.ubys_parser import (
    SessionExpiredError,
    discover_home_routes,
    extract_ajax_csrf_token,
    extract_login_csrf_token,
    has_active_captcha,
    normalize_letter_grade,
    normalize_score,
    normalize_status,
    parse_class_detail,
    parse_course_materials,
    parse_exam_schedule_url,
    parse_grades_index,
    parse_sap_id,
    parse_schedule_url,
    parse_student_gano,
    parse_student_program_hints,
    parse_transcript,
    parse_ubys_home_announcements,
)
from src.weather import (
    WeatherError,
    build_weather_advice,
    describe_wmo_code,
    fetch_weather_forecast,
    parse_open_meteo_response,
    parse_wttr_response,
)

SAMPLE_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
  <script>
    var _verifiedreCaptcha = JSON.parse(Base64.decode("ZmFsc2U="));
  </script>
</head>
<body>
  <div class="main-login-div">
    <form action="/" id="loginForm" method="post">
      <input name="__RequestVerificationToken" type="hidden" value="LOGIN_TOKEN_123" />
      <input type="text" name="username" id="username" />
      <input type="password" name="password" id="password" />
    </form>
  </div>
  <form id="__AjaxAntiForgeryForm" action="#" method="post">
    <input name="__RequestVerificationToken" type="hidden" value="AJAX_TOKEN_456" />
  </form>
  <form id="loginCodeForm" method="post">
    <input name="__RequestVerificationToken" type="hidden" value="CODE_TOKEN_789" />
  </form>
</body>
</html>
"""

SAMPLE_GRADES_INDEX_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="panel panel-default">
    <div class="panel-heading">2025-2026 Güz Dönemi</div>
    <div class="panel-body">
      <table class="table table-bordered">
        <thead>
          <tr>
            <th>Ders Kodu</th>
            <th>Ders Adı</th>
            <th>Kredi</th>
            <th>AKTS</th>
            <th>Devamsızlık</th>
            <th>Vize</th>
            <th>Geçme Notu</th>
            <th>HBN</th>
            <th>Başarı Durumu</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td rowspan="2">
              <a href="/AIS/Student/Class/ClassDetail?classId=12345%21ABC%2199">BLM201</a>
            </td>
            <td>Veri Yapıları &amp; Algoritmalar</td>
            <td>4,0</td>
            <td>6</td>
            <td>%0</td>
            <td>75</td>
            <td>78,50</td>
            <td>BA</td>
            <td>Başarılı</td>
          </tr>
          <tr>
            <td colspan="8">
              <span>Vize: 75,00</span> | <span>Final: 82</span>
            </td>
          </tr>
          <tr>
            <td rowspan="2">
              <a href="/AIS/Student/Class/ClassDetail?classId=99887!XYZ">MAT102</a>
            </td>
            <td>Matematik II</td>
            <td>3</td>
            <td>5</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>Durumu Netleşmemiş</td>
          </tr>
          <tr>
            <td colspan="8">
              <span>Vize: 60</span> | <span>Final: -</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""

SAMPLE_CLASS_DETAIL_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="instructor">
    <div class="name"><a href="#">Dr. Öğr. Üyesi Ahmet Yılmaz</a></div>
    <div class="avarage">Sınıf Not Ortalaması : 58,40</div>
  </div>
  <div class="success-status">Başarılı (BA)</div>
  <div class="tab-pane active">
    <div class="table-responsive">
      <table class="table table-striped">
        <thead>
          <tr>
            <th>Sınav Tipi</th>
            <th>Sınav Adı</th>
            <th>İlan Tarihi</th>
            <th>Sınav Notu</th>
            <th>Mazeret</th>
            <th>Sınıf Sıralaması</th>
            <th>Sınıf Ortalaması</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Ara Sınav</td>
            <td>Vize</td>
            <td>15.11.2025 14:30</td>
            <td>75,00</td>
            <td>-</td>
            <td>12 / 85</td>
            <td>54,25</td>
          </tr>
          <tr>
            <td>Kısa Sınav</td>
            <td>Quiz 1</td>
            <td>22.11.2025 09:00</td>
            <td>G</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
          </tr>
          <tr>
            <td>Yarıyıl Sonu</td>
            <td>Final</td>
            <td>10.01.2026 17:15</td>
            <td>82,50</td>
            <td>-</td>
            <td>8 / 85</td>
            <td>61,00</td>
          </tr>
          <tr>
            <td>Bütünleme</td>
            <td>Bütünleme</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""


class ParserTests(unittest.TestCase):
    def test_csrf_tokens_and_captcha_detection(self) -> None:
        self.assertEqual(extract_login_csrf_token(SAMPLE_LOGIN_HTML), "LOGIN_TOKEN_123")
        self.assertEqual(extract_ajax_csrf_token(SAMPLE_LOGIN_HTML), "AJAX_TOKEN_456")
        self.assertFalse(has_active_captcha(SAMPLE_LOGIN_HTML))

        captcha_html = SAMPLE_LOGIN_HTML.replace("ZmFsc2U=", "dHJ1ZQ==")
        self.assertTrue(has_active_captcha(captcha_html))

    def test_parse_sap_id(self) -> None:
        html_onclick = """<a href="#" onclick="selectAcademicProgram('abc123XYZ')">Program</a>"""
        self.assertEqual(parse_sap_id(html_onclick), "abc123XYZ")

        html_href = """<a href="/AIS/Student/Class/Index?sapid=xyz789%21&amp;history=false">Derslerim</a>"""
        self.assertEqual(parse_sap_id(html_href), "xyz789!")

        self.assertIsNone(parse_sap_id("<html><body>No sap id here</body></html>"))

    def test_normalization_helpers(self) -> None:
        self.assertEqual(normalize_score("80,00"), "80")
        self.assertEqual(normalize_score("75,50"), "75.5")
        self.assertEqual(normalize_score("0,0"), "0")
        self.assertEqual(normalize_score("G"), "G")
        self.assertEqual(normalize_score("DZ"), "DZ")
        self.assertIsNone(normalize_score("-"))
        self.assertIsNone(normalize_score("  Girilmedi "))

        self.assertIsNone(normalize_letter_grade("Durumu Netleşmemiş"))
        self.assertIsNone(normalize_letter_grade("-"))
        self.assertEqual(normalize_letter_grade("aa"), "AA")

        self.assertIsNone(normalize_status("Durumu Netleşmemiş"))
        self.assertEqual(normalize_status("Başarılı"), "Başarılı")

    def test_parse_grades_index(self) -> None:
        courses = parse_grades_index(SAMPLE_GRADES_INDEX_HTML)
        self.assertEqual(len(courses), 2)

        first = courses[0]
        self.assertEqual(first.semester, "2025-2026 Güz Dönemi")
        self.assertEqual(first.code, "BLM201")
        self.assertEqual(first.name, "Veri Yapıları & Algoritmalar")
        self.assertEqual(first.class_id, "12345!ABC!99")
        self.assertEqual(first.passing_grade, "78.5")
        self.assertEqual(first.letter_grade, "BA")
        self.assertEqual(first.status, "Başarılı")
        self.assertEqual([(e.name, e.score) for e in first.exams], [("Vize", "75"), ("Final", "82")])

        second = courses[1]
        self.assertEqual(second.code, "MAT102")
        self.assertEqual(second.class_id, "99887!XYZ")
        self.assertIsNone(second.passing_grade)
        self.assertIsNone(second.letter_grade)
        self.assertIsNone(second.status)
        self.assertEqual([(e.name, e.score) for e in second.exams], [("Vize", "60"), ("Final", None)])

    def test_parse_class_detail(self) -> None:
        detail = parse_class_detail(SAMPLE_CLASS_DETAIL_HTML)
        self.assertEqual(detail["instructor"], "Dr. Öğr. Üyesi Ahmet Yılmaz")
        self.assertEqual(detail["class_average"], "58.4")
        self.assertEqual(detail["letter_grade"], "BA")

        exams = detail["exams"]
        self.assertEqual(len(exams), 4)
        self.assertEqual(exams[0].exam_type, "Ara Sınav")
        self.assertEqual(exams[0].name, "Vize")
        self.assertEqual(exams[0].score, "75")
        self.assertEqual(exams[0].ranking, "12 / 85")
        self.assertEqual(exams[0].class_average, "54.25")
        self.assertEqual(exams[0].announcement_date, "15.11.2025 14:30")

        self.assertEqual(exams[1].name, "Quiz 1")
        self.assertEqual(exams[1].score, "G")

        self.assertEqual(exams[2].name, "Final")
        self.assertEqual(exams[2].score, "82.5")

        self.assertEqual(exams[3].name, "Bütünleme")
        self.assertIsNone(exams[3].score)

    def test_session_expired_raises(self) -> None:
        with self.assertRaises(SessionExpiredError):
            parse_grades_index(SAMPLE_LOGIN_HTML)
        with self.assertRaises(SessionExpiredError):
            parse_class_detail(SAMPLE_LOGIN_HTML)


class DifferAndStateTests(unittest.TestCase):
    def test_diff_courses_detects_new_updated_and_preserves_failed_detail(self) -> None:
        prev = {
            "2025-2026 Güz::MAT102": CourseGrade(
                semester="2025-2026 Güz",
                code="MAT102",
                name="Matematik II",
                passing_grade=None,
                letter_grade=None,
                status=None,
                exams=[
                    ExamGrade(exam_type="Ara Sınav", name="Vize", score="60"),
                    ExamGrade(exam_type="Yarıyıl Sonu", name="Final", score=None),
                ],
            ).to_dict(),
            "2025-2026 Güz::FIZ101": CourseGrade(
                semester="2025-2026 Güz",
                code="FIZ101",
                name="Fizik I",
                exams=[ExamGrade(exam_type="Ara Sınav", name="Vize", score="50")],
            ).to_dict(),
        }

        curr_mat = CourseGrade(
            semester="2025-2026 Güz",
            code="MAT102",
            name="Matematik II",
            passing_grade="72",
            letter_grade="BB",
            status="Başarılı",
            exams=[
                ExamGrade(exam_type="Ara Sınav", name="Vize", score="65"),
                ExamGrade(exam_type="Yarıyıl Sonu", name="Final", score="G", class_average="45"),
            ],
        )
        # Detay çekimi başarısız oldu -> önceki sınavlar korunmalı, sahte bildirim/silme olmamalı
        curr_fiz_failed = CourseGrade(
            semester="2025-2026 Güz",
            code="FIZ101",
            name="Fizik I",
            exams=[],
            detail_fetched=False,
        )

        changes = diff_courses(prev, [curr_mat, curr_fiz_failed])
        change_types = [(c.course_code, c.change_type, c.label, c.old_value, c.new_value) for c in changes]

        self.assertIn(("MAT102", "updated_exam_score", "Ara Sınav - Vize", "60", "65"), change_types)
        self.assertIn(("MAT102", "new_exam_score", "Yarıyıl Sonu - Final", None, "G"), change_types)
        self.assertIn(("MAT102", "new_passing_grade", "Geçme Notu", None, "72"), change_types)
        self.assertIn(("MAT102", "new_letter_grade", "Harf Notu (HBN)", None, "BB"), change_types)
        self.assertIn(("MAT102", "status_changed", "Başarı Durumu", None, "Başarılı"), change_types)
        self.assertFalse(any(c.course_code == "FIZ101" for c in changes))

        snapshot = build_course_snapshot([curr_mat, curr_fiz_failed], previous_courses=prev)
        self.assertEqual(len(snapshot["2025-2026 Güz::FIZ101"]["exams"]), 1)
        self.assertEqual(snapshot["2025-2026 Güz::FIZ101"]["exams"][0]["score"], "50")

        # Değişiklik yoksa boş liste dönmeli
        self.assertEqual(diff_courses(snapshot, [curr_mat, curr_fiz_failed]), [])

    def test_state_roundtrip_turkish_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "nested" / "grades_state.json"
            payload = {
                "schema_version": 1,
                "baseline_initialized": True,
                "courses": {
                    "2025-2026 Güz::ÖĞR101": {
                        "semester": "2025-2026 Güz",
                        "code": "ÖĞR101",
                        "name": "Türkçe & İletişim",
                    }
                },
            }
            save_state(state_path, payload)
            loaded = load_state(state_path)
            self.assertEqual(loaded, payload)


class NotifierAndFlowTests(unittest.TestCase):
    def test_telegram_formatting_escaping_and_chunking(self) -> None:
        courses = parse_grades_index(SAMPLE_GRADES_INDEX_HTML)
        baseline_msg = format_baseline_summary(courses)
        self.assertIn("Veri Yapıları &amp; Algoritmalar", baseline_msg)
        self.assertIn("Kastamonu ÜBYS Not Takibi Başlatıldı", baseline_msg)

        changes = diff_courses({}, [courses[0]])
        msg = format_grade_changes(changes, "https://ubys.kastamonu.edu.tr")
        self.assertIn("Veri Yapıları &amp; Algoritmalar", msg)
        self.assertIn("BA", msg)
        self.assertIn("https://ubys.kastamonu.edu.tr", msg)

        long_text = "\n".join(f"Satır {i}: " + ("x" * 100) for i in range(60))
        chunks = split_message(long_text, max_length=1000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual("\n".join(chunks), long_text)

    def test_run_once_baseline_and_error_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "grades_state.json"
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                alert_after_consecutive_errors=2,
                enable_dining=False,
                enable_calendar=False,
                enable_catalog=False,
                enable_weather=False,
                enable_announcements=False,
                enable_schedule=False,
                enable_exam_schedule=False,
                enable_materials=False,
                enable_weekly_briefing=False,
                enable_commands=False,
            )

            sample_courses = [
                CourseGrade(
                    semester="2025-2026 Güz",
                    code="BLM201",
                    name="Veri Yapıları",
                    exams=[ExamGrade(exam_type="Ara Sınav", name="Vize", score="75")],
                )
            ]

            with (
                patch("src.main.UBYSClient") as mock_client_cls,
                patch("src.main.TelegramNotifier") as mock_notifier_cls,
            ):
                instance = mock_client_cls.return_value.__enter__.return_value
                instance.login.side_effect = LoginError("Kullanıcı adı veya parola hatalı.")

                # Aynı giriş hatası 2 kez tekrarlanınca yalnızca 1 kez uyarı atmalı
                self.assertEqual(run_once(cfg), 1)
                self.assertEqual(run_once(cfg), 1)
                self.assertEqual(mock_notifier_cls.return_value.send_message.call_count, 1)

                # Şifre düzeltilip ilk başarılı çekim yapıldığında baseline olarak çalışmalı
                instance.login.side_effect = None
                instance.fetch_grades.return_value = sample_courses
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(mock_notifier_cls.return_value.send_message.call_count, 2)
                last_msg = mock_notifier_cls.return_value.send_message.call_args[0][0]
                self.assertIn("Kastamonu ÜBYS Not Takibi Başlatıldı", last_msg)

                # Ardışık ağ hatalarında alert_after_consecutive_errors=2 iken 2. hatada bildirmeli
                instance.fetch_grades.side_effect = NetworkError("Zaman aşımı")
                self.assertEqual(run_once(cfg), 1)
                self.assertEqual(mock_notifier_cls.return_value.send_message.call_count, 2)
                self.assertEqual(run_once(cfg), 1)
                self.assertEqual(mock_notifier_cls.return_value.send_message.call_count, 3)


class ConfigAndGistTests(unittest.TestCase):
    def test_legacy_env_aliases_and_gist_validation(self) -> None:
        env = {
            "OGRENCI_NO": "221234567",
            "SIFRE": "parola123",
            "BOT_TOKEN": "123:ABC",
            "CHAT_ID": "998877, 112233",
            "GIST_ID": "abc123gist",
            "GIST_TOKEN": "ghp_secret",
        }
        with patch("src.config.load_dotenv", None), patch.dict(os.environ, env, clear=True):
            cfg = load_config()
            self.assertEqual(cfg.ubys_username, "221234567")
            self.assertEqual(cfg.ubys_password, "parola123")
            self.assertEqual(cfg.telegram_bot_token, "123:ABC")
            self.assertEqual(cfg.telegram_chat_ids, ["998877", "112233"])
            self.assertEqual(cfg.gist_id, "abc123gist")
            self.assertEqual(cfg.gist_token, "ghp_secret")
            self.assertEqual(cfg.gist_filename, "grades_state.json")

        partial_gist_env = {
            "OGRENCI_NO": "221234567",
            "SIFRE": "parola123",
            "BOT_TOKEN": "123:ABC",
            "CHAT_ID": "998877",
            "GIST_ID": "abc123gist",
        }
        with patch("src.config.load_dotenv", None), patch.dict(os.environ, partial_gist_env, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_gist_state_store_load_and_save(self) -> None:
        store = GistStateStore(gist_id="gist123", gist_token="tok456", filename="grades_state.json")
        state_payload = {
            "schema_version": 1,
            "baseline_initialized": True,
            "courses": {"2025-2026 Güz::BLM201": {"code": "BLM201"}},
        }

        with patch("src.differ.httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value

            # 1. grades_state.json mevcutsa yükler
            resp_ok = MagicMock(status_code=200)
            resp_ok.json.return_value = {
                "files": {
                    "grades_state.json": {
                        "truncated": False,
                        "content": json.dumps(state_payload, ensure_ascii=False),
                    }
                }
            }
            client.get.return_value = resp_ok
            self.assertEqual(store.load(), state_payload)

            # 2. Yalnızca eski notlar.json varsa None döner (sıfırdan temiz başlar)
            resp_legacy = MagicMock(status_code=200)
            resp_legacy.json.return_value = {
                "files": {
                    "notlar.json": {"truncated": False, "content": "{}"}
                }
            }
            client.get.return_value = resp_legacy
            self.assertIsNone(store.load())

            # 3. HTTP 401 durumunda StateStorageError fırlatır
            client.get.return_value = MagicMock(status_code=401)
            with self.assertRaises(StateStorageError):
                store.load()

            # 4. save() PATCH gövdesini doğrular
            client.patch.return_value = MagicMock(status_code=200)
            store.save(state_payload)
            _, kwargs = client.patch.call_args
            sent_content = kwargs["json"]["files"]["grades_state.json"]["content"]
            self.assertEqual(json.loads(sent_content), state_payload)

            # 5. save() HTTP 403 durumunda StateStorageError fırlatır
            client.patch.return_value = MagicMock(status_code=403)
            with self.assertRaises(StateStorageError):
                store.save(state_payload)


class RegressionTests(unittest.TestCase):
    def test_inline_nested_table_colon_and_girmedi_dedup(self) -> None:
        html = """
        <div class="panel panel-default">
          <div class="panel-heading">2026 - Güz</div>
          <table>
            <thead>
              <tr>
                <th>Ders Kodu</th>
                <th>Ders Adı</th>
                <th>Kredi</th>
                <th>AKTS</th>
                <th>Devam</th>
                <th>Vize</th>
                <th>Geçme Notu</th>
                <th>HBN</th>
                <th>Başarı Durumu</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td rowspan="2"><a href="/AIS/Student/Class/ClassDetail?classId=ABC%21">BPBZ201</a></td>
                <td>İnternet Programcılığı</td>
                <td>3</td>
                <td>5</td>
                <td>-</td>
                <td>-</td>
                <td>0</td>
                <td>-</td>
                <td>Devamlı</td>
              </tr>
              <tr>
                <td colspan="8">
                  <table>
                    <tr><td>Vize :</td><td>Girmedi</td></tr>
                    <tr><td>Final :</td><td>Girmedi</td></tr>
                  </table>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        """
        self.assertIsNone(normalize_score("Girmedi"))
        self.assertEqual(normalize_score("G"), "G")

        courses = parse_grades_index(html)
        self.assertEqual(len(courses), 1)
        self.assertEqual([(e.name, e.score) for e in courses[0].exams], [("Vize", None), ("Final", None)])

    def test_telegram_notifier_retries_on_timeout_and_uses_ipv4(self) -> None:
        notifier = TelegramNotifier("bot-token", ["12345"], timeout=10.0, max_retries=3, retry_delay=0.5)
        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = {"ok": True}

        with (
            patch("src.notifier.httpx.HTTPTransport") as mock_transport,
            patch("src.notifier.httpx.Client") as mock_client_cls,
            patch("src.notifier.time.sleep") as mock_sleep,
        ):
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.side_effect = [
                httpx.ReadTimeout("The read operation timed out"),
                ok_resp,
            ]

            notifier.send_message("Merhaba test")

            mock_transport.assert_called_once_with(local_address="0.0.0.0")
            self.assertEqual(client.post.call_count, 2)
            mock_sleep.assert_called_once_with(0.5)


SAMPLE_SKS_HTML = """
<html><body>
  <a href="https://sks.kastamonu.edu.tr/images/formlar/BARINMA%20BILGI.pdf">Barınma</a>
  <a href="https://docs.google.com/spreadsheets/d/1h0bA-ByWSHOF5CGWMgsHPkSZ7WgiXMyTwrZlcu6Po0E/edit#gid=0">
    <i class="fas fa-money-bill-wave"></i> Yemekhane Listesi
  </a>
</body></html>
"""

SAMPLE_DINING_CSV = """\ufeff,,,,,,,,,
,KASTAMONU ÜNİVERSİTESİ REKTÖRLÜĞÜ 2026 GÜNCEL YEMEK LİSTESİ,,,,,,,,
,TARİH,1.YEMEK,,2.YEMEK,,3.YEMEK,,SOĞUK ÇEŞİTLER,
,2.11.2026,EZOGELİN Ç.,185KKAL,PÜRELİ TAVUK ŞİNİTZEL,474KKAL,SOSLU MAKARNA,365KKAL,MEVSİM SALATA,30KKAL
,4.11.2026,KAŞ. DOM. Ç.,189KKAL,KIYMALI FIRIN PATATES/ SOSLU FIRIN TAVUK,224KKAL/ 302KKAL,BULGUR PİLAVI,219KKAL,AYRAN,44KKAL
,19.11.2026,EZOGELİN Ç.,185KKAL,PÜRELİ ROSTO KÖFTE,370KKAL,SEBZELİ MAKARNA,348KKAL,CEVİZLİ KABAK TATLISI,194KKAL
,1.12.2026,EZOGELİN Ç.,185KKAL,ÇOBAN KAVURMA,332KKAL,SEBZELİ BULGUR PİLAVI,143KKAL,CEVİZLİ KABAK TATLISI,194KKAL
,Türker İhsan DEMİRTAŞ,,,Ali ACARCA,,,Mehmet Sena AYGÜL,,
"""


class DiningTests(unittest.TestCase):
    def test_turkish_title_and_sheet_link_extraction(self) -> None:
        self.assertEqual(tr_title("PÜRELİ ROSTO KÖFTE"), "Püreli Rosto Köfte")
        self.assertEqual(tr_title("İZMİR KÖFTE"), "İzmir Köfte")
        self.assertEqual(tr_title("IZGARA KÖFTE(BULGUR PİLAVI GARNİ.)"), "Izgara Köfte (Bulgur Pilavı Garni.)")
        self.assertEqual(tr_title("PİRİNÇ PİLAVI"), "Pirinç Pilavı")

        sheet_url = extract_dining_sheet_url(SAMPLE_SKS_HTML)
        self.assertEqual(
            sheet_url,
            "https://docs.google.com/spreadsheets/d/1h0bA-ByWSHOF5CGWMgsHPkSZ7WgiXMyTwrZlcu6Po0E/edit#gid=0",
        )
        self.assertEqual(
            build_csv_export_url(sheet_url or ""),
            "https://docs.google.com/spreadsheets/d/1h0bA-ByWSHOF5CGWMgsHPkSZ7WgiXMyTwrZlcu6Po0E/export?format=csv&gid=0",
        )

    def test_parse_dining_csv_dates_calories_and_formatting(self) -> None:
        menus = parse_dining_csv(SAMPLE_DINING_CSV, source_url="https://sks.kastamonu.edu.tr/")
        self.assertEqual([m.menu_date for m in menus], [
            date(2026, 11, 2),
            date(2026, 11, 4),
            date(2026, 11, 19),
            date(2026, 12, 1),
        ])

        nov4 = menus[1]
        self.assertEqual(nov4.items[1].name, "Kıymalı Fırın Patates / Soslu Fırın Tavuk")
        self.assertEqual(nov4.items[1].calories, "224/302 kkal")
        self.assertEqual(nov4.total_calories_min, 189 + 224 + 219 + 44)
        self.assertEqual(nov4.total_calories_max, 189 + 302 + 219 + 44)

        nov19 = menus[2]
        self.assertEqual(nov19.total_calories_min, 1097)
        self.assertEqual(nov19.total_calories_max, 1097)

        # Hafta sonu fallback (21.11 Cumartesi -> 1.12)
        next_menu = get_next_menu(menus, date(2026, 11, 21))
        self.assertIsNotNone(next_menu)
        self.assertEqual(next_menu.menu_date, date(2026, 12, 1))

        msg = format_daily_menu(nov4)
        self.assertIn("Günün Yemekhane Menüsü", msg)
        self.assertIn("4 Kasım 2026, Çarşamba", msg)
        self.assertIn("676–754 kkal", msg)


class CalendarTests(unittest.TestCase):
    def test_faculty_resolution_term_and_filtering(self) -> None:
        self.assertEqual(resolve_faculty_name("GENEL"), "Genel")
        self.assertEqual(resolve_faculty_name("TIP"), "Tıp Fakültesi")
        self.assertEqual(resolve_faculty_name("VET"), "Veteriner Fakültesi")
        self.assertEqual(resolve_faculty_name("DIS"), "Diş Hekimliği Fakültesi")
        self.assertEqual(resolve_faculty_name("LISANSUSTU"), "Lisansüstü Eğitim Enstitüsü")
        self.assertEqual(resolve_faculty_name("TURIZM"), "Turizm Fakültesi")

        html = '<div class="timeline"><div class="timeline-item active" data-donem="2026-2027">2026-2027</div></div>'
        self.assertEqual(extract_active_term(html), "2026-2027")

        api_groups = [
            {
                "ay": 11,
                "yil": 2026,
                "etkinlikler": [
                    {
                        "id": 101,
                        "baslamaTarihi": "26.11.2026",
                        "bitisTarihi": "26.11.2026",
                        "etkinlikAdi": "Güz Yarıyılı Ara Sınavlar",
                        "kategori": "Ders ve Sınav",
                        "donem": "2026-2027",
                        "fakulte": "Genel",
                        "googleCalendarUrl": "https://calendar.google.com/calendar/render?text=Vize",
                    },
                    {
                        "id": 102,
                        "baslamaTarihi": "22.11.2026",
                        "bitisTarihi": "24.11.2026",
                        "etkinlikAdi": "Pedagojik Formasyon Kayıtları",
                        "kategori": "Pedagojik Formasyon",
                        "donem": "2026-2027",
                        "fakulte": "Genel",
                    },
                    {
                        "id": 103,
                        "baslamaTarihi": "20.11.2026",
                        "bitisTarihi": "29.11.2026",
                        "etkinlikAdi": "Güz Yarıyılı Ara Sınav Not Girişi",
                        "kategori": "Ders ve Sınav",
                        "donem": "2026-2027",
                        "fakulte": "Genel",
                    },
                    {
                        "id": 104,
                        "baslamaTarihi": "21.09.2026",
                        "bitisTarihi": "08.01.2027",
                        "etkinlikAdi": "Güz Yarıyılı Ders Başlama/Ders Bitiş",
                        "kategori": "Ders ve Sınav",
                        "donem": "2026-2027",
                        "fakulte": "Genel",
                    },
                ],
            }
        ]
        all_events = parse_calendar_api_json(api_groups)
        self.assertEqual(len(all_events), 4)

        student_events = filter_events_by_categories(all_events, "STUDENT")
        self.assertEqual([e.event_id for e in student_events], ["104", "103", "101"])
        self.assertEqual(len(filter_events_by_categories(all_events, "ALL")), 4)

        today = date(2026, 11, 20)
        # 101: 6 gün sonra (eşiğin dışında), 103: bugün (0 gün kaldı)
        reminders = find_milestone_reminders(student_events, today, [7, 3, 1, 0], sent_milestones={})
        self.assertEqual([(e.event_id, d) for e, d in reminders], [("103", 0)])

        # 19 Kasım'da 101 tam 7 gün kala eşiğinde
        reminders_19 = find_milestone_reminders(
            student_events,
            date(2026, 11, 19),
            [7, 3, 1, 0],
            sent_milestones={},
        )
        self.assertEqual([(e.event_id, d) for e, d in reminders_19], [("103", 1), ("101", 7)])
        # Tekrar bildirilmemeli
        self.assertEqual(
            find_milestone_reminders(
                student_events,
                date(2026, 11, 19),
                [7, 3, 1, 0],
                sent_milestones={"101:7": "2026-11-19", "103:1": "2026-11-19"},
            ),
            [],
        )

        ongoing, upcoming = find_ongoing_and_upcoming(student_events, today, lookahead_days=30)
        # 104 tüm dönem (109 gün, sınav/kayıt değil) gürültü olarak dışarıda kalmalı, 103 devam edende olmalı
        self.assertEqual([e.event_id for e in ongoing], ["103"])
        self.assertEqual([e.event_id for e in upcoming], ["101"])

        rem_msg = format_calendar_reminders(reminders_19, "Genel", "https://akademiktakvim.kastamonu.edu.tr/")
        self.assertIn("7 GÜN KALDI", rem_msg)
        self.assertIn("Google Takvime Ekle", rem_msg)

        digest_msg = format_calendar_digest(
            ongoing,
            upcoming,
            today,
            "Genel",
            "2026-2027",
            30,
            "https://akademiktakvim.kastamonu.edu.tr/",
        )
        self.assertIn("Şu An Devam Edenler", digest_msg)
        self.assertIn("Yaklaşan Etkinlikler", digest_msg)


class SwissToolFlowTests(unittest.TestCase):
    def test_run_once_dining_calendar_dedup_and_error_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=True,
                enable_dining=True,
                enable_calendar=True,
                enable_catalog=False,
                enable_weather=False,
                enable_announcements=False,
                enable_schedule=False,
                enable_exam_schedule=False,
                enable_materials=False,
                enable_weekly_briefing=False,
                enable_commands=False,
                notify_on_first_run=False,
            )

            sample_courses = [
                CourseGrade(
                    semester="2026 - Güz",
                    code="BPBZ201",
                    name="İnternet Programcılığı",
                )
            ]
            # 23 Kasım 2026 Pazartesi, saat 09:00 TR -> hafta içi & Pazartesi özet günü
            monday_dt = datetime(2026, 11, 23, 9, 0, tzinfo=TR_TZ)
            monday_menu = DailyMenu(
                menu_date=date(2026, 11, 23),
                items=[DiningItem(name="Mercimek Ç.", calories="120 kkal", category="Çorba")],
                total_calories_min=120,
                total_calories_max=120,
            )
            cal_event = CalendarEvent(
                event_id="500",
                title="Güz Ara Sınav",
                start_date=date(2026, 11, 30),
                end_date=date(2026, 12, 4),
                category="Ders ve Sınav",
                faculty="Genel",
                term="2026-2027",
            )

            with (
                patch("src.main.now_tr", return_value=monday_dt),
                patch("src.main.UBYSClient") as mock_ubys,
                patch("src.main.fetch_dining_menus", return_value=[monday_menu]) as mock_dining,
                patch(
                    "src.main.fetch_calendar_events",
                    return_value=("Genel", "2026-2027", [cal_event]),
                ) as mock_cal,
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                ubys_inst = mock_ubys.return_value.__enter__.return_value
                ubys_inst.fetch_grades.return_value = sample_courses
                ubys_inst.last_home_gano = None

                # İlk çalıştırma: 1 yemekhane + 1 takvim hatırlatması (7 gün kala) + 1 Pazartesi özeti = 3 mesaj
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(mock_notifier.return_value.send_message.call_count, 3)

                # Aynı gün ikinci çalıştırma: yemekhane ve takvim tekrar gönderilmemeli
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(mock_notifier.return_value.send_message.call_count, 3)
                self.assertEqual(mock_dining.call_count, 1)
                self.assertEqual(mock_cal.call_count, 1)

            # Ertesi gün Salı (24 Kasım) saat 09:00 -> Yemekhane hata verse bile not takibi 0 dönmeli
            tuesday_dt = datetime(2026, 11, 24, 9, 0, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=tuesday_dt),
                patch("src.main.UBYSClient") as mock_ubys,
                patch("src.main.fetch_dining_menus", side_effect=DiningError("SKS geçici hata")),
                patch("src.main.fetch_calendar_events", side_effect=CalendarError("Takvim geçici hata")),
                patch("src.main.TelegramNotifier"),
            ):
                tue_inst = mock_ubys.return_value.__enter__.return_value
                tue_inst.fetch_grades.return_value = sample_courses
                tue_inst.last_home_gano = None
                self.assertEqual(run_once(cfg), 0)


class GradeCalculatorTests(unittest.TestCase):
    def test_vize_100_final_targets_and_baraj(self) -> None:
        self.assertEqual(score_to_letter(90), ("AA", 4.0))
        self.assertEqual(score_to_letter(55), ("DC", 1.5))
        self.assertEqual(score_to_letter(39), ("FF", 0.0))

        analysis = calculate_final_targets(100, midterm_weight=0.40, final_weight=0.60, final_min_score=0)
        targets = {t.letter: (t.required_final, t.status) for t in analysis.targets}
        self.assertEqual(targets["DC"], (25, "achievable"))
        self.assertEqual(targets["CC"], (34, "achievable"))
        self.assertEqual(targets["CB"], (42, "achievable"))
        self.assertEqual(targets["BB"], (59, "achievable"))
        self.assertEqual(targets["BA"], (75, "achievable"))
        self.assertEqual(targets["AA"], (84, "achievable"))

        # Final alt barajı 50 iken DC/CC/CB en az 50 olmalı
        baraj = calculate_final_targets(100, final_min_score=50)
        baraj_map = {t.letter: t.required_final for t in baraj.targets}
        self.assertEqual(baraj_map["DC"], 50)
        self.assertEqual(baraj_map["CC"], 50)
        self.assertEqual(baraj_map["CB"], 50)
        self.assertEqual(baraj_map["BB"], 59)

        # Vize 20 iken BB/BA/AA imkansız, maks 68.0 (CB)
        low = calculate_final_targets(20)
        self.assertEqual(low.max_possible_total, 68.0)
        self.assertEqual(low.max_possible_letter, "CB")
        low_map = {t.letter: t.status for t in low.targets}
        self.assertEqual(low_map["BB"], "impossible")
        self.assertEqual(low_map["AA"], "impossible")
        self.assertEqual(low_map["CC"], "achievable")

        calc_msg = format_grade_calculator(analysis)
        self.assertIn("Finalden <code>34</code>+", calc_msg)

    def test_estimate_and_grade_change_integration(self) -> None:
        est = estimate_course_grade(80, 70)
        self.assertEqual(est.weighted_total, 74.0)
        self.assertEqual(est.letter_grade, "CB")
        self.assertEqual(est.coefficient, 2.5)
        self.assertTrue(est.is_passing)

        # Final barajı altında kalan final FF olmalı
        est_baraj = estimate_course_grade(100, 45, final_min_score=50)
        self.assertEqual(est_baraj.letter_grade, "FF")
        self.assertFalse(est_baraj.is_passing)

        course_vize = CourseGrade(
            semester="2026 - Güz",
            code="BPBZ201",
            name="İnternet Programcılığı",
            exams=[ExamGrade(exam_type="Ara Sınav", name="Vize", score="100")],
        )
        changes_vize = diff_courses({}, [course_vize])
        msg_vize = format_grade_changes(changes_vize, "https://ubys.kastamonu.edu.tr", courses=[course_vize])
        self.assertIn("Final Hedefleri", msg_vize)
        self.assertIn("Finalden <code>34</code>+", msg_vize)

        course_both = CourseGrade(
            semester="2026 - Güz",
            code="BPBZ201",
            name="İnternet Programcılığı",
            exams=[
                ExamGrade(exam_type="Ara Sınav", name="Vize", score="80"),
                ExamGrade(exam_type="Yarıyıl Sonu", name="Final", score="70"),
            ],
        )
        changes_both = diff_courses({}, [course_both])
        msg_both = format_grade_changes(changes_both, "https://ubys.kastamonu.edu.tr", courses=[course_both])
        self.assertIn("Tahmini Ortalama", msg_both)
        self.assertIn("74.00", msg_both)
        self.assertIn("CB", msg_both)


class AttendanceTests(unittest.TestCase):
    def test_theory_practice_mixed_and_risk_levels(self) -> None:
        # Teorik 3 saat * 14 hafta * 0.30 = 12.6 -> floor 12 saat (4 gün)
        # 9 saat = 3 gün kullanıldığında 3 saat = 1 tam gün kalır -> warning
        c_warn = CourseGrade(
            semester="2026 - Güz",
            code="BLM101",
            name="Algoritmalar",
            theoretical_hours=3.0,
            practical_hours=0.0,
            absent_total_hours=9.0,
            attendance_status="Devamlı",
        )
        r_warn = evaluate_course_attendance(c_warn)
        self.assertEqual(r_warn.max_total_absent, 12.0)
        self.assertEqual(r_warn.remaining_total, 3.0)
        self.assertEqual(r_warn.max_total_days, 4)
        self.assertEqual(r_warn.used_total_days, 3.0)
        self.assertEqual(r_warn.remaining_total_days, 1)
        self.assertEqual(r_warn.risk_level, "warning")

        # 10 saat kullanıldığında 2 saat kalır -> 0 tam gün -> critical
        c_crit = CourseGrade(
            semester="2026 - Güz",
            code="BLM101",
            name="Algoritmalar",
            theoretical_hours=3.0,
            practical_hours=0.0,
            absent_total_hours=10.0,
            attendance_status="Devamlı",
        )
        r_crit = evaluate_course_attendance(c_crit)
        self.assertEqual(r_crit.remaining_total_days, 0)
        self.assertEqual(r_crit.risk_level, "critical")

        # Uygulamalı 2 saat * 14 hafta * 0.20 = 5.6 -> floor 5 saat (2 tam gün)
        c_prac = CourseGrade(
            semester="2026 - Güz",
            code="LAB102",
            name="Fizik Lab",
            theoretical_hours=0.0,
            practical_hours=2.0,
            absent_total_hours=4.0,
        )
        r_prac = evaluate_course_attendance(c_prac)
        self.assertEqual(r_prac.max_practice_absent, 5.0)
        self.assertEqual(r_prac.remaining_practice, 1.0)
        self.assertEqual(r_prac.max_practice_days, 2)
        self.assertEqual(r_prac.remaining_practice_days, 0)
        self.assertEqual(r_prac.risk_level, "critical")

        # Karma 2+2 -> Teorik 8 saat (4 gün), Uygulama 5 saat (2 gün)
        c_mix = CourseGrade(
            semester="2026 - Güz",
            code="KRM202",
            name="Karma Ders",
            theoretical_hours=2.0,
            practical_hours=2.0,
            absent_theoretical_hours=2.0,
            absent_practical_hours=1.0,
        )
        r_mix = evaluate_course_attendance(c_mix)
        self.assertEqual(r_mix.max_theory_absent, 8.0)
        self.assertEqual(r_mix.remaining_theory, 6.0)
        self.assertEqual(r_mix.max_practice_absent, 5.0)
        self.assertEqual(r_mix.remaining_practice, 4.0)
        self.assertEqual(r_mix.max_theory_days, 4)
        self.assertEqual(r_mix.remaining_theory_days, 3)
        self.assertEqual(r_mix.max_practice_days, 2)
        self.assertEqual(r_mix.remaining_practice_days, 2)
        self.assertEqual(r_mix.max_total_days, 2)
        self.assertEqual(r_mix.remaining_total_days, 2)
        self.assertEqual(r_mix.risk_level, "safe")

    def test_parse_attendance_columns_and_diff_alerts(self) -> None:
        html = """
        <div class="panel panel-default">
          <div class="panel-heading">2026 - Güz</div>
          <table>
            <thead>
              <tr>
                <th>Ders Kodu</th>
                <th>Ders Adı</th>
                <th>T+U</th>
                <th>Kredi</th>
                <th>Devamsızlık</th>
                <th>Vize</th>
                <th>Geçme Notu</th>
                <th>HBN</th>
                <th>Başarı Durumu</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td rowspan="2"><a href="/AIS/Student/Class/ClassDetail?classId=123">BPBZ201</a></td>
                <td>İnternet Programcılığı</td>
                <td>2+2</td>
                <td>3</td>
                <td>4 Saat (%10)</td>
                <td>-</td>
                <td>0</td>
                <td>-</td>
                <td>Devamlı</td>
              </tr>
              <tr><td colspan="8">Vize: -</td></tr>
            </tbody>
          </table>
        </div>
        """
        courses = parse_grades_index(html)
        self.assertEqual(len(courses), 1)
        c = courses[0]
        self.assertEqual(c.theoretical_hours, 2.0)
        self.assertEqual(c.practical_hours, 2.0)
        self.assertEqual(c.absent_total_hours, 4.0)
        self.assertEqual(c.absent_percent, 10.0)
        self.assertEqual(c.attendance_status, "Devamlı")

        prev_reports = evaluate_all_attendance(courses)
        prev_snap = build_attendance_snapshot(prev_reports)

        # Devamsızlık artınca uyarı üretmeli
        c.absent_total_hours = 11.0
        new_reports = evaluate_all_attendance([c])
        alerts = diff_attendance(prev_snap, new_reports)
        self.assertEqual(len(alerts), 1)
        alert_msg = format_attendance_alerts(alerts, "https://ubys.kastamonu.edu.tr")
        self.assertIn("BPBZ201", alert_msg)
        self.assertIn("4", alert_msg)
        self.assertIn("11", alert_msg)

        # Aynı durumda tekrar uyarı üretmemeli
        self.assertEqual(diff_attendance(build_attendance_snapshot(new_reports), new_reports), [])

        rep_msg = format_attendance_report(new_reports, "https://ubys.kastamonu.edu.tr")
        self.assertIn("Devamsızlık Takip Raporu", rep_msg)


class TranscriptTests(unittest.TestCase):
    def test_parse_transcript_jsm_and_html_fallback_and_gano(self) -> None:
        student_info = {"StudentId": 1, "Programs": [{"GANO": 3.42}]}
        info_b64 = base64.b64encode(json.dumps(student_info).encode("utf-8")).decode("ascii")
        home_html = f'<script>var StudentInfo = JSON.parse(Base64.decode("{info_b64}"));</script>'
        self.assertEqual(parse_student_gano(home_html), 3.42)

        jsm_payload = {
            "Transcripts": [
                {
                    "GANO": 3.42,
                    "TotalCredit": 60,
                    "TotalEcts": 90,
                    "Semesters": [
                        {
                            "SemesterName": "2025-2026 Güz",
                            "SemesterAverage": 3.30,
                            "CumulativeAverage": 3.30,
                            "Courses": [
                                {"CourseCode": "BLM101", "CourseName": "Programlama I", "Credit": 4, "Ects": 6, "Grade": "AA"},
                            ],
                        },
                        {
                            "SemesterName": "2025-2026 Bahar",
                            "SemesterAverage": 3.55,
                            "CumulativeAverage": 3.42,
                            "Courses": [
                                {"CourseCode": "BLM102", "CourseName": "Programlama II", "Credit": 4, "Ects": 6, "Grade": "BA"},
                            ],
                        },
                    ],
                }
            ]
        }
        jsm_b64 = base64.b64encode(json.dumps(jsm_payload).encode("utf-8")).decode("ascii")
        summary = parse_transcript(f'<script>var _jsm = JSON.parse(Base64.decode("{jsm_b64}"));</script>')
        self.assertEqual(summary.gano, 3.42)
        self.assertEqual(len(summary.semesters), 2)
        self.assertEqual(summary.semesters[1].courses[0].letter_grade, "BA")

        msg = format_transcript_summary(summary, "https://ubys.kastamonu.edu.tr")
        self.assertIn("3.42", msg)
        self.assertIn("BLM102 - Programlama II", msg)

        gano_msg = format_gano_change(3.30, 3.42, "https://ubys.kastamonu.edu.tr")
        self.assertIn("+0.12", gano_msg)

        # HTML fallback testi
        html_fb = """
        <table id="test">
          <caption><b>1. Yarıyıl</b></caption>
          <tbody>
            <tr><td>MAT101</td><td>Matematik I</td><td>4</td><td>BA</td></tr>
            <tr><td colspan="3">Dönem Ortalaması</td><td>3,25</td></tr>
            <tr><td colspan="3">Birikimli Ortalama</td><td>3,25</td></tr>
          </tbody>
        </table>
        """
        fb_summary = parse_transcript(html_fb)
        self.assertEqual(fb_summary.gano, 3.25)
        self.assertEqual(fb_summary.semesters[0].courses[0].letter_grade, "BA")


class CatalogAndCourseWeightsTests(unittest.TestCase):
    def test_parse_course_detail_jsm_and_extract_curriculum(self) -> None:
        jsm_30_70 = {
            "CourseDetail": {
                "TheoreticalCredit": 3.0,
                "PractiseCredit": 1.0,
                "LaboratoryCredit": 1.0,
                "Credit": 4.0,
                "Ects": 5.0,
            },
            "AssessmentMethodDetailList": [
                {"ExamName": "Vize", "Order": 1, "PercentageContribution": 30.0},
                {"ExamName": "Final", "Order": 9, "PercentageContribution": 70.0},
            ],
        }
        b64_30_70 = base64.b64encode(json.dumps(jsm_30_70).encode("utf-8")).decode("ascii")
        parsed_30 = parse_course_detail_jsm(f'<script>var _jsm = JSON.parse(Base64.decode("{b64_30_70}"));</script>')
        self.assertEqual(parsed_30["theoretical_hours"], 3.0)
        self.assertEqual(parsed_30["practical_hours"], 1.0)
        self.assertEqual(parsed_30["lab_hours"], 1.0)
        self.assertEqual(parsed_30["midterm_weight"], 0.3)
        self.assertEqual(parsed_30["final_weight"], 0.7)

        jsm_multi = {
            "CourseDetail": {"TheoreticalCredit": 4.0, "PractiseCredit": 0.0, "LaboratoryCredit": 0.0},
            "AssessmentMethodDetailList": [
                {"ExamName": "Vize", "PercentageContribution": 30.0},
                {"ExamName": "Ödev", "PercentageContribution": 10.0},
                {"ExamName": "Final", "PercentageContribution": 60.0},
            ],
        }
        b64_multi = base64.b64encode(json.dumps(jsm_multi).encode("utf-8")).decode("ascii")
        parsed_multi = parse_course_detail_jsm(f'<script>_jsm = JSON.parse(Base64.decode("{b64_multi}"));</script>')
        self.assertEqual(parsed_multi["midterm_weight"], 0.3)
        self.assertEqual(parsed_multi["final_weight"], 0.6)
        self.assertEqual(len(parsed_multi["assessments"]), 3)

        cur_json = {
            "CurriculumDetails": [
                {
                    "EncryptedId": "CUR_ENC_1",
                    "CurriculumCources": [
                        {
                            "Course": {
                                "Code": "BPBZ201",
                                "Name": "İnternet Programcılığı",
                                "TheoreticalCredit": 3.0,
                                "PractiseCredit": 1.0,
                                "LaboratoryCredit": 0.0,
                                "Credit": 4.0,
                                "Ects": 4.0,
                                "EncryptedId": "C_ENC_1",
                                "CourseType": 12301,
                                "IsApproved": True,
                                "IsActiveForBologna": True,
                            }
                        },
                        {
                            "ElectivePool": {
                                "ElectivePoolCourses": [
                                    {
                                        "Code": "BPBS213",
                                        "Name": "Nesne Tabanlı Programlama-I",
                                        "TheoreticalCredit": 2.0,
                                        "PractiseCredit": 0.0,
                                        "LaboratoryCredit": 1.0,
                                        "Credit": 3.0,
                                        "Ects": 3.0,
                                        "EncryptedId": "C_ENC_2",
                                        "IsApproved": True,
                                        "IsActiveForBologna": True,
                                    }
                                ]
                            }
                        },
                    ],
                }
            ]
        }
        extracted = extract_curriculum_courses(cur_json)
        self.assertIn("BPBZ201", extracted)
        self.assertIn("BPBS213", extracted)
        self.assertFalse(extracted["BPBZ201"]["is_elective"])
        self.assertTrue(extracted["BPBS213"]["is_elective"])
        self.assertEqual(extracted["BPBS213"]["lab_hours"], 1.0)

    def test_rank_program_candidates_and_hints(self) -> None:
        home_html = """
        <div class="panel">
          <a href="#" onclick="selectAcademicProgram('SAP1')">
            Kastamonu MYO - Bilgisayar Programcılığı
          </a>
        </div>
        <table>
          <tr><th>Bölüm</th><td>Bilgisayar Teknolojileri Bölümü</td></tr>
        </table>
        """
        hints = parse_student_program_hints(home_html)
        self.assertTrue(any("Bilgisayar Programcılığı" in h for h in hints))
        self.assertIn("Bilgisayar Teknolojileri Bölümü", hints)

        units = [
            {
                "IsAcademicProgram": True,
                "AcademicProgramId": 5611,
                "CurriculumId": 100,
                "FullAcademicProgramName": "Cide Rıfat Ilgaz Meslek Yüksekokulu - Bilgisayar Programcılığı",
                "Name": "Bilgisayar Programcılığı",
            },
            {
                "IsAcademicProgram": True,
                "AcademicProgramId": 5511,
                "CurriculumId": 101,
                "FullAcademicProgramName": "Kastamonu Meslek Yüksekokulu Müdürlüğü - Bilgisayar Teknolojileri Bölümü / Bilgisayar Programcılığı",
                "Name": "Bilgisayar Programcılığı",
            },
            {
                "IsAcademicProgram": True,
                "AcademicProgramId": 9999,
                "CurriculumId": 102,
                "FullAcademicProgramName": "Tıp Fakültesi - Tıp",
                "Name": "Tıp",
            },
        ]
        courses = [
            CourseGrade(semester="2026 - Güz", code="BPBZ201", name="İnternet Programcılığı"),
            CourseGrade(semester="2026 - Güz", code="BPBZ207", name="Bilgisayar Ağları"),
        ]

        # 1. SAYISAL ID override doğrudan eşleşmeli
        by_id = rank_program_candidates(units, [], courses, program_override="5511")
        self.assertEqual([u["AcademicProgramId"] for u in by_id], [5511])

        # 2. Home/Index hint'leri ("Kastamonu MYO ...") Cide yerine 5511'i öne geçirmeli
        by_hint = rank_program_candidates(units, hints, courses)
        self.assertEqual(by_hint[0]["AcademicProgramId"], 5511)

        # 3. Sıfır hint olsa bile BP ön eki + Bilgisayar ders adı ile Bilgisayar Programcılığı adaylarını Tıp önüne geçirmeli
        by_courses = rank_program_candidates(units, [], courses)
        self.assertIn(by_courses[0]["AcademicProgramId"], {5511, 5611})
        self.assertNotIn(9999, [u["AcademicProgramId"] for u in by_courses])

    def test_weight_priority_chain_and_calc_cli(self) -> None:
        # 1. parse_weight_pair + config parsing
        self.assertEqual(parse_weight_pair("30/70"), (0.3, 0.7))
        self.assertEqual(parse_weight_pair("30"), (0.3, 0.7))
        self.assertEqual(parse_weight_pair("0.35-0.65"), (0.35, 0.65))

        env = {
            "OGRENCI_NO": "221234567",
            "SIFRE": "parola123",
            "BOT_TOKEN": "123:ABC",
            "CHAT_ID": "998877",
            "ENABLE_CATALOG": "false",
            "UBYS_PROGRAM": "5511",
            "COURSE_WEIGHTS": "BPBZ201:30/70; BPBZ207=40",
            "COURSE_HOURS": "BPBZ201:3+1, BPBZ207:4",
        }
        with patch("src.config.load_dotenv", None), patch.dict(os.environ, env, clear=True):
            cfg = load_config()
            self.assertFalse(cfg.enable_catalog)
            self.assertEqual(cfg.ubys_program, "5511")
            self.assertEqual(cfg.course_weights, {"BPBZ201": (0.3, 0.7), "BPBZ207": (0.4, 0.6)})
            self.assertEqual(cfg.course_hours, {"BPBZ201": (3.0, 1.0), "BPBZ207": (4.0, 0.0)})

        # 2. UBYS Final henüz girilmemişken bile (score=None) Final weight=%70 + Vize weight=%30 tanınmalı
        course_unscored_final = CourseGrade(
            semester="2026 - Güz",
            code="BPBZ201",
            name="İnternet Programcılığı",
            exams=[
                ExamGrade(exam_type="Ara Sınav", name="Vize", score="100", weight=0.30),
                ExamGrade(exam_type="Yarıyıl Sonu", name="Final", score=None, weight=0.70),
            ],
            midterm_weight=0.40,
            final_weight=0.60,
            weight_source="bologna",
        )
        mw, fw, src = resolve_course_weights(course_unscored_final)
        self.assertEqual((mw, fw, src), (0.30, 0.70, "ubys"))
        analysis, estimate = analyze_course_grades(course_unscored_final)
        self.assertIsNone(estimate)
        assert analysis is not None
        targets_map = {t.letter: t.required_final for t in analysis.targets}
        # 100 * 0.30 + Final * 0.70 >= 60 -> Final >= 30/0.7 = 42.85 -> ceil 43
        self.assertEqual(targets_map["CC"], 43)
        # 100 * 0.30 + Final * 0.70 >= 90 -> Final >= 60/0.7 = 85.71 -> ceil 86
        self.assertEqual(targets_map["AA"], 86)

        # 3. Bologna ağırlığı (UBYS'de weight yoksa %30/%70 kullanılır) + COURSE_WEIGHTS ("manual") hepsini ezer
        course_bologna = CourseGrade(
            semester="2026 - Güz",
            code="BPBZ203",
            name="Görsel Programlama I",
            exams=[
                ExamGrade(exam_type="Ara Sınav", name="Vize", score="100"),
                ExamGrade(exam_type="Yarıyıl Sonu", name="Final", score=None),
            ],
        )
        cat = {
            "BPBZ203": CourseCatalogEntry(
                code="BPBZ203",
                name="Görsel Programlama I",
                theoretical_hours=3.0,
                practical_hours=1.0,
                lab_hours=0.0,
                midterm_weight=0.30,
                final_weight=0.70,
            )
        }
        enrich_courses_with_catalog([course_bologna], cat)
        self.assertEqual((course_bologna.theoretical_hours, course_bologna.practical_hours), (3.0, 1.0))
        self.assertEqual(course_bologna.hours_source, "bologna")
        self.assertEqual(resolve_course_weights(course_bologna), (0.30, 0.70, "bologna"))

        # COURSE_WEIGHTS ("manual") UBYS'den de Bologna'dan da öncelikli
        enrich_courses_with_catalog(
            [course_unscored_final],
            cat,
            course_weights_overrides={"BPBZ201": (0.25, 0.75)},
            course_hours_overrides={"BPBZ201": (2.0, 2.0)},
        )
        self.assertEqual(resolve_course_weights(course_unscored_final), (0.25, 0.75, "manual"))
        self.assertEqual((course_unscored_final.theoretical_hours, course_unscored_final.practical_hours), (2.0, 2.0))
        self.assertEqual(course_unscored_final.hours_source, "manual")

        # 4. --calc 100 --weights 30/70 CLI akışı
        with patch("src.config.load_dotenv", None), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cli_main(["--calc", "100", "--weights", "30/70"]), 0)
            self.assertEqual(cli_main(["--calc", "100", "--weights", "invalid"]), 2)

    def test_day_based_attendance_formatting(self) -> None:
        courses = [
            CourseGrade(
                semester="2026 - Güz",
                code="BPBZ207",
                name="Bilgisayar Ağları",
                theoretical_hours=4.0,
                practical_hours=0.0,
                attendance_status="Devamlı",
            ),
            CourseGrade(
                semester="2026 - Güz",
                code="BPBZ201",
                name="İnternet Programcılığı",
                theoretical_hours=3.0,
                practical_hours=1.0,
                attendance_status="Devamlı",
            ),
            CourseGrade(
                semester="2026 - Güz",
                code="BPBS213",
                name="Nesne Tabanlı Programlama-I",
                theoretical_hours=2.0,
                practical_hours=1.0,
                absent_theoretical_hours=2.0,
                absent_practical_hours=1.0,
                attendance_status="Devamlı",
            ),
            CourseGrade(
                semester="2026 - Güz",
                code="BPBZ205",
                name="Mesleki Yabancı Dil I",
                theoretical_hours=2.0,
                practical_hours=0.0,
                absent_total_hours=7.0,
                attendance_status="Devamlı",
            ),
        ]
        reports = evaluate_all_attendance(courses)
        msg = format_attendance_report(reports, "https://ubys.kastamonu.edu.tr")

        self.assertIn("4 gün hakkın var (16 saat)", msg)
        self.assertIn("Teorik 4 gün (12 saat), Uyg 2 gün (2 saat)", msg)
        self.assertIn("Tam gün: 2 gün hakkın var", msg)
        self.assertIn("Teorik: 1/4 gün (Kalan: 3 gün / 6s)", msg)
        self.assertIn("Uyg: 1/2 gün (Kalan: 1 gün / 1s)", msg)
        self.assertIn("0 tam gün (1 saat)", msg)

    def test_catalog_state_caching_in_run_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=True,
                enable_dining=False,
                enable_calendar=False,
                enable_attendance=True,
                enable_catalog=True,
                enable_weather=False,
                enable_announcements=False,
                enable_schedule=False,
                enable_exam_schedule=False,
                enable_materials=False,
                enable_weekly_briefing=False,
                enable_commands=False,
                notify_on_first_run=False,
            )
            courses_initial = [
                CourseGrade(
                    semester="2026 - Güz",
                    code="BPBZ201",
                    name="İnternet Programcılığı",
                    exams=[ExamGrade(exam_type="Ara Sınav", name="Vize", score="100")],
                )
            ]
            courses_with_new = [
                CourseGrade(semester="2026 - Güz", code="BPBZ201", name="İnternet Programcılığı"),
                CourseGrade(semester="2026 - Güz", code="BPBZ209", name="İşletim Sistemleri"),
            ]
            cat_entries = {
                "BPBZ201": CourseCatalogEntry(
                    code="BPBZ201",
                    name="İnternet Programcılığı",
                    theoretical_hours=3.0,
                    practical_hours=1.0,
                    midterm_weight=0.30,
                    final_weight=0.70,
                ),
                "BPBZ207": CourseCatalogEntry(
                    code="BPBZ207",
                    name="Bilgisayar Ağları",
                    theoretical_hours=4.0,
                    practical_hours=0.0,
                    midterm_weight=0.40,
                    final_weight=0.60,
                ),
            }

            with (
                patch("src.main.UBYSClient") as mock_ubys,
                patch("src.main.fetch_catalog_for_courses", return_value=(cat_entries, 5511, "Kastamonu MYO")) as mock_cat,
                patch("src.main.TelegramNotifier"),
            ):
                inst = mock_ubys.return_value.__enter__.return_value
                inst.last_home_gano = None
                inst.student_program_hints = ["Kastamonu MYO"]

                # 1. İlk çalıştırma: katalog çekilir ve Gist/state içine önbelleklenir
                inst.fetch_grades.return_value = [CourseGrade(**courses_initial[0].__dict__)]
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(mock_cat.call_count, 1)

                saved = load_state(state_path)
                assert saved is not None
                saved_course = saved["courses"]["2026 - Güz::BPBZ201"]
                self.assertEqual(saved_course["theoretical_hours"], 3.0)
                self.assertEqual(saved_course["practical_hours"], 1.0)
                self.assertEqual(saved_course["midterm_weight"], 0.30)
                self.assertEqual(saved_course["final_weight"], 0.70)
                self.assertEqual(saved["swiss_tool"]["course_catalog"]["program_id"], 5511)

                # 2. İkinci çalıştırma aynı derslerle: katalog tekrar sorulmamalı (cache hit)
                inst.fetch_grades.return_value = [
                    CourseGrade(
                        semester="2026 - Güz",
                        code="BPBZ201",
                        name="İnternet Programcılığı",
                        exams=[ExamGrade(exam_type="Ara Sınav", name="Vize", score="100")],
                    )
                ]
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(mock_cat.call_count, 1)

                # 3. Yeni ders kodu gelince katalog yenilenmeli
                inst.fetch_grades.return_value = courses_with_new
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(mock_cat.call_count, 2)

                # 4. Katalog hatasında not takibi yine de başarıyla (0) tamamlanmalı
                mock_cat.side_effect = BolognaCatalogError("Bologna geçici hata")
                saved = load_state(state_path)
                assert saved is not None
                saved["swiss_tool"]["course_catalog"]["updated_date"] = "2020-01-01"
                save_state(state_path, saved)
                inst.fetch_grades.return_value = [
                    CourseGrade(semester="2026 - Güz", code="BPBZ205", name="Mesleki Yabancı Dil I")
                ]
                self.assertEqual(run_once(cfg), 0)


class WeatherTests(unittest.TestCase):
    def test_wmo_advice_and_open_meteo_parse(self) -> None:
        self.assertEqual(describe_wmo_code(73), ("Kar Yağışlı", "❄️"))
        advice_snow = build_weather_advice(-2.0, 3.0, 80, 35.0, 73)
        self.assertIn("Kar yağışı", advice_snow)
        self.assertIn("don riski", advice_snow)
        self.assertIn("Rüzgâr", advice_snow)

        sample_json = {
            "current": {
                "temperature_2m": 6.4,
                "apparent_temperature": 4.1,
                "weather_code": 61,
                "wind_speed_10m": 14.0,
            },
            "daily": {
                "time": ["2026-11-23", "2026-11-24", "2026-11-25"],
                "weather_code": [61, 2, 0],
                "temperature_2m_min": [2.0, 1.0, -1.0],
                "temperature_2m_max": [10.0, 12.0, 13.0],
                "precipitation_probability_max": [75, 20, 5],
            },
        }
        wf = parse_open_meteo_response(sample_json, "Kastamonu (Kuzeykent)")
        self.assertEqual(wf.forecast_date, date(2026, 11, 23))
        self.assertEqual(wf.condition_text, "Hafif Yağmur")
        self.assertEqual(wf.precip_probability, 75)
        self.assertIn("şemsiye", wf.advice)
        self.assertEqual(len(wf.daily_summaries), 3)
        self.assertIsNotNone(wf.tomorrow_summary)

        report_msg = format_weather_report(wf)
        self.assertIn("Kastamonu (Kuzeykent) Hava Durumu", report_msg)
        self.assertIn("3 Günlük Görünüm", report_msg)

        menu = DailyMenu(
            menu_date=date(2026, 11, 23),
            items=[DiningItem(name="Mercimek Ç.", calories="120 kkal", category="Çorba")],
            total_calories_min=120,
            total_calories_max=120,
        )
        menu_with_weather = format_daily_menu(menu, weather=wf)
        self.assertIn("Kastamonu (Kuzeykent)", menu_with_weather)
        self.assertIn("Hafif Yağmur", menu_with_weather)


class AnnouncementTests(unittest.TestCase):
    def test_joomla_portal_ubys_and_keyword_filtering(self) -> None:
        joomla_html = """
        <div class="sppb-addon">
          <a class="sppb-articles-scroller-link" href="/duyurular/123-guz-sinav-programi">
            <span class="sppb-articles-scroller-day">18</span>
            <span class="sppb-articles-scroller-month">Kas</span>
            <div class="sppb-addon-articles-scroller-title">2026-2027 Güz Yarıyılı Ara Sınav Takvimi Açıklandı</div>
            <div class="sppb-articles-scroller-introtext">Sınav salonları ÜBYS üzerinden ilan edilmiştir.</div>
          </a>
          <a class="sppb-articles-scroller-link" href="/duyurular/124-yemek-kart">
            <span class="sppb-articles-scroller-day">17</span>
            <span class="sppb-articles-scroller-month">Kas</span>
            <div class="sppb-addon-articles-scroller-title">Yemek Kartı Bakiye Yükleme Noktaları Güncellendi</div>
          </a>
        </div>
        """
        items = parse_announcements_html(joomla_html, "OİDB", "https://oidb.kastamonu.edu.tr/")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].published_date, "18 Kas")
        self.assertEqual(items[0].url, "https://oidb.kastamonu.edu.tr/duyurular/123-guz-sinav-programi")

        portal_html = """
        <a href="/tr/gundem/2026-kyk-burs-basvurulari-basladi">19 Kasım 2026 KYK Burs Başvuru Sonuçları ve Duyurusu</a>
        <a href="/tr/gundem">Tümünü Göster</a>
        """
        portal_items = parse_announcements_html(portal_html, "Kastamonu Üni", "https://kastamonu.edu.tr/tr")
        self.assertEqual(len(portal_items), 1)
        self.assertIn("KYK Burs", portal_items[0].title)
        self.assertEqual(portal_items[0].published_date, "19 Kasım 2026")

        ubys_home_html = """
        <div class="panel panel-default">
          <div class="panel-heading">Duyurular</div>
          <ul>
            <li><a href="/AIS/Student/Home/Announcement?id=5">2026 Güz Mazeret Sınavı Başvuruları Başladı</a></li>
          </ul>
        </div>
        """
        ubys_items = parse_ubys_home_announcements(ubys_home_html, "https://ubys.kastamonu.edu.tr")
        self.assertEqual(len(ubys_items), 1)
        self.assertEqual(ubys_items[0].source, "ÜBYS")

        seen_ids = {items[1].announcement_id}
        filtered = filter_new_announcements(items, seen_ids=seen_ids, keywords=["sınav"])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].announcement_id, items[0].announcement_id)

        msg = format_announcements(filtered)
        self.assertIn("Yeni Duyuru Bildirimi", msg)
        self.assertIn("[OİDB]", msg)


class GpaProjectionTests(unittest.TestCase):
    def test_gpa_honor_and_conditional_pass_projection(self) -> None:
        courses = [
            CourseGrade(
                semester="2026 - Güz",
                code="BPBZ201",
                name="İnternet Programcılığı",
                credit="4",
                exams=[
                    ExamGrade(exam_type="Ara Sınav", name="Vize", score="90", weight=0.40),
                    ExamGrade(exam_type="Yarıyıl Sonu", name="Final", score="95", weight=0.60),
                ],
            ),
            CourseGrade(
                semester="2026 - Güz",
                code="BPBZ203",
                name="Görsel Programlama",
                credit="4",
                letter_grade="BA",
            ),
            CourseGrade(
                semester="2026 - Güz",
                code="BPBZ205",
                name="Mesleki İngilizce",
                credit="2",
                letter_grade="AA",
            ),
        ]
        proj = project_semester_gpa(courses, base_gano=3.10, base_credits=30.0)
        # 4*4.0 + 4*3.5 + 2*4.0 = 38.0 / 10.0 = 3.80 YANO
        self.assertEqual(proj.projected_yano, 3.80)
        # (3.10*30 + 38.0) / 40 = 131 / 40 = 3.275 -> Python bankacı yuvarlamasıyla 3.27
        self.assertEqual(proj.projected_gano, 3.27)
        self.assertEqual(proj.honor_status, "yuksek_onur")

        msg = format_gpa_projection(proj, "https://ubys.kastamonu.edu.tr")
        self.assertIn("Yüksek Onur Belgesi", msg)
        self.assertIn("3.80", msg)
        self.assertIn("3.27", msg)

        # DC koşullu geçme + FF varken onur belgesi olmamalı
        risky_courses = [
            CourseGrade(semester="2026 - Güz", code="D1", name="Ders 1", credit="4", letter_grade="DC"),
            CourseGrade(semester="2026 - Güz", code="D2", name="Ders 2", credit="4", letter_grade="AA"),
            CourseGrade(semester="2026 - Güz", code="D3", name="Ders 3", credit="2", letter_grade="FF"),
        ]
        risk_proj = project_semester_gpa(risky_courses, base_gano=1.80, base_credits=30.0)
        self.assertTrue(risk_proj.has_failing_grade)
        self.assertTrue(risk_proj.has_conditional_grade)
        self.assertFalse(risk_proj.dc_pass_safe)
        self.assertEqual(risk_proj.honor_status, "risk")
        self.assertIn("DC/DD Koşullu Ders Uyarısı", format_gpa_projection(risk_proj, "https://ubys.kastamonu.edu.tr"))


class ScheduleAndMaterialsTests(unittest.TestCase):
    def test_weekly_schedule_exam_schedule_and_course_materials(self) -> None:
        home_links = """
        <a href="/AIS/Student/WeeklySchedule/Index?sapid=abc">Haftalık Ders Programı</a>
        <a href="/AIS/Student/ExamSchedule/Index?sapid=abc">Sınav Takvimi</a>
        """
        self.assertEqual(parse_schedule_url(home_links), "/AIS/Student/WeeklySchedule/Index?sapid=abc")
        self.assertEqual(parse_exam_schedule_url(home_links), "/AIS/Student/ExamSchedule/Index?sapid=abc")

        grid_html = """
        <table>
          <thead><tr><th>Saat</th><th>Pazartesi</th><th>Salı</th></tr></thead>
          <tbody>
            <tr>
              <td>09:00 - 10:50</td>
              <td>BPBZ201 İnternet Programcılığı<br/>Lab-2<br/>Dr. Rahime Çelik</td>
              <td>-</td>
            </tr>
            <tr>
              <td>13:00 - 14:50</td>
              <td></td>
              <td>BPBZ203 Görsel Programlama<br/>Amfi-1</td>
            </tr>
          </tbody>
        </table>
        """
        slots = parse_weekly_schedule(grid_html)
        self.assertEqual(len(slots), 2)
        monday_slots = get_slots_for_day(slots, date(2026, 11, 23))
        self.assertEqual(len(monday_slots), 1)
        self.assertEqual(monday_slots[0].course_code, "BPBZ201")
        self.assertEqual(monday_slots[0].classroom, "Lab-2")
        self.assertIn("BPBZ201", format_daily_schedule(monday_slots, date(2026, 11, 23), "https://ubys.kastamonu.edu.tr"))
        self.assertIn("Salı", format_weekly_schedule(slots, "https://ubys.kastamonu.edu.tr"))

        # Base64 _jsm JSON formatı desteği
        sched_jsm_b64 = base64.b64encode(
            json.dumps(
                [
                    {
                        "DayOfWeek": 3,
                        "CourseCode": "BPBZ207",
                        "CourseName": "Bilgisayar Ağları",
                        "StartTime": "11:00",
                        "EndTime": "12:50",
                        "Classroom": "D-102",
                    }
                ]
            ).encode("utf-8")
        ).decode("ascii")
        jsm_slots = parse_weekly_schedule(f'<script>var _jsm = JSON.parse(Base64.decode("{sched_jsm_b64}"));</script>')
        self.assertEqual(len(jsm_slots), 1)
        self.assertEqual(jsm_slots[0].day_name, "Çarşamba")
        self.assertEqual(jsm_slots[0].classroom, "D-102")

        exam_html = """
        <table>
          <thead><tr><th>Ders Kodu</th><th>Ders Adı</th><th>Sınav Türü</th><th>Tarih</th><th>Saat</th><th>Derslik</th><th>Sıra</th></tr></thead>
          <tbody>
            <tr><td>BPBZ201</td><td>İnternet Programcılığı</td><td>Ara Sınav</td><td>24.11.2026</td><td>10:00</td><td>KMYO-Z04</td><td>12</td></tr>
            <tr><td>BPBZ203</td><td>Görsel Programlama</td><td>Ara Sınav</td><td>26.11.2026</td><td>14:00</td><td>Lab-1</td><td>-</td></tr>
          </tbody>
        </table>
        """
        exams = parse_exam_schedule(exam_html)
        self.assertEqual(len(exams), 2)
        today = date(2026, 11, 23)
        reminders = find_exam_reminders(exams, today, [7, 3, 1, 0], sent_keys={})
        # 24.11 -> 1 gün kaldı, 26.11 -> 3 gün kaldı
        self.assertEqual(len(reminders), 2)
        self.assertEqual(reminders[0][1], 1)
        self.assertEqual(reminders[1][1], 3)
        sent = {exam_reminder_key(reminders[0][0], 1): "2026-11-23"}
        reminders2 = find_exam_reminders(exams, today, [7, 3, 1, 0], sent_keys=sent)
        self.assertEqual(len(reminders2), 1)

        rem_msg = format_exam_reminders(reminders, "https://ubys.kastamonu.edu.tr")
        self.assertIn("YARIN SINAV VAR", rem_msg)
        self.assertIn("KMYO-Z04", rem_msg)
        self.assertIn("ÜBYS Sınav Takvimi", format_exam_schedule(exams, today, "https://ubys.kastamonu.edu.tr"))

        material_html = """
        <a href="/AIS/Student/Class/DownloadFile?id=99">Hafta_07_Sunum.pdf</a>
        <table>
          <thead><tr><th>Ödev Başlığı</th><th>Son Teslim Tarihi</th></tr></thead>
          <tbody>
            <tr><td>PHP CRUD Projesi</td><td>30.11.2026</td></tr>
          </tbody>
        </table>
        """
        detail = parse_class_detail(
            material_html,
            course_code="BPBZ201",
            course_name="İnternet Programcılığı",
            base_url="https://ubys.kastamonu.edu.tr",
        )
        mats = detail["materials"]
        self.assertEqual(len(mats), 2)
        mat_msg = format_material_alerts(mats, "https://ubys.kastamonu.edu.tr")
        self.assertIn("Hafta_07_Sunum.pdf", mat_msg)
        self.assertIn("30.11.2026", mat_msg)


class TelegramCommandsAndBriefingTests(unittest.TestCase):
    def test_command_parser_auth_filter_and_config_env(self) -> None:
        self.assertEqual(parse_bot_command("/hesapla@KastamonuBot 80 30/70"), ("hesapla", ["80", "30/70"]))
        self.assertEqual(parse_bot_command("/devamsızlık"), ("devamsizlik", []))
        self.assertEqual(parse_bot_command("/bilinmeyen"), (None, []))

        env = {
            "UBYS_USERNAME": "221234567",
            "UBYS_PASSWORD": "secret",
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "12345",
            "ANNOUNCEMENT_URLS": "KMYO|https://kmyo.kastamonu.edu.tr/, https://mf.kastamonu.edu.tr/",
            "ANNOUNCEMENT_KEYWORDS": "burs, sınav, staj",
            "EXAM_REMINDER_DAYS": "5,2,0",
            "WEEKLY_BRIEFING_HOUR": "21",
            "ENABLE_COMMANDS": "false",
            "WEATHER_LOCATION": "Merkez Kampüs",
        }
        with patch("src.config.load_dotenv", None), patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertEqual(
            cfg.announcement_urls,
            [("KMYO", "https://kmyo.kastamonu.edu.tr"), ("MF", "https://mf.kastamonu.edu.tr")],
        )
        self.assertEqual(cfg.announcement_keywords, ["burs", "sınav", "staj"])
        self.assertEqual(cfg.exam_reminder_days, [5, 2, 0])
        self.assertEqual(cfg.weekly_briefing_hour, 21)
        self.assertFalse(cfg.enable_commands)
        self.assertEqual(cfg.weather_location, "Merkez Kampüs")

        reply_help = handle_command("yardim", [], cfg, {})
        self.assertIn("/hesapla", reply_help)
        reply_calc = handle_command("hesapla", ["80", "30/70"], cfg, {})
        self.assertIn("%30", reply_calc)
        self.assertIn("BA", reply_calc)

        # process_telegram_commands yalnızca yetkili TELEGRAM_CHAT_ID'yi yanıtlamalı
        mock_notifier = MagicMock()
        mock_notifier.set_my_commands.return_value = True
        mock_notifier.get_updates.return_value = [
            {"update_id": 100, "message": {"chat": {"id": 99999}, "text": "/yardim"}},
            {"update_id": 101, "message": {"chat": {"id": 12345}, "text": "/hesapla 85"}},
        ]
        swiss_state: dict[str, object] = {}
        handled, dirty = process_telegram_commands(
            cfg,
            swiss_state,
            {"today": date(2026, 11, 23)},
            notifier_factory=lambda: mock_notifier,
        )
        self.assertEqual(handled, 1)
        self.assertTrue(dirty)
        self.assertEqual(swiss_state["telegram_commands_version"], BOT_COMMANDS_VERSION)
        self.assertEqual(swiss_state["telegram_last_update_id"], 101)
        mock_notifier.send_message.assert_called_once()
        self.assertEqual(mock_notifier.send_message.call_args.kwargs["chat_ids_override"], ["12345"])

        # Haftalık Pazar brifingi formatlama kontrolü
        briefing_msg = format_weekly_briefing(
            today=date(2026, 11, 22),
            ongoing_cal=[],
            upcoming_cal=[],
            exams=[
                ExamScheduleItem(
                    course_code="BPBZ201",
                    course_name="İnternet Programcılığı",
                    exam_type="Ara Sınav",
                    exam_date=date(2026, 11, 25),
                    exam_time="10:00",
                    classroom="Lab-1",
                )
            ],
            attendance_reports=[],
            gpa_projection=None,
            weather=None,
            base_url="https://ubys.kastamonu.edu.tr",
        )
        self.assertIn("Haftalık Kastamonu ÜBYS Öğrenci Özeti", briefing_msg)
        self.assertIn("BPBZ201", briefing_msg)


class PolishAndReliabilityTests(unittest.TestCase):
    def test_weather_wttr_fallback_and_parse(self) -> None:
        wttr_sample = {
            "current_condition": [{"temp_C": "16", "FeelsLikeC": "15", "weatherCode": "116", "windspeedKmph": "12"}],
            "weather": [
                {"date": "2026-11-20", "mintempC": "5", "maxtempC": "18", "hourly": [{"chanceofrain": "10", "weatherCode": "116"}, {"chanceofrain": "68", "weatherCode": "353"}]},
                {"date": "2026-11-21", "mintempC": "7", "maxtempC": "14", "hourly": [{"chanceofrain": "80", "weatherCode": "302"}]},
                {"date": "2026-11-22", "mintempC": "0", "maxtempC": "11", "hourly": [{"chanceofrain": "5", "weatherCode": "248"}]},
            ],
        }
        wf = parse_wttr_response(wttr_sample, "Kastamonu (Kuzeykent)")
        self.assertEqual(wf.current_temp, 16.0)
        self.assertEqual(wf.precip_probability, 68)
        self.assertEqual(len(wf.daily_summaries), 3)

        resp_om_err = MagicMock(status_code=503)
        resp_wttr_ok = MagicMock(status_code=200)
        resp_wttr_ok.json.return_value = wttr_sample
        with (
            patch("src.weather.time.sleep"),
            patch("src.weather.httpx.Client") as mock_cli,
        ):
            cli_inst = mock_cli.return_value.__enter__.return_value
            cli_inst.get.side_effect = [resp_om_err, resp_om_err, resp_wttr_ok]
            fallback_wf = fetch_weather_forecast()
        self.assertEqual(fallback_wf.current_temp, 16.0)
        self.assertIn("şemsiye", fallback_wf.advice)

    def test_announcements_dots_apostrophe_balance_and_paragraph_split(self) -> None:
        html_ann = """
        <a class="sppb-articles-scroller-link" href="/duyuru/1">
          <span class="sppb-articles-scroller-day">13</span>
          <span class="sppb-articles-scroller-month">Kas</span>
          <div class="sppb-addon-articles-scroller-title">ÖZYES Ek Yerleştirme Sonuçları</div>
          <div class="sppb-articles-scroller-introtext">...</div>
        </a>
        <a class="sppb-articles-scroller-link" href="/duyuru/2">
          <span class="sppb-articles-scroller-day">16</span>
          <span class="sppb-articles-scroller-month">Kas</span>
          <div class="sppb-addon-articles-scroller-title">Havuz Tadilatı Hakkında</div>
          <div class="sppb-articles-scroller-introtext">Merkezi' nde bakım çalışması vardır.</div>
        </a>
        """
        parsed = parse_announcements_html(html_ann, "OİDB", "https://oidb.kastamonu.edu.tr/")
        self.assertEqual(parsed[0].summary, "")
        self.assertEqual(parsed[1].summary, "Merkezi'nde bakım çalışması vardır.")

        mixed = [
            Announcement(announcement_id=f"o{i}", source="OİDB", title=f"OİDB Duyuru {i}", url=f"https://o/{i}")
            for i in range(10)
        ] + [
            Announcement(announcement_id=f"s{i}", source="SKS", title=f"SKS Duyuru {i}", url=f"https://s/{i}")
            for i in range(4)
        ]
        preview = format_announcements(mixed, is_preview=True)
        self.assertIn("[OİDB]", preview)
        self.assertIn("[SKS]", preview)
        self.assertIn("en güncel 8 tanesi", preview)

        # Blok bazlı bölme başlığı ve bağlantıyı ayırmamalı
        blocks = [f"🏷️ <b>[SRC]</b>\n• <a href=\"https://x/{i}\">Duyuru Başlığı {i}</a>" for i in range(15)]
        msg = "\n\n".join(blocks)
        chunks = split_message(msg, max_length=300)
        self.assertGreater(len(chunks), 2)
        for ch in chunks:
            for part in ch.split("\n\n"):
                if "🏷️" in part:
                    self.assertIn("• <a href=", part)

    def test_transcript_clean_semesters_course_summary_and_home_routes(self) -> None:
        tr = TranscriptSummary(
            gano=2.86,
            semesters=[
                TranscriptSemester(
                    name="2 . Yarıyıl",
                    semester_gpa=2.82,
                    courses=[TranscriptCourse(code="BPZ102", name="Algoritmalar", letter_grade="BB")],
                ),
                TranscriptSemester(
                    name="3 . Yarıyıl",
                    semester_gpa=0.00,
                    courses=[TranscriptCourse(code="BPZ201", name="İnternet Prog.", letter_grade=None)],
                ),
                TranscriptSemester(
                    name="4 . Yarıyıl",
                    semester_gpa=0.00,
                    courses=[TranscriptCourse(code="BPZ202", name="Sistem Analizi", letter_grade=None)],
                ),
            ],
        )
        t_msg = format_transcript_summary(tr, "https://ubys.kastamonu.edu.tr")
        self.assertIn("2. Yarıyıl", t_msg)
        self.assertIn("Henüz not girilmedi", t_msg)
        self.assertNotIn("YANO: 0.00", t_msg)
        self.assertIn("Aktif Dönem (3. Yarıyıl)", t_msg)
        self.assertIn("BPZ201 - İnternet Prog.", t_msg)
        self.assertIn("Gelecek Dönem", t_msg)
        self.assertNotIn("BPZ202 - Sistem Analizi", t_msg)
        self.assertIn("Son Notlu Dönem (2. Yarıyıl)", t_msg)
        self.assertIn("BPZ102 - Algoritmalar", t_msg)

        act_sem, grad_sem, act_idx = select_transcript_semesters(
            tr,
            active_courses=[CourseGrade(semester="2026 - Güz", code="BPZ201", name="İnternet Prog.")],
        )
        assert act_sem is not None and grad_sem is not None
        self.assertEqual(act_idx, 1)
        self.assertIn("3", act_sem.name)
        self.assertIn("2", grad_sem.name)

        c_msg = format_test_summary(
            [
                CourseGrade(
                    semester="2026 - Güz",
                    code="BPBS213",
                    name="Nesne Tabanlı Programlama-I",
                    attendance_status="Devamlı",
                )
            ]
        )
        self.assertIn("Henüz not yok", c_msg)
        self.assertIn("Vize/Final: %40/%60", c_msg)
        self.assertIn("Devamlı", c_msg)

        home_js_html = """
        <button onclick="openMenu('/AIS/Student/LessonProgram/Index?sapid=SECRET123')">Ders Programı</button>
        <div data-url="/AIS/Student/StudentExam/Index?sapid=SECRET123">Sınav Takvimi</div>
        """
        routes = discover_home_routes(home_js_html)
        self.assertEqual(routes, ["/AIS/Student/LessonProgram/Index", "/AIS/Student/StudentExam/Index"])
        self.assertTrue(all("SECRET" not in r for r in routes))
        self.assertEqual(parse_schedule_url(home_js_html), "/AIS/Student/LessonProgram/Index?sapid=SECRET123")
        self.assertEqual(parse_exam_schedule_url(home_js_html), "/AIS/Student/StudentExam/Index?sapid=SECRET123")

    def test_netix_weekly_schedule_post_and_department_exam_pdfs(self) -> None:
        # 1. _weeklySchedulle (Netix Events[] şeması, StartHour/FinishHour, WorkCenterName, çoklu hafta deduplikasyonu)
        weekly_payload = [
            {
                "Events": [
                    {
                        "DayOfWeek": 1,
                        "StartHour": 9,
                        "StartMinute": 0,
                        "FinishHour": 10,
                        "FinishMinute": 45,
                        "CourseName": "BPBZ201.1 İnternet Programcılığı",
                        "WorkCenterName": "KMYO-Lab 2",
                        "InstructorName": "Dr. Rahime Çelik\r\nGörgüt",
                    },
                    {
                        "DayOfWeek": 1,
                        "StartHour": 9,
                        "StartMinute": 0,
                        "FinishHour": 10,
                        "FinishMinute": 45,
                        "CourseName": "BPBZ201.1 İnternet Programcılığı",
                        "WorkCenterName": "KMYO-Lab 2",
                        "InstructorName": "Dr. Rahime Çelik Görgüt",
                    },
                    {
                        "DayOfWeek": 3,
                        "StartHour": 13,
                        "StartMinute": 30,
                        "FinishHour": 15,
                        "FinishMinute": 15,
                        "CourseName": "BPBZ207.1 Bilgisayar Ağları",
                        "WorkCenterName": "Derslik 104",
                        "InstructorName": "Öğr. Gör. Hakan Can",
                    },
                ]
            }
        ]
        b64_sched = base64.b64encode(json.dumps(weekly_payload).encode("utf-8")).decode("ascii")
        sched_html = f"<script>var _weeklySchedulle = JSON.parse(Base64.decode(\"{b64_sched}\"));</script>"
        slots = parse_weekly_schedule(sched_html)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].day_of_week, 0)
        self.assertEqual(slots[0].start_time, "09:00")
        self.assertEqual(slots[0].end_time, "10:45")
        self.assertEqual(slots[0].course_code, "BPBZ201")
        self.assertEqual(slots[0].course_name, "İnternet Programcılığı")
        self.assertEqual(slots[0].classroom, "KMYO-Lab 2")
        self.assertEqual(slots[0].instructor, "Dr. Rahime Çelik Görgüt")

        # 2. UBYSClient.fetch_weekly_schedule GetWeeklySchedule POST çağrısı
        student_info_json = base64.b64encode(
            json.dumps(
                {
                    "Programs": [
                        {
                            "StudentId": 998877,
                            "RecordYear": 2025,
                            "RecordSemester": 1,
                            "UnitName": "Kastamonu Meslek Yüksekokulu",
                            "AcademicProgramName": "Bilgisayar Programcılığı",
                        }
                    ]
                }
            ).encode("utf-8")
        ).decode("ascii")
        home_stub = f'<script>var StudentInfo = JSON.parse(Base64.decode("{student_info_json}"));</script>'
        with UBYSClient("https://ubys.kastamonu.edu.tr") as ubys:
            ubys._logged_in = True
            with patch.object(ubys, "_request") as mock_req:
                mock_req.side_effect = [
                    MagicMock(status_code=200, url="https://ubys.kastamonu.edu.tr/AIS/Student/Home/Index", text=home_stub),
                    MagicMock(status_code=200, url="https://ubys.kastamonu.edu.tr/AIS/Student/Home/GetWeeklySchedule", text=sched_html),
                ]
                fetched_slots = ubys.fetch_weekly_schedule(semester_hint="2026 - Güz")
        self.assertEqual(len(fetched_slots), 2)
        post_call = mock_req.call_args_list[1]
        self.assertEqual(post_call.args[0], "POST")
        self.assertIn("GetWeeklySchedule", post_call.args[1])
        self.assertEqual(post_call.kwargs["json"]["co"]["StudentId"], 998877)
        self.assertEqual(post_call.kwargs["json"]["co"]["Year"], 2026)
        self.assertEqual(post_call.kwargs["json"]["co"]["SemesterId"], "1")

        # 3. Fakülte/MYO otomatik eşleştirme & bölüm Sınav Programları sekmesinden aktif dönem PDF çıkarımı
        units = infer_faculty_sources(["Kastamonu Meslek Yüksekokulu - Bilgisayar Programcılığı"])
        self.assertEqual(units, [("KMYO", "https://kmyo.kastamonu.edu.tr/")])

        kmyo_menu_html = """
        <nav>
          <a href="/index.php/boeluemler/bilgisayar-teknolojileri/bilgisayar-programciligi">Bilgisayar Programcılığı</a>
          <a href="/index.php/boeluemler/elektrik/mekatronik">Mekatronik</a>
        </nav>
        """
        dept_url = parse_department_program_url(
            kmyo_menu_html,
            "https://kmyo.kastamonu.edu.tr/",
            ["Kastamonu Meslek Yüksekokulu", "Bilgisayar Programcılığı"],
        )
        self.assertEqual(
            dept_url,
            "https://kmyo.kastamonu.edu.tr/index.php/boeluemler/bilgisayar-teknolojileri/bilgisayar-programciligi",
        )

        dept_html = """
        <ul>
          <li><a href="#tab-ders">Ders Programları</a></li>
          <li><a href="#tab-sinav">Sınav Programları</a></li>
        </ul>
        <div id="tab-sinav">
          <p>Aktif Dönem İçin Tıklayınız</p>
          <p>Bilgisayar Programcılığı Programı 2026 - 2027 Eğitim Öğretim Yılı Güz Yarıyılı Vize Takvimi için
            <a href="/images/2026-2027/Duyurular/Sinav_Programlari/2026-2027-Gz/Vize/bil.pdf">TIKLAYINIZ</a>
          </p>
          <p>Önceki Dönem Programları İçin Tıklayınız</p>
          <p>Bilgisayar Programcılığı Programı 2024 - 2025 Vize Takvimi için
            <a href="/images/2024-2025/vize.pdf">TIKLAYINIZ</a>
          </p>
        </div>
        """
        pdfs = parse_department_exam_pdfs(dept_html, dept_url, "KMYO")
        self.assertEqual(len(pdfs), 1)
        self.assertEqual(pdfs[0].source, "KMYO Sınav PDF")
        self.assertIn("2026 - 2027", pdfs[0].title)
        self.assertNotIn("2024", pdfs[0].title)
        self.assertTrue(is_exam_announcement(pdfs[0]))

        exam_msg = format_exam_schedule([], date(2026, 11, 20), "https://ubys.kastamonu.edu.tr", exam_announcements=pdfs)
        self.assertIn("Bölüm / Fakülte Sınav Programı", exam_msg)
        self.assertIn("bil.pdf", exam_msg)

    def test_second_year_schedule_filtering_and_university_wide_exam_pdfs(self) -> None:
        # 1. sınıf derslerini içeren yanlış yıl yanıtını reddedip 2. sınıf adayını ve karma programda sadece aktif dersleri seçmeli
        second_year_courses = [
            CourseGrade(semester="2026 - Güz", code="BPBZ201", name="İnternet Programcılığı"),
            CourseGrade(semester="2026 - Güz", code="BPBZ207", name="Bilgisayar Ağları"),
        ]
        self.assertEqual(infer_student_class_year(second_year_courses), 2)

        first_year_only_payload = [
            {
                "Events": [
                    {
                        "DayOfWeek": 1,
                        "StartHour": 9,
                        "StartMinute": 0,
                        "FinishHour": 10,
                        "FinishMinute": 45,
                        "CourseName": "BPBZ101.1 Bilgi ve İletişim Teknolojisi",
                        "WorkCenterName": "Derslik 101",
                    }
                ]
            }
        ]
        mixed_second_year_payload = [
            {
                "Events": [
                    {
                        "DayOfWeek": 1,
                        "StartHour": 9,
                        "StartMinute": 0,
                        "FinishHour": 10,
                        "FinishMinute": 45,
                        "CourseName": "BPBZ101.1 Bilgi ve İletişim Teknolojisi",
                        "WorkCenterName": "Derslik 101",
                    },
                    {
                        "DayOfWeek": 2,
                        "StartHour": 10,
                        "StartMinute": 0,
                        "FinishHour": 11,
                        "FinishMinute": 45,
                        "CourseName": "BPBZ201.1 İnternet Programcılığı",
                        "WorkCenterName": "Lab-2",
                    },
                    {
                        "DayOfWeek": 4,
                        "StartHour": 13,
                        "StartMinute": 0,
                        "FinishHour": 14,
                        "FinishMinute": 45,
                        "CourseName": "BPBZ207.1 Bilgisayar Ağları",
                        "WorkCenterName": "Derslik 104",
                    },
                ]
            }
        ]
        b64_first = base64.b64encode(json.dumps(first_year_only_payload).encode("utf-8")).decode("ascii")
        b64_mixed = base64.b64encode(json.dumps(mixed_second_year_payload).encode("utf-8")).decode("ascii")
        html_first = f'<script>var _weeklySchedulle = JSON.parse(Base64.decode("{b64_first}"));</script>'
        html_mixed = f'<script>var _weeklySchedulle = JSON.parse(Base64.decode("{b64_mixed}"));</script>'

        # filter_slots_for_active_courses I. ve II. dersleri karıştırmamalı
        parsed_mixed = parse_weekly_schedule(html_mixed)
        filtered = filter_slots_for_active_courses(parsed_mixed, second_year_courses)
        self.assertEqual([s.course_code for s in filtered], ["BPBZ201", "BPBZ207"])

        student_info_json = base64.b64encode(
            json.dumps(
                {
                    "Programs": [
                        {
                            "StudentId": 554433,
                            "RecordYear": 2025,
                            "RecordSemester": 1,
                            "UnitName": "Kastamonu Meslek Yüksekokulu",
                            "AcademicProgramName": "Bilgisayar Programcılığı",
                        }
                    ]
                }
            ).encode("utf-8")
        ).decode("ascii")
        home_stub = f'<script>var StudentInfo = JSON.parse(Base64.decode("{student_info_json}"));</script>'

        with UBYSClient("https://ubys.kastamonu.edu.tr") as ubys:
            ubys._logged_in = True
            with patch.object(ubys, "_request") as mock_req:
                mock_req.side_effect = [
                    MagicMock(status_code=200, url="https://ubys.kastamonu.edu.tr/AIS/Student/Home/Index", text=home_stub),
                    MagicMock(status_code=200, url="https://ubys.kastamonu.edu.tr/AIS/Student/Home/GetWeeklySchedule", text=html_first),
                    MagicMock(status_code=200, url="https://ubys.kastamonu.edu.tr/AIS/Student/Home/GetWeeklySchedule", text=html_mixed),
                ]
                res_slots = ubys.fetch_weekly_schedule(
                    semester_hint="2026 - Güz",
                    active_courses=second_year_courses,
                )
        self.assertEqual([s.course_code for s in res_slots], ["BPBZ201", "BPBZ207"])
        self.assertEqual(mock_req.call_count, 3)

        # Sekmesiz genel fakülte sınav duyurusu gövdesinden bölüm + sınıf eşleşmeli PDF çıkarımı (üniversite geneli)
        mmf_units = infer_faculty_sources(["Mühendislik ve Mimarlık Fakültesi - Bilgisayar Mühendisliği"])
        self.assertEqual(mmf_units, [("MMF", "https://mmf.kastamonu.edu.tr/")])

        mmf_article_html = """
        <div itemprop="articleBody">
          <p>Makine Mühendisliği Vize Sınav Programı için <a href="/files/makine_vize.pdf">Tıklayınız</a></p>
          <p>Bilgisayar Mühendisliği 1. Sınıf 2026-2027 Güz Vize Sınav Programı için <a href="/files/bil_1_vize.pdf">Tıklayınız</a></p>
          <p>Bilgisayar Mühendisliği 2. Sınıf 2026-2027 Güz Vize Sınav Programı için <a href="/files/bil_2_vize.pdf">Tıklayınız</a></p>
        </div>
        """
        mmf_pdfs = parse_department_exam_pdfs(
            mmf_article_html,
            "https://mmf.kastamonu.edu.tr/duyurular/vize-programi",
            "MMF",
            max_items=1,
            program_hints=["Mühendislik ve Mimarlık Fakültesi", "Bilgisayar Mühendisliği"],
            class_year=2,
            allow_general_page=True,
        )
        self.assertEqual(len(mmf_pdfs), 1)
        self.assertIn("bil_2_vize.pdf", mmf_pdfs[0].url)

    def test_transcript_elective_resolution_and_staj_b_handling(self) -> None:
        # 1. parse_transcript TakenCourses alt listesindeki gerçek seçmeli dersi ayrıştırmalı
        nested_payload = {
            "Transcripts": [
                {
                    "GANO": 2.86,
                    "Semesters": [
                        {
                            "SemesterName": "3 . Yarıyıl",
                            "SemesterAverage": 0.0,
                            "Courses": [
                                {
                                    "CourseCode": "MS-III",
                                    "CourseName": "MESLEKİ SEÇMELİ-III",
                                    "TakenCourses": [
                                        {
                                            "CourseCode": "BPBS213",
                                            "CourseName": "Nesne Tabanlı Programlama-I",
                                            "Credit": 2,
                                            "Ects": 4,
                                            "Grade": "",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        b64_nested = base64.b64encode(json.dumps(nested_payload).encode("utf-8")).decode("ascii")
        nested_summary = parse_transcript(
            f'<script>var _jsm = JSON.parse(Base64.decode("{b64_nested}"));</script>'
        )
        self.assertEqual(nested_summary.semesters[0].courses[0].code, "BPBS213")
        self.assertEqual(nested_summary.semesters[0].courses[0].name, "Nesne Tabanlı Programlama-I")

        # 2. Staj: B varken 3. Yarıyıl YANO: 0.00 / Son Notlu Dönem olmamalı ve MS-III / S-III çözülmeli
        summary = TranscriptSummary(
            gano=2.86,
            semesters=[
                TranscriptSemester(
                    name="1 . Yarıyıl",
                    semester_gpa=2.90,
                    courses=[
                        TranscriptCourse(code="BPBZ101", name="Bilgisayar Donanımı", letter_grade="DD"),
                        TranscriptCourse(code="BPBZ103", name="Programlama Temelleri", letter_grade="BA"),
                    ],
                ),
                TranscriptSemester(
                    name="2 . Yarıyıl",
                    semester_gpa=2.82,
                    courses=[
                        TranscriptCourse(code="BPBZ102", name="Algoritmalar", letter_grade="BB"),
                    ],
                ),
                TranscriptSemester(
                    name="3 . Yarıyıl",
                    semester_gpa=0.00,
                    courses=[
                        TranscriptCourse(code="BPBZ201", name="İnternet Programcılığı"),
                        TranscriptCourse(code="BPBZ203", name="Görsel Programlama I"),
                        TranscriptCourse(code="BPBZ205", name="Mesleki Yabancı Dil I"),
                        TranscriptCourse(code="BPBZ207", name="Bilgisayar Ağları"),
                        TranscriptCourse(code="BPBZ209", name="İşletim Sistemleri"),
                        TranscriptCourse(code="BPBZ211", name="Staj", letter_grade="B"),
                        TranscriptCourse(code="MS-III", name="MESLEKİ SEÇMELİ-III"),
                        TranscriptCourse(code="S-III", name="SEÇMELI-III"),
                    ],
                ),
                TranscriptSemester(
                    name="4 . Yarıyıl",
                    semester_gpa=0.00,
                    courses=[
                        TranscriptCourse(code="BPBZ202", name="Sistem Analizi ve Tasarımı"),
                    ],
                ),
            ],
        )
        active_courses = [
            CourseGrade(semester="2026 - Güz", code="BPBZ201", name="İnternet Programcılığı"),
            CourseGrade(semester="2026 - Güz", code="BPBZ203", name="Görsel Programlama I"),
            CourseGrade(semester="2026 - Güz", code="BPBZ205", name="Mesleki Yabancı Dil I"),
            CourseGrade(semester="2026 - Güz", code="BPBZ207", name="Bilgisayar Ağları"),
            CourseGrade(semester="2026 - Güz", code="BPBZ209", name="İşletim Sistemleri"),
            CourseGrade(semester="2026 - Güz", code="BPBS213", name="Nesne Tabanlı Programlama-I"),
            CourseGrade(semester="2026 - Güz", code="BPBS231", name="Bilgisayarlı Kurgu Teknikleri"),
            CourseGrade(semester="2026 - Güz", code="BPBZ101", name="Bilgisayar Donanımı"),
        ]

        msg = format_transcript_summary(summary, "https://ubys.kastamonu.edu.tr", active_courses=active_courses)
        self.assertNotIn("YANO: 0.00", msg)
        self.assertIn("• <b>3. Yarıyıl</b> (Aktif Dönem — Henüz not girilmedi)", msg)
        self.assertIn("📌 <b>Aktif Dönem (3. Yarıyıl):</b>", msg)
        self.assertIn("BPBZ211 - Staj: <code>B</code>", msg)
        self.assertIn("BPBS213 - Nesne Tabanlı Programlama-I (Seçmeli)", msg)
        self.assertIn("BPBS231 - Bilgisayarlı Kurgu Teknikleri (Seçmeli)", msg)
        self.assertNotIn("MS-III", msg)
        self.assertNotIn("S-III", msg)
        self.assertNotIn("MESLEKİ SEÇMELİ-III", msg)
        self.assertNotIn("BPBZ101 - Bilgisayar Donanımı (Seçmeli)", msg)
        self.assertIn("📚 <b>Son Notlu Dönem (2. Yarıyıl):</b>", msg)
        self.assertIn("BPBZ102 - Algoritmalar: <code>BB</code>", msg)


class ModuleSchedulingAndIndependenceTests(unittest.TestCase):
    @staticmethod
    def _base_course() -> CourseGrade:
        return CourseGrade(
            semester="2026 - Güz",
            code="BPBZ201",
            name="İnternet Programcılığı",
            exams=[ExamGrade(exam_type="Ara Sınav", name="Vize", score="85")],
        )

    @staticmethod
    def _sample_weather() -> WeatherForecast:
        return WeatherForecast(
            location_name="Kastamonu (Kuzeykent)",
            forecast_date=date(2026, 11, 23),
            current_temp=4.0,
            apparent_temp=2.0,
            temp_min=1.0,
            temp_max=9.0,
            precip_probability=10,
            wind_speed=12.0,
            weather_code=2,
            condition_text="Parçalı Bulutlu",
            condition_icon="⛅",
            advice="Serin hava, ince mont yeterli.",
        )

    def test_other_modules_run_even_when_no_new_grades(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            course = self._base_course()
            save_state(
                state_path,
                {
                    "schema_version": 1,
                    "baseline_initialized": True,
                    "courses": build_course_snapshot([course]),
                    "swiss_tool": {
                        "seen_announcement_ids": ["old_ann_1"],
                    },
                },
            )
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=True,
                enable_dining=True,
                enable_weather=True,
                enable_calendar=True,
                enable_announcements=True,
                enable_schedule=True,
                enable_exam_schedule=True,
                enable_attendance=True,
                enable_transcript=False,
                enable_catalog=False,
                enable_materials=False,
                enable_weekly_briefing=False,
                enable_commands=False,
            )

            monday_dt = datetime(2026, 11, 23, 8, 20, tzinfo=TR_TZ)
            monday_menu = DailyMenu(
                menu_date=date(2026, 11, 23),
                items=[DiningItem(name="Mercimek Ç.", calories="120 kkal", category="Çorba")],
                total_calories_min=120,
                total_calories_max=120,
            )
            cal_event = CalendarEvent(
                event_id="500",
                title="Güz Ara Sınav",
                start_date=date(2026, 11, 30),
                end_date=date(2026, 12, 4),
                category="Ders ve Sınav",
                faculty="Genel",
                term="2026-2027",
            )
            ann = Announcement(
                announcement_id="new_ann_1",
                source="OİDB",
                title="Yeni Akademik Duyuru",
                url="https://oidb.kastamonu.edu.tr/duyuru/1",
            )
            slot = ScheduleSlot(
                day_of_week=0,
                day_name="Pazartesi",
                start_time="09:00",
                end_time="10:45",
                course_code="BPBZ201",
                course_name="İnternet Programcılığı",
                classroom="Lab-2",
            )
            exam = ExamScheduleItem(
                course_code="BPBZ201",
                course_name="İnternet Programcılığı",
                exam_type="Ara Sınav",
                exam_date=date(2026, 11, 24),
                exam_time="10:00",
                classroom="KMYO-Z04",
            )

            with (
                patch("src.main.now_tr", return_value=monday_dt),
                patch("src.main.UBYSClient") as mock_ubys,
                patch("src.main.fetch_dining_menus", return_value=[monday_menu]),
                patch("src.main.fetch_weather_forecast", return_value=self._sample_weather()),
                patch("src.main.fetch_calendar_events", return_value=("Genel", "2026-2027", [cal_event])),
                patch("src.main.fetch_all_announcements", return_value=[ann]),
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                inst = mock_ubys.return_value.__enter__.return_value
                inst.fetch_grades.return_value = [course]
                inst.last_home_gano = None
                inst.student_program_hints = []
                inst.home_announcements = []
                inst.fetch_weekly_schedule.return_value = [slot]
                inst.fetch_exam_schedule.return_value = [exam]

                self.assertEqual(run_once(cfg), 0)

            sent_msgs = [call.args[0] for call in mock_notifier.return_value.send_message.call_args_list]
            self.assertEqual(len(sent_msgs), 6)
            joined = "\n---\n".join(sent_msgs)
            self.assertNotIn("ÜBYS Not Bildirimi", joined)
            self.assertIn("Günün Yemekhane Menüsü", joined)
            self.assertIn("Kastamonu (Kuzeykent)", joined)
            self.assertIn("Akademik Takvim", joined)
            self.assertIn("Yeni Akademik Duyuru", joined)
            self.assertIn("Günün Ders Programı", joined)
            self.assertIn("YARIN SINAV VAR", joined)

    def test_standalone_weather_fallback_and_dedup(self) -> None:
        monday_dt = datetime(2026, 11, 23, 8, 20, tzinfo=TR_TZ)
        later_dt = datetime(2026, 11, 23, 9, 43, tzinfo=TR_TZ)

        # 1. Yemekhane kapalıyken hafta içi bağımsız hava durumu gönderilmeli ve aynı gün tekrarlanmamalı
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=False,
                enable_dining=False,
                enable_weather=True,
                enable_calendar=False,
                enable_announcements=False,
                enable_schedule=False,
                enable_exam_schedule=False,
                enable_weekly_briefing=False,
                enable_commands=False,
            )
            with (
                patch("src.main.now_tr", side_effect=[monday_dt, later_dt]),
                patch("src.main.fetch_weather_forecast", return_value=self._sample_weather()) as mock_wf,
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_wf.call_count, 1)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 1)
            self.assertIn("Hava Durumu", mock_notifier.return_value.send_message.call_args[0][0])

        # 2. Yemekhanede bugün menü yoksa bağımsız hava durumu yine gönderilmeli
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=False,
                enable_dining=True,
                enable_weather=True,
                enable_calendar=False,
                enable_announcements=False,
                enable_schedule=False,
                enable_exam_schedule=False,
                enable_weekly_briefing=False,
                enable_commands=False,
            )
            with (
                patch("src.main.now_tr", return_value=monday_dt),
                patch("src.main.fetch_dining_menus", return_value=[]),
                patch("src.main.fetch_weather_forecast", return_value=self._sample_weather()),
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 1)
            self.assertIn("Hava Durumu", mock_notifier.return_value.send_message.call_args[0][0])

        # 3. Yemekhane menüsü hava durumuyla gönderildiyse ayrıca tekrar hava durumu atılmamalı
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=False,
                enable_dining=True,
                enable_weather=True,
                enable_calendar=False,
                enable_announcements=False,
                enable_schedule=False,
                enable_exam_schedule=False,
                enable_weekly_briefing=False,
                enable_commands=False,
            )
            monday_menu = DailyMenu(
                menu_date=date(2026, 11, 23),
                items=[DiningItem(name="Mercimek Ç.", calories="120 kkal", category="Çorba")],
            )
            with (
                patch("src.main.now_tr", side_effect=[monday_dt, later_dt]),
                patch("src.main.fetch_dining_menus", return_value=[monday_menu]),
                patch("src.main.fetch_weather_forecast", return_value=self._sample_weather()) as mock_wf,
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_wf.call_count, 1)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 1)
            self.assertIn("Günün Yemekhane Menüsü", mock_notifier.return_value.send_message.call_args[0][0])

    def test_schedule_and_exams_use_cache_when_grades_fail_and_preserve_cache_on_empty_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            mon_slot = ScheduleSlot(
                day_of_week=0,
                day_name="Pazartesi",
                start_time="09:00",
                end_time="10:45",
                course_code="BPBZ201",
                course_name="İnternet Programcılığı",
                classroom="Lab-2",
            )
            tue_slot = ScheduleSlot(
                day_of_week=1,
                day_name="Salı",
                start_time="13:00",
                end_time="14:45",
                course_code="BPBZ201",
                course_name="İnternet Programcılığı",
                classroom="Lab-1",
            )
            exam = ExamScheduleItem(
                course_code="BPBZ201",
                course_name="İnternet Programcılığı",
                exam_type="Ara Sınav",
                exam_date=date(2026, 11, 24),
                exam_time="10:00",
                classroom="KMYO-Z04",
            )
            save_state(
                state_path,
                {
                    "schema_version": 1,
                    "baseline_initialized": True,
                    "courses": build_course_snapshot([self._base_course()]),
                    "swiss_tool": {
                        "schedule_cache": {
                            "updated_date": "2026-11-20",
                            "slots": [mon_slot.to_dict(), tue_slot.to_dict()],
                        },
                        "exam_schedule_cache": {
                            "updated_date": "2026-11-22",
                            "exams": [exam.to_dict()],
                        },
                    },
                },
            )
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                alert_after_consecutive_errors=5,
                enable_grades=True,
                enable_dining=False,
                enable_weather=False,
                enable_calendar=False,
                enable_announcements=False,
                enable_schedule=True,
                enable_exam_schedule=True,
                enable_attendance=False,
                enable_transcript=False,
                enable_catalog=False,
                enable_materials=False,
                enable_weekly_briefing=False,
                enable_commands=False,
            )

            # 1. ÜBYS not çekimi hata verse bile önbellekteki ders programı ve sınav hatırlatması çalışmalı
            monday_dt = datetime(2026, 11, 23, 8, 20, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=monday_dt),
                patch("src.main.UBYSClient") as mock_ubys,
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                inst = mock_ubys.return_value.__enter__.return_value
                inst.fetch_grades.side_effect = NetworkError("ÜBYS zaman aşımı")
                self.assertEqual(run_once(cfg), 1)
            sent1 = [call.args[0] for call in mock_notifier.return_value.send_message.call_args_list]
            self.assertEqual(len(sent1), 2)
            self.assertIn("Günün Ders Programı", sent1[0])
            self.assertIn("YARIN SINAV VAR", sent1[1])

            # 2. Yenileme boş liste [] döndürse bile mevcut geçerli schedule_cache silinmemeli
            saved_mid = load_state(state_path)
            assert saved_mid is not None
            saved_mid["swiss_tool"]["schedule_cache"]["updated_date"] = "2026-11-10"
            save_state(state_path, saved_mid)

            tuesday_dt = datetime(2026, 11, 24, 8, 20, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=tuesday_dt),
                patch("src.main.UBYSClient") as mock_ubys,
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                inst = mock_ubys.return_value.__enter__.return_value
                inst.fetch_grades.return_value = [self._base_course()]
                inst.last_home_gano = None
                inst.student_program_hints = []
                inst.home_announcements = []
                inst.fetch_weekly_schedule.return_value = []
                inst.fetch_exam_schedule.return_value = []
                self.assertEqual(run_once(cfg), 0)

            sent2 = [call.args[0] for call in mock_notifier.return_value.send_message.call_args_list]
            self.assertTrue(any("Günün Ders Programı" in m and "Lab-1" in m for m in sent2))
            saved_after = load_state(state_path)
            assert saved_after is not None
            self.assertEqual(len(saved_after["swiss_tool"]["schedule_cache"]["slots"]), 2)

            # 3. Önbellekteki slots=[] ve active_sem_courses=[] iken schedule yenileme tekrar denenmeli
            saved_after["swiss_tool"]["schedule_cache"] = {"updated_date": "2026-11-24", "slots": []}
            save_state(state_path, saved_after)
            wednesday_dt = datetime(2026, 11, 25, 8, 20, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=wednesday_dt),
                patch("src.main.UBYSClient") as mock_ubys,
                patch("src.main.TelegramNotifier"),
            ):
                inst = mock_ubys.return_value.__enter__.return_value
                inst.fetch_grades.return_value = []
                inst.last_home_gano = None
                inst.student_program_hints = []
                inst.home_announcements = []
                inst.fetch_weekly_schedule.return_value = []
                inst.fetch_exam_schedule.return_value = []
                self.assertEqual(run_once(cfg), 0)
                self.assertEqual(inst.fetch_weekly_schedule.call_count, 1)

    def test_weekly_briefing_sunday_evening_and_monday_early_catchup(self) -> None:
        def _make_cfg(state_path: Path) -> Config:
            return Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=False,
                enable_dining=False,
                enable_weather=False,
                enable_calendar=False,
                enable_announcements=False,
                enable_schedule=False,
                enable_exam_schedule=False,
                enable_weekly_briefing=True,
                weekly_briefing_hour=20,
                enable_commands=False,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            cfg = _make_cfg(state_path)

            # Pazar 04:06 TR -> henüz brifing saati değil, gönderilmemeli
            sun_early = datetime(2026, 11, 22, 4, 6, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=sun_early),
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 0)

            # Pazar 20:23 TR -> gönderilmeli ve 2026-W47 kaydedilmeli
            sun_evening = datetime(2026, 11, 22, 20, 23, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=sun_evening),
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 1)
            saved = load_state(state_path)
            assert saved is not None
            self.assertEqual(saved["swiss_tool"]["last_weekly_briefing"], "2026-W47")

            # Pazartesi 04:29 TR -> Pazar akşamı zaten gönderildiği için tekrar edilmemeli
            mon_early = datetime(2026, 11, 23, 4, 29, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=mon_early),
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 0)

        # Pazar 20:23 çalıştırması düştüyse Pazartesi 04:29 TR'de telafi olarak gönderilmeli
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state_catchup.json"
            cfg = _make_cfg(state_path)
            mon_early = datetime(2026, 11, 23, 4, 29, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=mon_early),
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 1)
            saved_c = load_state(state_path)
            assert saved_c is not None
            self.assertEqual(saved_c["swiss_tool"]["last_weekly_briefing"], "2026-W47")

        # Pazartesi 08:20 TR -> sabah 06:00 sonrası pencere kapalı olduğundan gönderilmemeli
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state_late.json"
            cfg = _make_cfg(state_path)
            mon_morning = datetime(2026, 11, 23, 8, 20, tzinfo=TR_TZ)
            with (
                patch("src.main.now_tr", return_value=mon_morning),
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 0)

    def test_weekend_morning_calendar_reminders_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            slot = ScheduleSlot(
                day_of_week=5,
                day_name="Cumartesi",
                start_time="10:00",
                end_time="11:45",
                course_code="BPBZ201",
                course_name="İnternet Programcılığı",
            )
            save_state(
                state_path,
                {
                    "schema_version": 1,
                    "baseline_initialized": True,
                    "courses": {},
                    "swiss_tool": {
                        "schedule_cache": {"updated_date": "2026-11-20", "slots": [slot.to_dict()]},
                    },
                },
            )
            cfg = Config(
                ubys_username="221234567",
                ubys_password="secret",
                telegram_bot_token="token",
                telegram_chat_ids=["12345"],
                state_file=state_path,
                enable_grades=False,
                enable_dining=True,
                enable_weather=True,
                enable_calendar=True,
                enable_announcements=False,
                enable_schedule=True,
                enable_exam_schedule=False,
                enable_weekly_briefing=False,
                enable_commands=False,
            )
            sat_dt = datetime(2026, 11, 21, 8, 17, tzinfo=TR_TZ)
            cal_event = CalendarEvent(
                event_id="501",
                title="Ders Kayıt Son Günü",
                start_date=date(2026, 11, 22),
                end_date=date(2026, 11, 22),
                category="Kayıt (İlk / Yenileme)",
                faculty="Genel",
                term="2026-2027",
            )
            with (
                patch("src.main.now_tr", return_value=sat_dt),
                patch("src.main.fetch_calendar_events", return_value=("Genel", "2026-2027", [cal_event])),
                patch("src.main.fetch_dining_menus") as mock_dining,
                patch("src.main.fetch_weather_forecast") as mock_weather,
                patch("src.main.TelegramNotifier") as mock_notifier,
            ):
                self.assertEqual(run_once(cfg), 0)
            self.assertEqual(mock_dining.call_count, 0)
            self.assertEqual(mock_weather.call_count, 0)
            self.assertEqual(mock_notifier.return_value.send_message.call_count, 1)
            self.assertIn("Ders Kayıt Son Günü", mock_notifier.return_value.send_message.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
