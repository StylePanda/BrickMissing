from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

LEGAL_BASE = {
    "LEGAL_OPERATOR_NAME": "Max Mustermann",
    "LEGAL_OPERATOR_ADDRESS": "Musterweg 1, 1010 Wien",
    "LEGAL_OPERATOR_CITY": "1010 Wien",
    "LEGAL_OPERATOR_EMAIL": "kontakt@example.test",
    "LEGAL_OPERATOR_COUNTRY": "Österreich",
}


@override_settings(**LEGAL_BASE)
class LegalPageTests(TestCase):
    def test_legal_pages_are_public(self):
        for name in ("legal:imprint", "legal:privacy"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("X-Robots-Tag", response)

    def test_account_pages_are_not_indexable(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    @override_settings(
        LEGAL_OPERATOR_NAME="<script>alarm(1)</script>",
        LEGAL_OPERATOR_ADDRESS="<img src=x onerror=alarm(1)>",
    )
    def test_operator_information_is_escaped(self):
        response = self.client.get(reverse("legal:imprint"))
        self.assertNotContains(response, "<script>", html=False)
        self.assertContains(response, "&lt;script&gt;alarm(1)&lt;/script&gt;", html=False)
        self.assertNotContains(response, "<img src=x", html=False)

    @override_settings(
        LEGAL_COMPANY_NAME="",
        LEGAL_COMPANY_REGISTER_NUMBER="",
        LEGAL_COMPANY_REGISTER_COURT="",
        LEGAL_VAT_ID="",
    )
    def test_optional_company_fields_are_hidden_when_empty(self):
        response = self.client.get(reverse("legal:imprint"))
        self.assertNotContains(response, "Firmenbuchnummer")
        self.assertNotContains(response, "UID")

    @override_settings(LEGAL_COMPANY_NAME="Beispiel GmbH", LEGAL_VAT_ID="ATU00000000")
    def test_configured_optional_fields_are_shown(self):
        response = self.client.get(reverse("legal:imprint"))
        self.assertContains(response, "Beispiel GmbH")
        self.assertContains(response, "ATU00000000")

    @override_settings(
        LEGAL_OPERATOR_NAME="Simon Weiss",
        LEGAL_OPERATOR_CITY="Wien",
        LEGAL_OPERATOR_EMAIL="kontakt@example.test",
    )
    def test_imprint_contains_shared_stylepanda_project_information(self):
        response = self.client.get(reverse("legal:imprint"))
        for text in (
            "Medieninhaber",
            "Simon Weiss",
            "Wohnort: Wien",
            "Kontakt",
            "kontakt@example.test",
            "Unter StylePanda werden private, nichtkommerzielle Webprojekte",
            "BrickMissing, eine private Webanwendung",
            "Sets, Teilen, Fehlteilen, Inventar",
            "StylePanda Tools",
            "browserbasierter Text- und PDF-Werkzeuge",
            "Hinweis zu BrickMissing",
            "unabhängiges Projekt",
            "LEGO® ist eine Marke der LEGO Gruppe",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, "Musterweg 1")

    def test_imprint_states_minimal_media_law_basis_with_official_ris_link(self):
        response = self.client.get(reverse("legal:imprint"))
        self.assertNotContains(response, "E-Commerce-Gesetz")
        self.assertContains(response, "ris.bka.gv.at")
        self.assertContains(response, "§ 25 Abs. 5 Mediengesetz (MedienG)")
        self.assertContains(response, "Wohnort: 1010 Wien")
        self.assertNotContains(response, "Musterweg 1")

    @override_settings(
        LEGAL_OPERATOR_ADDRESS="Musterstraße 1, 1150 Wien, Österreich",
        LEGAL_OPERATOR_CITY="1150 Wien",
    )
    def test_imprint_uses_explicit_city_not_address_or_country(self):
        response = self.client.get(reverse("legal:imprint"))
        self.assertContains(response, "Wohnort: 1150 Wien")
        self.assertNotContains(response, "Musterstraße 1")
        self.assertNotContains(response, "Österreich</span>")

    @override_settings(
        SECRET_KEY="do-not-render-secret",  # noqa: S106
        EMAIL_HOST_PASSWORD="do-not-render-mail-secret",  # noqa: S106
        BRICKLINK_TOKEN="do-not-render-token",  # noqa: S106
    )
    def test_legal_pages_do_not_render_secrets(self):
        response = self.client.get(reverse("legal:privacy"))
        for secret in ("do-not-render-secret", "do-not-render-mail-secret", "do-not-render-token"):
            self.assertNotContains(response, secret)

    def test_footer_auth_registration_profile_and_privacy_content(self):
        login = self.client.get(reverse("accounts:login"))
        self.assertContains(login, reverse("legal:imprint"))
        self.assertContains(login, reverse("legal:privacy"))
        register = self.client.get(reverse("accounts:register"))
        self.assertContains(register, "Datenschutzerklärung")
        user = get_user_model().objects.create_user(
            username="privacy-profile",
            email="privacy-profile@example.test",
            password="A-very-long-password-123",  # noqa: S106
            email_verified=True,
        )
        self.client.force_login(user)
        profile = self.client.get(reverse("accounts:profile"))
        for text in ("Datenschutz &amp; Daten", "Meine Daten exportieren", "Impressum"):
            self.assertContains(profile, text, html=False)
        privacy = self.client.get(reverse("legal:privacy"))
        for text in ("sessionid", "csrftoken", "brickmissing-theme", "Service-Worker-Cache"):
            self.assertContains(privacy, text)
        for text in (
            "Security-AuditEvents",
            "Gelesene Benachrichtigungen",
            "Soft-gelöschte Sets",
            "Legacy-Migrationsdaten",
            "Nginx täglich",
        ):
            self.assertContains(privacy, text)
        self.assertNotContains(privacy, "cookie-consent")
        self.assertNotContains(privacy, "googletagmanager.com")

    def test_privacy_final_check_is_ready_with_real_operator_data(self):
        output = StringIO()
        call_command("privacy_final_check", stdout=output)
        value = output.getvalue()
        self.assertIn("READ-ONLY", value)
        self.assertIn("PHASE 11 STATUS: READY", value)

    @override_settings(
        SETTINGS_MODULE="config.settings.production",
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        SECURE_HSTS_SECONDS=3600,
    )
    def test_privacy_final_check_is_ready_with_production_security(self):
        output = StringIO()
        call_command("privacy_final_check", stdout=output)
        self.assertIn("PHASE 11 STATUS: READY", output.getvalue())

    @override_settings(LEGAL_OPERATOR_NAME="", DEBUG=False)
    def test_privacy_final_check_blocks_missing_production_operator_data(self):
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("privacy_final_check", stdout=output)
        value = output.getvalue()
        self.assertIn("ERROR Betreiberbasisdaten", value)
        self.assertIn("PHASE 11 STATUS: NOT READY", value)
