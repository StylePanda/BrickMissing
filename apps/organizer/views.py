import uuid
from collections import OrderedDict
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.totp import decrypt_secret, qr_svg
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet
from apps.catalog.services import set_completeness
from apps.core.services import record_recent
from apps.integrations.services import RebrickableError, rebrickable_set_metadata
from apps.inventory.models import InventoryItem, WarehouseLocation

from .forms import WishlistItemForm, build_model_form
from .label_configuration import label_print_layout, normalize_start
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
        (
            "reference",
            "name",
            "quantity",
            "status",
            "priority",
            "target_price",
            "notes",
            "image_url",
            "theme",
            "year",
            "piece_count",
        ),
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
    suffix = " · Standard" if record.is_default else ""
    return record.name, f"{record.width_mm} × {record.height_mm} mm{suffix}"


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


MINIFIGURE_SORTS = {
    "set_number": "Setnummer aufsteigend",
    "-set_number": "Setnummer absteigend",
    "name": "Minifigurenname A–Z",
    "-name": "Minifigurenname Z–A",
    "figure_number": "Minifigur-ID aufsteigend",
    "-figure_number": "Minifigur-ID absteigend",
    "completeness": "Vollständigkeit",
    "-missing": "Fehlteile absteigend",
    "missing": "Fehlteile aufsteigend",
    "-required": "Benötigte Teile absteigend",
    "-owned": "Vorhandene Teile absteigend",
}

WISHLIST_STATUS_CHOICES = (
    ("wish", "Wunsch"),
    ("planned", "Geplant"),
    ("purchased", "Gekauft"),
)
WISHLIST_PRIORITY_CHOICES = (
    ("low", "Niedrig"),
    ("normal", "Normal"),
    ("high", "Hoch"),
    ("urgent", "Dringend"),
)
WISHLIST_SORTS = {
    "newest": ("-created_at", "-pk"),
    "oldest": ("created_at", "pk"),
    "name": ("name", "pk"),
    "-name": ("-name", "-pk"),
    "reference": ("reference", "pk"),
    "-reference": ("-reference", "-pk"),
    "priority_high": ("priority_order", "-created_at", "-pk"),
    "priority_low": ("priority_order", "-created_at", "-pk"),
    "price": ("target_price_empty", "target_price", "-created_at", "-pk"),
    "-price": ("target_price_empty", "-target_price", "-created_at", "-pk"),
    "pieces": ("piece_count_empty", "piece_count", "-created_at", "-pk"),
    "-pieces": ("piece_count_empty", "-piece_count", "-created_at", "-pk"),
    "year": ("year_empty", "year", "-created_at", "-pk"),
    "-year": ("year_empty", "-year", "-created_at", "-pk"),
}


def _minifigure_record(figure):
    parts = list(figure.parts.all())
    required = sum(part.quantity for part in parts if not part.is_spare)
    owned = sum(min(part.owned_quantity, part.quantity) for part in parts if not part.is_spare)
    missing = max(required - owned, 0)
    if not parts or not required:
        status, status_label = "unknown", "Unbekannt"
    elif missing == 0:
        status, status_label = "complete", "Vollständig"
    elif owned == 0:
        status, status_label = "missing", "Fehlend"
    else:
        status, status_label = "partial", "Teilweise"
    return {
        "figure": figure,
        "parts": parts,
        "required": required,
        "owned": owned,
        "missing": missing,
        "percent": round(owned * 100 / required) if required else 0,
        "status": status,
        "status_label": status_label,
    }


