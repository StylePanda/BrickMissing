from django.conf import settings
from django.db import models
from django.db.models import F, Q


class WarehouseLocation(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    name = models.CharField(max_length=191)
    location_type = models.CharField(max_length=50, default="Box")
    short_code = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    room = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=50, blank=True)
    capacity = models.PositiveIntegerField(default=0)
    photo_url = models.URLField(max_length=1000, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    locked = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "parent", "name"], name="unique_owner_location"
            )
        ]
        indexes = [models.Index(fields=["owner", "active"])]


class InventoryItem(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    part_number = models.CharField(max_length=100)
    design_id = models.CharField(max_length=100, blank=True)
    element_id = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=150, blank=True)
    category = models.CharField(max_length=150, blank=True)
    subcategory = models.CharField(max_length=150, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    condition = models.CharField(max_length=32, default="gebraucht")
    location = models.ForeignKey(
        WarehouseLocation, null=True, blank=True, on_delete=models.SET_NULL
    )
    image_url = models.URLField(max_length=1000, blank=True)
    source = models.CharField(max_length=150, blank=True)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(reserved_quantity__lte=F("quantity")),
                name="inventory_reserved_lte_quantity",
            ),
            models.UniqueConstraint(
                fields=["owner", "part_number", "color", "condition", "location"],
                name="unique_inventory_item",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "part_number"]),
            models.Index(fields=["owner", "element_id"]),
        ]

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity


class InventoryMovement(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=50)
    old_quantity = models.PositiveIntegerField()
    new_quantity = models.PositiveIntegerField()
    difference = models.IntegerField()
    old_reserved = models.PositiveIntegerField(default=0)
    new_reserved = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=191, blank=True)
    destination = models.CharField(max_length=191, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    note = models.TextField(blank=True)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
