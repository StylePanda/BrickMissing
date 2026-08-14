from __future__ import annotations

import hashlib
import secrets
import uuid

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    def _create_user(self, username, email, password, **extra_fields):
        email = self.normalize_email(email).casefold()
        return super()._create_user(username.strip(), email, password, **extra_fields)


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    legacy_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    totp_secret_encrypted = models.TextField(blank=True)
    totp_enabled = models.BooleanField(default=False)
    objects = UserManager()

    REQUIRED_FIELDS = ["email"]

    class Meta:
        constraints = []

    def save(self, *args, **kwargs):
        self.email = self.__class__.objects.normalize_email(self.email).casefold()
        super().save(*args, **kwargs)


class RecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    digest = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "digest"], name="unique_recovery_code")
        ]

    @staticmethod
    def digest_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    @classmethod
    def generate_for(cls, user: User, count: int = 10) -> list[str]:
        values = [secrets.token_hex(5).upper() for _ in range(count)]
        cls.objects.bulk_create([cls(user=user, digest=cls.digest_code(value)) for value in values])
        return values
