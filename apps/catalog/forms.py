from django import forms

from .models import LegoSet, Part, SetCopy, SetInventoryItem
from .part_status import expected_is_present


class LegoSetForm(forms.ModelForm):
    CONDITION_CHOICES = (("neu", "Neu"), ("gebraucht", "Gebraucht"))
    COMPLETENESS_CHOICES = (("vollständig", "Vollständig"), ("unvollständig", "Unvollständig"), ("unbekannt", "Unbekannt"))
    BUILD_STATUS_CHOICES = (("gebaut", "Aufgebaut"), ("aufgebaut", "Aufgebaut (bestehender Wert)"), ("zerlegt vollständig", "Zerlegt, vollständig"), ("zerlegt unvollständig", "Zerlegt, unvollständig"), ("in arbeit", "Im Aufbau"))
    condition = forms.ChoiceField(label="Kaufzustand", choices=CONDITION_CHOICES)
    build_status = forms.ChoiceField(label="Aufbaustatus", choices=BUILD_STATUS_CHOICES)
    class Meta:
        model = LegoSet
        exclude = ("owner", "legacy_id", "deleted_at", "completeness")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "theme": forms.TextInput(attrs={"autocomplete": "off"}),
            "subtheme": forms.TextInput(attrs={"autocomplete": "off"}),
            "purchase_price": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "current_value": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
        }
        labels = {
            "set_number": "Setnummer", "name": "Name", "theme": "Themenwelt",
            "subtheme": "Unterthema", "year": "Erscheinungsjahr", "total_parts": "Teileanzahl",
            "minifigures": "Minifiguren", "description": "Beschreibung", "favorite": "Favorit",
            "image_url": "Bild-URL", "purchase_date": "Kaufdatum", "purchase_price": "Kaufpreis",
            "current_value": "Aktueller Wert", "has_box": "Box vorhanden",
            "has_instructions": "Anleitung vorhanden", "has_stickers": "Sticker vorhanden",
            "notes": "Notizen",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("total_parts", "minifigures", "purchase_price", "current_value"):
            self.fields[field].required = False


class PartForm(forms.ModelForm):
    priority = forms.ChoiceField(
        label="Priorität",
        choices=(("low", "Niedrig"), ("normal", "Normal"), ("high", "Hoch"), ("urgent", "Dringend")),
    )
    class Meta:
        model = Part
        exclude = ("owner", "legacy_id", "deleted_at")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "unit_price": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
        }
        labels = {
            "lego_set": "Set-Zuordnung", "element_id": "Element-ID", "design_id": "Design-ID",
            "part_number": "Teilenummer", "name": "Name", "color": "Farbe",
            "quantity": "Benötigte Menge", "owned_quantity": "Vorhandene Menge",
            "unassigned_found_quantity": "Nicht zugeordnete Fundmenge", "is_present": "Vorhanden",
            "status": "Status", "unit_price": "Stückpreis", "supplier": "Lieferant",
            "notes": "Notizen", "image_url": "Bild-URL",
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lego_set"].queryset = LegoSet.objects.filter(
            owner=owner, deleted_at__isnull=True
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("owned_quantity") is not None and cleaned.get("unassigned_found_quantity") is not None:
            candidate = self.instance
            candidate.owned_quantity = cleaned["owned_quantity"]
            candidate.unassigned_found_quantity = cleaned["unassigned_found_quantity"]
            cleaned["is_present"] = expected_is_present(candidate)
        return cleaned

class SetCopyForm(forms.ModelForm):
    condition = forms.ChoiceField(label="Zustand", choices=LegoSetForm.CONDITION_CHOICES)
    completeness = forms.ChoiceField(label="Vollständigkeit", choices=LegoSetForm.COMPLETENESS_CHOICES)
    build_status = forms.ChoiceField(label="Aufbaustatus", choices=LegoSetForm.BUILD_STATUS_CHOICES)
    class Meta:
        model = SetCopy
        exclude = ("owner", "lego_set", "legacy_id", "deleted_at")
        widgets = {
            "purchase_price": forms.NumberInput(attrs={"min": "0", "step": "0.01"})
        }


class SetInventoryItemForm(forms.ModelForm):
    class Meta:
        model = SetInventoryItem
        exclude = ("lego_set", "legacy_id")
