from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class OwnedModel(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class LegoSet(OwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    set_number = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    theme = models.CharField(max_length=150, blank=True)
    subtheme = models.CharField(max_length=150, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    total_parts = models.PositiveIntegerField(default=0)
    minifigures = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    condition = models.CharField(max_length=32, default="gebraucht")
    completeness = models.CharField(max_length=32, default="unbekannt")
    build_status = models.CharField(max_length=64, default="zerlegt vollständig")
    favorite = models.BooleanField(default=False)
    image_url = models.URLField(max_length=1000, blank=True)
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    current_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    has_box = models.BooleanField(default=False)
    has_instructions = models.BooleanField(default=False)
    has_stickers = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    active_set_number = models.CharField(max_length=64, null=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "active_set_number"],
                name="unique_active_set_per_owner",
            )
        ]
        indexes = [
            models.Index(fields=["owner", "set_number"]),
            models.Index(fields=["owner", "year"]),
        ]

    def save(self, *args, **kwargs):
        self.active_set_number = self.set_number if self.deleted_at is None else None
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"active_set_number"}
        super().save(*args, **kwargs)


class SetCopy(OwnedModel):
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    lego_set = models.ForeignKey(LegoSet, on_delete=models.CASCADE, related_name="copies")
    inventory_number = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    condition = models.CharField(max_length=32, default="gebraucht")
    completeness = models.CharField(max_length=32, default="unbekannt")
    build_status = models.CharField(max_length=64, default="zerlegt vollständig")
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    notes = models.TextField(blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)


class SetInventoryItem(models.Model):
    lego_set = models.ForeignKey(LegoSet, on_delete=models.CASCADE, related_name="inventory_items")
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    part_number = models.CharField(max_length=100)
    element_id = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=255)
    color_id = models.IntegerField(null=True, blank=True)
    color_name = models.CharField(max_length=150, blank=True)
    required_quantity = models.PositiveIntegerField(default=1)
    owned_quantity = models.PositiveIntegerField(default=0)
    is_spare = models.BooleanField(default=False)
    image_url = models.URLField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lego_set", "part_number", "color_id", "is_spare"],
                name="unique_set_inventory_item",
            ),
            models.CheckConstraint(
                condition=Q(owned_quantity__gte=0), name="set_inventory_owned_nonnegative"
            ),
        ]
        indexes = [
            models.Index(fields=["lego_set", "part_number"]),
            models.Index(fields=["element_id"]),
        ]

    @property
    def missing_quantity(self):
        return max(self.required_quantity - self.owned_quantity, 0)


class Part(OwnedModel):
    class Status(models.TextChoices):
        MISSING = "missing", "Fehlt"
        FOUND = "found", "Gefunden"
        ORDERED = "ordered", "Bestellt"
        SHIPPED = "shipped", "Versendet"
        RECEIVED = "received", "Erhalten"
        INSTALLED = "installed", "Eingebaut"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    lego_set = models.ForeignKey(
        LegoSet, null=True, blank=True, on_delete=models.SET_NULL, related_name="parts"
    )
    element_id = models.CharField(max_length=100)
    design_id = models.CharField(max_length=100, blank=True)
    part_number = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=150, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    owned_quantity = models.PositiveIntegerField(default=0)
    unassigned_found_quantity = models.PositiveIntegerField(default=0)
    is_present = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.MISSING)
    priority = models.CharField(max_length=16, default="normal")
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    supplier = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["name", "color"]
        constraints = [
            models.CheckConstraint(
                condition=Q(owned_quantity__lte=F("quantity")), name="part_owned_lte_quantity"
            ),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="part_quantity_nonnegative"),
        ]
        indexes = [
            models.Index(fields=["owner", "status", "deleted_at"]),
            models.Index(fields=["owner", "element_id"]),
        ]

    @property
    def missing_quantity(self):
        return max(self.quantity - self.owned_quantity, 0)


class PartHistory(models.Model):
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=16, choices=Part.Status.choices)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
