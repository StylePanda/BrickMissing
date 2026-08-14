from django.conf import settings
from django.db import models
from django.utils import timezone


class PriceObservation(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    entity_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=64)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    shipping = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EUR")
    source = models.CharField(max_length=100, blank=True)
    supplier = models.CharField(max_length=191, blank=True)
    is_estimate = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["owner", "entity_type", "entity_id"])]


class ValueSnapshot(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    collection_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    missing_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    warehouse_quantity = models.PositiveIntegerField(default=0)
    captured_at = models.DateTimeField()

    class Meta:
        ordering = ["-captured_at"]
