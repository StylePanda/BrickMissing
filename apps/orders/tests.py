from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import LegoSet
from apps.inventory.models import InventoryItem, InventoryMovement, WarehouseLocation

from .models import Order, OrderItem


class OrderReceiptTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("buyer", "buyer@example.test", "A-long-safe-password-123", email_verified=True)
        self.other = User.objects.create_user("other", "other@example.test", "A-long-safe-password-123", email_verified=True)
        self.order = Order.objects.create(owner=self.user, supplier="Shop", status="ordered")
        self.item = OrderItem.objects.create(order=self.order, part_number="3001", name="Brick", quantity=3)
        self.client.force_login(self.user)

    def test_receipt_creates_inventory_and_movement(self):
        response = self.client.post(reverse("orders:receive_item", args=[self.order.pk, self.item.pk]), {"quantity": 3})
        self.assertRedirects(response, reverse("orders:detail", args=[self.order.pk]))
        inventory = InventoryItem.objects.get(owner=self.user, part_number="3001")
        self.assertEqual(inventory.quantity, 3)
        self.assertEqual(InventoryMovement.objects.get(item=inventory).difference, 3)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "received")

    def test_receipt_rejects_overdelivery_and_foreign_order(self):
        self.assertEqual(self.client.post(reverse("orders:receive_item", args=[self.order.pk, self.item.pk]), {"quantity": 4}).status_code, 400)
        foreign = Order.objects.create(owner=self.other, supplier="Other")
        foreign_item = OrderItem.objects.create(order=foreign, part_number="x", quantity=1)
        self.assertEqual(self.client.post(reverse("orders:receive_item", args=[foreign.pk, foreign_item.pk]), {"quantity": 1}).status_code, 404)

    def test_order_get_edit_child_and_relation_assignment_idor(self):
        foreign = Order.objects.create(owner=self.other, supplier="Foreign")
        foreign_item = OrderItem.objects.create(order=foreign, part_number="x", quantity=1)
        for url in (
            reverse("orders:detail", args=[foreign.pk]),
            reverse("orders:edit", args=[foreign.pk]),
            reverse("orders:item_create", args=[foreign.pk]),
            reverse("orders:item_edit", args=[foreign.pk, foreign_item.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 404)
        foreign_inventory = InventoryItem.objects.create(
            owner=self.other, part_number="foreign", name="Foreign", quantity=1
        )
        foreign_set = LegoSet.objects.create(
            owner=self.other, set_number="foreign-order", name="Foreign"
        )
        foreign_location = WarehouseLocation.objects.create(owner=self.other, name="Foreign")
        response = self.client.post(
            reverse("orders:item_create", args=[self.order.pk]),
            {
                "inventory_item": foreign_inventory.pk,
                "part_number": "3001", "name": "Injected", "color": "", "quantity": 1,
                "received_quantity": 0, "damaged_quantity": 0, "wrong_quantity": 0,
                "unit_price": "0", "target_set": foreign_set.pk,
                "target_location": foreign_location.pk, "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(OrderItem.objects.filter(order=self.order, name="Injected").exists())
