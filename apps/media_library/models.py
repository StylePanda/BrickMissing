import uuid

from django.conf import settings
from django.db import models


def private_upload_path(instance, filename):
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"users/{instance.owner_id}/{uuid.uuid4().hex}.{suffix}"


class PrivateDocument(models.Model):
    ENTITY_LABELS = {"set": "Set", "part": "Teil", "order": "Bestellung", "inventory": "Inventar", "moc": "MOC", "other": "Sonstiges"}
    DOCUMENT_LABELS = {"invoice": "Rechnung", "instructions": "Anleitung", "photo": "Foto", "certificate": "Zertifikat", "other": "Sonstiges", "sonstiges": "Sonstiges"}
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=64)
    document_type = models.CharField(max_length=50, default="sonstiges")
    title = models.CharField(max_length=191)
    file = models.FileField(upload_to=private_upload_path)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    version = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def entity_type_label(self):
        return self.ENTITY_LABELS.get(self.entity_type, self.entity_type)

    @property
    def document_type_label(self):
        return self.DOCUMENT_LABELS.get(self.document_type, self.document_type)
