"""Public documentation routes and safe Markdown rendering."""

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from .pages import PAGES, DocumentationPage
from .rendering import render_document


class DocumentationPageTests(SimpleTestCase):
    def test_every_public_page_is_anonymously_readable(self):
        for page in (page for page in PAGES if page.audience == "public"):
            with self.subTest(page=page.slug):
                url = reverse(f"documentation:{page.route_name}")
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="docs-content"')
                self.assertContains(response, 'aria-label="Dokumentationsseiten"')
                self.assertContains(response, f'href="{url}" aria-current="page"')
                self.assertContains(response, '/static/css/docs.css')

    def test_index_uses_repository_markdown_and_converts_links(self):
        response = self.client.get("/docs/")
        self.assertContains(response, "BrickMissing 8.6.0")
        self.assertContains(response, '<a href="/docs/getting-started/">Erste Schritte</a>', html=True)
        self.assertNotContains(response, 'href="/docs/developer/"')

    def test_published_pages_have_no_unresolved_markdown_links(self):
        root = Path(__file__).resolve().parents[2] / "docs"
        for page in PAGES:
            with self.subTest(page=page.source):
                html = render_document(page.source, (root / page.source).read_text(encoding="utf-8"))
                hrefs = re.findall(r'href="([^"]+)"', html)
                self.assertNotIn("#", hrefs)
                self.assertFalse(any(link.endswith(".md") for link in hrefs))

    def test_public_markdown_has_no_administrator_links(self):
        root = Path(__file__).resolve().parents[2] / "docs"
        for page in (page for page in PAGES if page.audience == "public"):
            with self.subTest(page=page.source):
                html = render_document(page.source, (root / page.source).read_text(encoding="utf-8"))
                self.assertNotIn('href="/docs/developer/', html)

    def test_future_developer_page_is_admin_only_by_metadata(self):
        future = DocumentationPage("developer/future", "developer/future.md", "Zukunft")
        self.assertEqual(future.audience, "admin")
        self.assertTrue(all(page.audience == "admin" for page in PAGES
                            if page.slug == "developer" or page.slug.startswith("developer/")))

    def test_unknown_and_traversal_paths_return_404(self):
        for path in (
            "/docs/does-not-exist/", "/docs/.env/", "/docs/manage.py/",
            "/docs/%2e%2e/%2e%2e/.env/", "/docs/%2e%2e%2f.env/",
            "/docs/developer/../../.env/", "/docs/developer/%2e%2e/.env/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    @override_settings(DEBUG=False)
    def test_missing_configured_file_returns_generic_404(self):
        with TemporaryDirectory() as empty_root:
            with patch("apps.documentation.views.document_root", return_value=Path(empty_root)):
                response = self.client.get("/docs/sets/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(empty_root.encode(), response.content)

    def test_main_navigation_reaches_docs_without_login(self):
        response = self.client.get("/docs/sets/")
        self.assertContains(response, '<a href="/docs/">Hilfe</a>', html=True)
        self.assertNotContains(response, ">Entwickler</h2>")
        self.assertNotContains(response, '/docs/developer/')


class AuthenticatedNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="docs-reader", email="docs-reader@example.test",
            password="docs-test-password",  # noqa: S106 - ephemeral test account
        )
        cls.admin = User.objects.create_user(
            username="docs-admin", email="docs-admin@example.test",
            password="docs-admin-password",  # noqa: S106 - ephemeral test account
            is_staff=True,
        )

    def test_main_navigation_highlights_help(self):
        self.client.force_login(self.user)
        response = self.client.get("/docs/sets/")
        self.assertContains(response, '<a class="nav-home" href="/docs/" aria-current="page">Hilfe</a>',
                            html=True)

    def test_public_index_is_readable_for_normal_user_and_admin(self):
        for user in (self.user, self.admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get("/docs/").status_code, 200)

    def test_all_developer_pages_require_staff(self):
        for page in (page for page in PAGES if page.audience == "admin"):
            url = reverse(f"documentation:{page.route_name}")
            with self.subTest(url=url):
                self.client.logout()
                self.assertEqual(self.client.get(url).status_code, 404)
                self.client.force_login(self.user)
                self.assertEqual(self.client.get(url).status_code, 404)
                self.client.force_login(self.admin)
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_developer_navigation_is_admin_only(self):
        self.client.force_login(self.user)
        normal = self.client.get("/docs/")
        self.assertNotContains(normal, ">Entwickler</h2>")
        self.assertNotContains(normal, '/docs/developer/')

        self.client.force_login(self.admin)
        administrator = self.client.get("/docs/")
        self.assertContains(administrator, ">Entwickler</h2>")
        self.assertContains(administrator, 'href="/docs/developer/"')
        self.assertContains(administrator, 'href="/docs/developer/versioning/"')

    def test_developer_relative_parent_link_stays_inside_docs(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/docs/developer/releases/"),
                            '<a href="/docs/developer/versioning/">Versionierung</a>', html=True)

    def test_cache_never_reuses_administrator_navigation(self):
        self.client.force_login(self.admin)
        administrator = self.client.get("/docs/")
        self.assertContains(administrator, ">Entwickler</h2>")
        self.assertIn("private", administrator["Cache-Control"])
        self.assertIn("no-store", administrator["Cache-Control"])
        self.assertIn("Cookie", administrator["Vary"])

        self.client.force_login(self.user)
        normal = self.client.get("/docs/")
        self.assertNotContains(normal, ">Entwickler</h2>")
        self.assertIn("no-store", normal["Cache-Control"])
        self.assertIn("Cookie", normal["Vary"])
        self.assertEqual(self.client.get("/docs/developer/").status_code, 404)

        self.client.logout()
        anonymous = self.client.get("/docs/")
        self.assertNotContains(anonymous, ">Entwickler</h2>")
        self.assertIn("no-store", anonymous["Cache-Control"])


class MarkdownRenderingTests(SimpleTestCase):
    def test_headings_lists_links_tables_and_code_blocks(self):
        markdown = (
            "# Titel\n\n- [Sets](sets.md)\n- Zweitens\n\n"
            "| A | B |\n| --- | --- |\n| Eins | Zwei |\n\n"
            "```text\nsehr-langer-technischer-begriff\n```\n"
        )
        html = render_document("index.md", markdown)
        self.assertIn("<h1>Titel</h1>", html)
        self.assertIn('<a href="/docs/sets/">Sets</a>', html)
        self.assertIn("<ul>", html)
        self.assertIn('class="docs-table-wrap"', html)
        self.assertIn("<table>", html)
        self.assertIn("<pre><code", html)

    def test_raw_html_and_unsafe_urls_cannot_execute(self):
        markdown = (
            '<script>alert(1)</script>\n\n'
            '<img src=x onerror=alert(1)>\n\n'
            '[bad](javascript:alert(1))\n\n'
            '[outside](../../.env)\n\n'
            '[plain](http://example.test)\n\n'
            '[safe](https://example.test/page)\n'
        )
        html = render_document("index.md", markdown)
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn('href="../../.env"', html)
        self.assertNotIn('href="http://', html)
        self.assertIn('<a href="https://example.test/page">safe</a>', html)

    def test_relative_links_and_fragments(self):
        html = render_document(
            "developer/releases.md",
            "[Version](../VERSIONING.md#release) [Architektur](architecture.md) [Hier](#oben)",
        )
        self.assertIn('href="/docs/developer/versioning/#release"', html)
        self.assertIn('href="/docs/developer/architecture/"', html)
        self.assertIn('href="#oben"', html)
