import re

from django.contrib.auth import get_user_model
from django.db.backends.mysql.base import DatabaseWrapper as MySQLDatabaseWrapper
from django.test import TestCase
from django.urls import reverse

from .models import LegoSet, Part, SetInventoryItem
from .services import missing_quantity_expression, with_authoritative_missing_quantity


class UnsignedMissingQuantityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "unsigned-quantity", "unsigned-quantity@example.test", "Strong-password-123"
        )
        self.client.force_login(self.user)
        self.lego_set = LegoSet.objects.create(
            owner=self.user, set_number="unsigned-quantity-1", name="Unsigned quantity"
        )

    def inventory(self, number, required, owned, *, spare=False):
        return SetInventoryItem.objects.create(
            lego_set=self.lego_set,
            part_number=number,
            element_id=number,
            name=number,
            color_name="Black",
            required_quantity=required,
            owned_quantity=owned,
            is_spare=spare,
        )

    def test_missing_expression_handles_positive_equal_and_overowned_quantities(self):
        expected = ((3, 1, 2), (3, 3, 0), (3, 5, 0), (1, 2, 0), (1, 10000, 0))
        items = [
            self.inventory(f"case-{index}", required, owned)
            for index, (required, owned, _missing) in enumerate(expected)
        ]

        actual = dict(
            SetInventoryItem.objects.filter(pk__in=[item.pk for item in items])
            .annotate(missing=missing_quantity_expression("required_quantity"))
            .values_list("part_number", "missing")
        )

        for index, (_required, _owned, missing) in enumerate(expected):
            self.assertEqual(actual[f"case-{index}"], missing)
            self.assertEqual(items[index].missing_quantity, missing)

    def test_generated_mysql_sql_guards_subtraction_with_case_and_signed_output(self):
        expression = missing_quantity_expression("required_quantity")
        self.assertEqual(expression.output_field.get_internal_type(), "IntegerField")
        mysql_connection = MySQLDatabaseWrapper(
            {
                "NAME": "compile_only",
                "USER": "",
                "PASSWORD": "",
                "HOST": "localhost",
                "PORT": "3306",
                "OPTIONS": {},
            },
            alias="mysql_compile_only",
        )
        query = SetInventoryItem.objects.annotate(missing=expression).values("missing").query
        sql, _params = query.get_compiler(connection=mysql_connection).as_sql()
        normalized = re.sub(r"\s+", " ", sql).upper()
        self.assertRegex(
            normalized,
            r"CASE WHEN .*OWNED_QUANTITY.* >= .*REQUIRED_QUANTITY.* THEN .* ELSE .*REQUIRED_QUANTITY.* - .*OWNED_QUANTITY.* END",
        )
        self.assertNotIn("GREATEST(", normalized)

    def test_set_detail_and_inventory_filters_process_overowned_normal_and_spare_rows(self):
        normal = self.inventory("normal-over", 1, 2)
        spare = self.inventory("spare-over", 1, 10000, spare=True)
        shortage = self.inventory("normal-short", 3, 1)

        response = self.client.get(reverse("catalog:set_detail", args=[self.lego_set.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["inventory_stats"]["missing"], 2)
        self.assertEqual(response.context["inventory_stats"]["owned"], 10003)
        self.assertEqual(response.context["inventory_stats"]["required"], 5)
        self.assertEqual(
            {item.pk: item.missing_amount for item in response.context["page_obj"].object_list},
            {normal.pk: 0, spare.pk: 0, shortage.pk: 2},
        )

        for kind, item in (("normal", normal), ("spare", spare)):
            complete = self.client.get(
                reverse("catalog:set_detail", args=[self.lego_set.pk]),
                {"art": kind, "stock": "complete"},
            )
            self.assertEqual(complete.status_code, 200)
            self.assertEqual([row.pk for row in complete.context["page_obj"].object_list], [item.pk])
        for stock, expected_ids in (("partial", [shortage.pk]), ("missing", [])):
            filtered = self.client.get(
                reverse("catalog:set_detail", args=[self.lego_set.pk]), {"stock": stock}
            )
            self.assertEqual(filtered.status_code, 200)
            self.assertEqual(
                [row.pk for row in filtered.context["page_obj"].object_list], expected_ids
            )

        normal.refresh_from_db()
        spare.refresh_from_db()
        self.assertEqual((normal.owned_quantity, spare.owned_quantity), (2, 10000))

    def test_overowned_inventory_completeness_and_missing_parts_remain_valid(self):
        normal = self.inventory("normal-over", 1, 2)
        spare = self.inventory("spare-over", 1, 10000, spare=True)
        normal_mirror = Part.objects.create(
            owner=self.user, lego_set=self.lego_set, element_id=normal.element_id,
            part_number=normal.part_number, name=normal.name, color=normal.color_name,
            quantity=1, owned_quantity=0,
        )
        spare_mirror = Part.objects.create(
            owner=self.user, lego_set=self.lego_set, element_id=spare.element_id,
            part_number=spare.part_number, name=spare.name, color=spare.color_name,
            quantity=1, owned_quantity=0,
        )

        annotated = with_authoritative_missing_quantity(
            Part.objects.filter(pk__in=[normal_mirror.pk, spare_mirror.pk]),
            include_spares=True,
        )
        self.assertEqual(
            dict(annotated.values_list("pk", "authoritative_missing_quantity")),
            {normal_mirror.pk: 0, spare_mirror.pk: 0},
        )
        response = self.client.get(reverse("catalog:missing_parts"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "normal-over")
        self.assertNotContains(response, "spare-over")
        self.assertContains(
            self.client.get(reverse("catalog:set_list"), {"completeness": "complete"}),
            "Unsigned quantity",
        )
        self.assertEqual(
            list(SetInventoryItem.objects.order_by("pk").values_list("owned_quantity", flat=True)),
            [2, 10000],
        )

    def test_mark_all_spares_present_is_idempotent_and_never_reduces_overstock(self):
        missing = self.inventory("missing-spare", 3, 0, spare=True)
        partial = self.inventory("partial-spare", 4, 2, spare=True)
        complete = self.inventory("complete-spare", 2, 2, spare=True)
        overowned = self.inventory("over-spare", 1, 10000, spare=True)
        normal = self.inventory("normal", 5, 1)
        url = reverse("catalog:mark_all_spares_present")

        first_response = self.client.post(url, follow=True)
        self.assertContains(first_response, "2 Ersatzteil-Einträge wurden als vollständig vorhanden markiert.")
        second_response = self.client.post(url, follow=True)
        self.assertContains(second_response, "Alle Ersatzteile sind bereits vollständig vorhanden")

        for item in (missing, partial, complete, overowned, normal):
            item.refresh_from_db()
        self.assertEqual(missing.owned_quantity, 3)
        self.assertEqual(partial.owned_quantity, 4)
        self.assertEqual(complete.owned_quantity, 2)
        self.assertEqual(overowned.owned_quantity, 10000)
        self.assertEqual(normal.owned_quantity, 1)
