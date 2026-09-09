from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SetFilterAlignmentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "alignment", "alignment@example.test", "A-long-safe-password-123"
        )
        self.client.force_login(self.user)

    def test_all_set_controls_use_the_same_direct_layout_wrapper(self):
        response = self.client.get(reverse("catalog:set_list"))
        content = response.content.decode()

        self.assertEqual(content.count('class="filter-field"'), 5)
        for label in ("Suche", "Themenwelt", "Vollständigkeit", "Sortierung"):
            self.assertIn('class="filter-label" for=', content)
            self.assertIn(f">{label}</label>", content)
        self.assertIn(
            '<div class="filter-field"><span class="filter-label" '
            'id="missing-color-label">Fehlende Farben</span>',
            content,
        )
        self.assertContains(
            response,
            'class="color-filter" data-color-filter aria-labelledby="missing-color-label"',
        )
        self.assertNotIn('<div><span class="filter-label">Fehlende Farben', content)

    def test_shared_layout_has_no_missing_color_offset_rule(self):
        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".filter-field { display: grid;", css)
        self.assertIn(".set-filters > .filter-field:first-child", css)
        self.assertIn("details[open] > summary {", css)
        self.assertNotIn("\ndetails[open] summary {", css)
        self.assertNotIn("missing-color-label {", css)
        self.assertNotIn(".set-filters .color-filter { margin", css)
