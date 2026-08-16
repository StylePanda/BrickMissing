import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.services import create_email_change, send_verification_email


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PUBLIC_URL="https://brickmissing.example",
    DEFAULT_FROM_EMAIL="BrickMissing <noreply@example.test>",
)
class EmailDesignTests(TestCase):
    credential = "A-very-long-password-123"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "Mail <User>",
            "mail@example.test",
            self.credential,
            email_verified=True,
        )

    def _html(self, message):
        self.assertEqual(len(message.alternatives), 1)
        alternative = message.alternatives[0]
        self.assertEqual(alternative.mimetype, "text/html")
        return alternative.content

    def _assert_common_mail_safety(self, message):
        html = self._html(message)
        no_reply_notice = "Bitte antworte nicht auf diese Nachricht"
        self.assertIn(no_reply_notice, html)
        self.assertIn(no_reply_notice, message.body)
        self.assertIn("https://brickmissing.example/datenschutz/", html)
        self.assertIn("https://brickmissing.example/impressum/", html)
        self.assertNotIn("127.0.0.1", message.body + html)
        self.assertNotRegex(html.lower(), r"<script|javascript:|<iframe|<link")
        self.assertNotRegex(html.lower(), r"google-analytics|tracking-pixel|webfont|fonts\.")
        self.assertNotIn(self.user.password, message.body + html)
        self.assertNotIn("EMAIL_HOST_PASSWORD", message.body + html)
        return html

    def test_no_reply_notice_is_central_and_contains_no_address(self):
        templates = Path(settings.BASE_DIR) / "templates" / "emails"
        html_base = (templates / "base.html").read_text(encoding="utf-8")
        text_base = (templates / "base.txt").read_text(encoding="utf-8")
        self.assertIn("Bitte antworte nicht auf diese Nachricht", html_base)
        self.assertIn("Bitte antworte nicht auf diese Nachricht", text_base)
        for template in templates.iterdir():
            if template.is_file():
                self.assertNotIn("noreply@", template.read_text(encoding="utf-8").lower())

    def test_midnight_violet_colors_are_explicit_in_base_and_content(self):
        templates = Path(settings.BASE_DIR) / "templates" / "emails"
        base = (templates / "base.html").read_text(encoding="utf-8").lower()
        verification = (templates / "verify_email.html").read_text(encoding="utf-8").lower()
        for color in ("#0b0812", "#171020", "#4c3568", "#f7f4fb", "#9b6cff"):
            self.assertIn(color, base + verification)
        self.assertIn("#21182e", verification)
        self.assertIn("mso-padding-alt", verification)

    def test_verification_email_has_text_html_cta_and_escaped_user(self):
        request = self.client.request().wsgi_request
        send_verification_email(request, self.user)
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "BrickMissing – E-Mail-Adresse bestätigen")
        self.assertEqual(message.content_subtype, "plain")
        html = self._assert_common_mail_safety(message)
        self.assertIn("E-Mail-Adresse bestätigen", html)
        self.assertIn("https://brickmissing.example/konto/verifizieren/", message.body)
        self.assertIn("Mail &lt;User&gt;", html)
        self.assertNotIn("Mail <User>", html)

    def test_email_change_has_text_and_html(self):
        request = self.client.request().wsgi_request
        create_email_change(request, self.user, "new@example.test")
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "BrickMissing – Neue E-Mail-Adresse bestätigen")
        html = self._assert_common_mail_safety(message)
        self.assertIn("Neue E-Mail-Adresse bestätigen", html)
        self.assertIn(
            "https://brickmissing.example/konto/profil/e-mail-bestaetigen/",
            message.body,
        )

    def test_password_reset_has_text_html_subject_and_absolute_fallback(self):
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": self.user.email}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "BrickMissing – Passwort zurücksetzen")
        html = self._assert_common_mail_safety(message)
        self.assertIn("Passwort zurücksetzen", html)
        self.assertRegex(
            message.body,
            r"https://brickmissing\.example/konto/passwort-neu/[^\s]+/[^\s]+/",
        )

    def test_test_email_view_has_text_and_html(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("test_email"), {"recipient": "recipient@example.test"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("backups:list"))
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "BrickMissing – E-Mail-Test")
        html = self._assert_common_mail_safety(message)
        self.assertIn("E-Mail-Test erfolgreich", html)
        self.assertIn("HTML- und Plain-Text-Mailversand", message.body)

    def test_management_test_email_uses_both_parts(self):
        call_command("test_email", "recipient@example.test")
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "BrickMissing – E-Mail-Test")
        self._assert_common_mail_safety(message)

    def test_html_contains_no_external_image_or_tracking_request(self):
        send_verification_email(self.client.request().wsgi_request, self.user)
        html = self._html(mail.outbox[-1])
        self.assertEqual(re.findall(r"<(?:img|script)[^>]+src=", html, re.I), [])
