import uuid

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.core.rate_limit import limited
from apps.core.services import record_recent
from apps.inventory.models import InventoryItem
from apps.orders.models import Order
from apps.organizer.models import Moc, SetMinifigure

from .colors import grouped_colors
from .forms import LegoSetForm, PartForm, SetCopyForm, SetInventoryItemForm
from .models import LegoSet, Part, SetCopy, SetInventoryItem
from .services import set_completeness as _set_completeness
from .services import soft_delete, update_part


def _page(request, queryset, size=50):
    return Paginator(queryset, size).get_page(request.GET.get("page"))


@login_required
def dashboard(request):
    sets = LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True)
    parts = Part.objects.filter(owner=request.user, deleted_at__isnull=True)
    return render(
        request,
        "catalog/dashboard.html",
        {
            "set_count": sets.count(),
            "part_count": parts.count(),
            "missing_count": parts.filter(status=Part.Status.MISSING).aggregate(
                total=Sum("quantity")
            )["total"]
            or 0,
            "recent_sets": sets[:6],
            "inventory_quantity": InventoryItem.objects.filter(owner=request.user).aggregate(
                total=Sum("quantity")
            )["total"]
            or 0,
            "open_orders": Order.objects.filter(owner=request.user, deleted_at__isnull=True)
            .exclude(status__in=["received", "cancelled"])
            .count(),
            "moc_count": Moc.objects.filter(owner=request.user).count(),
            "minifigure_count": SetMinifigure.objects.filter(owner=request.user).count(),
        },
    )


@login_required
def set_list(request):
    queryset = LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True)
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(set_number__icontains=query) | Q(name__icontains=query) | Q(theme__icontains=query)
        )
    theme = request.GET.get("theme", "").strip()
    if theme:
        queryset = queryset.filter(theme__iexact=theme)
    ordering = request.GET.get("sort", "-created_at")
    ordering = ordering if ordering in {"-created_at", "set_number", "name", "-year", "-current_value"} else "-created_at"
    queryset = queryset.order_by(ordering)
    return render(
        request, "catalog/set_list.html", {"page_obj": _page(request, queryset), "query": query, "theme": theme, "sort": ordering}
    )


@login_required
def set_detail(request, pk):
    lego_set = get_object_or_404(
        LegoSet.objects.prefetch_related("inventory_items", "parts", "copies", "minifigures_inventory__parts"),
        pk=pk,
        owner=request.user,
        deleted_at__isnull=True,
    )
    record_recent(
        request.user, "set", lego_set.pk, f"{lego_set.set_number} · {lego_set.name}",
        request.path,
    )
    inventory = lego_set.inventory_items.all()
    kind = request.GET.get("art", "all")
    if kind == "normal":
        inventory = inventory.filter(is_spare=False)
    elif kind == "spare":
        inventory = inventory.filter(is_spare=True)
    query = request.GET.get("q", "").strip()
    if query:
        inventory = inventory.filter(Q(part_number__icontains=query) | Q(element_id__icontains=query) | Q(name__icontains=query) | Q(color_name__icontains=query))
    selected_colors = [value for value in request.GET.getlist("color") if value]
    if selected_colors:
        inventory = inventory.filter(color_name__in=selected_colors)
    stock = request.GET.get("stock", "all")
    if stock == "complete":
        inventory = inventory.filter(owned_quantity__gte=F("required_quantity"))
    elif stock == "partial":
        inventory = inventory.filter(owned_quantity__gt=0, owned_quantity__lt=F("required_quantity"))
    elif stock == "missing":
        inventory = inventory.filter(owned_quantity=0)
    sort = request.GET.get("sort", "name")
    inventory_sorting = {
        "name": ("name", "pk"), "-name": ("-name", "pk"),
        "part_number": ("part_number", "pk"), "-part_number": ("-part_number", "pk"),
        "color": ("color_name", "name"), "required": ("required_quantity", "name"),
        "-required": ("-required_quantity", "name"), "owned": ("owned_quantity", "name"),
        "-owned": ("-owned_quantity", "name"), "missing": ("missing_amount", "name"),
        "-missing": ("-missing_amount", "name"),
    }
    sort = sort if sort in inventory_sorting else "name"
    inventory = inventory.annotate(missing_amount=F("required_quantity") - F("owned_quantity")).order_by(*inventory_sorting[sort])
    all_inventory = lego_set.inventory_items.all()
    colors = list(all_inventory.exclude(color_name="").values_list("color_name", flat=True).distinct().order_by("color_name"))
    stats = all_inventory.aggregate(positions=Count("pk"), required=Sum("required_quantity"), owned=Sum("owned_quantity"))
    stats = {key: value or 0 for key, value in stats.items()}
    stats["missing"] = max(stats["required"] - stats["owned"], 0)
    stats["percent"] = min(round(stats["owned"] * 100 / stats["required"]), 100) if stats["required"] else 0
    return render(request, "catalog/set_detail.html", {"lego_set": lego_set, "inventory_items": inventory, "inventory_stats": stats, "inventory_kind": kind, "inventory_query": query, "inventory_stock": stock, "inventory_sort": sort, "color_groups": grouped_colors(colors), "selected_colors": selected_colors, "color_summary": f"{len(selected_colors)} Farben" if selected_colors else "Alle Farben", "derived_completeness": _set_completeness(lego_set)})


