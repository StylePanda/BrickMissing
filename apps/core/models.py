from django.conf import settings
from django.db import models


class Notification(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    kind = models.CharField(max_length=50)
    title = models.CharField(max_length=191)
    message = models.TextField()
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SavedView(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    area = models.CharField(max_length=50)
    name = models.CharField(max_length=191)
    path = models.CharField(max_length=255)
    configuration = models.JSONField(default=dict)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "area", "name"], name="unique_saved_view")
        ]


class RecentItem(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=64)
    label = models.CharField(max_length=255)
    path = models.CharField(max_length=255)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-viewed_at"]


class DataQualityIssue(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    issue_key = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=64, blank=True)
    severity = models.CharField(max_length=20, default="warning")
    message = models.CharField(max_length=255)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["severity", "issue_key"]
