from fractions import Fraction

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Part
from .part_sorting import parsed_part_dimensions, part_size_form_sort_key


def score(name):
    parsed = parsed_part_dimensions(name)
    return parsed[0] if parsed else None


class PhysicalSizeTests(SimpleTestCase):
    def test_basis_and_long_parts_increase(self):
        for dimensions in (
            ["1 x 1", "1 x 2", "1 x 4", "1 x 8", "1 x 12", "1 x 16"],
            ["2 x 2", "2 x 4", "4 x 4", "6 x 8", "8 x 16"],
        ):
            scores = [score("Brick " + item) for item in dimensions]
            self.assertEqual(scores, sorted(scores))
            self.assertEqual(len(set(scores)), len(scores))
        self.assertGreater(score("Brick 1 x 8"), score("Brick 3 x 3"))
        self.assertGreater(score("Brick 1 x 16"), score("Brick 4 x 4"))

    def test_3d_extent_increases(self):
        self.assertLess(score("Panel 2 x 2 x 1"), score("Panel 2 x 2 x 3"))
        self.assertLess(score("Panel 2 x 4 x 1"), score("Panel 2 x 4 x 3"))
        self.assertEqual(parsed_part_dimensions("Panel 2 x 4 x 3")[1], (2, 4, 3))

    def test_technic_lengths_and_named_lengths(self):
        scores = [score("Technic Axle " + str(length) + "L") for length in (3, 5, 7, 9, 11, 15)]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(len(set(scores)), len(scores))
        self.assertEqual(score("Technic Beam 7"), score("Technic Beam 7L"))
        self.assertGreater(score("Technic Axle 15L"), score("Brick 2 x 2"))

    def test_local_fractional_and_metric_names(self):
        self.assertEqual(
            parsed_part_dimensions("Vehicle Base 4 x 12 x 3/4")[1],
            (4, 12, 3 / 4),
        )
        self.assertEqual(
            parsed_part_dimensions("Brick Wedged 1 x 2 x 2/3")[1],
            (1, 2, Fraction(2, 3)),
        )
        self.assertLess(score("Tyre 37 x 18 R Balloon"), score("Plate 2 x 16"))

    def test_regression_design_30248_without_identity_rule(self):
        target = "Helicopter Skid Rails 12 x 6"
        self.assertEqual(parsed_part_dimensions(target)[1], (6, 12))
        self.assertGreater(score(target), score("Brick 2 x 4"))
        self.assertLess(
            part_size_form_sort_key(target, design_id="30248", element_id="6259802", descending=True),
            part_size_form_sort_key("Plate 2 x 4", descending=True),
        )

    def test_unrelated_numbers_remain_unknown(self):
        for name in ("Model 2024", "Slope 45", "Design 6259802", "Part 90 degrees", "Unknown 15L"):
            self.assertIsNone(parsed_part_dimensions(name))
        self.assertIsNone(parsed_part_dimensions("Brick 0 x 2"))

    def test_global_order_unknown_and_stability(self):
        names = [
            "Wing 8 x 16", "Brick 1 x 1", "Panel 4 x 6", "Plate 1 x 2",
            "Base 6 x 12", "Technic Beam 15L", "Tile 2 x 2",
            "Axle Connector", "Animal Tail", "Slope 1 x 2",
        ]
        for descending in (False, True):
            ordered = sorted(names, key=lambda name: part_size_form_sort_key(name, descending=descending))
            self.assertEqual(
                ordered,
                sorted(reversed(names), key=lambda name: part_size_form_sort_key(name, descending=descending)),
            )
            self.assertEqual(ordered[-2:], ["Axle Connector", "Animal Tail"])
            known_scores = [score(name) for name in ordered[:-2]]
            self.assertEqual(known_scores, sorted(known_scores, reverse=descending))
        self.assertEqual(ordered[0], "Wing 8 x 16")

    def test_identity_and_color_do_not_affect_size(self):
        keys = [
            part_size_form_sort_key("Brick 2 x 4", design_id="3001", element_id=element, color=color)
            for element, color in (("a", "Black"), ("b", "White"), ("c", "Red"))
        ]
        self.assertEqual({key[1] for key in keys}, {score("Brick 2 x 4")})
        self.assertEqual(len(set(keys)), 3)


class PhysicalSizeViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "physical-size", "physical-size@example.test", "A-long-safe-password-123"
        )
        self.client.force_login(self.user)
        for element, name, color in (
            ("wing", "Wing 8 x 16", "Red"),
            ("brick", "Brick 1 x 1", "Red"),
            ("panel", "Panel 4 x 6", "Blue"),
            ("plate", "Plate 1 x 2", "Red"),
            ("unknown", "Animal Tail", "Red"),
        ):
            Part.objects.create(
                owner=self.user, element_id=element, part_number=element,
                name=name, color=color, quantity=2, owned_quantity=0,
                status=Part.Status.MISSING,
            )

    def test_both_views_filter_before_sort_and_do_not_mutate(self):
        for view in ("catalog:part_list", "catalog:missing_parts"):
            url = reverse(view)
            for filters in ({"q": "Plate"}, {"color": "Red"}, {"status": "missing"}, {}):
                if view == "catalog:part_list" and "color" in filters:
                    continue
                baseline = self.client.get(url, filters)
                asc = self.client.get(url, {**filters, "sort": "size_form"})
                desc = self.client.get(url, {**filters, "sort": "-size_form"})
                def names(response, is_part_list=view == "catalog:part_list"):
                    rows = response.context["page_obj"].object_list
                    return [row.name if is_part_list else row["name"] for row in rows]
                self.assertCountEqual(names(asc), names(baseline))
                self.assertCountEqual(names(desc), names(baseline))
                for response, descending in ((asc, False), (desc, True)):
                    ordered = names(response)
                    known = [score(name) for name in ordered if score(name) is not None]
                    self.assertEqual(known, sorted(known, reverse=descending))
                    self.assertEqual(
                        ordered[len(known):],
                        [name for name in ordered if score(name) is None],
                    )
                self.assertEqual(asc.context["sort"], "size_form")
                self.assertEqual(desc.context["sort"], "-size_form")
        self.assertEqual(
            list(Part.objects.filter(owner=self.user).values_list("quantity", "owned_quantity", "status")),
            [(2, 0, "missing")] * 5,
        )
