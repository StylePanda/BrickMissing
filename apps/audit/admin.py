from django.contrib import admin

from .models import AuditEvent

AuditEvent._meta.verbose_name = "Audit-Ereignis"
AuditEvent._meta.verbose_name_plural = "Audit-Ereignisse"


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_user", "entity_type", "entity_id")
    list_filter = ("action", "entity_type")
    search_fields = ("action", "entity_id", "request_id")
    readonly_fields = tuple(field.name for field in AuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
