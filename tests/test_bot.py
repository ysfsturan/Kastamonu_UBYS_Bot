"""Kastamonu ÜBYS Not Bildirim Botu birim testleri."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from src.config import Config, ConfigError, load_config
from src.differ import (
    GistStateStore,
    StateStorageError,
    build_course_snapshot,
    diff_courses,
    load_state,
    save_state,
)
from src.main import run_once
from src.models import CourseGrade, ExamGrade
from src.notifier import (
    TelegramNotifier,
    format_baseline_summary,
    format_grade_changes,
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


if __name__ == "__main__":
    unittest.main()
