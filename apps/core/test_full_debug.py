from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from scripts import full_debug


class FullDebugToolTests(TestCase):
    def test_sanitize_masks_secrets_emails_and_ansi(self):
        value = full_debug.sanitize(
            "SECRET_KEY=super-secret password: hidden user@example.test \x1b[31mred"
        )
        self.assertNotIn("super-secret", value)
        self.assertNotIn("hidden", value)
        self.assertNotIn("user@example.test", value)
        self.assertNotIn("\x1b", value)
        self.assertIn("[MASKED]", value)

    def test_guarded_failure_is_reported_and_later_sections_survive(self):
        report = full_debug.Report()
        with report.guarded("kaputter Schritt"):
            raise RuntimeError("controlled failure")
        report.section("SPÄTER", ["wurde ausgeführt"])
        output = report.render()
        self.assertIn("[ERROR] kaputter Schritt", output)
        self.assertIn("SPÄTER", output)
        self.assertIn("wurde ausgeführt", output)

    @mock.patch.object(full_debug, "idor_audit")
    @mock.patch.object(full_debug, "static_and_service_worker")
    @mock.patch.object(full_debug, "security_audit")
    @mock.patch.object(full_debug, "source_audit")
    @mock.patch.object(full_debug, "database_audit")
    @mock.patch.object(full_debug, "forms_and_models")
    @mock.patch.object(full_debug, "url_audit")
    @mock.patch.object(full_debug, "javascript_audit")
    @mock.patch.object(full_debug, "framework_commands")
    @mock.patch.object(full_debug, "header")
    @mock.patch.object(full_debug, "django_setup", return_value=object())
    def test_main_always_writes_utf8_report_when_subcheck_fails(self, django_setup, header, framework, javascript, urls, forms, database, source, security, static, idor):
        del django_setup, header, framework, javascript, urls, forms, source, security, static, idor
        database.side_effect = RuntimeError("database unavailable")
        with TemporaryDirectory() as directory:
            output = Path(directory) / "debug.txt"
            code = full_debug.main(["--output", str(output)])
            text = output.read_text(encoding="utf-8")
        self.assertEqual(code, 2)
        self.assertIn("BRICKMISSING FULL APPLICATION DIAGNOSTIC", text)
        self.assertIn("database unavailable", text)
        self.assertIn("ZUSAMMENFASSUNG", text)

    @mock.patch("urllib.request.urlopen")
    def test_production_http_uses_get_only(self, urlopen):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.headers = {"Content-Type": "text/html"}
        urlopen.return_value = response
        report = full_debug.Report()
        full_debug.public_http(report, "https://brickmissing.example")
        self.assertTrue(urlopen.called)
        for call in urlopen.call_args_list:
            self.assertEqual(call.args[0].method, "GET")

    def test_non_https_production_origin_is_rejected(self):
        with self.assertRaises(ValueError):
            full_debug.public_http(full_debug.Report(), "http://127.0.0.1:8000")

    @mock.patch("scripts.full_debug.shutil.which", return_value=None)
    def test_missing_node_is_warning_not_error(self, _which):
        report = full_debug.Report()
        full_debug.javascript_audit(report)
        self.assertEqual(report.findings[-1].severity, "WARNING")
        self.assertIn("SKIPPED", report.render())
