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

from src.attendance import (
    build_attendance_snapshot,
    diff_attendance,
    evaluate_all_attendance,
    evaluate_course_attendance,
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
from src.config import Config, ConfigError, load_config
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
    score_to_letter,
)
from src.main import TR_TZ, run_once
from src.models import (
    CalendarEvent,
    CourseGrade,
    DailyMenu,
    DiningItem,
    ExamGrade,
    TranscriptCourse,
    TranscriptSemester,
    TranscriptSummary,
)
from src.notifier import (
    TelegramNotifier,
    format_attendance_alerts,
    format_attendance_report,
    format_baseline_summary,
    format_calendar_digest,
    format_calendar_reminders,
    format_daily_menu,
    format_gano_change,
    format_grade_calculator,
    format_grade_changes,
    format_transcript_summary,
    split_message,
)
from src.ubys_client import LoginError, NetworkError
from src.ubys_parser import (
    SessionExpiredError,
    extract_ajax_csrf_token,
    extract_login_csrf_token,
    has_active_captcha,
    normalize_letter_grade,
    normalize_score,
    normalize_status,
    parse_class_detail,
    parse_grades_index,
    parse_sap_id,
    parse_student_gano,
    parse_transcript,
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
        # Teorik 3 saat * 14 hafta * 0.30 = 12.6 -> floor 12 saat
        c_warn = CourseGrade(
            semester="2026 - Güz",
            code="BLM101",
            name="Algoritmalar",
            theoretical_hours=3.0,
            practical_hours=0.0,
            absent_total_hours=10.0,
            attendance_status="Devamlı",
        )
        r_warn = evaluate_course_attendance(c_warn)
        self.assertEqual(r_warn.max_total_absent, 12.0)
        self.assertEqual(r_warn.remaining_total, 2.0)
        self.assertEqual(r_warn.risk_level, "warning")

        c_crit = CourseGrade(
            semester="2026 - Güz",
            code="BLM101",
            name="Algoritmalar",
            theoretical_hours=3.0,
            practical_hours=0.0,
            absent_total_hours=11.0,
            attendance_status="Devamlı",
        )
        self.assertEqual(evaluate_course_attendance(c_crit).risk_level, "critical")

        # Uygulamalı 2 saat * 14 hafta * 0.20 = 5.6 -> floor 5 saat
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
        self.assertEqual(r_prac.risk_level, "critical")

        # Karma 2+2 -> Teorik 8, Uygulama 5
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


if __name__ == "__main__":
    unittest.main()
