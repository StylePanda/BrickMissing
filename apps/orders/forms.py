from django import forms

from .models import Order, OrderItem


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        exclude = ("owner", "legacy_id", "deleted_at")


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        exclude = ("order", "legacy_id")

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inventory_item"].queryset = self.fields["inventory_item"].queryset.filter(owner=owner)
        self.fields["target_set"].queryset = self.fields["target_set"].queryset.filter(owner=owner)
        self.fields["target_location"].queryset = self.fields["target_location"].queryset.filter(owner=owner)

