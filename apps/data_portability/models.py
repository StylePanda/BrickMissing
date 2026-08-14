import uuid

from django.conf import settings
from django.db import models


class LegacyImportRecord(models.Model):
    source_fingerprint = models.CharField(max_length=64)
    source_table = models.CharField(max_length=100)
    source_pk = models.CharField(max_length=100)
    target_model = models.CharField(max_length=150)
    target_pk = models.CharField(max_length=100)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_fingerprint", "source_table", "source_pk"],
                name="unique_legacy_import_record",
            )
        ]


class LegacyArchiveRecord(models.Model):
    source_fingerprint = models.CharField(max_length=64)
    source_table = models.CharField(max_length=100)
    source_pk = models.CharField(max_length=100)
    payload = models.JSONField()
    classification = models.CharField(max_length=100, default="archived_for_validation")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_fingerprint", "source_table", "source_pk"],
                name="unique_legacy_archive_record",
            )
        ]


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source_format = models.CharField(max_length=10)
    payload = models.JSONField(default=dict)
    report = models.JSONField(default=dict)
    committed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
