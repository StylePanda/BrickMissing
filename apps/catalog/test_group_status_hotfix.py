from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.organizer.models import MinifigurePart, SetMinifigure

from .models import LegoSet, Part, SetInventoryItem
from .part_status import group_quantity_status


class GroupQuantityStatusTests(SimpleTestCase):
    def test_required_owned_matrix(self):
        cases = (
            (1, 0, None, ("missing", "Fehlt")),
            (2, 0, None, ("missing", "Fehlt")),
            (2, 1, None, ("partial", "Teilweise")),
            (3, 2, None, ("partial", "Teilweise")),
            (1, 1, None, ("complete", "Erhalten")),
            (2, 2, None, ("complete", "Erhalten")),
            (2, 3, None, ("complete", "Erhalten")),
            # An over-owned allocation must not cancel another allocation's shortage.
            (2, 2, 1, ("partial", "Teilweise")),
        )
        for required, owned, missing, expected in cases:
            with self.subTest(required=required, owned=owned, missing=missing):
                self.assertEqual(
                    group_quantity_status(required, owned, missing), expected
                )


class MissingPartGroupStatusRegressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "group-status", "group-status@example.test", "A-long-password-123"
        )
        self.other = get_user_model().objects.create_user(
            "group-status-other",
            "group-status-other@example.test",
            "A-long-password-456",
        )
        self.client.force_login(self.user)
        self.url = reverse("catalog:missing_parts")

    def make_part(self, suffix, **values):
        defaults = {
            "owner": self.user,
            "element_id": f"element-{suffix}",
            "part_number": f"part-{suffix}",
            "name": f"Part {suffix}",
            "color": "White",
            "quantity": 1,
            "owned_quantity": 0,
            "status": Part.Status.MISSING,
        }
        defaults.update(values)
        return Part.objects.create(**defaults)

    def groups(self, **params):
        return list(self.client.get(self.url, params).context["page_obj"].object_list)

    def test_visible_status_is_missing_for_zero_owned_and_partial_for_some_owned(self):
        zero_one = self.make_part("zero-one")
        zero_two = self.make_part("zero-two", quantity=2)
        partial = self.make_part("partial", quantity=2, owned_quantity=1)

        groups = {group["element_id"]: group for group in self.groups()}

        self.assertEqual(groups[zero_one.element_id]["status_label"], "Fehlt")
        self.assertEqual(groups[zero_two.element_id]["status_label"], "Fehlt")
        self.assertEqual(groups[partial.element_id]["status_label"], "Teilweise")

    def test_production_shape_uses_authoritative_allocation_not_stale_received_status(self):
        lego_set = LegoSet.objects.create(
            owner=self.user,
            set_number="7245",
            name="Prisoner Transport, Black Logo",
        )
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="2436",
            element_id="4282737",
            name="Bracket 1 x 2 - 1 x 4 [Square Corners]",
            color_name="White",
            required_quantity=1,
            owned_quantity=0,
        )
        part = self.make_part(
            "production",
            lego_set=lego_set,
            element_id="4282737",
            part_number="2436",
            name="Bracket 1 x 2 - 1 x 4 [Square Corners]",
            status=Part.Status.RECEIVED,
        )

        response = self.client.get(self.url)
        group = response.context["page_obj"].object_list[0]

        self.assertEqual(
            (group["required"], group["owned"], group["missing"]), (1, 0, 1)
        )
        self.assertEqual((group["status"], group["status_label"]), ("missing", "Fehlt"))
        self.assertEqual(group["allocations"][0], part)
        self.assertContains(response, 'option value="missing" selected')
        self.assertNotContains(response, 'option value="received" selected')

    def test_quantity_reduction_clears_stale_possession_workflow_status(self):
        part = self.make_part(
            "reduce",
            quantity=2,
            owned_quantity=2,
            status=Part.Status.RECEIVED,
        )

        response = self.client.post(
            reverse("catalog:missing_part_quantity", args=[part.pk]),
            {"owned_quantity": 0},
        )
        part.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual((part.owned_quantity, part.status), (0, Part.Status.MISSING))

    def test_inline_and_bulk_status_updates_reject_possession_with_shortage(self):
        first = self.make_part("inline", quantity=2, owned_quantity=1)
        second = self.make_part("bulk")

        inline = self.client.post(
            reverse("catalog:missing_part_status", args=[first.pk]),
            {"status": Part.Status.RECEIVED},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        bulk = self.client.post(
            reverse("catalog:missing_parts_bulk"),
            {"item": [first.pk, second.pk], "action": Part.Status.INSTALLED},
        )
        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual((inline.status_code, bulk.status_code), (400, 400))
        self.assertEqual(first.status, Part.Status.MISSING)
        self.assertEqual(second.status, Part.Status.MISSING)

    def test_grouping_keeps_color_owner_and_identity_boundaries(self):
        own_white = self.make_part("shared", element_id="shared", color="White")
        own_black = self.make_part("black", element_id="shared", color="Black")
        self.make_part(
            "foreign",
            owner=self.other,
            element_id="shared",
            color="White",
            quantity=9,
            owned_quantity=8,
        )

        groups = self.groups()

        self.assertEqual(len(groups), 2)
        self.assertEqual(
            {group["color"] for group in groups}, {own_white.color, own_black.color}
        )
        self.assertTrue(all(group["status_label"] == "Fehlt" for group in groups))

    def test_multiple_set_allocations_aggregate_their_open_quantities(self):
        first_set = LegoSet.objects.create(owner=self.user, set_number="one", name="One")
        second_set = LegoSet.objects.create(owner=self.user, set_number="two", name="Two")
        self.make_part(
            "first", lego_set=first_set, element_id="aggregate", quantity=2, owned_quantity=1
        )
        missing = self.make_part(
            "second", lego_set=second_set, element_id="aggregate", quantity=1, owned_quantity=0
        )

        group = self.groups()[0]

        self.assertIn(missing, group["allocations"])
        self.assertEqual((group["required"], group["owned"], group["missing"]), (3, 1, 2))
        self.assertEqual(group["status_label"], "Teilweise")

    def test_spare_allocation_does_not_override_normal_shortage(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="spare", name="Spare")
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="normal",
            element_id="normal-element",
            name="Normal",
            color_name="White",
            required_quantity=2,
            owned_quantity=0,
        )
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="spare",
            element_id="normal-element",
            name="Spare",
            color_name="White",
            required_quantity=1,
            owned_quantity=1,
            is_spare=True,
        )
        self.make_part(
            "mirror",
            lego_set=lego_set,
            element_id="normal-element",
            part_number="normal",
            quantity=2,
        )

        group = self.groups()[0]

        self.assertEqual((group["required"], group["owned"], group["missing"]), (2, 0, 2))
        self.assertEqual(group["status_label"], "Fehlt")

    def test_minifigure_part_uses_the_same_quantity_status_semantics(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="mini", name="Mini")
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig", name="Figure"
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="head",
            name="Head",
            color_name="White",
            quantity=2,
            owned_quantity=1,
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="spare-head",
            name="Spare head",
            color_name="Black",
            quantity=5,
            owned_quantity=0,
            is_spare=True,
        )

        group = self.groups(kind="minifigure")[0]

        self.assertTrue(group["is_minifigure"])
        self.assertEqual((group["missing"], group["status_label"]), (1, "Teilweise"))
        self.assertEqual(len(self.groups(kind="minifigure")), 1)
