from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.forms import modelform_factory
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.totp import qr_svg
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet
from apps.core.services import record_recent
from apps.inventory.models import InventoryItem, WarehouseLocation

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
)

AREAS = {
    "collections": (Collection, "Sammlungen", ("name", "description", "is_shared")),
    "mocs": (
        Moc,
        "MOCs",
        (
            "collection",
            "location",
            "name",
            "project_code",
            "description",
            "status",
            "version",
            "progress",
            "instruction_url",
            "image_url",
            "notes",
        ),
    ),
    "wishlist": (
        WishlistItem,
        "Wunschliste",
        ("collection", "entity_type", "reference", "name", "priority", "target_price", "notes"),
    ),
    "loans": (
        Loan,
        "Ausleihen",
        ("entity_type", "entity_id", "borrower", "loaned_at", "due_at", "returned_at", "notes"),
    ),
    "notes": (PersonalNote, "Notizen", ("title", "content")),
    "labels": (
        LabelTemplate,
        "Etikettenvorlagen",
        ("name", "width_mm", "height_mm", "orientation", "configuration", "is_default"),
    ),
    "minifigures": (
        SetMinifigure,
        "Minifiguren",
        ("lego_set", "figure_number", "name", "quantity", "owned_quantity", "image_url", "notes"),
    ),
}


def _collection_display(record):
    return record.name, record.description


def _moc_display(record):
    return record.name, record.project_code or record.status


def _wishlist_display(record):
    return record.name, record.reference


def _loan_display(record):
    return record.borrower, f"{record.entity_type}: {record.entity_id}"


def _note_display(record):
    return record.title, "Persönliche Notiz"


def _label_display(record):
    return record.name, f"{record.width_mm} × {record.height_mm} mm"


def _minifigure_display(record):
    return record.name, f"{record.figure_number} · Set {record.lego_set.set_number}"


AREA_DISPLAY = {
    "collections": _collection_display,
    "mocs": _moc_display,
    "wishlist": _wishlist_display,
    "loans": _loan_display,
    "notes": _note_display,
    "labels": _label_display,
    "minifigures": _minifigure_display,
}


def _area(name):
    try:
        return AREAS[name]
    except KeyError:
        raise Http404 from None


@login_required
def area_list(request, area):
    model, title, _ = _area(area)
    records = model.objects.filter(owner=request.user).order_by("-pk")[:500]
    display = AREA_DISPLAY[area]
    rows = []
    for record in records:
        label, secondary = display(record)
        rows.append({"record": record, "label": label, "secondary": secondary})
    return render(request, "organizer/list.html", {"rows": rows, "title": title, "area": area})


@login_required
def area_edit(request, area, pk=None):
    model, title, fields = _area(area)
    instance = get_object_or_404(model, pk=pk, owner=request.user) if pk else None
    form_class = modelform_factory(model, fields=fields)
    form = form_class(request.POST or None, instance=instance)
    for name in ("collection",):
        if name in form.fields:
            form.fields[name].queryset = Collection.objects.filter(owner=request.user)
    if "location" in form.fields:
        form.fields["location"].queryset = WarehouseLocation.objects.filter(owner=request.user)
    if "lego_set" in form.fields:
        form.fields["lego_set"].queryset = LegoSet.objects.filter(owner=request.user)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.owner = request.user
        saved.full_clean()
        saved.save()
        AuditEvent.objects.create(
            actor=request.user,
            target_user=request.user,
            action=f"{area}.saved",
            entity_type=model._meta.model_name,
            entity_id=str(saved.pk),
            request_id=request.request_id,
        )
        return redirect("organizer:list", area=area)
    return render(
        request,
        "catalog/form.html",
        {"form": form, "title": f"{title}: {'Bearbeiten' if instance else 'Neu'}"},
    )


@login_required
@require_POST
def area_delete(request, area, pk):
    model, _, _ = _area(area)
    instance = get_object_or_404(model, pk=pk, owner=request.user)
    identifier = str(instance.pk)
    instance.delete()
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action=f"{area}.deleted",
        entity_type=model._meta.model_name,
        entity_id=identifier,
        request_id=request.request_id,
    )
    return redirect("organizer:list", area=area)


@login_required
def area_detail(request, area, pk):
    model, title, _ = _area(area)
    if area not in {"collections", "mocs", "minifigures"}:
        raise Http404
    instance = get_object_or_404(model, pk=pk, owner=request.user)
    record_recent(request.user, area, instance.pk, instance.name, request.path)
    return render(
        request, "organizer/detail.html", {"item": instance, "title": title, "area": area}
    )


