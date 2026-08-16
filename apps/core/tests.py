import hashlib
import re
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part
from apps.inventory.models import InventoryItem
from apps.organizer.models import Moc

from .client_ip import client_ip
from .models import DataQualityIssue, SavedView


class HealthAndHeadersTests(TestCase):
    def test_health_and_security_headers(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.json()["database"], "ok")
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertTrue(response["X-Request-ID"])

    def test_csp_keeps_strict_script_policy(self):
        response = self.client.get(reverse("health"))
        policy = response["Content-Security-Policy"]

        self.assertIn("script-src 'self'", policy)
        self.assertNotIn("'unsafe-inline'", policy)
        self.assertNotIn("'unsafe-eval'", policy)


class TestMailPrivacyTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_testmail_audit_hashes_recipient(self):
        user = User.objects.create_user(
            "mail-admin",
            "mail-admin@example.test",
            "A-long-safe-password-123",
            is_staff=True,
        )
        self.client.force_login(user)
        recipient = "private-recipient@example.test"
        response = self.client.post(reverse("test_email"), {"recipient": recipient})
        self.assertRedirects(
            response, reverse("backups:list"), fetch_redirect_response=False
        )
        event = AuditEvent.objects.get(action="email.test")
        self.assertNotIn(recipient, str(event.details))
        self.assertEqual(
            event.details["recipient_sha256"],
            hashlib.sha256(recipient.encode("utf-8")).hexdigest(),
        )


class PrivacyProductionAuditTests(TestCase):
    @override_settings(
        EMAIL_HOST_PASSWORD="must-not-appear",  # noqa: S106 - inert test sentinel
        SECRET_KEY="must-not-appear-secret",  # noqa: S106 - inert test sentinel
        BRICKLINK_TOKEN="must-not-appear-token",  # noqa: S106 - inert test sentinel
    )
    def test_command_is_read_only_and_does_not_print_secrets(self):
        output = StringIO()
        call_command("privacy_production_audit", stdout=output)
        text = output.getvalue()
        self.assertIn("READ-ONLY", text)
        self.assertIn("Security-Audit Retention Tage", text)
        self.assertIn("Staff Anzahl", text)
        self.assertIn("Legal Basis Status", text)
        self.assertNotIn("must-not-appear", text)


class AdminInterfaceTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            "administrator", "admin@example.test", "A-long-safe-password-123"
        )
        self.client.force_login(self.admin_user)

    def test_dashboard_has_branding_navigation_and_empty_state(self):
        response = self.client.get(reverse("admin:index"))

        self.assertContains(response, "BrickMissing")
        self.assertContains(response, "Systemverwaltung")
        self.assertContains(response, "Letzte Änderungen")
        self.assertContains(response, "Noch keine Aktivitäten vorhanden.")
        self.assertContains(response, 'href="/"')
        self.assertContains(response, "admin/css/brickmissing-admin.css")
        self.assertNotContains(response, "java" + "script:")
        content = response.content.decode()
        self.assertLess(content.index("Verwalten"), content.index("Hinzufügen"))

    def test_admin_add_actions_are_compact_icon_buttons(self):
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'class="addlink icon-only"')
        self.assertContains(response, 'aria-label="Hinzufügen"')

    def test_primary_admin_lists_and_forms_remain_available(self):
        lego_set = LegoSet.objects.create(
            owner=self.admin_user, set_number="10300", name="Zeitmaschine"
        )
        part = Part.objects.create(
            owner=self.admin_user, lego_set=lego_set, element_id="3001", name="Stein"
        )
        urls = (
            reverse("admin:accounts_user_changelist"),
            reverse("admin:catalog_legoset_changelist"),
            reverse("admin:catalog_part_changelist"),
            reverse("admin:inventory_inventoryitem_changelist"),
            reverse("admin:catalog_legoset_change", args=[lego_set.pk]),
            reverse("admin:catalog_part_change", args=[part.pk]),
            reverse("admin:catalog_part_delete", args=[part.pk]),
            reverse("admin:catalog_part_history", args=[part.pk]),
            reverse("admin:app_list", args=["organizer"]),
            reverse("admin:organizer_collection_changelist"),
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        filtered = self.client.get(
            reverse("admin:catalog_part_changelist"),
            {"q": "Stein", "status__exact": "missing", "p": 0},
        )
        self.assertContains(filtered, "Stein")

    def test_admin_login_translation_and_layout_hooks(self):
        self.client.logout()
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anmelden")
        self.assertContains(response, "BrickMissing")
        stylesheet = (settings.BASE_DIR / "static" / "admin" / "css" / "brickmissing-admin.css").read_text(encoding="utf-8")
        for selector in ("#changelist-filter", "#toolbar", ".paginator", ".delete-confirmation", ".change-history", ".login", "#recent-actions-module"):
            with self.subTest(selector=selector):
                self.assertIn(selector, stylesheet)

    def test_staff_permissions_are_not_broadened(self):
        staff = User.objects.create_user(
            "mitarbeiter", "staff@example.test", "A-long-safe-password-456", is_staff=True
        )
        self.client.force_login(staff)

        dashboard = self.client.get(reverse("admin:index"))
        self.assertContains(dashboard, "keine Administrationsrechte")
        self.assertEqual(
            self.client.get(reverse("admin:accounts_user_changelist")).status_code, 403
        )


class InterfaceQualityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "interface", "interface@example.test", "A-long-safe-password-123"
        )
        self.client.force_login(self.user)

    def test_primary_navigation_marks_current_area(self):
        response = self.client.get(reverse("catalog:set_list"))

        self.assertContains(response, 'aria-current="page">Sets</a>')
        self.assertContains(response, "Import und Export")
        self.assertContains(response, "Lagerorte")
        self.assertContains(response, 'class="nav-toggle ghost"')
        self.assertContains(response, "icons/brickmissing.svg")

    def test_missing_parts_has_exactly_one_primary_navigation_item(self):
        response = self.client.get(reverse("catalog:missing_parts"))
        navigation = re.search(r'<nav id="main-navigation".*?</nav>', response.content.decode(), re.DOTALL).group()
        self.assertEqual(navigation.count('aria-current="page"'), 1)
        self.assertIn('aria-current="page">Fehlteile</a>', navigation)

    def test_global_search_finds_all_supported_identifiers_and_paginates(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="SEARCH-SET", name="Burg")
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="E-100", design_id="DESIGN-42", name="Stein")
        InventoryItem.objects.create(owner=self.user, part_number="P-1", element_id="INV-ELEMENT", design_id="INV-DESIGN", name="Platte")
        Moc.objects.create(owner=self.user, project_code="MOC-SEARCH", name="Turm")
        for query, expected in (("SEARCH-SET", "Burg"), ("DESIGN-42", "Stein"), ("INV-ELEMENT", "Platte"), ("MOC-SEARCH", "Turm")):
            with self.subTest(query=query):
                self.assertContains(self.client.get(reverse("global_search"), {"q": query}), expected)
        Part.objects.bulk_create([Part(owner=self.user, element_id=f"PAGE-{index}", name="Treffer") for index in range(30)])
        response = self.client.get(reverse("global_search"), {"q": "Treffer", "parts_page": 2})
        self.assertEqual(response.context["parts"].paginator.count, 30)
        self.assertEqual(response.context["parts"].number, 2)

    def test_custom_error_pages_render(self):
        for template_name, expected in (
            ("400.html", "Die Anfrage konnte nicht verarbeitet werden."),
            ("403.html", "Du hast keinen Zugriff"),
            ("404.html", "Seite nicht gefunden"),
            ("500.html", "Etwas ist schiefgegangen"),
        ):
            with self.subTest(template=template_name):
                rendered = render_to_string(template_name)
                self.assertIn(expected, rendered)

    def test_all_templates_keep_csp_safe_ui_contract(self):
        forbidden = re.compile(
            r"javascript:|\son(?:click|change|submit|input|keydown|keyup|load)\s*=|<script(?![^>]*\bsrc=)|<style\b|\sstyle\s*=",
            re.IGNORECASE,
        )
        templates = sorted((Path(settings.BASE_DIR) / "templates").rglob("*.html"))
        self.assertTrue(templates)
        for template in templates:
            with self.subTest(template=template.relative_to(settings.BASE_DIR)):
                self.assertIsNone(forbidden.search(template.read_text(encoding="utf-8")))

    def test_midnight_violet_assets_and_wide_layout_exist(self):
        static_root = Path(settings.BASE_DIR) / "static"
        css = (static_root / "css" / "app.css").read_text(encoding="utf-8")
        manifest = (static_root / "manifest.webmanifest").read_text(encoding="utf-8")
        self.assertIn("--color-primary: #9b6cff", css)
        self.assertIn("--container-wide: 1760px", css)
        self.assertIn("icons/brickmissing.svg", manifest)
        self.assertTrue((static_root / "icons" / "brickmissing.svg").is_file())
        self.assertIn("[hidden] { display: none !important; }", css)


class ClientIPTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_direct_client_cannot_spoof_forwarded_header(self):
        request = self.factory.get(
            "/", REMOTE_ADDR="198.51.100.10", HTTP_X_FORWARDED_FOR="203.0.113.8"
        )
        self.assertEqual(client_ip(request), "198.51.100.10")

    def test_loopback_proxy_header_is_accepted(self):
        request = self.factory.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.8")
        self.assertEqual(client_ip(request), "203.0.113.8")

    def test_forwarded_chain_is_rejected(self):
        request = self.factory.get(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.8, 10.0.0.2"
        )
        self.assertEqual(client_ip(request), "127.0.0.1")


class SavedViewAndQualityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "owner", "owner@example.test", "A-long-safe-password-123", email_verified=True
        )
        self.other = User.objects.create_user(
            "other", "other@example.test", "A-long-safe-password-123", email_verified=True
        )
        self.client.force_login(self.user)

    def test_saved_view_save_load_rename_delete_and_ownership(self):
        self.client.post(
            reverse("saved_views"),
            {"name": "Red", "area": "parts", "path": "/fehlteile/", "query": "color=Red&sort=name"},
        )
        item = SavedView.objects.get(owner=self.user)
        self.assertContains(self.client.get(reverse("saved_views")), "color=Red")
        self.client.post(
            reverse("saved_views"),
            {
                "pk": item.pk,
                "name": "Renamed",
                "area": "parts",
                "path": "/fehlteile/",
                "query": "color=Red",
            },
        )
        item.refresh_from_db()
        self.assertEqual(item.name, "Renamed")
        foreign = SavedView.objects.create(
            owner=self.other, name="Foreign", area="parts", path="/", configuration={}
        )
        self.assertEqual(
            self.client.post(reverse("saved_view_delete", args=[foreign.pk])).status_code, 404
        )
        self.client.post(reverse("saved_view_delete", args=[item.pk]))
        self.assertFalse(SavedView.objects.filter(pk=item.pk).exists())

    def test_quality_scan_finds_duplicates_and_invalid_identifiers(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="100-1", name="One")
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="bad id", name="Part")
        Part.objects.create(
            owner=self.user, lego_set=lego_set, element_id="bad id", name="Duplicate"
        )
        self.client.post(reverse("quality_scan"))
        keys = set(
            DataQualityIssue.objects.filter(owner=self.user).values_list("issue_key", flat=True)
        )
        self.assertIn("duplicate_part", keys)
        self.assertIn("invalid_element_id", keys)
