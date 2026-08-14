from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.audit.models import AuditEvent

from .models import AccountSession, PendingEmailChange, RecoveryCode, User

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

    def save_model(self, request, obj, form, change):
        previous = User.objects.filter(pk=obj.pk).first() if change else None
        super().save_model(request, obj, form, change)
        role_fields = ("is_active", "is_staff", "is_superuser")
        changes = {
            field: {"from": getattr(previous, field), "to": getattr(obj, field)}
            for field in role_fields
            if previous and getattr(previous, field) != getattr(obj, field)
        }
        if changes:
            AuditEvent.objects.create(
                actor=request.user,
                target_user=obj,
                action="account.roles_changed",
                details=changes,
                request_id=getattr(request, "request_id", None),
            )


@admin.register(RecoveryCode)
class RecoveryCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "used_at")
    readonly_fields = ("digest",)


@admin.register(PendingEmailChange, AccountSession)
class AccountSecurityStateAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
