import csv
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.organizer.models import MinifigurePart, SetMinifigure


class MissingCsvQuantityConsistencyTests(TestCase):
    password = "A-very-long-password-123"  # noqa: S105 - test credential

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "quantity-consistency",
            "quantity-consistency@example.test",
            self.password,
            email_verified=True,
        )
        self.other = get_user_model().objects.create_user(
            "quantity-consistency-other",
            "quantity-consistency-other@example.test",
            self.password,
            email_verified=True,
        )
        self.client.force_login(self.user)

    def allocation(
        self,
        *,
        set_number,
        required,
        owned,
        color="Dark Bluish Gray",
        identifier="30237a",
        inventory_element_id="",
        owner=None,
        deleted_at=None,
        spare=False,
        part_owned=0,
    ):
        owner = owner or self.user
        lego_set = LegoSet.objects.create(
            owner=owner,
            set_number=set_number,
            name="Police Headquarters" if set_number == "7744" else f"Set {set_number}",
            deleted_at=deleted_at,
        )
        item = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number=identifier,
            element_id=inventory_element_id,
            name="Brick Special 1 x 2 with Vertical Clip",
            color_id=72,
            color_name=color,
            required_quantity=required,
            owned_quantity=owned,
            is_spare=spare,
        )
        part = Part.objects.create(
            owner=owner,
            lego_set=lego_set,
            element_id=identifier,
            design_id=identifier,
            part_number=identifier,
            name=item.name,
            color=color,
            quantity=required,
            owned_quantity=part_owned,
            status=Part.Status.MISSING,
        )
        return lego_set, item, part

    def ui(self, **params):
        response = self.client.get(reverse("catalog:missing_parts"), params)
        return response, list(response.context["page_obj"].object_list)

    def csv_rows(self, **params):
        response = self.client.get(reverse("data_portability:export_csv"), params)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        return response, rows

    def test_30237a_7744_card_one_and_global_csv_four_are_consistent(self):
        _set_7744, item_7744, part_7744 = self.allocation(set_number="7744", required=7, owned=6)
        self.allocation(set_number="7207", required=2, owned=0, color="White")
        self.allocation(set_number="7208", required=11, owned=10, color="Red")
        self.allocation(set_number="9442", required=1, owned=1)

        response, groups = self.ui(q="30237a")
        _csv_response, rows = self.csv_rows()

        gray = next(group for group in groups if group["color"] == "Dark Bluish Gray")
        self.assertEqual((gray["required"], gray["owned"], gray["missing"]), (7, 6, 1))
        self.assertEqual(gray["allocations"], [part_7744])
        self.assertEqual(item_7744.missing_quantity, 1)
        self.assertEqual(response.context["missing_total"], 4)
        self.assertEqual(sum(group["missing"] for group in groups), 4)
        self.assertEqual(rows, [["elementId", "quantity"], ["30237a", "4"]])
        self.assertEqual(part_7744.owned_quantity, 0)

        _filtered_response, filtered = self.csv_rows(color="Dark Bluish Gray")
        self.assertEqual(filtered, [["elementId", "quantity"], ["30237a", "1"]])

    def test_single_and_multiple_set_allocations_share_the_same_subtotal(self):
        self.allocation(set_number="A", required=7, owned=6, identifier="single")
        _response, groups = self.ui(q="single")
        _csv_response, rows = self.csv_rows()
        self.assertEqual(
            (groups[0]["required"], groups[0]["owned"], groups[0]["missing"]), (7, 6, 1)
        )
        self.assertIn(["single", "1"], rows)

        self.allocation(set_number="B1", required=7, owned=6, identifier="multi")
        self.allocation(set_number="B2", required=5, owned=2, identifier="multi")
        _response, groups = self.ui(q="multi")
        _csv_response, rows = self.csv_rows()
        self.assertEqual(
            (groups[0]["required"], groups[0]["owned"], groups[0]["missing"]), (12, 8, 4)
        )
        self.assertIn(["multi", "4"], rows)

    def test_complete_over_owned_spare_deleted_and_foreign_do_not_add_shortages(self):
        self.allocation(set_number="complete", required=7, owned=7, identifier="complete")
        self.allocation(set_number="over", required=7, owned=9, identifier="over")
        lego_set, _item, _part = self.allocation(
            set_number="spare", required=7, owned=0, identifier="spare", spare=True
        )
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="spare",
            name="Normal",
            color_name="Dark Bluish Gray",
            required_quantity=1,
            owned_quantity=1,
        )
        self.allocation(
            set_number="deleted",
            required=9,
            owned=0,
            identifier="deleted",
            deleted_at=timezone.now(),
        )
        self.allocation(
            set_number="foreign",
            required=9,
            owned=0,
            identifier="foreign",
            owner=self.other,
        )

        _response, groups = self.ui()
        _csv_response, rows = self.csv_rows()

        self.assertEqual(groups, [])
        self.assertEqual(rows, [["elementId", "quantity"]])

    def test_exact_element_precedes_blank_fallback_without_double_counting(self):
        lego_set, item, part = self.allocation(
            set_number="exact",
            required=7,
            owned=6,
            identifier="exact-element",
            inventory_element_id="exact-element",
        )
        item.part_number = "shared-design"
        item.save(update_fields=["part_number", "updated_at"])
        part.design_id = "shared-design"
        part.part_number = "shared-design"
        part.save(update_fields=["design_id", "part_number", "updated_at"])
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="shared-design",
            element_id="",
            name="Fallback",
            color_name=part.color,
            required_quantity=8,
            owned_quantity=0,
        )

        _response, groups = self.ui(q="exact-element")
        _csv_response, rows = self.csv_rows()

        self.assertEqual(groups[0]["missing"], 1)
        self.assertEqual(rows, [["elementId", "quantity"], ["exact-element", "1"]])

    def test_duplicate_part_mirror_is_not_counted_twice_in_ui_or_csv(self):
        lego_set, _item, part = self.allocation(
            set_number="duplicate", required=7, owned=6, identifier="duplicate"
        )
        Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id=part.element_id,
            design_id=part.design_id,
            part_number=part.part_number,
            name="Duplicate legacy mirror",
            color=part.color,
            quantity=99,
            owned_quantity=0,
            status=Part.Status.MISSING,
        )

        _response, groups = self.ui(q="duplicate")
        _csv_response, rows = self.csv_rows()

        self.assertEqual(len(groups), 1)
        self.assertEqual(
            (groups[0]["required"], groups[0]["owned"], groups[0]["missing"]), (7, 6, 1)
        )
        self.assertEqual(len(groups[0]["allocations"]), 1)
        self.assertEqual(rows, [["elementId", "quantity"], ["duplicate", "1"]])

    def test_minifigure_part_and_set_inventory_totals_remain_additive(self):
        self.allocation(set_number="normal-mini", required=2, owned=1, identifier="normal")
        lego_set = LegoSet.objects.create(owner=self.user, set_number="mini", name="Minifigure set")
        figure = SetMinifigure.objects.create(
            owner=self.user,
            lego_set=lego_set,
            figure_number="fig-1",
            name="Officer",
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="head",
            element_id="mini-head",
            name="Head",
            color_name="Yellow",
            quantity=3,
            owned_quantity=1,
        )
        Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            part_number="head",
            element_id="mini-head",
            name="Head mirror",
            color="Yellow",
            quantity=3,
            owned_quantity=0,
            status=Part.Status.MISSING,
        )

        response, groups = self.ui()
        _csv_response, rows = self.csv_rows()

        self.assertEqual(response.context["missing_total"], 3)
        self.assertEqual(sum(group["missing"] for group in groups), 3)
        self.assertIn(["normal", "1"], rows)
        self.assertIn(["mini-head", "2"], rows)