@login_required
def minifigure_list(request):
    figures = (
        SetMinifigure.objects.filter(owner=request.user, lego_set__deleted_at__isnull=True)
        .select_related("lego_set")
    )
    query = request.GET.get("q", "").strip()
    if query:
        figures = figures.filter(
            models.Q(name__icontains=query)
            | models.Q(figure_number__icontains=query)
            | models.Q(lego_set__set_number__icontains=query)
            | models.Q(lego_set__name__icontains=query)
        )
    set_id = request.GET.get("set", "")
    if set_id:
        figures = figures.filter(lego_set_id=set_id)
    sort = request.GET.get("sort", "set_number")
    if sort not in MINIFIGURE_SORTS:
        sort = "set_number"
    integer_field = models.IntegerField()
    figures = figures.annotate(
        required_total=models.functions.Coalesce(
            models.Sum(
                "parts__quantity",
                filter=models.Q(parts__is_spare=False),
                output_field=integer_field,
            ),
            models.Value(0),
            output_field=integer_field,
        ),
        owned_total=models.functions.Coalesce(
            models.Sum(
                models.functions.Least(
                    models.F("parts__owned_quantity"), models.F("parts__quantity")
                ),
                filter=models.Q(parts__is_spare=False),
                output_field=integer_field,
            ),
            models.Value(0),
            output_field=integer_field,
        ),
    ).annotate(
        missing_total=models.F("required_total") - models.F("owned_total"),
        completeness_order=models.Case(
            models.When(required_total=0, then=models.Value(3)),
            models.When(missing_total=0, then=models.Value(0)),
            models.When(owned_total=0, then=models.Value(2)),
            default=models.Value(1),
            output_field=integer_field,
        ),
    )
    ordering = {
        "set_number": ("lego_set__set_number", "pk"),
        "-set_number": ("-lego_set__set_number", "pk"),
        "name": ("name", "pk"),
        "-name": ("-name", "pk"),
        "figure_number": ("figure_number", "pk"),
        "-figure_number": ("-figure_number", "pk"),
        "completeness": ("completeness_order", "name", "pk"),
        "-missing": ("-missing_total", "name", "pk"),
        "missing": ("missing_total", "name", "pk"),
        "-required": ("-required_total", "name", "pk"),
        "-owned": ("-owned_total", "name", "pk"),
    }
    page_obj = Paginator(
        figures.order_by(*ordering[sort]).prefetch_related("parts"), 30
    ).get_page(request.GET.get("page"))
    records = [_minifigure_record(figure) for figure in page_obj.object_list]
    groups = OrderedDict()
    for record in records:
        lego_set = record["figure"].lego_set
        group = groups.setdefault(lego_set.pk, {"lego_set": lego_set, "figures": []})
        group["figures"].append(record)
    available_sets = LegoSet.objects.filter(
        owner=request.user, deleted_at__isnull=True, minifigures_inventory__isnull=False
    ).distinct().order_by("set_number")
    return render(
        request,
        "organizer/minifigure_list.html",
        {
            "groups": list(groups.values()),
            "figure_count": page_obj.paginator.count,
            "page_obj": page_obj,
            "query": query,
            "set_id": set_id,
            "available_sets": available_sets,
            "sort": sort,
            "sorts": MINIFIGURE_SORTS,
        },
    )


def _area(name):
    try:
        return AREAS[name]
    except KeyError:
        raise Http404 from None