@login_required
def set_edit(request, pk=None):
    lego_set = (
        get_object_or_404(LegoSet, pk=pk, owner=request.user, deleted_at__isnull=True)
        if pk
        else None
    )
    form = LegoSetForm(request.POST or None, instance=lego_set)
    if request.method == "POST" and form.is_valid():
        instance = form.save(commit=False)
        instance.owner = request.user
        instance.save()
        AuditEvent.objects.create(
            actor=request.user,
            target_user=request.user,
            action="set.saved",
            entity_type="set",
            entity_id=str(instance.pk),
            request_id=request.request_id,
        )
        return redirect("catalog:set_detail", pk=instance.pk)
    def suggestions(field):
        values = LegoSet.objects.filter(owner=request.user).exclude(**{field: ""}).values_list(field, flat=True)
        normalized = {}
        for value in values:
            cleaned = " ".join(value.split())
            if cleaned:
                key = cleaned.casefold()
                current = normalized.get(key)
                if current is None or (current.islower() and not cleaned.islower()):
                    normalized[key] = cleaned
        return sorted(normalized.values(), key=str.casefold)

    return render(
        request,
        "catalog/set_form.html",
        {
            "form": form, "title": "Set bearbeiten" if lego_set else "Set hinzufügen",
            "theme_suggestions": suggestions("theme"),
            "subtheme_suggestions": suggestions("subtheme"),
            "rebrickable_connected": request.user.has_rebrickable_api_key,
        },
    )


@login_required
@require_POST
def set_delete(request, pk):
    soft_delete(
        get_object_or_404(LegoSet, pk=pk, owner=request.user, deleted_at__isnull=True),
        request.user,
        request.request_id,
    )
    return redirect("catalog:set_list")


