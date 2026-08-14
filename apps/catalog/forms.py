from django import forms

from .models import LegoSet, Part, SetCopy, SetInventoryItem


class LegoSetForm(forms.ModelForm):
    class Meta:
        model = LegoSet
        exclude = ("owner", "legacy_id", "deleted_at")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("total_parts", "minifigures", "purchase_price", "current_value"):
            self.fields[field].required = False


class PartForm(forms.ModelForm):
    class Meta:
        model = Part
        exclude = ("owner", "legacy_id", "deleted_at")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lego_set"].queryset = LegoSet.objects.filter(
            owner=owner, deleted_at__isnull=True
        )


class SetCopyForm(forms.ModelForm):
    class Meta:
        model = SetCopy
        exclude = ("owner", "lego_set", "legacy_id", "deleted_at")


class SetInventoryItemForm(forms.ModelForm):
    class Meta:
        model = SetInventoryItem
        exclude = ("lego_set", "legacy_id")
