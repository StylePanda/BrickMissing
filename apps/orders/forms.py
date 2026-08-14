from django import forms

from .models import Order, OrderItem


class OrderForm(forms.ModelForm):
    status = forms.ChoiceField(label="Status", choices=(("draft", "Entwurf"), ("ordered", "Bestellt"), ("shipped", "Versendet"), ("received", "Erhalten"), ("cancelled", "Storniert")))
    payment_status = forms.ChoiceField(label="Zahlungsstatus", required=False, choices=(("", "– Bitte wählen –"), ("open", "Offen"), ("paid", "Bezahlt"), ("refunded", "Erstattet")))
    shipping_status = forms.ChoiceField(label="Versandstatus", required=False, choices=(("", "– Bitte wählen –"), ("pending", "Ausstehend"), ("shipped", "Versendet"), ("delivered", "Zugestellt")))
    currency = forms.ChoiceField(label="Währung", choices=(("EUR", "EUR – Euro"), ("USD", "USD – US-Dollar"), ("GBP", "GBP – Britisches Pfund"), ("CHF", "CHF – Schweizer Franken")))

    class Meta:
        model = Order
        exclude = ("owner", "legacy_id", "deleted_at")
        labels = {"supplier": "Lieferant", "order_number": "Bestellnummer", "order_date": "Bestelldatum", "expected_delivery": "Erwartete Lieferung", "delivery_date": "Lieferdatum", "goods_total": "Warenwert", "shipping_cost": "Versandkosten", "total": "Gesamt", "tracking_number": "Sendungsnummer", "tracking_url": "Tracking-URL", "notes": "Notizen"}
        widgets = {"order_date": forms.DateInput(attrs={"type": "date"}), "expected_delivery": forms.DateInput(attrs={"type": "date"}), "delivery_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        exclude = ("order", "legacy_id")

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inventory_item"].queryset = self.fields["inventory_item"].queryset.filter(owner=owner)
        self.fields["target_set"].queryset = self.fields["target_set"].queryset.filter(owner=owner)
        self.fields["target_location"].queryset = self.fields["target_location"].queryset.filter(owner=owner)
