from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import RecoveryCode, User

User._meta.verbose_name = "Benutzerkonto"
User._meta.verbose_name_plural = "Benutzerkonten"
RecoveryCode._meta.verbose_name = "Wiederherstellungscode"
RecoveryCode._meta.verbose_name_plural = "Wiederherstellungscodes"


@admin.register(User)
class BrickMissingUserAdmin(UserAdmin):
    readonly_fields = ("id", "created_at", "updated_at", "legacy_id")
    fieldsets = UserAdmin.fieldsets + (
        (
            "BrickMissing",
            {
                "fields": (
                    "id",
                    "email_verified",
                    "legacy_id",
                    "created_at",
                    "updated_at",
                    "deactivated_at",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("BrickMissing", {"fields": ("email",)}),)
    list_display = ("username", "email", "email_verified", "is_active", "is_staff")
    list_per_page = 50


@admin.register(RecoveryCode)
class RecoveryCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "used_at")
    readonly_fields = ("digest",)
