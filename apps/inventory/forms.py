from django import forms

from .models import InventoryItem, WarehouseLocation


class WarehouseLocationForm(forms.ModelForm):
    class Meta:
        model = WarehouseLocation
        exclude = ("owner", "legacy_id", "archived_at")
        labels = {"parent": "Übergeordneter Lagerort", "name": "Name", "location_type": "Art des Lagerorts", "short_code": "Kurzcode", "description": "Beschreibung", "room": "Raum", "color": "Farbkennzeichnung", "capacity": "Kapazität", "photo_url": "Foto-URL", "notes": "Notizen", "active": "Aktiv", "locked": "Gesperrt"}
        widgets = {"capacity": forms.NumberInput(attrs={"class": "compact-number", "min": 0}), "description": forms.Textarea(attrs={"rows": 3}), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = WarehouseLocation.objects.filter(
            owner=owner, archived_at__isnull=True
        )


class InventoryItemForm(forms.ModelForm):
    condition = forms.ChoiceField(
        label="Zustand",
        choices=(("neu", "Neu"), ("gebraucht", "Gebraucht")),
    )
    quantity = forms.IntegerField(min_value=0, label="Bestand", widget=forms.NumberInput(attrs={"class": "compact-number"}))
    reserved_quantity = forms.IntegerField(min_value=0, label="Reserviert", widget=forms.NumberInput(attrs={"class": "compact-number"}))

    class Meta:
        model = InventoryItem
        exclude = (
            "owner", "legacy_id", "archived_at", "quantity", "reserved_quantity"
        )
        labels = {"part_number": "Teilenummer", "design_id": "Design-ID", "element_id": "Element-ID", "name": "Bezeichnung", "color": "Farbe", "category": "Kategorie", "subcategory": "Unterkategorie", "condition": "Zustand", "location": "Lagerort", "image_url": "Bild-URL", "source": "Quelle", "purchase_price": "Einkaufspreis", "unit_price": "Stückpreis", "notes": "Notizen"}
        widgets = {"purchase_price": forms.NumberInput(attrs={"class": "compact-number", "step": "0.01", "min": 0}), "unit_price": forms.NumberInput(attrs={"class": "compact-number", "step": "0.01", "min": 0}), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = WarehouseLocation.objects.filter(
            owner=owner, archived_at__isnull=True
        )
        if self.instance.pk:
            self.fields["quantity"].initial = self.instance.quantity
            self.fields["reserved_quantity"].initial = self.instance.reserved_quantity

    def clean(self):
        cleaned = super().clean()
        quantity = cleaned.get("quantity")
        reserved = cleaned.get("reserved_quantity")
        if quantity is not None and reserved is not None and reserved > quantity:
            self.add_error(
                "reserved_quantity", "Reservierung darf den Bestand nicht übersteigen."
            )
        return cleaned