@login_required
def area_list(request, area):
    model, title, _ = _area(area)
    records = model.objects.filter(owner=request.user)
    if area == "wishlist":
        records = records.filter(entity_type="set")
        query = request.GET.get("q", "").strip()[:200]
        status = request.GET.get("status", "")
        priority = request.GET.get("priority", "")
        theme = request.GET.get("theme", "").strip()
        if query:
            records = records.filter(
                models.Q(reference__icontains=query)
                | models.Q(name__icontains=query)
                | models.Q(theme__icontains=query)
            )
        valid_statuses = {value for value, _ in WISHLIST_STATUS_CHOICES}
        valid_priorities = {value for value, _ in WISHLIST_PRIORITY_CHOICES}
        if status not in valid_statuses:
            status = ""
        if priority not in valid_priorities:
            priority = ""
        if status:
            records = records.filter(status=status)
        if priority:
            records = records.filter(priority=priority)
        if theme:
            records = records.filter(theme=theme)
        themes = list(
            WishlistItem.objects.filter(owner=request.user, entity_type="set")
            .exclude(theme="")
            .values_list("theme", flat=True)
            .distinct()
            .order_by("theme")
        )
        sort = request.GET.get("sort", "newest")
        if sort not in WISHLIST_SORTS:
            sort = "newest"
        priority_order = models.Case(
            models.When(priority="urgent", then=models.Value(0)),
            models.When(priority="high", then=models.Value(1)),
            models.When(priority="normal", then=models.Value(2)),
            default=models.Value(3),
            output_field=models.IntegerField(),
        )
        if sort == "priority_low":
            priority_order = models.Case(
                models.When(priority="low", then=models.Value(0)),
                models.When(priority="normal", then=models.Value(1)),
                models.When(priority="high", then=models.Value(2)),
                default=models.Value(3),
                output_field=models.IntegerField(),
            )
        records = records.annotate(
            priority_order=priority_order,
            target_price_empty=models.Case(
                models.When(target_price__gt=0, then=models.Value(0)),
                default=models.Value(1), output_field=models.IntegerField(),
            ),
            piece_count_empty=models.Case(
                models.When(piece_count__isnull=False, piece_count__gt=0, then=models.Value(0)),
                default=models.Value(1), output_field=models.IntegerField(),
            ),
            year_empty=models.Case(
                models.When(year__isnull=False, then=models.Value(0)),
                default=models.Value(1), output_field=models.IntegerField(),
            ),
        ).order_by(*WISHLIST_SORTS[sort])
        page_obj = Paginator(records, 50).get_page(request.GET.get("page"))
        has_filters = any((query, status, priority, theme)) or sort != "newest"
        return render(
            request,
            "organizer/wishlist_list.html",
            {
                "title": title,
                "area": area,
                "page_obj": page_obj,
                "query": query,
                "status": status,
                "priority": priority,
                "theme": theme,
                "themes": themes,
                "statuses": WISHLIST_STATUS_CHOICES,
                "priorities": WISHLIST_PRIORITY_CHOICES,
                "sort": sort,
                "has_filters": has_filters,
                "result_count": page_obj.paginator.count,
            },
        )
    records = (
        records.order_by("-is_default", "name", "pk")
        if area == "labels"
        else records.order_by("-pk")
    )
    page_obj = Paginator(records, 50).get_page(request.GET.get("page"))
    display = AREA_DISPLAY[area]
    rows = []
    for record in page_obj.object_list:
        label, secondary = display(record)
        rows.append({"record": record, "label": label, "secondary": secondary})
    return render(
        request,
        "organizer/list.html",
        {"rows": rows, "title": title, "area": area, "page_obj": page_obj},
    )


@login_required
def area_edit(request, area, pk=None):
    model, title, fields = _area(area)
    instance = get_object_or_404(model, pk=pk, owner=request.user) if pk else None
    if area == "wishlist":
        form = WishlistItemForm(request.POST or None, instance=instance, owner=request.user)
    else:
        form_class = build_model_form(model, fields)
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
        if area == "wishlist" and not instance:
            saved.entity_type = "set"
        if area == "wishlist":
            reference_changed = not instance or saved.reference != instance.reference
            if reference_changed:
                if not request.user.rebrickable_api_key_encrypted:
                    form.add_error(None, "Bitte hinterlege zuerst deinen Rebrickable API-Key in den Kontoeinstellungen.")
                    return render(request, "organizer/form.html", {"form": form, "title": f"{title}: {'Bearbeiten' if instance else 'Neu'}", "area": area})
                try:
                    metadata = rebrickable_set_metadata(
                        saved.reference, decrypt_secret(request.user.rebrickable_api_key_encrypted)
                    )
                except RebrickableError as exc:
                    form.add_error(None, str(exc))
                    return render(request, "organizer/form.html", {"form": form, "title": f"{title}: {'Bearbeiten' if instance else 'Neu'}", "area": area})
                saved.reference = metadata["set_number"]
                saved.name = metadata["name"]
                saved.image_url = metadata["image_url"]
                saved.theme = metadata["theme"]
                saved.year = metadata["year"]
                saved.piece_count = metadata["total_parts"]
                duplicate = WishlistItem.objects.filter(
                    owner=request.user, entity_type="set", reference=saved.reference
                )
                if instance:
                    duplicate = duplicate.exclude(pk=instance.pk)
                if duplicate.exists():
                    form.add_error(None, "Dieses Set ist bereits in deiner Wunschliste vorhanden.")
                    return render(request, "organizer/form.html", {"form": form, "title": f"{title}: {'Bearbeiten' if instance else 'Neu'}", "area": area})
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
        "organizer/form.html",
        {"form": form, "title": f"{title}: {'Bearbeiten' if instance else 'Neu'}", "area": area},
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
@require_GET
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
    layout = label_print_layout(template)
    configuration = layout.configuration
    rows = configuration.rows
    columns = configuration.columns
    capacity = rows * columns
    start = normalize_start(request.GET.get("start"), capacity)
    orientation = layout.orientation
    orientation_label = "Querformat" if orientation == "landscape" else "Hochformat"

    remaining = capacity - start + 1
    return render(
        request,
        "organizer/label_preview.html",
        {
            "label_template": template,
            "label_configuration": configuration,
            "label_width": f"{layout.width_mm:.2f}",
            "label_height": f"{layout.height_mm:.2f}",
            "items": items[:remaining],
            "query": query,
            "mode": mode,
            "rows": rows,
            "columns": columns,
            "capacity": capacity,
            "start": start,
            "leading_slots": range(start - 1),
            "orientation": orientation,
            "orientation_label": orientation_label,
            "margin_top": f"{configuration.margin_top:.2f}",
            "margin_right": f"{configuration.margin_right:.2f}",
            "margin_bottom": f"{configuration.margin_bottom:.2f}",
            "margin_left": f"{configuration.margin_left:.2f}",
        },
    )