@login_required
def part_list(request):
    queryset = Part.objects.filter(owner=request.user, deleted_at__isnull=True).select_related(
        "lego_set"
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        queryset = queryset.filter(
            Q(element_id__icontains=query)
            | Q(part_number__icontains=query)
            | Q(name__icontains=query)
            | Q(color__icontains=query)
        )
    if status in Part.Status.values:
        queryset = queryset.filter(status=status)
    ordering = request.GET.get("sort", "name")
    ordering = ordering if ordering in {"name", "element_id", "color", "-quantity", "-updated_at"} else "name"
    queryset = queryset.order_by(ordering)
    return render(
        request,
        "catalog/part_list.html",
        {
            "page_obj": _page(request, queryset),
            "query": query,
            "status": status,
            "statuses": Part.Status.choices,
            "sort": ordering,
        },
    )


@login_required
def missing_parts(request):
    queryset = Part.objects.filter(
        owner=request.user,
        deleted_at__isnull=True,
    ).select_related("lego_set")
    query = request.GET.get("q", "").strip()
    selected_colors = [value for value in request.GET.getlist("color") if value]
    status = request.GET.get("status", "")
    minimum = request.GET.get("minimum", "").strip()
    if query:
        queryset = queryset.filter(
            Q(part_number__icontains=query)
            | Q(element_id__icontains=query)
            | Q(name__icontains=query)
            | Q(lego_set__set_number__icontains=query)
            | Q(lego_set__name__icontains=query)
        )
    if selected_colors:
        queryset = queryset.filter(color__in=selected_colors)
    set_filter = request.GET.get("set", "").strip()
    if set_filter:
        queryset = queryset.filter(lego_set_id=set_filter, lego_set__owner=request.user)
    part_kind = request.GET.get("kind", "all")
    if part_kind == "assigned":
        queryset = queryset.filter(lego_set__isnull=False)
    elif part_kind == "unassigned":
        queryset = queryset.filter(lego_set__isnull=True)
    rarity = request.GET.get("rarity", "all")
    if rarity == "single":
        queryset = queryset.filter(quantity=1)
    elif rarity == "multiple":
        queryset = queryset.filter(quantity__gte=2)
    ordering = request.GET.get("sort", "name")
    sort_fields = {
        "name": "name", "-name": "name", "part_number": "part_number",
        "element_id": "element_id", "color": "color", "quantity": "required",
        "-quantity": "required", "owned_quantity": "owned",
        "-owned_quantity": "owned", "missing": "missing", "-missing": "missing",
        "lego_set__set_number": "first_set", "-lego_set__set_number": "first_set",
    }
    ordering = ordering if ordering in sort_fields else "name"
    colors = (
        Part.objects.filter(owner=request.user, deleted_at__isnull=True)
        .exclude(color="")
        .values_list("color", flat=True)
        .distinct()
        .order_by("color")
    )
    records = list(queryset.order_by("pk"))
    grouped = {}
    for part in records:
        identity = part.element_id.strip().casefold()
        if not identity:
            identity = (part.design_id or part.part_number).strip().casefold()
        key = (identity, part.color.strip().casefold())
        group = grouped.setdefault(key, {
            "element_id": part.element_id, "design_id": part.design_id,
            "part_number": part.part_number, "name": part.name, "color": part.color,
            "image_url": part.image_url, "required": 0, "owned": 0, "missing": 0,
            "allocations": [], "statuses": set(), "cost": 0,
        })
        group["required"] += part.quantity
        group["owned"] += part.owned_quantity
        group["missing"] += part.missing_quantity
        group["statuses"].add(part.status)
        group["cost"] += part.unit_price * part.quantity
        if not group["image_url"] and part.image_url:
            group["image_url"] = part.image_url
        group["allocations"].append(part)
    groups = list(grouped.values())
    for group in groups:
        if group["missing"] == 0:
            group["status"], group["status_label"] = Part.Status.FOUND, "Gefunden"
        elif group["owned"]:
            group["status"], group["status_label"] = "partial", "Teilweise vorhanden"
        else:
            group["status"], group["status_label"] = Part.Status.MISSING, "Fehlt"
        group["first_set"] = min(
            (item.lego_set.set_number for item in group["allocations"] if item.lego_set),
            default="",
        )
        group["bulk_value"] = ",".join(str(item.pk) for item in group["allocations"])
    if status == Part.Status.ORDERED:
        groups = [group for group in groups if group["statuses"] == {Part.Status.ORDERED}]
    elif status in {Part.Status.MISSING, Part.Status.FOUND, "partial"}:
        groups = [group for group in groups if group["status"] == status]
    elif not status:
        groups = [group for group in groups if group["missing"] > 0]
    if minimum.isdigit():
        groups = [group for group in groups if group["missing"] >= int(minimum)]
    groups.sort(
        key=lambda group: (group[sort_fields[ordering]], group["name"].casefold()),
        reverse=ordering.startswith("-"),
    )
    page_obj = Paginator(groups, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/missing_parts.html",
        {
            "page_obj": page_obj,
            "missing_total": sum(group["missing"] for group in groups),
            "query": query,
            "color_groups": grouped_colors(list(colors)),
            "selected_colors": selected_colors,
            "color_summary": f"{len(selected_colors)} Farben" if selected_colors else "Alle Farben",
            "status": status,
            "statuses": (
                (Part.Status.MISSING, "Fehlt"), ("partial", "Teilweise vorhanden"),
                (Part.Status.ORDERED, "Bestellt"), (Part.Status.FOUND, "Gefunden/Vollständig"),
            ),
            "part_statuses": Part.Status.choices,
            "minimum": minimum,
            "sort": ordering,
            "set_filter": set_filter,
            "sets": LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True).order_by("set_number"),
            "part_kind": part_kind,
            "rarity": rarity,
        },
    )


@login_required
@require_POST
@transaction.atomic
def missing_parts_bulk(request):
    if limited(request, "missing-parts-bulk", 60, 3600, per_user=True):
        return HttpResponse("Rate limit exceeded", status=429)
    identifiers = []
    for value in request.POST.getlist("item")[:500]:
        for candidate in value.split(","):
            try:
                identifiers.append(uuid.UUID(candidate))
            except (ValueError, AttributeError):
                continue
    identifiers = list(dict.fromkeys(identifiers))[:500]
    action = request.POST.get("action")
    if action not in {"found", "missing", "ordered"}:
        return HttpResponse("Ungültige Aktion", status=400)
    records = Part.objects.select_for_update().filter(
        owner=request.user, pk__in=identifiers, deleted_at__isnull=True
    )
    changed = 0
    for part in records:
        if action == "found":
            part.owned_quantity = part.quantity
            part.status = Part.Status.FOUND
        elif action == "missing":
            part.owned_quantity = 0
            part.status = Part.Status.MISSING
        else:
            part.status = Part.Status.ORDERED
        part.full_clean()
        part.save(update_fields=["owned_quantity", "status", "updated_at"])
        changed += 1
    AuditEvent.objects.create(
        actor=request.user, target_user=request.user, action="missing_parts.bulk",
        details={"operation": action, "count": changed}, request_id=request.request_id,
    )
    return redirect("catalog:missing_parts")