@login_required
def label_preview(request, pk):
    template = get_object_or_404(LabelTemplate, pk=pk, owner=request.user)
    mode = request.GET.get("mode", "part")
    if mode == "set":
        items = LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True).order_by(
            "set_number"
        )
    elif mode == "minifigure":
        items = (
            SetMinifigure.objects.filter(owner=request.user)
            .select_related("lego_set")
            .order_by("lego_set__set_number", "figure_number")
        )
    else:
        mode = "part"
        items = InventoryItem.objects.filter(owner=request.user, archived_at__isnull=True).order_by(
            "name", "part_number"
        )
    selected = [value for value in request.GET.getlist("item") if value.isdigit()]
    if selected:
        items = items.filter(pk__in=selected)
    query = request.GET.get("q", "").strip()
    if query and mode == "part":
        items = items.filter(
            models.Q(part_number__icontains=query)
            | models.Q(element_id__icontains=query)
            | models.Q(name__icontains=query)
        )
    elif query and mode == "set":
        items = items.filter(
            models.Q(set_number__icontains=query) | models.Q(name__icontains=query)
        )
    elif query:
        items = items.filter(
            models.Q(figure_number__icontains=query) | models.Q(name__icontains=query)
        )
    configuration = template.configuration or {}
    rows = min(max(int(configuration.get("rows", 4)), 1), 20)
    columns = min(max(int(configuration.get("columns", 2)), 1), 10)
    capacity = rows * columns
    start = min(max(int(request.GET.get("start", 1) or 1), 1), capacity)
    orientation = (
        template.orientation if template.orientation in {"portrait", "landscape"} else "portrait"
    )

    def millimeters(name, default=0):
        try:
            value = min(max(float(configuration.get(name, default)), 0), 50)
            return f"{value:.2f}"
        except (TypeError, ValueError):
            return f"{float(default):.2f}"

    remaining = capacity - start + 1
    return render(
        request,
        "organizer/label_preview.html",
        {
            "label_template": template,
            "items": items[:remaining],
            "query": query,
            "mode": mode,
            "rows": rows,
            "columns": columns,
            "capacity": capacity,
            "start": start,
            "leading_slots": range(start - 1),
            "orientation": orientation,
            "margin_top": millimeters("margin_top"),
            "margin_right": millimeters("margin_right"),
            "margin_bottom": millimeters("margin_bottom"),
            "margin_left": millimeters("margin_left"),
        },
    )


@login_required
def label_print_css(request, pk):
    template = get_object_or_404(LabelTemplate, pk=pk, owner=request.user)
    configuration = template.configuration or {}

    def number(name, default, minimum, maximum):
        try:
            return min(max(float(configuration.get(name, default)), minimum), maximum)
        except (TypeError, ValueError):
            return float(default)

    rows = int(number("rows", 4, 1, 20))
    columns = int(number("columns", 2, 1, 10))
    orientation = (
        template.orientation if template.orientation in {"portrait", "landscape"} else "portrait"
    )
    margins = [
        number(name, 0, 0, 50)
        for name in ("margin_top", "margin_right", "margin_bottom", "margin_left")
    ]
    css = (
        f"@page{{size:A4 {orientation};margin:{margins[0]:.2f}mm {margins[1]:.2f}mm {margins[2]:.2f}mm {margins[3]:.2f}mm}}"
        f".label-sheet{{grid-template-columns:repeat({columns},{float(template.width_mm):.2f}mm);grid-template-rows:repeat({rows},{float(template.height_mm):.2f}mm)}}"
        f".print-label{{width:{float(template.width_mm):.2f}mm;height:{float(template.height_mm):.2f}mm}}"
    )
    return HttpResponse(css, content_type="text/css; charset=utf-8")


@login_required
def label_qr(request, pk, item_pk):
    get_object_or_404(LabelTemplate, pk=pk, owner=request.user)
    item = get_object_or_404(InventoryItem, pk=item_pk, owner=request.user)
    return HttpResponse(
        qr_svg(f"inventory:{item.pk}:{item.part_number}"),
        content_type="image/svg+xml",
    )


def _moc_parts_snapshot(moc):
    return list(
        moc.parts.order_by("pk").values(
            "part_number",
            "name",
            "color",
            "required_quantity",
            "allocated_quantity",
            "notes",
            "inventory_item_id",
        )
    )


