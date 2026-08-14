from django.contrib import admin

from .forms import LABELS
from .models import (
    Collection,
    CollectionMember,
    LabelTemplate,
    Loan,
    MinifigurePart,
    Moc,
    MocPart,
    MocVersion,
    PersonalNote,
    SetMinifigure,
    WishlistItem,
    WorkshopDocument,
)

MODEL_NAMES = {
    Collection: ("Sammlung", "Sammlungen"),
    CollectionMember: ("Sammlungsmitglied", "Sammlungsmitglieder"),
    Moc: ("MOC", "MOCs"),
    MocPart: ("MOC-Teil", "MOC-Teile"),
    MocVersion: ("MOC-Version", "MOC-Versionen"),
    WishlistItem: ("Wunschlisteneintrag", "Wunschlisteneinträge"),
    Loan: ("Ausleihe", "Ausleihen"),
    PersonalNote: ("Persönliche Notiz", "Persönliche Notizen"),
    WorkshopDocument: ("Werkstattdokument", "Werkstattdokumente"),
    LabelTemplate: ("Etikettenvorlage", "Etikettenvorlagen"),
    SetMinifigure: ("Set-Minifigur", "Set-Minifiguren"),
    MinifigurePart: ("Minifigurenteil", "Minifigurenteile"),
}
for model, (singular, plural) in MODEL_NAMES.items():
    model._meta.verbose_name = singular
    model._meta.verbose_name_plural = plural


class GermanLabelsAdmin(admin.ModelAdmin):
    list_per_page = 50

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        for name, field in form.base_fields.items():
            if name in LABELS:
                field.label = LABELS[name]
        return form


@admin.register(Collection)
class CollectionAdmin(GermanLabelsAdmin):
    list_display = ("name", "owner", "is_shared", "updated_at")
    list_filter = ("is_shared",)
    search_fields = ("name", "owner__username", "owner__email")


@admin.register(Moc)
class MocAdmin(GermanLabelsAdmin):
    list_display = ("name", "project_code", "owner", "status", "progress")
    list_filter = ("status",)
    search_fields = ("name", "project_code", "owner__username")


@admin.register(SetMinifigure)
class SetMinifigureAdmin(GermanLabelsAdmin):
    list_display = ("figure_number", "name", "lego_set", "owner", "owned_quantity", "quantity")
    search_fields = ("figure_number", "name", "lego_set__set_number", "owner__username")


@admin.register(WishlistItem)
class WishlistAdmin(GermanLabelsAdmin):
    list_display = ("name", "reference", "owner", "priority", "target_price")
    list_filter = ("priority", "entity_type")
    search_fields = ("name", "reference", "owner__username")


@admin.register(Loan)
class LoanAdmin(GermanLabelsAdmin):
    list_display = ("borrower", "entity_type", "entity_id", "owner", "loaned_at", "returned_at")
    list_filter = ("entity_type",)
    search_fields = ("borrower", "entity_id", "owner__username")


@admin.register(PersonalNote, LabelTemplate, CollectionMember, MocPart, MocVersion, MinifigurePart, WorkshopDocument)
class OrganizerRecordAdmin(GermanLabelsAdmin):
    pass
