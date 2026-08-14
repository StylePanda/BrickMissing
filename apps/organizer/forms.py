from django import forms
from django.db import models

LABELS = {
    "collection": "Sammlung", "location": "Lagerort", "lego_set": "LEGO-Set",
    "inventory_item": "Bestandsteil", "user": "Benutzerkonto", "role": "Rolle",
    "name": "Name", "description": "Beschreibung", "is_shared": "Freigegeben",
    "project_code": "Projektcode", "status": "Status", "version": "Version",
    "progress": "Fortschritt in Prozent", "instruction_url": "Anleitungs-URL",
    "image_url": "Bild-URL", "notes": "Notizen", "entity_type": "Eintragstyp",
    "reference": "Referenz", "priority": "Priorität", "target_price": "Zielpreis",
    "entity_id": "Eintragskennung", "borrower": "Ausgeliehen an",
    "loaned_at": "Ausgeliehen am", "due_at": "Fällig am", "returned_at": "Zurückgegeben am",
    "title": "Titel", "content": "Inhalt", "width_mm": "Breite (mm)",
    "height_mm": "Höhe (mm)", "orientation": "Ausrichtung",
    "configuration": "Konfiguration", "is_default": "Standardvorlage",
    "figure_number": "Figurennummer", "quantity": "Benötigte Menge",
    "owned_quantity": "Vorhandene Menge", "part_number": "Teilenummer",
    "element_id": "Element-ID", "color_id": "Farb-ID", "color_name": "Farbe",
    "color": "Farbe", "is_spare": "Ersatzteil", "required_quantity": "Benötigte Menge",
    "allocated_quantity": "Zugeordnete Menge",
}

CHOICES = {
    "role": (("viewer", "Lesen"), ("editor", "Bearbeiten"), ("owner", "Verwalten")),
    "priority": (("low", "Niedrig"), ("normal", "Normal"), ("high", "Hoch"), ("urgent", "Dringend")),
    "orientation": (("landscape", "Querformat"), ("portrait", "Hochformat")),
    "entity_type": (("set", "LEGO-Set"), ("part", "Teil"), ("minifigure", "Minifigur"), ("moc", "MOC")),
}


def build_model_form(model, fields):
    widgets = {}
    for name in fields:
        field = model._meta.get_field(name)
        if isinstance(field, (models.IntegerField, models.DecimalField)):
            widgets[name] = forms.NumberInput(attrs={"class": "compact-number"})
        elif isinstance(field, models.TextField):
            widgets[name] = forms.Textarea(attrs={"rows": 4})
        elif isinstance(field, models.DateTimeField):
            widgets[name] = forms.DateTimeInput(attrs={"type": "datetime-local"})
    form_class = forms.modelform_factory(
        model,
        fields=fields,
        labels={name: LABELS.get(name, name.replace("_", " ").capitalize()) for name in fields},
        widgets=widgets,
    )

    class OrganizerForm(form_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for name, choices in CHOICES.items():
                if name in self.fields:
                    current = self.initial.get(name) or getattr(self.instance, name, "")
                    available = list(choices)
                    if current and current not in {value for value, _ in available}:
                        available.append((current, f"Bestehender Wert: {current}"))
                    self.fields[name].widget = forms.Select(choices=available)

    return OrganizerForm