@login_required
def moc_version_edit(request, moc_pk, pk=None):
    moc = get_object_or_404(Moc, pk=moc_pk, owner=request.user)
    version = get_object_or_404(MocVersion, pk=pk, moc=moc) if pk else None
    form_class = modelform_factory(MocVersion, fields=("version", "name", "description", "notes"))
    form = form_class(request.POST or None, instance=version)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.moc = moc
        if not version:
            saved.parts_snapshot = _moc_parts_snapshot(moc)
        saved.full_clean()
        saved.save()
        AuditEvent.objects.create(
            actor=request.user,
            target_user=request.user,
            action="moc.version_saved",
            entity_type="moc_version",
            entity_id=str(saved.pk),
            request_id=request.request_id,
        )
        return redirect("organizer:detail", area="mocs", pk=moc.pk)
    return render(
        request,
        "catalog/form.html",
        {"form": form, "title": "MOC-Version bearbeiten" if version else "MOC-Version erstellen"},
    )


@login_required
@require_POST
def moc_version_delete(request, moc_pk, pk):
    moc = get_object_or_404(Moc, pk=moc_pk, owner=request.user)
    version = get_object_or_404(MocVersion, pk=pk, moc=moc)
    identifier = str(version.pk)
    version.delete()
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="moc.version_deleted",
        entity_type="moc_version",
        entity_id=identifier,
        request_id=request.request_id,
    )
    return redirect("organizer:detail", area="mocs", pk=moc.pk)


@login_required
@require_POST
@transaction.atomic
def moc_version_activate(request, moc_pk, pk):
    moc = get_object_or_404(Moc.objects.select_for_update(), pk=moc_pk, owner=request.user)
    version = get_object_or_404(MocVersion, pk=pk, moc=moc)
    replacements = []
    for raw in version.parts_snapshot:
        inventory_id = raw.get("inventory_item_id")
        if inventory_id and not request.user.inventoryitem_set.filter(pk=inventory_id).exists():
            inventory_id = None
        replacements.append(
            MocPart(
                moc=moc,
                inventory_item_id=inventory_id,
                part_number=str(raw.get("part_number", ""))[:100],
                name=str(raw.get("name", ""))[:255],
                color=str(raw.get("color", ""))[:150],
                required_quantity=max(int(raw.get("required_quantity", 1)), 0),
                allocated_quantity=max(int(raw.get("allocated_quantity", 0)), 0),
                notes=str(raw.get("notes", "")),
            )
        )
    moc.parts.all().delete()
    MocPart.objects.bulk_create(replacements)
    moc.version = version.version
    moc.save(update_fields=["version", "updated_at"])
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="moc.version_activated",
        entity_type="moc_version",
        entity_id=str(version.pk),
        request_id=request.request_id,
    )
    return redirect("organizer:detail", area="mocs", pk=moc.pk)


@login_required
def child_edit(request, area, parent_pk, pk=None):
    if area == "mocs":
        parent = get_object_or_404(Moc, pk=parent_pk, owner=request.user)
        model, relation, fields = (
            MocPart,
            "moc",
            (
                "inventory_item",
                "part_number",
                "name",
                "color",
                "required_quantity",
                "allocated_quantity",
                "notes",
            ),
        )
    elif area == "minifigures":
        parent = get_object_or_404(SetMinifigure, pk=parent_pk, owner=request.user)
        model, relation, fields = (
            MinifigurePart,
            "minifigure",
            (
                "part_number",
                "element_id",
                "name",
                "color_id",
                "color_name",
                "quantity",
                "owned_quantity",
                "is_spare",
                "image_url",
            ),
        )
    elif area == "collections":
        parent = get_object_or_404(Collection, pk=parent_pk, owner=request.user)
        model, relation, fields = CollectionMember, "collection", ("user", "role")
    else:
        raise Http404
    instance = get_object_or_404(model, pk=pk, **{relation: parent}) if pk else None
    form_class = modelform_factory(model, fields=fields)
    form = form_class(request.POST or None, instance=instance)
    if "inventory_item" in form.fields:
        form.fields["inventory_item"].queryset = form.fields["inventory_item"].queryset.filter(
            owner=request.user
        )
    if "user" in form.fields:
        form.fields["user"].queryset = (
            form.fields["user"].queryset.filter(is_active=True).order_by("username")
        )
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        setattr(saved, relation, parent)
        saved.full_clean()
        saved.save()
        AuditEvent.objects.create(
            actor=request.user,
            target_user=request.user,
            action=f"{area}.child_saved",
            entity_type=model._meta.model_name,
            entity_id=str(saved.pk),
            request_id=request.request_id,
        )
        return redirect("organizer:detail", area=area, pk=parent.pk)
    return render(
        request,
        "catalog/form.html",
        {"form": form, "title": "Bestandteil bearbeiten" if instance else "Bestandteil hinzufügen"},
    )
