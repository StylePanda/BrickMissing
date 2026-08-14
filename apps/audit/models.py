import hashlib

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_actions",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_targets",
    )
    actor_identifier = models.CharField(max_length=64, blank=True)
    actor_username_snapshot = models.CharField(max_length=150, blank=True)
    actor_email_hash = models.CharField(max_length=64, blank=True)
    target_identifier = models.CharField(max_length=64, blank=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_repr_snapshot = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=100, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    remote_address = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def preserve_attribution(self) -> list[str]:
        changed = []
        if self.actor_id and self.actor:
            if not self.actor_identifier:
                self.actor_identifier = str(self.actor_id)
                changed.append("actor_identifier")
            if not self.actor_username_snapshot:
                self.actor_username_snapshot = self.actor.get_username()[:150]
                changed.append("actor_username_snapshot")
            if not self.actor_email_hash and self.actor.email:
                normalized = self.actor.email.strip().casefold().encode("utf-8")
                self.actor_email_hash = hashlib.sha256(normalized).hexdigest()
                changed.append("actor_email_hash")
        if self.target_user_id and self.target_user:
            if not self.target_identifier:
                self.target_identifier = str(self.target_user_id)
                changed.append("target_identifier")
            if not self.target_type:
                self.target_type = "accounts.User"
                changed.append("target_type")
            if not self.target_repr_snapshot:
                self.target_repr_snapshot = self.target_user.get_username()[:255]
                changed.append("target_repr_snapshot")
        elif self.entity_type and not self.target_type:
            self.target_type = self.entity_type[:100]
            changed.append("target_type")
        return changed

    def save(self, *args, **kwargs):
        changed = self.preserve_attribution()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and changed:
            kwargs["update_fields"] = set(update_fields) | set(changed)
        super().save(*args, **kwargs)
