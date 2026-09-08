import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.catalog.services import (
    authoritative_lego_export_rows,
    owned_quantity_consistency_rows,
    set_completeness,
)
from apps.integrations.rebrickable_sync import synchronize_set
from apps.organizer.models import MinifigurePart, SetMinifigure


class OwnedQuantitySynchronizationTests(TestCase):
    password = "A-very-long-password-123"  # noqa: S105

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "quantity-sync",
            "quantity-sync@example.test",
            self.password,
            email_verified=True,
        )
        self.client.force_login(self.user)

    def allocation(
        self,
        *,
        element_id="4117070",
        inventory_element_id="4117070",
        part_number="3062b",
        color="Tan",
        required=42,
        inventory_owned=3,
        part_owned=3,
        set_number="4645",
    ):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number=set_number, name="Harbor"
        )
        item = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number=part_number,
            element_id=inventory_element_id,
            name="Brick Round 1 x 1",
            color_id=19,
            color_name=color,
            required_quantity=required,
            owned_quantity=inventory_owned,
        )
        part = Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id=element_id,
            design_id=part_number,
            part_number=part_number,
            name=item.name,
            color=color,
            quantity=required,
            owned_quantity=part_owned,
            status=Part.Status.MISSING,
        )
        return lego_set, item, part

    def unavailable_upload(self, element_id="4117070", quantity=42):
        return SimpleUploadedFile(
            "unavailable.json",
            json.dumps(
                [{"elementId": element_id, "quantity": quantity, "error": "Unavailable"}]
            ).encode(),
            content_type="application/json",
        )

    def test_4117070_fehlteile_update_is_atomic_and_consistent_after_reload(self):
        lego_set, item, part = self.allocation()

        response = self.client.post(
            reverse("catalog:missing_part_quantity", args=[part.pk]),
            {"owned_quantity": 36},
        )

        self.assertRedirects(response, reverse("catalog:missing_parts"))
        part = Part.objects.get(pk=part.pk)
        item = SetInventoryItem.objects.get(pk=item.pk)
        self.assertEqual((part.owned_quantity, item.owned_quantity), (36, 36))
        self.assertEqual((part.quantity, item.required_quantity), (42, 42))

        missing = self.client.get(reverse("catalog:missing_parts"))
        group = missing.context["page_obj"].object_list[0]
        self.assertEqual((group["required"], group["owned"], group["missing"]), (42, 36, 6))
        self.assertContains(missing, "<span data-allocation-owned>36</span>", html=True)
        self.assertContains(missing, "<span data-allocation-missing>6</span>", html=True)
        detail = self.client.get(reverse("catalog:set_detail", args=[lego_set.pk]))
        detail_item = list(detail.context["page_obj"])[0]
        self.assertEqual(detail_item.missing_amount, 6)
        self.assertEqual(set_completeness(lego_set)["missing"], 6)
        self.assertEqual(
            authoritative_lego_export_rows(self.user),
            [{"element_id": "4117070", "export_quantity": 6}],
        )
        unavailable = self.client.post(
            reverse("data_portability:lego_unavailable"),
            {"file": self.unavailable_upload(quantity=39)},
        )
        match = unavailable.context["results"][0]["matches"][0]
        self.assertEqual(match.authoritative_missing_quantity, 6)
        self.assertContains(unavailable, "<dt>LEGO-Menge</dt><dd>39</dd>", html=True)
        self.assertContains(unavailable, "<dt>Aktuell fehlend</dt><dd>6</dd>", html=True)

    def test_existing_contradiction_is_displayed_from_authoritative_inventory(self):
        _lego_set, _item, part = self.allocation(part_owned=36, inventory_owned=3)

        missing = self.client.get(reverse("catalog:missing_parts"))
        group = missing.context["page_obj"].object_list[0]
        part_list = self.client.get(reverse("catalog:part_list"))
        editor = self.client.get(reverse("catalog:part_edit", args=[part.pk]))

        self.assertEqual((group["owned"], group["missing"]), (3, 39))
        self.assertContains(missing, 'name="owned_quantity" value="3"')
        self.assertContains(part_list, "3/42")
        self.assertEqual(editor.context["form"].initial["owned_quantity"], 3)

    def test_set_detail_update_synchronizes_part_mirror(self):
        lego_set, item, part = self.allocation(part_owned=1)

        response = self.client.post(
            reverse("catalog:set_inventory_quantity", args=[lego_set.pk, item.pk]),
            {"owned_quantity": 36},
        )

        self.assertEqual(response.status_code, 302)
        part.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((part.owned_quantity, item.owned_quantity), (36, 36))

    def test_set_bulk_quantity_update_synchronizes_part_mirror(self):
        lego_set, item, part = self.allocation(part_owned=1)

        self.client.post(
            reverse("catalog:set_inventory_action", args=[lego_set.pk, "complete"])
        )

        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, part.owned_quantity), (42, 42))

    def test_full_part_editor_writes_owned_to_authoritative_allocation(self):
        lego_set, item, part = self.allocation(part_owned=3)
        response = self.client.post(
            reverse("catalog:part_edit", args=[part.pk]),
            {
                "lego_set": str(lego_set.pk),
                "element_id": "4117070",
                "design_id": "3062b",
                "part_number": "3062b",
                "name": part.name,
                "color": "Tan",
                "quantity": 42,
                "owned_quantity": 36,
                "unassigned_found_quantity": 0,
                "status": Part.Status.MISSING,
                "priority": "normal",
                "unit_price": 0,
                "supplier": "",
                "notes": "",
                "image_url": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, part.owned_quantity), (36, 36))

    def test_full_set_inventory_editor_synchronizes_part_mirror(self):
        lego_set, item, part = self.allocation(part_owned=3)
        response = self.client.post(
            reverse("catalog:set_inventory_edit", args=[lego_set.pk, item.pk]),
            {
                "part_number": "3062b",
                "element_id": "4117070",
                "name": item.name,
                "color_id": 19,
                "color_name": "Tan",
                "required_quantity": 42,
                "owned_quantity": 36,
                "is_spare": "",
                "image_url": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, part.owned_quantity), (36, 36))

    def test_blank_element_fallback_update_is_synchronized(self):
        _set, item, part = self.allocation(inventory_element_id="", part_owned=0)

        self.client.post(
            reverse("catalog:missing_part_quantity", args=[part.pk]),
            {"owned_quantity": 36},
        )

        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((part.owned_quantity, item.owned_quantity), (36, 36))

    def test_color_set_owner_and_spare_rows_are_isolated(self):
        lego_set, normal, part = self.allocation()
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="3062b",
            element_id="4117070",
            name="Spare",
            color_id=19,
            color_name="Tan",
            required_quantity=2,
            owned_quantity=1,
            is_spare=True,
        )
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="3062b-blue",
            element_id="4117070",
            name="Other color",
            color_id=1,
            color_name="Blue",
            required_quantity=42,
            owned_quantity=2,
        )
        other_set = LegoSet.objects.create(
            owner=self.user, set_number="other-1", name="Other"
        )
        foreign_set_item = SetInventoryItem.objects.create(
            lego_set=other_set,
            part_number="3062b",
            element_id="4117070",
            name="Other set",
            color_name="Tan",
            required_quantity=42,
            owned_quantity=2,
        )

        self.client.post(
            reverse("catalog:missing_part_quantity", args=[part.pk]),
            {"owned_quantity": 36},
        )

        normal.refresh_from_db()
        foreign_set_item.refresh_from_db()
        spare = lego_set.inventory_items.get(is_spare=True)
        blue = lego_set.inventory_items.get(color_name="Blue")
        self.assertEqual(normal.owned_quantity, 36)
        self.assertEqual((spare.owned_quantity, blue.owned_quantity), (1, 2))
        self.assertEqual(foreign_set_item.owned_quantity, 2)

    def test_manual_part_keeps_part_owned_quantity(self):
        part = Part.objects.create(
            owner=self.user,
            element_id="manual",
            name="Manual",
            quantity=10,
            owned_quantity=1,
        )

        self.client.post(
            reverse("catalog:missing_part_quantity", args=[part.pk]),
            {"owned_quantity": 7},
        )

        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 7)

    def test_ambiguous_match_fails_without_partial_write(self):
        lego_set, first, part = self.allocation()
        second = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="alternate",
            element_id="4117070",
            name="Ambiguous",
            color_id=20,
            color_name="Tan",
            required_quantity=42,
            owned_quantity=5,
        )

        response = self.client.post(
            reverse("catalog:missing_part_quantity", args=[part.pk]),
            {"owned_quantity": 36},
        )

        self.assertEqual(response.status_code, 409)
        part.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(
            (part.owned_quantity, first.owned_quantity, second.owned_quantity),
            (3, 3, 5),
        )

    def test_minifigure_edit_synchronizes_part_mirror(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="mini-1", name="Mini"
        )
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-1", name="Figure"
        )
        component = MinifigurePart.objects.create(
            minifigure=figure,
            part_number="973",
            element_id="mini-element",
            name="Torso",
            color_name="Tan",
            quantity=4,
            owned_quantity=1,
        )
        mirror = Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id="mini-element",
            design_id="973",
            name="Torso mirror",
            color="Tan",
            quantity=4,
            owned_quantity=1,
        )

        response = self.client.post(
            reverse(
                "organizer:minifigure_part_quantity", args=[figure.pk, component.pk]
            ),
            {"owned_quantity": 3},
        )

        self.assertEqual(response.status_code, 302)
        component.refresh_from_db()
        mirror.refresh_from_db()
        self.assertEqual((component.owned_quantity, mirror.owned_quantity), (3, 3))

    def test_minifigure_bulk_update_synchronizes_part_mirror(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="mini-bulk-1", name="Mini bulk"
        )
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-2", name="Figure"
        )
        component = MinifigurePart.objects.create(
            minifigure=figure,
            part_number="973",
            element_id="mini-bulk-element",
            name="Torso",
            color_name="Tan",
            quantity=4,
            owned_quantity=1,
        )
        mirror = Part.objects.create(
            owner=self.user,
            lego_set=lego_set,
            element_id="mini-bulk-element",
            design_id="973",
            name="Torso mirror",
            color="Tan",
            quantity=4,
            owned_quantity=1,
        )

        self.client.post(
            reverse(
                "organizer:minifigure_inventory_action", args=[figure.pk, "complete"]
            )
        )

        component.refresh_from_db()
        mirror.refresh_from_db()
        self.assertEqual((component.owned_quantity, mirror.owned_quantity), (4, 4))

    def test_rebrickable_refresh_preserves_consistent_authoritative_ownership(self):
        lego_set, item, part = self.allocation(inventory_owned=36, part_owned=36)

        synchronize_set(
            lego_set,
            "key",
            set_fetcher=lambda _number, _key: (
                {"name": "Harbor", "num_parts": 30},
                [
                    {
                        "part": {"part_num": "3062b", "name": item.name},
                        "color": {"id": 19, "name": "Tan"},
                        "element_id": "4117070",
                        "quantity": 30,
                    }
                ],
            ),
            minifigure_fetcher=lambda _number, _key: [],
        )

        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, part.owned_quantity), (36, 36))
        self.assertEqual((item.required_quantity, part.quantity), (30, 36))


class OwnedQuantityConsistencyAuditTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "audit-sync", "audit-sync@example.test", "A-long-password-123"
        )

    def create_case(
        self,
        suffix,
        *,
        part_owned,
        inventory_owned,
        inventory_element=None,
        part_color="Tan",
        inventory_color="Tan",
        spare=False,
        owner=None,
    ):
        owner = owner or self.user
        lego_set = LegoSet.objects.create(
            owner=owner, set_number=f"audit-{suffix}", name=f"Audit {suffix}"
        )
        element = f"element-{suffix}"
        number = f"design-{suffix}"
        item = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number=number,
            element_id=element if inventory_element is None else inventory_element,
            name="Inventory",
            color_name=inventory_color,
            required_quantity=10,
            owned_quantity=inventory_owned,
            is_spare=spare,
        )
        part = Part.objects.create(
            owner=owner,
            lego_set=lego_set,
            element_id=element,
            design_id=number,
            name="Part",
            color=part_color,
            quantity=10,
            owned_quantity=part_owned,
        )
        return item, part

    def test_read_only_audit_detects_only_same_allocation_divergences(self):
        self.create_case("consistent", part_owned=3, inventory_owned=3)
        newer_part_item, newer_part = self.create_case(
            "part-newer", part_owned=8, inventory_owned=2
        )
        newer_inventory_item, newer_inventory = self.create_case(
            "inventory-newer", part_owned=2, inventory_owned=8
        )
        _blank_item, blank = self.create_case(
            "blank", part_owned=7, inventory_owned=4, inventory_element=""
        )
        self.create_case(
            "color", part_owned=7, inventory_owned=4, inventory_color="Blue"
        )
        self.create_case("spare", part_owned=7, inventory_owned=4, spare=True)
        Part.objects.create(
            owner=self.user,
            element_id="manual",
            name="Manual",
            quantity=10,
            owned_quantity=7,
        )
        foreign = get_user_model().objects.create_user(
            "audit-foreign", "audit-foreign@example.test", "A-long-password-123"
        )
        self.create_case("foreign", part_owned=9, inventory_owned=1, owner=foreign)
        now = timezone.now()
        SetInventoryItem.objects.filter(pk=newer_part_item.pk).update(
            updated_at=now - timedelta(hours=2)
        )
        Part.objects.filter(pk=newer_part.pk).update(updated_at=now)
        Part.objects.filter(pk=newer_inventory.pk).update(
            updated_at=now - timedelta(hours=2)
        )
        SetInventoryItem.objects.filter(pk=newer_inventory_item.pk).update(
            updated_at=now
        )

        before = list(Part.objects.order_by("pk").values())
        with self.assertNumQueries(3):
            rows = owned_quantity_consistency_rows(user=self.user)
        after = list(Part.objects.order_by("pk").values())

        self.assertEqual(after, before)
        self.assertEqual(
            {row["part_id"] for row in rows},
            {str(newer_part.pk), str(newer_inventory.pk), str(blank.pk)},
        )
        blank_row = next(row for row in rows if row["part_id"] == str(blank.pk))
        self.assertEqual(
            (
                blank_row["part_required"],
                blank_row["part_owned"],
                blank_row["authoritative_required"],
                blank_row["authoritative_owned"],
                blank_row["difference"],
            ),
            (10, 7, 10, 4, 3),
        )
        self.assertIsNotNone(blank_row["part_updated_at"])
        self.assertIsNotNone(blank_row["authoritative_updated_at"])

    def test_management_command_is_scoped_and_read_only(self):
        _item, part = self.create_case("command", part_owned=8, inventory_owned=2)
        output = StringIO()

        call_command(
            "audit_owned_quantity_consistency",
            user_id=str(self.user.pk),
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn(str(part.pk), text)
        self.assertIn("divergences: 1", text)
        self.assertIn("audit_mode: read-only", text)