def _bounded_quantity(value, maximum):
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return None
    return quantity if 0 <= quantity <= maximum else None


@login_required
@require_POST
@transaction.atomic
def missing_part_quantity(request, pk):
    part = get_object_or_404(Part.objects.select_for_update(), pk=pk, owner=request.user, deleted_at__isnull=True)
    quantity = _bounded_quantity(request.POST.get("owned_quantity"), part.quantity)
    if quantity is None:
        return HttpResponse("Der vorhandene Bestand ist ungültig.", status=400)
    part.owned_quantity = quantity
    part.status = Part.Status.FOUND if quantity == part.quantity else Part.Status.MISSING
    part.full_clean()
    part.save(update_fields=["owned_quantity", "status", "updated_at"])
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="missing_part.quantity_changed", entity_type="part", entity_id=str(part.pk), details={"owned_quantity": quantity}, request_id=request.request_id)
    return redirect("catalog:missing_parts")


@login_required
@require_POST
@transaction.atomic
def missing_part_status(request, pk):
    part = get_object_or_404(Part.objects.select_for_update(), pk=pk, owner=request.user, deleted_at__isnull=True)
    status = request.POST.get("status")
    if status not in Part.Status.values:
        return HttpResponse("Der Status ist ungültig.", status=400)
    part.status = status
    if status == Part.Status.MISSING:
        part.owned_quantity = 0
    elif status in {Part.Status.FOUND, Part.Status.RECEIVED, Part.Status.INSTALLED}:
        part.owned_quantity = part.quantity
    part.full_clean()
    part.save(update_fields=["owned_quantity", "status", "updated_at"])
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="missing_part.status_changed", entity_type="part", entity_id=str(part.pk), details={"status": status}, request_id=request.request_id)
    return redirect("catalog:missing_parts")


@login_required
def part_edit(request, pk=None):
    part = (
        get_object_or_404(Part, pk=pk, owner=request.user, deleted_at__isnull=True) if pk else None
    )
    form = PartForm(request.POST or None, instance=part, owner=request.user)
    if request.method == "GET" and part:
        record_recent(request.user, "part", part.pk, part.name, request.path)
    if request.method == "POST" and form.is_valid():
        if part:
            update_part(part, form.cleaned_data, request.user, request.request_id)
        else:
            instance = form.save(commit=False)
            instance.owner = request.user
            instance.full_clean()
            instance.save()
            AuditEvent.objects.create(
                actor=request.user,
                target_user=request.user,
                action="part.created",
                entity_type="part",
                entity_id=str(instance.pk),
                request_id=request.request_id,
            )
        return redirect("catalog:part_list")
    return render(
        request,
        "catalog/part_form.html",
        {"form": form, "title": "Teil bearbeiten" if part else "Teil hinzufügen"},
    )


@login_required
@require_POST
def part_delete(request, pk):
    soft_delete(
        get_object_or_404(Part, pk=pk, owner=request.user, deleted_at__isnull=True),
        request.user,
        request.request_id,
    )
    return redirect("catalog:part_list")


@login_required
def trash(request):
    return render(
        request,
        "catalog/trash.html",
        {
            "sets": LegoSet.objects.filter(owner=request.user, deleted_at__isnull=False),
            "parts": Part.objects.filter(owner=request.user, deleted_at__isnull=False),
        },
    )


@login_required
@require_POST
def restore(request, kind, pk):
    model = LegoSet if kind == "set" else Part if kind == "part" else None
    if model is None:
        return redirect("catalog:trash")
    item = get_object_or_404(model, pk=pk, owner=request.user, deleted_at__isnull=False)
    item.deleted_at = None
    item.save(update_fields=["deleted_at", "updated_at"])
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action=f"{kind}.restored",
        entity_type=kind,
        entity_id=str(pk),
        request_id=request.request_id,
    )
    return redirect("catalog:trash")


