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
from apps.integrations.models import PriceObservation

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
        self.assertContains(response, 'data-nav-group')
        self.assertContains(response, "Sammlung")
        self.assertContains(response, "Import & Export")
        self.assertContains(response, "Inventar")
        self.assertContains(response, 'class="nav-toggle ghost"')
        self.assertContains(response, "icons/brickmissing.svg")

    def test_grouped_navigation_keeps_routes_and_hides_global_search_from_primary(self):
        response = self.client.get(reverse("catalog:set_list"))
        navigation = re.search(r'<nav id="main-navigation".*?</nav>', response.content.decode(), re.DOTALL).group()
        self.assertIn(reverse("catalog:set_list"), navigation)
        self.assertIn(reverse("catalog:part_list"), navigation)
        self.assertIn(reverse("catalog:missing_parts"), navigation)
        self.assertIn(reverse("inventory:list"), navigation)
        self.assertIn(reverse("orders:list"), navigation)
        self.assertIn(reverse("organizer:label_studio"), navigation)
        self.assertIn(reverse("data_portability:import_page"), navigation)
        self.assertNotIn(reverse("media_library:list"), navigation)
        self.assertNotIn(reverse("global_search"), navigation)
        self.assertIn('class="nav-group', navigation)
        self.assertNotIn('class="nav-home" href="/suche/', navigation)

    def test_navigation_permissions_and_account_logout_semantics_remain(self):
        response = self.client.get(reverse("catalog:set_list"))
        content = response.content.decode()
        self.assertIn(reverse("accounts:profile"), content)
        self.assertIn(reverse("accounts:sessions"), content)
        self.assertIn(reverse("accounts:logout"), content)
        self.assertIn('method="post" action="/konto/abmelden/"', content)
        self.assertNotIn(reverse("backups:list"), content)

    def test_navigation_disclosure_markup_contains_accessible_controls(self):
        response = self.client.get(reverse("catalog:set_list"))
        content = response.content.decode()
        self.assertIn('aria-controls="main-navigation"', content)
        self.assertIn('data-nav-group', content)
        self.assertIn('summary>Sets</summary>', content)

    def test_navigation_group_labels_follow_active_collection_subsection(self):
        cases = (
            ("catalog:set_list", "Sets"),
            ("catalog:part_list", "Teile"),
            ("catalog:missing_parts", "Fehlteile"),
            ("inventory:list", "Inventar"),
            ("inventory:locations", "Inventar"),
            ("orders:list", "Bestellungen"),
            ("organizer:label_studio", "Etiketten & QR-Codes"),
        )
        for route_name, label in cases:
            with self.subTest(route_name=route_name):
                content = self.client.get(reverse(route_name)).content.decode()
                self.assertIn(f"<summary>{label}</summary>", content)

    def test_missing_parts_has_exactly_one_primary_navigation_item(self):
        response = self.client.get(reverse("catalog:missing_parts"))
        navigation = re.search(r'<nav id="main-navigation".*?</nav>', response.content.decode(), re.DOTALL).group()
        self.assertEqual(navigation.count('aria-current="page"'), 1)
        self.assertIn('aria-current="page">Fehlteile</a>', navigation)

    def test_trash_activates_only_system_navigation_group(self):
        response = self.client.get(reverse("catalog:trash"))
        navigation = re.search(
            r'<nav id="main-navigation".*?</nav>',
            response.content.decode(),
            re.DOTALL,
        ).group()
        self.assertEqual(navigation.count('class="nav-group is-active"'), 1)
        self.assertIn("<summary>Papierkorb</summary>", navigation)
        self.assertNotIn('<details class="nav-group is-active" data-nav-group><summary>Sammlung</summary>', navigation)
        self.assertIn('aria-current="page">Papierkorb</a>', navigation)

    def test_dashboard_search_finds_owned_sets_parts_and_minifigures(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="SEARCH-SET", name="Burg")
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="E-100", design_id="DESIGN-42", name="Stein")
        for query, expected in (("SEARCH-SET", "Burg"), ("DESIGN-42", "Stein")):
            with self.subTest(query=query):
                self.assertContains(self.client.get(reverse("dashboard"), {"q": query}), expected)
        redirect_response = self.client.get(reverse("global_search"), {"q": "SEARCH-SET"})
        self.assertRedirects(redirect_response, "/?q=SEARCH-SET")

    def test_ctrl_k_targets_dashboard_collection_search(self):
        response = self.client.get(reverse("catalog:set_list"))
        self.assertContains(
            response,
            f'data-dashboard-search-url="{reverse("dashboard")}#collection-search"',
        )
        source = (Path(settings.BASE_DIR) / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('getElementById("collection-search")', source)
        self.assertIn('window.location.hash === "#collection-search"', source)
        self.assertNotIn('getElementById("global-search")', source)
        self.assertNotIn('window.location.assign("/suche/")', source)

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
        browser_forbidden = re.compile(
            r"javascript:|\son(?:click|change|submit|input|keydown|keyup|load)\s*=|<script(?![^>]*\bsrc=)|<style\b|\sstyle\s*=",
            re.IGNORECASE,
        )
        email_forbidden = re.compile(
            r"javascript:|\son(?:click|change|submit|input|keydown|keyup|load)\s*=|<script|<style\b",
            re.IGNORECASE,
        )
        templates = sorted((Path(settings.BASE_DIR) / "templates").rglob("*.html"))
        self.assertTrue(templates)
        for template in templates:
            with self.subTest(template=template.relative_to(settings.BASE_DIR)):
                forbidden = (
                    email_forbidden
                    if template.parent.name == "emails"
                    else browser_forbidden
                )
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

    def test_quality_view_groups_repeated_issues_without_mutating_data(self):
        DataQualityIssue.objects.bulk_create([
            DataQualityIssue(owner=self.user, issue_key="missing_price_owner", entity_type="price", entity_id=str(index), severity="warning", message="Historische Preisbeobachtung ohne Eigentümer (Legacy-Import)")
            for index in range(3)
        ])
        response = self.client.get(reverse("quality"))
        self.assertContains(response, "Problemarten")
        self.assertNotContains(response, "Fehlerarten")
        self.assertContains(response, "Warnung")
        self.assertContains(response, 'class="table-wrap"')
        self.assertContains(response, 'class="quality-details"')
        self.assertContains(response, "3")
        self.assertEqual(response.context["issue_groups"][0]["count"], 3)
        self.assertEqual(DataQualityIssue.objects.filter(owner=self.user).count(), 3)

    def test_legacy_price_owner_issue_is_warning_and_scan_is_read_only(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        orphan = PriceObservation.objects.create(
            owner=None,
            entity_type="set",
            entity_id="legacy-1",
            price="4.50",
        )
        owned = PriceObservation.objects.create(
            owner=self.user,
            entity_type="set",
            entity_id="owned-1",
            price="5.00",
        )
        self.client.post(reverse("quality_scan"))
        issue = DataQualityIssue.objects.get(owner=self.user, issue_key="missing_price_owner")
        self.assertEqual(issue.severity, "warning")
        self.assertIn("Legacy-Import", issue.message)
        self.assertEqual(
            DataQualityIssue.objects.filter(owner=self.user, severity="error").count(), 0
        )
        self.assertEqual(PriceObservation.objects.get(pk=orphan.pk).owner_id, None)
        self.assertEqual(PriceObservation.objects.get(pk=owned.pk).owner_id, self.user.pk)

    def test_quality_localizes_error_severity_and_saved_views_have_mobile_hook(self):
        DataQualityIssue.objects.create(
            owner=self.user,
            issue_key="broken",
            entity_type="set",
            entity_id="1",
            severity="error",
            message="Defekter Datensatz",
        )
        self.assertContains(self.client.get(reverse("quality")), ">Fehler</span>")
        SavedView.objects.create(
            owner=self.user,
            name="Mobile",
            area="parts",
            path="/teile/",
            configuration={},
        )
        saved = self.client.get(reverse("saved_views"))
        self.assertContains(saved, 'class="row saved-view-manager-row"')
        css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".saved-view-manager-row", css)
        self.assertIn(".quality-details", css)
