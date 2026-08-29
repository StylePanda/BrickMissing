from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from .admin import InventoryItemAdmin
from .forms import InventoryItemForm
from .models import InventoryItem, InventoryMovement, WarehouseLocation
from .services import adjust_inventory, change_inventory


class InventoryIntegrityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "stock",
            "stock@example.test",
            "A-very-long-password-123",
            email_verified=True,
        )
        self.item = InventoryItem.objects.create(
            owner=self.user,
            part_number="3001",
            name="Brick",
            quantity=5,
            reserved_quantity=1,
        )

    def test_increase_decrease_and_reservation_create_complete_movements(self):
        adjust_inventory(self.item, self.user, 8, 2, "test")
        current = InventoryItem.objects.get(pk=self.item.pk)
        self.assertEqual((current.quantity, current.reserved_quantity), (8, 2))
        movement = current.movements.get()
        self.assertEqual(
            (
                movement.old_quantity,
                movement.new_quantity,
                movement.difference,
                movement.old_reserved,
                movement.new_reserved,
            ),
            (5, 8, 3, 1, 2),
        )
        change_inventory(current, self.user, quantity_delta=-3, movement_type="test")
        current.refresh_from_db()
        self.assertEqual(current.quantity, 5)

    def test_invalid_stock_is_rejected_without_movement(self):
        for quantity, reserved in [(-1, 0), (2, -1), (2, 3)]:
            with self.assertRaises(ValidationError):
                adjust_inventory(self.item, self.user, quantity, reserved, "test")
        self.item.refresh_from_db()
        self.assertEqual((self.item.quantity, self.item.reserved_quantity), (5, 1))

    def test_condition_uses_fixed_semantic_choices(self):
        field = InventoryItemForm().fields["condition"]
        self.assertEqual(list(field.choices), [("neu", "Neu"), ("gebraucht", "Gebraucht")])
        self.assertFalse(InventoryMovement.objects.exists())

    def test_failure_rolls_back_item_and_movement(self):
        with patch(
            "apps.inventory.services.AuditEvent.objects.create", side_effect=RuntimeError
        ):
            with self.assertRaises(RuntimeError), transaction.atomic():
                adjust_inventory(self.item, self.user, 9, 1, "test")
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 5)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_stale_callers_do_not_lose_delta_updates(self):
        first_snapshot = InventoryItem.objects.get(pk=self.item.pk)
        second_snapshot = InventoryItem.objects.get(pk=self.item.pk)
        change_inventory(
            first_snapshot, self.user, quantity_delta=2, movement_type="concurrent"
        )
        change_inventory(
            second_snapshot, self.user, quantity_delta=3, movement_type="concurrent"
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)
        self.assertEqual(
            list(
                self.item.movements.order_by("created_at").values_list(
                    "old_quantity", "new_quantity"
                )
            ),
            [(5, 7), (7, 10)],
        )

    def test_edit_view_uses_service(self):
        self.client.force_login(self.user)
        data = {
            "part_number": "3001",
            "design_id": "",
            "element_id": "",
            "name": "Brick changed",
            "color": "",
            "category": "",
            "subcategory": "",
            "quantity": 7,
            "reserved_quantity": 2,
            "condition": "gebraucht",
            "location": "",
            "image_url": "",
            "source": "",
            "purchase_price": "0",
            "unit_price": "0",
            "notes": "",
        }
        response = self.client.post(reverse("inventory:edit", args=[self.item.pk]), data)
        self.assertRedirects(response, reverse("inventory:list"))
        self.item.refresh_from_db()
        self.assertEqual((self.item.quantity, self.item.reserved_quantity), (7, 2))
        self.assertEqual(self.item.name, "Brick changed")
        self.assertEqual(self.item.movements.count(), 1)

    def test_admin_cannot_bypass_stock_service(self):
        model_admin = InventoryItemAdmin(InventoryItem, admin.site)
        readonly = model_admin.get_readonly_fields(None, self.item)
        self.assertIn("quantity", readonly)
        self.assertIn("reserved_quantity", readonly)

    def test_foreign_inventory_location_and_qr_are_not_accessible(self):
        other = get_user_model().objects.create_user(
            "stock-other", "stock-other@example.test", "A-very-long-password-123",
            email_verified=True,
        )
        foreign_location = WarehouseLocation.objects.create(owner=other, name="Foreign")
        foreign_item = InventoryItem.objects.create(
            owner=other, location=foreign_location, part_number="x", name="Foreign", quantity=1
        )
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("inventory:edit", args=[foreign_item.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("inventory:location_edit", args=[foreign_location.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("inventory:location_qr", args=[foreign_location.pk])).status_code, 404)

    def test_inventory_page_exposes_location_filter_and_management_link(self):
        location = WarehouseLocation.objects.create(owner=self.user, name="Box A")
        self.client.force_login(self.user)
        response = self.client.get(reverse("inventory:list"))
        self.assertContains(response, "Lagerorte verwalten")
        self.assertContains(response, 'name="location"')
        self.assertContains(response, "Box A")
        self.assertEqual(self.client.get(reverse("inventory:list"), {"location": location.pk}).status_code, 200)

    def test_empty_location_is_archived_post_only_and_inventory_is_kept(self):
        location = WarehouseLocation.objects.create(owner=self.user, name="Empty")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("inventory:location_delete", args=[location.pk])).status_code, 405)
        response = self.client.post(reverse("inventory:location_delete", args=[location.pk]))
        self.assertRedirects(response, reverse("inventory:locations"))
        location.refresh_from_db()
        self.assertFalse(location.active)
        self.assertIsNotNone(location.archived_at)

    def test_location_with_inventory_is_not_archived(self):
        location = WarehouseLocation.objects.create(owner=self.user, name="Used")
        self.item.location = location
        self.item.save(update_fields=["location"])
        self.client.force_login(self.user)
        self.client.post(reverse("inventory:location_delete", args=[location.pk]))
        location.refresh_from_db()
        self.assertIsNone(location.archived_at)