@login_required
@require_POST
@transaction.atomic
def permanent_delete(request, kind, pk):
    model = LegoSet if kind == "set" else Part if kind == "part" else None
    if model is None:
        return HttpResponse("Ungültiger Eintragstyp", status=400)
    item = get_object_or_404(
        model.objects.select_for_update(), pk=pk, owner=request.user,
        deleted_at__isnull=False,
    )
    AuditEvent.objects.create(
        actor=request.user, target_user=request.user,
        action=f"{kind}.permanently_deleted", entity_type=kind,
        entity_id=str(pk), request_id=request.request_id,
    )
    item.delete()
    return redirect("catalog:trash")


@login_required
def set_copy_edit(request, set_pk, pk=None):
    lego_set = get_object_or_404(LegoSet, pk=set_pk, owner=request.user, deleted_at__isnull=True)
    instance = get_object_or_404(SetCopy, pk=pk, lego_set=lego_set, owner=request.user) if pk else None
    form = SetCopyForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.owner = request.user
        saved.lego_set = lego_set
        saved.full_clean()
        saved.save()
        AuditEvent.objects.create(actor=request.user, target_user=request.user, action="set_copy.saved", entity_type="set_copy", entity_id=str(saved.pk), request_id=request.request_id)
        return redirect("catalog:set_detail", pk=lego_set.pk)
    return render(request, "catalog/form.html", {"form": form, "title": "Setexemplar bearbeiten" if instance else "Setexemplar hinzufügen"})


@login_required
def set_inventory_edit(request, set_pk, pk=None):
    lego_set = get_object_or_404(LegoSet, pk=set_pk, owner=request.user, deleted_at__isnull=True)
    instance = get_object_or_404(SetInventoryItem, pk=pk, lego_set=lego_set) if pk else None
    form = SetInventoryItemForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.lego_set = lego_set
        saved.full_clean()
        saved.save()
        AuditEvent.objects.create(actor=request.user, target_user=request.user, action="set_inventory.saved", entity_type="set_inventory_item", entity_id=str(saved.pk), request_id=request.request_id)
        return redirect("catalog:set_detail", pk=lego_set.pk)
    return render(request, "catalog/form.html", {"form": form, "title": "Soll-/Ist-Teil bearbeiten" if instance else "Soll-/Ist-Teil hinzufügen"})


@login_required
@require_POST
@transaction.atomic
def set_inventory_action(request, set_pk, action):
    if limited(request, "inventory-bulk", 60, 3600, per_user=True):
        return HttpResponse("Rate limit exceeded", status=429)
    lego_set = get_object_or_404(LegoSet, pk=set_pk, owner=request.user, deleted_at__isnull=True)
    records = lego_set.inventory_items.select_for_update()
    if action == "complete":
        records.update(owned_quantity=F("required_quantity"))
    elif action == "missing":
        records.update(owned_quantity=0)
    elif action == "create-missing":
        for item in records.filter(owned_quantity__lt=F("required_quantity"), is_spare=False):
            quantity = item.required_quantity - item.owned_quantity
            part, created = Part.objects.get_or_create(owner=request.user, lego_set=lego_set, element_id=item.element_id or item.part_number, color=item.color_name, deleted_at__isnull=True, defaults={"part_number": item.part_number, "name": item.name, "quantity": quantity, "owned_quantity": 0, "status": Part.Status.MISSING, "image_url": item.image_url})
            if not created:
                part.quantity = quantity
                part.owned_quantity = min(part.owned_quantity, quantity)
                part.status = Part.Status.MISSING if part.owned_quantity < quantity else Part.Status.FOUND
                part.save(update_fields=["quantity", "owned_quantity", "status", "updated_at"])
    else:
        return redirect("catalog:set_detail", pk=lego_set.pk)
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action=f"set_inventory.{action}", entity_type="set", entity_id=str(lego_set.pk), request_id=request.request_id)
    return redirect("catalog:set_detail", pk=lego_set.pk)


@login_required
@require_POST
@transaction.atomic
def set_inventory_quantity(request, set_pk, pk):
    lego_set = get_object_or_404(LegoSet, pk=set_pk, owner=request.user, deleted_at__isnull=True)
    item = get_object_or_404(SetInventoryItem.objects.select_for_update(), pk=pk, lego_set=lego_set)
    quantity = _bounded_quantity(request.POST.get("owned_quantity"), item.required_quantity)
    if quantity is None:
        return HttpResponse("Der vorhandene Bestand ist ungültig.", status=400)
    item.owned_quantity = quantity
    item.full_clean()
    item.save(update_fields=["owned_quantity", "updated_at"])
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="set_inventory.quantity_changed", entity_type="set_inventory_item", entity_id=str(item.pk), details={"owned_quantity": quantity}, request_id=request.request_id)
    return redirect("catalog:set_detail", pk=lego_set.pk)
