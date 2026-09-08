import csv
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.catalog.services import authoritative_lego_export_rows
from apps.organizer.models import MinifigurePart, SetMinifigure


class LegoExportAuthoritativeQuantityTests(TestCase):
    password = "A-very-long-password-123"  # noqa: S105 - ephemeral test credential

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "quantity-export",
            "quantity-export@example.test",
            self.password,
            email_verified=True,
        )
        self.client.force_login(self.user)

    def allocation(
        self,
        *,
        element_id="3711b",
        color="Black",
        required=26,
        authoritative_owned=25,
        part_owned=0,
        status=Part.Status.MISSING,
        set_number="1000-1",
    ):
        lego_set = LegoSet.objects.create(
            owner=self.user,
            set_number=set_number,
            name=f"Set {set_number}",
        )
        item = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number=element_id.removesuffix("b"),
            element_id=element_id,
            name="Technic Axle",
            color_id=0,
            color_name=color,
            required_quantity=required,
            owned_quantity=authoritative_owned,
        )
        part = Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id=element_id,
            part_number=item.part_number,
            name=item.name,
            color=color,
            quantity=required,
            owned_quantity=part_owned,
            status=status,
        )
        return lego_set, item, part

    def exported(self, colors=()):
        query = [("color", color) for color in colors]
        response = self.client.get(reverse("data_portability:export_csv"), query)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        return response, rows

    def test_3711b_regression_uses_set_inventory_owned_quantity(self):
        _lego_set, _item, part = self.allocation()

        _response, rows = self.exported()

        self.assertEqual(part.quantity, 26)
        self.assertEqual(part.owned_quantity, 0)
        self.assertEqual(rows, [["elementId", "quantity"], ["3711b", "1"]])

    def test_zero_owned_exports_required_and_fully_or_over_owned_is_omitted(self):
        self.allocation(element_id="zero", authoritative_owned=0, set_number="1001-1")
        self.allocation(element_id="full", authoritative_owned=26, set_number="1002-1")
        self.allocation(element_id="over", authoritative_owned=30, set_number="1003-1")

        _response, rows = self.exported()

        self.assertEqual(rows, [["elementId", "quantity"], ["zero", "26"]])

    def test_multiple_allocations_sum_shortages_without_cross_allocation_offset(self):
        self.allocation(
            required=10,
            authoritative_owned=8,
            set_number="2001-1",
        )
        self.allocation(
            required=16,
            authoritative_owned=17,
            set_number="2002-1",
        )

        _response, rows = self.exported()

        self.assertEqual(rows, [["elementId", "quantity"], ["3711b", "2"]])

    def test_duplicate_part_mirrors_do_not_duplicate_one_inventory_allocation(self):
        lego_set, _item, _part = self.allocation()
        Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id="3711b",
            name="Duplicate legacy mirror",
            color="Black",
            quantity=26,
            owned_quantity=0,
            status=Part.Status.MISSING,
        )

        _response, rows = self.exported()

        self.assertEqual(rows, [["elementId", "quantity"], ["3711b", "1"]])

    def test_exact_element_and_color_prevent_cross_color_subtraction(self):
        self.allocation(
            element_id="red-element",
            color="Red",
            required=6,
            authoritative_owned=5,
            set_number="3001-1",
        )
        self.allocation(
            element_id="blue-element",
            color="Blue",
            required=6,
            authoritative_owned=1,
            set_number="3002-1",
        )

        _response, rows = self.exported()

        self.assertEqual(
            rows,
            [
                ["elementId", "quantity"],
                ["blue-element", "5"],
                ["red-element", "1"],
            ],
        )

    def test_manual_part_without_inventory_keeps_part_quantity_semantics(self):
        Part.objects.create(
            owner=self.user,
            element_id="manual",
            name="Manual",
            color="Black",
            quantity=26,
            owned_quantity=0,
            status=Part.Status.MISSING,
        )

        _response, rows = self.exported()

        self.assertEqual(rows, [["elementId", "quantity"], ["manual", "26"]])

    def test_user_status_and_deleted_scoping_remain_strict(self):
        _set, _item, deleted = self.allocation(
            element_id="deleted", set_number="4001-1"
        )
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at", "updated_at"])
        self.allocation(
            element_id="ordered",
            status=Part.Status.ORDERED,
            set_number="4002-1",
        )
        other = get_user_model().objects.create_user(
            "quantity-other",
            "quantity-other@example.test",
            self.password,
            email_verified=True,
        )
        Part.objects.create(
            owner=other,
            element_id="foreign",
            name="Foreign",
            quantity=99,
            status=Part.Status.MISSING,
        )

        _response, rows = self.exported()

        self.assertEqual(rows, [["elementId", "quantity"]])

    def test_color_filters_use_authoritative_quantities_for_one_many_and_all(self):
        self.allocation(
            element_id="black", color="Black", authoritative_owned=25, set_number="5001-1"
        )
        self.allocation(
            element_id="white", color="White", authoritative_owned=24, set_number="5002-1"
        )
        self.allocation(
            element_id="red", color="Red", authoritative_owned=23, set_number="5003-1"
        )

        self.assertEqual(self.exported(("Black",))[1][1:], [["black", "1"]])
        self.assertEqual(
            self.exported(("Black", "White"))[1][1:],
            [["black", "1"], ["white", "2"]],
        )
        self.assertEqual(
            self.exported()[1][1:],
            [["black", "1"], ["red", "3"], ["white", "2"]],
        )

    def test_authoritative_change_is_reflected_immediately_without_part_sync(self):
        _lego_set, item, part = self.allocation()
        self.assertEqual(self.exported()[1][1:], [["3711b", "1"]])

        item.owned_quantity = 26
        item.save(update_fields=["owned_quantity", "updated_at"])

        self.assertEqual(self.exported()[1], [["elementId", "quantity"]])
        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 0)

    def test_set_ui_export_and_unavailable_analysis_share_authoritative_result(self):
        lego_set, item, _part = self.allocation()

        detail = self.client.get(reverse("catalog:set_detail", args=[lego_set.pk]))
        inventory_row = list(detail.context["page_obj"].object_list)[0]
        _response, export_rows = self.exported()

        self.assertEqual(item.missing_quantity, 1)
        self.assertEqual(inventory_row.missing_amount, 1)
        self.assertEqual(export_rows[1], ["3711b", "1"])

    def test_minifigure_inventory_is_authoritative_when_part_mirror_exists(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="6001-1", name="Minifigure set"
        )
        figure = SetMinifigure.objects.create(
            owner=self.user,
            lego_set=lego_set,
            figure_number="fig-1",
            name="Figure",
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="head",
            element_id="head-black",
            name="Head",
            color_name="Black",
            quantity=3,
            owned_quantity=2,
        )
        Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id="head-black",
            name="Legacy minifigure mirror",
            color="Black",
            quantity=3,
            owned_quantity=0,
            status=Part.Status.MISSING,
        )

        self.assertEqual(self.exported()[1][1:], [["head-black", "1"]])

    def test_export_calculation_is_one_query_for_small_and_large_datasets(self):
        self.allocation(set_number="7001-1")
        with self.assertNumQueries(1):
            small = authoritative_lego_export_rows(self.user)
        for index in range(20):
            self.allocation(
                element_id=f"large-{index}",
                required=4,
                authoritative_owned=1,
                set_number=f"71{index:02d}-1",
            )
        with self.assertNumQueries(1):
            large = authoritative_lego_export_rows(self.user)

        self.assertEqual(small, [{"element_id": "3711b", "export_quantity": 1}])
        self.assertEqual(len(large), 21)

    def test_export_does_not_mutate_business_models(self):
        self.allocation()
        before = {
            model._meta.label: list(model.objects.order_by("pk").values())
            for model in (LegoSet, SetInventoryItem, Part)
        }

        response, _rows = self.exported()

        self.assertEqual(response.status_code, 200)
        after = {
            model._meta.label: list(model.objects.order_by("pk").values())
            for model in (LegoSet, SetInventoryItem, Part)
        }
        self.assertEqual(after, before)
