from django import forms

from .models import InventoryItem, WarehouseLocation


class WarehouseLocationForm(forms.ModelForm):
    class Meta:
        model = WarehouseLocation
        exclude = ("owner", "legacy_id", "archived_at")

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = WarehouseLocation.objects.filter(
            owner=owner, archived_at__isnull=True
        )


class InventoryItemForm(forms.ModelForm):
    quantity = forms.IntegerField(min_value=0)
    reserved_quantity = forms.IntegerField(min_value=0)

    class Meta:
        model = InventoryItem
        exclude = (
            "owner", "legacy_id", "archived_at", "quantity", "reserved_quantity"
        )

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
