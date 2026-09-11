from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.templatetags.privacy import proxied_image_url
from apps.organizer.models import MinifigurePart, SetMinifigure

from .models import LegoSet, Part, SetInventoryItem
from .services import dashboard_collection_data


class DashboardTests(TestCase):
    def setUp(self):
        self.password = "A-long-safe-password-123"  # noqa: S105 - test credential
        self.user = get_user_model().objects.create_user(
            "dashboard-owner",
            "dashboard-owner@example.test",
            self.password,
            first_name="Ada",
        )
        self.other = get_user_model().objects.create_user(
            "dashboard-other", "dashboard-other@example.test", self.password
        )
        self.client.force_login(self.user)

    def make_set(self, number, *, owner=None, theme="Space", name=None, image_url=""):
        return LegoSet.objects.create(
            owner=owner or self.user,
            set_number=number,
            name=name or f"Set {number}",
            theme=theme,
            image_url=image_url,
        )

    def test_dashboard_loads_with_dynamic_welcome_actions_and_no_second_search(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Willkommen zurück, Ada!")
        self.assertNotContains(response, 'id="collection-search"')
        for route in (
            reverse("catalog:set_create"),
            reverse("catalog:part_create"),
            reverse("organizer:minifigure_list"),
            reverse("data_portability:export_csv"),
            reverse("catalog:set_list"),
            reverse("catalog:missing_parts"),
            reverse("data_portability:import_page"),
            reverse("catalog:trash"),
        ):
            self.assertContains(response, f'href="{route}"')
        self.assertContains(response, "dashboard-banner")
        self.assertContains(response, 'src="/static/img/dashboard-banner.webp"')
        self.assertContains(response, 'class="dashboard-banner-image"')
        self.assertNotContains(response, "Banner-Platzhalter")

    def test_dashboard_uses_authoritative_owner_scoped_quantities(self):
        lego_set = self.make_set("100-1")
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            element_id="300101",
            part_number="3001",
            color_name="Red",
            name="Brick",
            required_quantity=10,
            owned_quantity=6,
        )
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="spare",
            name="Spare",
            required_quantity=50,
            owned_quantity=0,
            is_spare=True,
        )
        Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id="300101",
            name="Stale mirror",
            quantity=99,
            owned_quantity=0,
        )
        figure = SetMinifigure.objects.create(
            owner=self.user,
            lego_set=lego_set,
            figure_number="fig-1",
            name="Figure",
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            element_id="362601",
            part_number="3626",
            color_name="Yellow",
            name="Head",
            quantity=2,
            owned_quantity=1,
        )
        foreign_set = self.make_set("other-1", owner=self.other)
        SetInventoryItem.objects.create(
            lego_set=foreign_set,
            part_number="foreign",
            name="Foreign",
            required_quantity=1000,
            owned_quantity=0,
        )
        SetMinifigure.objects.create(
            owner=self.other,
            lego_set=foreign_set,
            figure_number="other-fig",
            name="Other figure",
        )

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["set_count"], 1)
        self.assertEqual(response.context["part_count"], 1)
        self.assertEqual(response.context["lego_parts_total"], 12)
        self.assertEqual(response.context["lego_parts_owned"], 7)
        self.assertEqual(response.context["lego_parts_missing"], 5)
        self.assertEqual(response.context["missing_position_count"], 2)
        self.assertEqual(response.context["minifigure_count"], 1)
        self.assertEqual(response.context["owned_percent_display"], "58,3")
        self.assertEqual(response.context["missing_percent_display"], "41,7")

    def test_zero_part_empty_state_has_safe_percentages(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["lego_parts_total"], 0)
        self.assertEqual(response.context["owned_percent"], 0.0)
        self.assertEqual(response.context["missing_percent"], 0.0)
        self.assertContains(response, "Noch keine Sets vorhanden")
        self.assertContains(response, "Keine Fehlteile")
        self.assertContains(response, "Noch keine Themenwelten")

    def test_recent_sets_are_newest_first_owner_scoped_and_limited_to_three(self):
        now = timezone.now()
        image_url = "https://example.test/images/recent-0.webp"
        sets = [
            self.make_set(
                f"recent-{index}",
                image_url=image_url if index == 0 else "",
            )
            for index in range(5)
        ]
        for index, lego_set in enumerate(sets):
            LegoSet.objects.filter(pk=lego_set.pk).update(
                created_at=now - timedelta(days=index)
            )
        foreign = self.make_set("foreign-newest", owner=self.other)
        LegoSet.objects.filter(pk=foreign.pk).update(created_at=now + timedelta(days=1))

        response = self.client.get(reverse("dashboard"))
        recent = response.context["recent_sets"]
        self.assertEqual(len(recent), 3)
        self.assertEqual([item.pk for item in recent], [item.pk for item in sets[:3]])
        self.assertNotIn(foreign.pk, {item.pk for item in recent})
        for lego_set in sets[:3]:
            self.assertContains(
                response,
                f'href="{reverse("catalog:set_detail", args=[lego_set.pk])}"',
            )
        self.assertNotContains(
            response,
            f'href="{reverse("catalog:set_detail", args=[sets[3].pk])}"',
        )
        self.assertContains(response, f'src="{proxied_image_url(image_url)}"')
        self.assertContains(response, "dashboard-image-placeholder", count=2)

    def test_recent_set_images_use_centered_contain_layout(self):
        self.make_set("image-1", image_url="https://example.test/set.webp")
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'class="dashboard-set-media"')
        stylesheet = (
            Path(__file__).resolve().parents[2] / "static" / "css" / "app.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".dashboard-set-media img", stylesheet)
        self.assertIn("object-fit: contain", stylesheet)
        self.assertIn("object-position: center", stylesheet)

    def test_parts_shortcut_keeps_existing_route_and_correct_label(self):
        response = self.client.get(reverse("dashboard"))
        part_route = reverse("catalog:part_list")
        self.assertContains(response, f'href="{part_route}"><span aria-hidden="true">▦</span><span>Teile</span>')
        self.assertNotContains(response, "<span>Farben</span>")

    def test_donut_svg_is_mathematically_valid_for_edge_cases(self):
        lego_set = self.make_set("donut-1")
        cases = (
            (1000, 977, "97.7", "2.3", "-97.7", "97,7", "2,3"),
            (100, 100, "100.0", "0.0", "-100.0", "100,0", "0,0"),
            (100, 0, "0.0", "100.0", "0.0", "0,0", "100,0"),
            (100, 50, "50.0", "50.0", "-50.0", "50,0", "50,0"),
            (1000, 999, "99.9", "0.1", "-99.9", "99,9", "0,1"),
            (0, 0, "0.0", "0.0", "0.0", "0,0", "0,0"),
        )
        for required, owned, owned_svg, missing_svg, offset, owned_text, missing_text in cases:
            with self.subTest(required=required, owned=owned):
                SetInventoryItem.objects.all().delete()
                if required:
                    SetInventoryItem.objects.create(
                        lego_set=lego_set,
                        part_number="donut-part",
                        name="Donut part",
                        required_quantity=required,
                        owned_quantity=owned,
                    )
                response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.context["owned_percent_svg"], owned_svg)
                self.assertEqual(response.context["missing_percent_svg"], missing_svg)
                self.assertEqual(response.context["missing_percent_offset_svg"], offset)
                self.assertEqual(response.context["owned_percent_display"], owned_text)
                self.assertEqual(response.context["missing_percent_display"], missing_text)
                self.assertContains(
                    response,
                    'class="dashboard-donut-owned" cx="21" cy="21" r="15.9155" pathLength="100"',
                )
                self.assertContains(
                    response,
                    f'class="dashboard-donut-missing" cx="21" cy="21" r="15.9155" pathLength="100" stroke-dasharray="{missing_svg} {owned_svg}" stroke-dashoffset="{offset}"',
                )
                self.assertNotContains(response, "dashboard-donut-owned\" cx=\"21\" cy=\"21\" r=\"15.9155\" pathLength=\"100\" stroke-dasharray")
                markup = response.content.decode()
                self.assertNotIn("NaN", markup)
                self.assertNotIn("Infinity", markup)

    def test_donut_retains_text_summary_and_owner_isolation(self):
        own_set = self.make_set("donut-own")
        foreign_set = self.make_set("donut-foreign", owner=self.other)
        SetInventoryItem.objects.create(
            lego_set=own_set,
            part_number="own",
            name="Own",
            required_quantity=1000,
            owned_quantity=977,
        )
        SetInventoryItem.objects.create(
            lego_set=foreign_set,
            part_number="foreign",
            name="Foreign",
            required_quantity=1000,
            owned_quantity=0,
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["lego_parts_total"], 1000)
        self.assertEqual(response.context["lego_parts_owned"], 977)
        self.assertEqual(response.context["lego_parts_missing"], 23)
        self.assertContains(
            response,
            'aria-label="977 Teile vorhanden, 23 Teile fehlend, 1000 Teile gesamt"',
        )

    def test_top_five_aggregates_authoritative_normal_and_minifigure_shortages(self):
        lego_set = self.make_set("top-1")
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-top", name="Figure"
        )
        for index, required in enumerate((2, 3, 4, 5, 6, 7)):
            SetInventoryItem.objects.create(
                lego_set=lego_set,
                element_id=f"part-{index}",
                part_number=f"design-{index}",
                color_name="Blue",
                name=f"Part {index}",
                required_quantity=required,
                owned_quantity=0,
            )
        MinifigurePart.objects.create(
            minifigure=figure,
            element_id="part-5",
            part_number="design-5",
            color_name="Blue",
            name="Part 5",
            quantity=3,
            owned_quantity=1,
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="ignored-spare",
            name="Ignored spare",
            quantity=100,
            owned_quantity=0,
            is_spare=True,
        )
        response = self.client.get(reverse("dashboard"))
        top = response.context["top_missing_parts"]
        self.assertEqual(len(top), 5)
        self.assertEqual((top[0]["identifier"], top[0]["missing"]), ("part-5", 9))
        self.assertNotIn("ignored-spare", {item["identifier"] for item in top})

    def test_themes_are_owner_scoped_aggregated_and_limited(self):
        for index in range(9):
            self.make_set(f"theme-{index}", theme=f"Theme {index}")
        self.make_set("theme-extra", theme="Theme 0")
        self.make_set("foreign-theme", owner=self.other, theme="Secret")
        response = self.client.get(reverse("dashboard"))
        themes = response.context["top_themes"]
        self.assertEqual(len(themes), 7)
        self.assertEqual(themes[0], {"theme": "Theme 0", "set_count": 2})
        self.assertNotIn("Secret", {item["theme"] for item in themes})

    def test_dashboard_get_does_not_mutate_inventory_or_status(self):
        lego_set = self.make_set("readonly-1")
        allocation = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="readonly",
            name="Read only",
            required_quantity=4,
            owned_quantity=1,
        )
        part = Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id="readonly",
            name="Read only",
            quantity=4,
            owned_quantity=1,
            status=Part.Status.MISSING,
        )
        before = (allocation.owned_quantity, allocation.updated_at, part.status, part.updated_at)
        self.client.get(reverse("dashboard"))
        allocation.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual(
            (allocation.owned_quantity, allocation.updated_at, part.status, part.updated_at),
            before,
        )

    def test_dashboard_data_uses_a_fixed_number_of_bulk_queries(self):
        with CaptureQueriesContext(connection) as captured:
            dashboard_collection_data(self.user)
        self.assertLessEqual(len(captured), 9)
