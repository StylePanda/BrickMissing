from django.conf import settings
from django.db import models

from apps.catalog.models import LegoSet
from apps.inventory.models import InventoryItem, WarehouseLocation


class Collection(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_collections"
    )
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=191)
    description = models.TextField(blank=True)
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CollectionMember(models.Model):
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, default="viewer")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection", "user"], name="unique_collection_member")
        ]


class Moc(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.SET_NULL)
    location = models.ForeignKey(
        WarehouseLocation, null=True, blank=True, on_delete=models.SET_NULL
    )
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=191)
    project_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=32, default="Planung")
    version = models.CharField(max_length=32, default="1.0")
    progress = models.PositiveSmallIntegerField(default=0)
    instruction_url = models.URLField(max_length=1000, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    notes = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class MocPart(models.Model):
    moc = models.ForeignKey(Moc, on_delete=models.CASCADE, related_name="parts")
    inventory_item = models.ForeignKey(
        InventoryItem, null=True, blank=True, on_delete=models.SET_NULL
    )
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    part_number = models.CharField(max_length=100)
    name = models.CharField(max_length=255, blank=True)
    color = models.CharField(max_length=150, blank=True)
    required_quantity = models.PositiveIntegerField(default=1)
    allocated_quantity = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)


class MocVersion(models.Model):
    moc = models.ForeignKey(Moc, on_delete=models.CASCADE, related_name="versions")
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    version = models.CharField(max_length=32)
    name = models.CharField(max_length=191, blank=True)
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    parts_snapshot = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["moc", "version"], name="unique_moc_version")
        ]


class WishlistItem(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.SET_NULL)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    entity_type = models.CharField(max_length=32, default="set")
    reference = models.CharField(max_length=191)
    name = models.CharField(max_length=255)
    priority = models.CharField(max_length=20, default="normal")
    target_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Loan(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    entity_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=64)
    borrower = models.CharField(max_length=191)
    loaned_at = models.DateTimeField()
    due_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)


class PersonalNote(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=120)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WorkshopDocument(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    payload = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class LabelTemplate(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=191)
    width_mm = models.DecimalField(max_digits=7, decimal_places=2, default=50)
    height_mm = models.DecimalField(max_digits=7, decimal_places=2, default=30)
    orientation = models.CharField(max_length=20, default="landscape")
    configuration = models.JSONField(default=dict)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="unique_owner_label_template")]


class SetMinifigure(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    lego_set = models.ForeignKey(
        LegoSet, on_delete=models.CASCADE, related_name="minifigures_inventory"
    )
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    figure_number = models.CharField(max_length=100)
    name = models.CharField(max_length=191)
    quantity = models.PositiveIntegerField(default=1)
    owned_quantity = models.PositiveIntegerField(default=0)
    image_url = models.URLField(max_length=1000, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "lego_set", "figure_number"], name="unique_set_minifigure"
            )
        ]


class MinifigurePart(models.Model):
    minifigure = models.ForeignKey(SetMinifigure, on_delete=models.CASCADE, related_name="parts")
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    part_number = models.CharField(max_length=100)
    element_id = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=191)
    color_id = models.IntegerField(null=True, blank=True)
    color_name = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    owned_quantity = models.PositiveIntegerField(default=0)
    is_spare = models.BooleanField(default=False)
    image_url = models.URLField(max_length=1000, blank=True)
