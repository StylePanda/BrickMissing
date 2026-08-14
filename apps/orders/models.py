from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.catalog.models import LegoSet
from apps.inventory.models import InventoryItem, WarehouseLocation


class Order(models.Model):
    STATUS_LABELS = {"draft": "Entwurf", "ordered": "Bestellt", "shipped": "Versendet", "received": "Erhalten", "cancelled": "Storniert"}
    PAYMENT_LABELS = {"": "–", "open": "Offen", "paid": "Bezahlt", "refunded": "Erstattet"}
    SHIPPING_LABELS = {"": "–", "pending": "Ausstehend", "shipped": "Versendet", "delivered": "Zugestellt"}
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    supplier = models.CharField(max_length=191)
    order_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=32, default="ordered")
    order_date = models.DateField(null=True, blank=True)
    expected_delivery = models.DateField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    goods_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EUR")
    payment_status = models.CharField(max_length=32, blank=True)
    shipping_status = models.CharField(max_length=32, blank=True)
    tracking_number = models.CharField(max_length=191, blank=True)
    tracking_url = models.URLField(max_length=1000, blank=True)
    notes = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "status", "deleted_at"])]

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def payment_status_label(self):
        return self.PAYMENT_LABELS.get(self.payment_status, self.payment_status)

    @property
    def shipping_status_label(self):
        return self.SHIPPING_LABELS.get(self.shipping_status, self.shipping_status)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    inventory_item = models.ForeignKey(
        InventoryItem, null=True, blank=True, on_delete=models.SET_NULL
    )
    part_number = models.CharField(max_length=100)
    name = models.CharField(max_length=255, blank=True)
    color = models.CharField(max_length=150, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    received_quantity = models.PositiveIntegerField(default=0)
    damaged_quantity = models.PositiveIntegerField(default=0)
    wrong_quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    target_set = models.ForeignKey(LegoSet, null=True, blank=True, on_delete=models.SET_NULL)
    target_location = models.ForeignKey(
        WarehouseLocation, null=True, blank=True, on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(received_quantity__lte=F("quantity")),
                name="order_received_lte_quantity",
            ),
            models.CheckConstraint(
                condition=Q(damaged_quantity__lte=F("quantity")), name="order_damaged_lte_quantity"
            ),
        ]
