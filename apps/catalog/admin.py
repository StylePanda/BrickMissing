from django.contrib import admin

from .models import LegoSet, Part, PartHistory, SetCopy, SetInventoryItem

LegoSet._meta.verbose_name = "LEGO-Set"
LegoSet._meta.verbose_name_plural = "LEGO-Sets"
Part._meta.verbose_name = "Teil"
Part._meta.verbose_name_plural = "Teile"
SetCopy._meta.verbose_name = "Setexemplar"
SetCopy._meta.verbose_name_plural = "Setexemplare"
SetInventoryItem._meta.verbose_name = "Soll-/Ist-Teil"
SetInventoryItem._meta.verbose_name_plural = "Soll-/Ist-Teile"
PartHistory._meta.verbose_name = "Teileverlauf"
PartHistory._meta.verbose_name_plural = "Teileverläufe"


@admin.register(LegoSet)
class LegoSetAdmin(admin.ModelAdmin):
    list_display = ("set_number", "name", "owner", "year", "deleted_at")
    search_fields = ("set_number", "name", "owner__username", "owner__email")
    list_filter = ("year", "condition", "deleted_at")
    list_per_page = 50


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("element_id", "name", "color", "owner", "status", "quantity")
    search_fields = ("element_id", "part_number", "name", "owner__username")
    list_filter = ("status", "priority", "deleted_at")
    list_per_page = 50


admin.site.register([SetCopy, SetInventoryItem, PartHistory])