@login_required
@require_GET
def label_print_css(request, pk):
    template = get_object_or_404(LabelTemplate, pk=pk, owner=request.user)
    layout = label_print_layout(template)
    configuration = layout.configuration
    margins = (
        configuration.margin_top,
        configuration.margin_right,
        configuration.margin_bottom,
        configuration.margin_left,
    )
    css = (
        f"@page{{size:A4 {layout.orientation};margin:{margins[0]:.2f}mm "
        f"{margins[1]:.2f}mm {margins[2]:.2f}mm {margins[3]:.2f}mm}}"
        f".label-sheet{{grid-template-columns:repeat({configuration.columns},"
        f"{layout.width_mm:.2f}mm);grid-template-rows:repeat({configuration.rows},"
        f"{layout.height_mm:.2f}mm)}}"
        f".print-label{{width:{layout.width_mm:.2f}mm;height:{layout.height_mm:.2f}mm}}"
    )
    return HttpResponse(css, content_type="text/css; charset=utf-8")


@login_required
@require_GET
def label_qr(request, pk, item_pk):
    get_object_or_404(LabelTemplate, pk=pk, owner=request.user)
    item = get_object_or_404(InventoryItem, pk=item_pk, owner=request.user)
    return HttpResponse(
        qr_svg(f"{_public_origin(request)}{reverse('inventory:edit', args=[item.pk])}", border=4),
        content_type="image/svg+xml",
    )


LABEL_TYPES = {
    "full": "Vollständiges Set-Etikett",
    "collected": "Setnummern gesammelt · jede einmal",
    "per_minifigure": "Nur Setnummer · einmal pro Minifigur",
    "colors": "Kontrollsackerl · frei beschriftbar",
    "minifigure": "Minifiguren-Etikett",
    "missing_parts": "Fehlteile-/Setteil-Etikett",
}
QR_TARGETS = {
    "set": "Setseite",
    "inventory": "Inventarliste",
    "missing": "Fehlteile",
    "edit": "Bearbeiten",
    "bricklink": "BrickLink",
    "rebrickable": "Rebrickable",
}


def _public_origin(request):
    configured = getattr(settings, "PUBLIC_URL", "").strip().rstrip("/")
    return configured or request.build_absolute_uri("/").rstrip("/")


def _set_number_slug(lego_set):
    return lego_set.set_number if "-" in lego_set.set_number else f"{lego_set.set_number}-1"


def _qr_target(request, lego_set, target):
    if target == "bricklink":
        return f"https://www.bricklink.com/v2/catalog/catalogitem.page?S={_set_number_slug(lego_set)}"
    if target == "rebrickable":
        return f"https://rebrickable.com/sets/{_set_number_slug(lego_set)}/"
    route = reverse("catalog:set_detail", args=[lego_set.pk])
    if target == "inventory":
        route += "#set-inventory"
    elif target == "missing":
        route = f'{reverse("catalog:missing_parts")}?set={lego_set.pk}'
    elif target == "edit":
        route = reverse("catalog:set_edit", args=[lego_set.pk])
    return f"{_public_origin(request)}{route}"


