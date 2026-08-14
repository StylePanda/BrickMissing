from django.contrib import admin

from .models import InventoryItem, InventoryMovement, WarehouseLocation

InventoryItem._meta.verbose_name = "Bestandsteil"
InventoryItem._meta.verbose_name_plural = "Bestandsteile"
InventoryMovement._meta.verbose_name = "Bestandsbewegung"
InventoryMovement._meta.verbose_name_plural = "Bestandsbewegungen"
WarehouseLocation._meta.verbose_name = "Lagerort"
WarehouseLocation._meta.verbose_name_plural = "Lagerorte"


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("part_number", "name", "owner", "quantity", "reserved_quantity")
    readonly_fields = ("quantity", "reserved_quantity")
    search_fields = ("part_number", "element_id", "name", "owner__username", "owner__email")
    list_filter = ("condition", "category", "archived_at")
    list_per_page = 50


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    readonly_fields = tuple(field.name for field in InventoryMovement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(WarehouseLocation)
