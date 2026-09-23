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

    def test_received_filter_does_not_show_a_missing_group(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="received-filter", name="Received filter"
        )
        SetInventoryItem.objects.create(
            lego_set=lego_set, part_number="2436", element_id="4282737",
            name="Bracket", color_name="White", required_quantity=1,
            owned_quantity=0,
        )
        self.make_part(
            "received-filter", lego_set=lego_set, element_id="4282737",
            part_number="2436", status=Part.Status.RECEIVED,
        )
        response = self.client.get(self.url, {"status": Part.Status.RECEIVED})
        self.assertEqual(list(response.context["page_obj"].object_list), [])
        self.assertNotContains(response, 'data-group-status>Fehlt</span>')

    def test_each_visible_workflow_filter_matches_badge_after_reload(self):
        for value in Part.Status.values:
            with self.subTest(status=value):
                self.make_part(value, status=value)
        for value in [*Part.Status.values, "partial"]:
            response = self.client.get(self.url, {"status": value})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, f'<option value="{value}" selected')
            for group in response.context["page_obj"].object_list:
                self.assertEqual(group["status"], value)
                self.assertContains(
                    response,
                    f'class="badge {value}" data-group-status>{group["status_label"]}</span>',
                )

    def test_ordered_group_and_mixed_group_use_card_status_for_filter(self):
        ordered = self.make_part("ordered-one", element_id="ordered", status=Part.Status.ORDERED)
        self.make_part("ordered-two", element_id="ordered", status=Part.Status.ORDERED)
        self.make_part("mixed-one", element_id="mixed", status=Part.Status.ORDERED)
        self.make_part("mixed-two", element_id="mixed", status=Part.Status.MISSING)
        ordered_groups = self.groups(status=Part.Status.ORDERED)
        missing_groups = self.groups(status=Part.Status.MISSING)
        self.assertEqual([group["element_id"] for group in ordered_groups], ["ordered"])
        self.assertEqual(ordered_groups[0]["status_label"], "Bestellt")
        self.assertEqual(len(ordered_groups[0]["allocations"]), 2)
        self.assertEqual([group["element_id"] for group in missing_groups], ["mixed"])
        self.assertEqual(missing_groups[0]["status_label"], "Fehlt")
        ordered.refresh_from_db()
        self.assertEqual(ordered.status, Part.Status.ORDERED)

    def test_status_change_then_fresh_filter_reload(self):
        part = self.make_part("change")
        url = reverse("catalog:missing_part_status", args=[part.pk])
        changed = self.client.post(
            url, {"status": Part.Status.ORDERED},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(changed.status_code, 200)
        part.refresh_from_db()
        self.assertEqual(part.status, Part.Status.ORDERED)
        self.assertEqual(self.groups(status=Part.Status.ORDERED)[0]["status_label"], "Bestellt")
        self.assertEqual(self.groups(status=Part.Status.MISSING), [])
        changed = self.client.post(
            url, {"status": Part.Status.MISSING},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(changed.status_code, 200)
        part.refresh_from_db()
        self.assertEqual(part.status, Part.Status.MISSING)
        self.assertEqual(self.groups(status=Part.Status.ORDERED), [])
        self.assertEqual(self.groups(status=Part.Status.MISSING)[0]["status_label"], "Fehlt")

    def test_minifigure_part_status_filter_uses_quantity_badge(self):
        figure = SetMinifigure.objects.create(
            owner=self.user, figure_number="loose", name="Loose"
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="head", name="Head",
            color_name="Black", quantity=2, owned_quantity=1,
        )
        self.assertEqual(self.groups(kind="minifigure", status="partial")[0]["status_label"], "Teilweise")
        self.assertEqual(self.groups(kind="minifigure", status=Part.Status.RECEIVED), [])

    def test_status_combines_with_search_color_set_and_size_sort(self):
        selected = LegoSet.objects.create(owner=self.user, set_number="selected", name="Selected")
        other = LegoSet.objects.create(owner=self.user, set_number="other", name="Other")
        self.make_part(
            "target", lego_set=selected, element_id="target",
            name="Brick 2 x 4", color="Black", status=Part.Status.ORDERED,
        )
        self.make_part(
            "wrong-color", lego_set=selected, element_id="wrong-color",
            name="Brick 2 x 4", color="Red", status=Part.Status.ORDERED,
        )
        self.make_part(
            "wrong-set", lego_set=other, element_id="wrong-set",
            name="Brick 2 x 4", color="Black", status=Part.Status.ORDERED,
        )
        self.make_part(
            "wrong-status", lego_set=selected, element_id="wrong-status",
            name="Brick 2 x 4", color="Black", status=Part.Status.MISSING,
        )
        params = {
            "status": Part.Status.ORDERED, "q": "Brick",
            "color": "Black", "set": str(selected.pk), "sort": "size_form",
        }
        response = self.client.get(self.url, params)
        self.assertEqual(
            [group["element_id"] for group in response.context["page_obj"].object_list],
            ["target"],
        )
        self.assertContains(response, '<option value="ordered" selected')
        self.assertContains(response, '<option value="size_form" selected')
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_status_filter_is_owner_and_deleted_set_scoped(self):
        active = LegoSet.objects.create(owner=self.user, set_number="active", name="Active")
        deleted = LegoSet.objects.create(
            owner=self.user, set_number="deleted", name="Deleted"
        )
        from django.utils import timezone
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at"])
        self.make_part(
            "active", lego_set=active, element_id="shared",
            color="Black", status=Part.Status.ORDERED,
        )
        self.make_part(
            "deleted", lego_set=deleted, element_id="shared",
            color="Black", status=Part.Status.MISSING,
        )
        self.make_part(
            "foreign", owner=self.other, element_id="shared",
            color="Black", status=Part.Status.MISSING,
        )
        groups = self.groups(status=Part.Status.ORDERED)
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["status"], groups[0]["missing"]), ("ordered", 1))
        self.assertEqual(self.groups(status=Part.Status.MISSING), [])

    def test_status_pagination_keeps_filter_without_duplicate_cards(self):
        for index in range(32):
            self.make_part(
                f"page-{index:02d}", element_id=f"page-{index:02d}",
                name=f"Page {index:02d}", status=Part.Status.ORDERED,
            )
        self.make_part("outside", status=Part.Status.MISSING)
        first = self.client.get(self.url, {"status": Part.Status.ORDERED})
        second = self.client.get(
            self.url, {"status": Part.Status.ORDERED, "page": "2"}
        )
        first_groups = list(first.context["page_obj"].object_list)
        second_groups = list(second.context["page_obj"].object_list)
        self.assertEqual((len(first_groups), len(second_groups)), (30, 2))
        self.assertEqual(
            len({group["element_id"] for group in first_groups + second_groups}), 32
        )
        self.assertContains(first, "status=ordered")
        self.assertTrue(all(group["status"] == "ordered" for group in first_groups + second_groups))

    def test_group_status_does_not_query_per_card(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.make_part("query-0", status=Part.Status.ORDERED)
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url, {"status": Part.Status.ORDERED})
        for index in range(1, 15):
            self.make_part(f"query-{index}", status=Part.Status.ORDERED)
        with CaptureQueriesContext(connection) as larger:
            response = self.client.get(self.url, {"status": Part.Status.ORDERED})
        self.assertEqual(response.context["page_obj"].paginator.count, 15)
        self.assertLessEqual(len(larger), len(small) + 1)

    def test_bulk_status_reload_filters_complete_group_atomically(self):
        first = self.make_part("bulk-first", element_id="bulk-shared")
        second = self.make_part("bulk-second", element_id="bulk-shared")
        response = self.client.post(
            reverse("catalog:missing_parts_bulk"),
            {"item": [str(first.pk), str(second.pk)], "action": Part.Status.ORDERED},
        )
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.status, second.status), (Part.Status.ORDERED, Part.Status.ORDERED))
        groups = self.groups(status=Part.Status.ORDERED)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["allocations"]), 2)
        self.assertEqual((groups[0]["status_label"], groups[0]["missing"]), ("Bestellt", 2))

    def test_received_status_on_complete_part_is_not_an_open_missing_card(self):
        part = self.make_part(
            "complete-received", quantity=1, owned_quantity=1,
            status=Part.Status.MISSING,
        )
        response = self.client.post(
            reverse("catalog:missing_part_status", args=[part.pk]),
            {"status": Part.Status.RECEIVED},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        part.refresh_from_db()
        self.assertEqual(part.status, Part.Status.RECEIVED)
        self.assertEqual(self.groups(status=Part.Status.RECEIVED), [])

    def test_same_minifigure_in_set_and_standalone_keeps_status_scoped(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="figure-set", name="Figure set"
        )
        assigned = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set,
            figure_number="fig-shared", name="Shared Figure",
        )
        standalone = SetMinifigure.objects.create(
            owner=self.user, lego_set=None,
            figure_number="fig-shared", name="Shared Figure",
        )
        for figure, owned in ((assigned, 0), (standalone, 1)):
            MinifigurePart.objects.create(
                minifigure=figure, part_number="head-shared",
                element_id="head-shared", name="Shared Head",
                color_name="Black", quantity=2, owned_quantity=owned,
            )
        missing = self.groups(kind="minifigure", status=Part.Status.MISSING)
        partial = self.groups(kind="minifigure", status="partial")
        self.assertEqual(len(missing), 1)
        self.assertEqual(len(partial), 1)
        self.assertEqual(missing[0]["allocations"][0].minifigure_id, assigned.pk)
        self.assertEqual(partial[0]["allocations"][0].minifigure_id, standalone.pk)
        self.assertEqual((missing[0]["missing"], partial[0]["missing"]), (2, 1))

    def test_set_inventory_item_workflow_matrix_uses_authoritative_shortage(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="status-matrix", name="Status matrix"
        )
        expected = {
            Part.Status.MISSING: "missing",
            Part.Status.FOUND: "missing",
            Part.Status.ORDERED: "ordered",
            Part.Status.SHIPPED: "shipped",
            Part.Status.RECEIVED: "missing",
            Part.Status.INSTALLED: "missing",
        }
        for status in Part.Status.values:
            identity = f"matrix-{status}"
            SetInventoryItem.objects.create(
                lego_set=lego_set, part_number=identity, element_id=identity,
                name=identity, color_name="Black",
                required_quantity=2, owned_quantity=0,
            )
            self.make_part(
                identity, lego_set=lego_set, element_id=identity,
                part_number=identity, color="Black", quantity=2,
                owned_quantity=2, status=status,
            )
        groups = {group["element_id"]: group for group in self.groups()}
        for status, result in expected.items():
            with self.subTest(status=status):
                group = groups[f"matrix-{status}"]
                self.assertEqual((group["required"], group["owned"], group["missing"]), (2, 0, 2))
                self.assertEqual(group["status"], result)
                self.assertIn(
                    group["element_id"],
                    [candidate["element_id"] for candidate in self.groups(status=result)],
                )

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