def _label_data(request, lego_set, qr_target):
    completeness = set_completeness(lego_set)
    minifigure_count = sum(figure.quantity for figure in lego_set.minifigures_inventory.all())
    return {
        "lego_set": lego_set,
        "completeness": completeness,
        "minifigure_count": minifigure_count,
        "qr_label": QR_TARGETS[qr_target],
        "qr_url": reverse("organizer:label_set_qr", args=[lego_set.pk])
        + f"?target={qr_target}",
        "target_url": _qr_target(request, lego_set, qr_target),
    }


def _collected_number_cells(numbers):
    """Return deterministic cut-grid metadata for a collected-number label."""
    count = len(numbers)
    cells = []
    for index, number in enumerate(numbers):
        row_start = (index // 4) * 4
        row_end = min(row_start + 4, count)
        cells.append(
            {
                "number": number,
                "row": index // 4,
                "column": index - row_start,
                "has_right_cut": index < row_end - 1,
                "has_bottom_cut": index + 4 < count,
            }
        )
    return cells


def _minifigure_label_data(request, figure):
    required = figure.quantity
    owned = figure.owned_quantity
    status = "complete" if owned >= required else "partial" if owned else "missing"
    return {
        "figure": figure,
        "status": status,
        "qr_url": reverse("organizer:label_minifigure_qr", args=[figure.pk]),
    }


def _missing_part_label_data(request, part, lego_set, *, minifigure=None):
    if minifigure is not None:
        qr_url = reverse("organizer:label_minifigure_qr", args=[minifigure.pk])
        target_url = f"{_public_origin(request)}{reverse('organizer:detail', args=['minifigures', minifigure.pk])}"
    else:
        qr_url = reverse("organizer:label_set_qr", args=[lego_set.pk]) + "?target=inventory"
        route = reverse("catalog:set_detail", args=[lego_set.pk])
        target_url = f"{_public_origin(request)}{route}?q={quote(part.part_number)}#set-inventory"
    return {
        "part": part,
        "lego_set": lego_set,
        "minifigure": minifigure,
        "color": getattr(part, "color_name", "") or getattr(part, "color", ""),
        "required": getattr(part, "required_quantity", None) or part.quantity,
        "owned": part.owned_quantity,
        "missing": part.missing_quantity,
        "status": "missing" if part.owned_quantity == 0 else "partial",
        "qr_url": qr_url,
        "target_url": target_url,
    }


@login_required
@require_http_methods(["GET", "POST"])
def label_studio(request):
    params = request.POST if request.method == "POST" else request.GET
    own_sets = (
        LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True)
        .prefetch_related("inventory_items", "minifigures_inventory__parts")
        .order_by("set_number")
    )
    query = params.get("q", "").strip()
    visible_sets = own_sets
    if query:
        visible_sets = visible_sets.filter(
            models.Q(set_number__icontains=query) | models.Q(name__icontains=query)
        )
    visible_sets = list(visible_sets)
    label_type = params.get("type", "full")
    if label_type not in LABEL_TYPES:
        label_type = "full"
    qr_target = params.get("qr_target", "set")
    if qr_target not in QR_TARGETS:
        qr_target = "set"
    capacity = 189 if label_type == "per_minifigure" else 8
    columns = 7 if label_type == "per_minifigure" else 2
    rows = 27 if label_type == "per_minifigure" else 4
    try:
        start = min(max(int(params.get("start", 1)), 1), capacity)
    except (TypeError, ValueError):
        start = 1
    selected_ids = []
    for value in params.getlist("item"):
        try:
            selected_ids.append(str(uuid.UUID(value)))
        except (AttributeError, TypeError, ValueError):
            continue
    if "selection" not in params:
        selected_sets = list(own_sets)
        selected_ids = [str(lego_set.pk) for lego_set in selected_sets]
    else:
        selected_sets = list(own_sets.filter(pk__in=selected_ids))
        selected_ids = [str(lego_set.pk) for lego_set in selected_sets]
    visible_ids = {str(lego_set.pk) for lego_set in visible_sets}
    hidden_selected_ids = [value for value in selected_ids if value not in visible_ids]
    checked_text = params.get("checked_text", "DURCHSUCHT").strip()[:40] or "DURCHSUCHT"
    try:
        checked_count = min(max(int(params.get("checked_count", 8)), 1), 100)
    except (TypeError, ValueError):
        checked_count = 8
    labels = []
    if label_type == "full":
        labels = [_label_data(request, lego_set, qr_target) for lego_set in selected_sets]
    elif label_type == "collected":
        numbers = sorted({lego_set.set_number for lego_set in selected_sets}, key=str.casefold)
        labels = []
        for offset in range(0, len(numbers), 20):
            chunk = numbers[offset : offset + 20]
            labels.append({"numbers": chunk, "number_cells": _collected_number_cells(chunk)})
    elif label_type == "per_minifigure":
        for lego_set in selected_sets:
            data = _label_data(request, lego_set, qr_target)
            labels.extend([data] * data["minifigure_count"])
    elif label_type == "minifigure":
        for lego_set in selected_sets:
            labels.extend(
                _minifigure_label_data(request, figure)
                for figure in lego_set.minifigures_inventory.all()
            )
    elif label_type == "missing_parts":
        part_query = params.get("part_query", "").strip().casefold()
        missing_status = params.get("missing_status", "all")
        missing_color = params.get("missing_color", "").strip().casefold()
        for lego_set in selected_sets:
            for part in lego_set.inventory_items.all():
                if part.is_spare or part.missing_quantity <= 0:
                    continue
                if part_query and part_query not in " ".join(
                    (part.part_number, part.element_id, part.name, part.color_name)
                ).casefold():
                    continue
                if missing_color and part.color_name.casefold() != missing_color:
                    continue
                status = "missing" if part.owned_quantity == 0 else "partial"
                if missing_status != "all" and status != missing_status:
                    continue
                labels.append(_missing_part_label_data(request, part, lego_set))
            for figure in lego_set.minifigures_inventory.all():
                for part in figure.parts.all():
                    if part.is_spare or part.missing_quantity <= 0:
                        continue
                    if part_query and part_query not in " ".join(
                        (part.part_number, part.element_id, part.name, part.color_name)
                    ).casefold():
                        continue
                    if missing_color and part.color_name.casefold() != missing_color:
                        continue
                    status = "missing" if part.owned_quantity == 0 else "partial"
                    if missing_status != "all" and status != missing_status:
                        continue
                    labels.append(_missing_part_label_data(request, part, lego_set, minifigure=figure))
    else:
        labels = [{"text": checked_text} for _ in range(checked_count)]
    slots = [None] * (start - 1) + labels if labels else []
    slots += [None] * ((-len(slots)) % capacity)
    label_pages = [slots[offset : offset + capacity] for offset in range(0, len(slots), capacity)]
    context = {
            "sets": visible_sets,
            "selected_ids": set(selected_ids),
            "hidden_selected_ids": hidden_selected_ids,
            "query": query,
            "label_type": label_type,
            "label_types": LABEL_TYPES,
            "qr_target": qr_target,
            "qr_targets": QR_TARGETS,
            "start": start,
            "start_positions": [
                {"value": value, "row": (value + columns - 1) // columns,
                 "column": ((value - 1) % columns) + 1}
                for value in range(1, capacity + 1)
            ],
            "show_images": params.get("images", "1") != "0",
            "checked_text": checked_text,
            "checked_count": checked_count,
            "part_query": params.get("part_query", "").strip(),
            "missing_status": params.get("missing_status", "all"),
            "missing_color": params.get("missing_color", "").strip(),
            "slots": slots,
            "label_pages": label_pages,
            "has_selected_sets": bool(selected_sets),
            "capacity": capacity,
            "columns": columns,
            "rows": rows,
            "public_origin": _public_origin(request),
        }
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(request, "organizer/labels/studio_update.html", context)
    return render(
        request,
        "organizer/label_studio.html",
        context,
    )


