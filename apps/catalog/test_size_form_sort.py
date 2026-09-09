from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Part
from .part_sorting import (
    parsed_part_dimensions,
    part_form_family,
    part_size_form_sort_key,
)


class PartSizeFormKeyTests(SimpleTestCase):
    def sorted_names(self, names, *, descending=False):
        return sorted(
            names,
            key=lambda name: part_size_form_sort_key(name, descending=descending),
        )

    def test_brick_dimensions_sort_small_to_large(self):
        names = [
            "Brick 2 x 4", "Brick 1 x 4", "Brick 1 x 1", "Brick 2 x 2",
            "Brick 1 x 3", "Brick 2 x 3", "Brick 1 x 2",
        ]
        self.assertEqual(
            self.sorted_names(names),
            [
                "Brick 1 x 1", "Brick 1 x 2", "Brick 1 x 3", "Brick 1 x 4",
                "Brick 2 x 2", "Brick 2 x 3", "Brick 2 x 4",
            ],
        )

    def test_descending_reverses_size_inside_family_not_family_order(self):
        names = ["Plate 1 x 1", "Brick 1 x 1", "Plate 2 x 4", "Brick 2 x 4"]
        self.assertEqual(
            self.sorted_names(names, descending=True),
            ["Brick 2 x 4", "Brick 1 x 1", "Plate 2 x 4", "Plate 1 x 1"],
        )

    def test_form_families_are_deterministic_and_stay_together(self):
        names = [
            "Tile 1 x 1", "Brick 2 x 4", "Slope 1 x 2", "Plate 2 x 2",
            "Brick 1 x 1", "Tile 2 x 2", "Plate 1 x 1",
        ]
        families = [part_form_family(name) for name in self.sorted_names(names)]
        self.assertEqual(
            families,
            ["brick", "brick", "plate", "plate", "tile", "tile", "slope"],
        )

    def test_technic_lengths_are_parsed_conservatively(self):
        self.assertEqual(parsed_part_dimensions("Technic Liftarm 5L"), (5, (5,)))
        self.assertEqual(parsed_part_dimensions("Technic Axle 6"), (6, (6,)))
        self.assertLess(
            part_size_form_sort_key("Technic Liftarm 3L"),
            part_size_form_sort_key("Technic Liftarm 7L"),
        )

    def test_rebrickable_style_names_map_to_practical_families(self):
        samples = {
            "Brick 1 x 2": "brick",
            "Plate, Modified 1 x 2 with Clip on Top": "plate",
            "Tile 2 x 2": "tile",
            "Slope 45 2 x 2": "slope",
            "Technic, Liftarm 1 x 7 Thick": "technic_liftarm",
            "Technic Axle 6": "technic_axle",
        }
        self.assertEqual(
            {name: part_form_family(name) for name in samples},
            samples,
        )
        self.assertEqual(part_form_family("Unknown", "Bricks"), "brick")

    def test_multiple_dimension_phrases_use_the_largest_reliable_footprint(self):
        self.assertEqual(
            parsed_part_dimensions("Bracket 1 x 2 - 1 x 4 [Square Corners]"),
            (4, (1, 4)),
        )

    def test_unknown_parts_have_stable_name_and_identifier_fallbacks(self):
        unparsed = ["Window Frame", "Animal Tail", "Window Glass"]
        first = self.sorted_names(unparsed)
        self.assertEqual(first, self.sorted_names(reversed(unparsed)))
        self.assertNotEqual(
            part_size_form_sort_key("Unknown", part_number="a"),
            part_size_form_sort_key("Unknown", part_number="b"),
        )


class SizeFormViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "size-form", "size-form@example.test", "A-long-safe-password-123"
        )
        self.client.force_login(self.user)
        self.missing_url = reverse("catalog:missing_parts")

    def make_part(self, element_id, name, *, color="Dark Bluish Gray"):
        return Part.objects.create(
            owner=self.user,
            element_id=element_id,
            part_number=element_id,
            name=name,
            color=color,
            quantity=2,
            owned_quantity=0,
            status=Part.Status.MISSING,
        )

    def names(self, response):
        return [group["name"] for group in response.context["page_obj"].object_list]

    def test_missing_parts_size_form_ascending_and_descending(self):
        self.make_part("brick-24", "Brick 2 x 4")
        self.make_part("brick-11", "Brick 1 x 1")
        self.make_part("brick-12", "Brick 1 x 2")

        ascending = self.client.get(self.missing_url, {"sort": "size_form"})
        descending = self.client.get(self.missing_url, {"sort": "-size_form"})

        self.assertEqual(
            self.names(ascending), ["Brick 1 x 1", "Brick 1 x 2", "Brick 2 x 4"]
        )
        self.assertEqual(
            self.names(descending), ["Brick 2 x 4", "Brick 1 x 2", "Brick 1 x 1"]
        )
        self.assertContains(ascending, "Größe/Form – aufsteigend")
        self.assertContains(descending, "Größe/Form – absteigend")

    def test_color_filter_is_applied_before_both_size_directions(self):
        self.make_part("gray-large", "Plate 2 x 4")
        self.make_part("gray-small", "Plate 1 x 1")
        self.make_part("red-small", "Plate 1 x 1", color="Red")

        ascending = self.client.get(
            self.missing_url,
            {"color": "Dark Bluish Gray", "sort": "size_form"},
        )
        descending = self.client.get(
            self.missing_url,
            {"color": "Dark Bluish Gray", "sort": "-size_form"},
        )

        self.assertEqual(self.names(ascending), ["Plate 1 x 1", "Plate 2 x 4"])
        self.assertEqual(self.names(descending), ["Plate 2 x 4", "Plate 1 x 1"])
        self.assertNotContains(ascending, "red-small")

    def test_part_list_uses_the_same_central_size_form_sort(self):
        self.make_part("tile-large", "Tile 2 x 4")
        self.make_part("tile-small", "Tile 1 x 1")
        url = reverse("catalog:part_list")

        ascending = list(
            self.client.get(url, {"sort": "size_form"}).context["page_obj"].object_list
        )
        descending = list(
            self.client.get(url, {"sort": "-size_form"}).context["page_obj"].object_list
        )

        self.assertEqual([part.name for part in ascending], ["Tile 1 x 1", "Tile 2 x 4"])
        self.assertEqual([part.name for part in descending], ["Tile 2 x 4", "Tile 1 x 1"])

    def test_pagination_preserves_size_sort_query(self):
        for index in range(1, 36):
            self.make_part(f"brick-{index}", f"Brick 1 x {index}")

        filters = {
            "q": "Brick",
            "color": "Dark Bluish Gray",
            "status": Part.Status.MISSING,
            "sort": "size_form",
        }
        first = self.client.get(self.missing_url, {**filters, "page": 1})
        second = self.client.get(self.missing_url, {**filters, "page": 2})

        self.assertEqual(len(first.context["page_obj"].object_list), 30)
        self.assertEqual(len(second.context["page_obj"].object_list), 5)
        self.assertEqual(self.names(first)[0], "Brick 1 x 1")
        self.assertEqual(self.names(second)[-1], "Brick 1 x 35")
        self.assertContains(first, "sort=size_form")
        self.assertContains(first, "q=Brick")
        self.assertContains(first, "status=missing")
        self.assertContains(first, "color=Dark+Bluish+Gray")

    def test_invalid_sort_falls_back_without_server_error(self):
        self.make_part("valid", "Brick 1 x 1")
        response = self.client.get(self.missing_url, {"sort": "not-a-sort"})
        part_response = self.client.get(reverse("catalog:part_list"), {"sort": "not-a-sort"})
        self.assertEqual((response.status_code, response.context["sort"]), (200, "name"))
        self.assertEqual(
            (part_response.status_code, part_response.context["sort"]), (200, "name")
        )

    def test_sorting_does_not_mutate_quantities_or_status(self):
        part = self.make_part("immutable", "Technic Axle 6")
        before = (part.quantity, part.owned_quantity, part.status, part.updated_at)

        self.client.get(self.missing_url, {"sort": "size_form"})
        self.client.get(reverse("catalog:part_list"), {"sort": "-size_form"})

        part.refresh_from_db()
        self.assertEqual(
            (part.quantity, part.owned_quantity, part.status, part.updated_at), before
        )
