from django.conf import settings
from django.db import models


class BackupArtifact(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    filename = models.CharField(max_length=255, unique=True)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    status = models.CharField(max_length=32, default="ready")
    created_at = models.DateTimeField(auto_now_add=True)
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