@login_required
@require_GET
def label_set_qr(request, set_pk):
    lego_set = get_object_or_404(
        LegoSet, pk=set_pk, owner=request.user, deleted_at__isnull=True
    )
    target = request.GET.get("target", "set")
    if target not in QR_TARGETS:
        target = "set"
    return HttpResponse(
        qr_svg(_qr_target(request, lego_set, target), border=4),
        content_type="image/svg+xml",
    )


@login_required
@require_GET
def label_minifigure_qr(request, figure_pk):
    figure = get_object_or_404(
        SetMinifigure.objects.select_related("lego_set"),
        pk=figure_pk,
        owner=request.user,
        lego_set__deleted_at__isnull=True,
    )
    target = f"{_public_origin(request)}{reverse('organizer:detail', args=['minifigures', figure.pk])}"
    return HttpResponse(qr_svg(target, border=4), content_type="image/svg+xml")


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
    form_class = build_model_form(MocVersion, ("version", "name", "description", "notes"))
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
        "organizer/form.html",
        {"form": form, "title": "MOC-Version bearbeiten" if version else "MOC-Version erstellen", "area": "mocs"},
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
    form_class = build_model_form(model, fields)
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
        "organizer/form.html",
        {"form": form, "title": "Bestandteil bearbeiten" if instance else "Bestandteil hinzufügen", "area": area},
    )


