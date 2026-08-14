from django import forms

from .models import LegoSet, Part, SetCopy, SetInventoryItem


class LegoSetForm(forms.ModelForm):
    CONDITION_CHOICES = (("neu", "Neu"), ("gebraucht", "Gebraucht"))
    COMPLETENESS_CHOICES = (("vollständig", "Vollständig"), ("unvollständig", "Unvollständig"), ("unbekannt", "Unbekannt"))
    BUILD_STATUS_CHOICES = (("gebaut", "Aufgebaut"), ("aufgebaut", "Aufgebaut (bestehender Wert)"), ("zerlegt vollständig", "Zerlegt, vollständig"), ("zerlegt unvollständig", "Zerlegt, unvollständig"), ("in arbeit", "Im Aufbau"))
    condition = forms.ChoiceField(label="Kaufzustand", choices=CONDITION_CHOICES)
    completeness = forms.ChoiceField(label="Vollständigkeit", choices=COMPLETENESS_CHOICES)
    build_status = forms.ChoiceField(label="Aufbaustatus", choices=BUILD_STATUS_CHOICES)
    class Meta:
        model = LegoSet
        exclude = ("owner", "legacy_id", "deleted_at")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "theme": forms.TextInput(attrs={"autocomplete": "off"}),
            "subtheme": forms.TextInput(attrs={"autocomplete": "off"}),
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
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}
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


class SetCopyForm(forms.ModelForm):
    condition = forms.ChoiceField(label="Zustand", choices=LegoSetForm.CONDITION_CHOICES)
    completeness = forms.ChoiceField(label="Vollständigkeit", choices=LegoSetForm.COMPLETENESS_CHOICES)
    build_status = forms.ChoiceField(label="Aufbaustatus", choices=LegoSetForm.BUILD_STATUS_CHOICES)
    class Meta:
        model = SetCopy
        exclude = ("owner", "lego_set", "legacy_id", "deleted_at")


class SetInventoryItemForm(forms.ModelForm):
    class Meta:
        model = SetInventoryItem
        exclude = ("lego_set", "legacy_id")