@login_required
@require_POST
@transaction.atomic
def minifigure_part_quantity(request, figure_pk, pk):
    figure = get_object_or_404(SetMinifigure, pk=figure_pk, owner=request.user)
    part = get_object_or_404(MinifigurePart.objects.select_for_update(), pk=pk, minifigure=figure)
    try:
        quantity = int(request.POST.get("owned_quantity", ""))
    except (TypeError, ValueError):
        quantity = -1
    if not 0 <= quantity <= part.quantity:
        return HttpResponse("Der vorhandene Bestand ist ungültig.", status=400)
    part.owned_quantity = quantity
    part.full_clean()
    part.save(update_fields=["owned_quantity"])
    part.refresh_from_db()
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="minifigure_part.quantity_changed", entity_type="minifigure_part", entity_id=str(part.pk), details={"owned_quantity": quantity}, request_id=request.request_id)
    if request.headers.get("Accept") == "application/json":
        figure_record = _minifigure_record(
            SetMinifigure.objects.prefetch_related("parts").get(pk=figure.pk)
        )
        completeness = set_completeness(
            LegoSet.objects.prefetch_related(
                "inventory_items", "minifigures_inventory__parts"
            ).get(pk=figure.lego_set_id)
        )
        return JsonResponse(
            {
                "ok": True,
                "part": {
                    "id": part.pk,
                    "minifigure_id": figure.pk,
                    "owned": part.owned_quantity,
                    "required": part.quantity,
                    "missing": part.missing_quantity,
                    "status": (
                        "complete" if part.missing_quantity == 0
                        else "missing" if part.owned_quantity == 0 else "partial"
                    ),
                    "status_label": (
                        "Komplett" if part.missing_quantity == 0
                        else "Fehlend" if part.owned_quantity == 0 else "Teilweise"
                    ),
                },
                "figure": {
                    "id": figure.pk,
                    "owned": figure_record["owned"],
                    "required": figure_record["required"],
                    "missing": figure_record["missing"],
                    "percent": figure_record["percent"],
                    "status": figure_record["status"],
                    "status_label": figure_record["status_label"],
                },
                "set": completeness,
            }
        )
    if request.POST.get("return") == "list":
        return redirect("organizer:minifigure_list")
    return redirect("organizer:detail", area="minifigures", pk=figure.pk)


@login_required
@require_POST
@transaction.atomic
def minifigure_inventory_action(request, figure_pk, action):
    figure = get_object_or_404(SetMinifigure, pk=figure_pk, owner=request.user)
    parts = figure.parts.select_for_update()
    if action == "complete":
        parts.update(owned_quantity=models.F("quantity"))
    elif action == "missing":
        parts.update(owned_quantity=0)
    else:
        return HttpResponse("Die Aktion ist ungültig.", status=400)
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action=f"minifigure_inventory.{action}", entity_type="set_minifigure", entity_id=str(figure.pk), request_id=request.request_id)
    return redirect("organizer:detail", area="minifigures", pk=figure.pk)
