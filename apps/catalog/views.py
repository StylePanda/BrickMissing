import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, Sum, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.core.models import SavedView
from apps.core.rate_limit import limited
from apps.core.services import record_recent
from apps.integrations.services import normalize_rebrickable_set_number
from apps.inventory.models import InventoryItem
from apps.orders.models import Order
from apps.organizer.models import MinifigurePart, Moc, SetMinifigure

from .colors import grouped_colors
from .forms import LegoSetForm, PartForm, SetCopyForm, SetInventoryItemForm
from .models import LegoSet, Part, SetCopy, SetInventoryItem
from .part_status import (
    group_workflow_status,
    stock_state,
    synchronize_presence_marker,
    workflow_status_label,
)
from .services import set_completeness as _set_completeness
from .services import soft_delete, update_part


def _page(request, queryset, size=50):
    return Paginator(queryset, size).get_page(request.GET.get("page"))


def _set_inventory_return_url(request, lego_set):
    fallback = f"{reverse('catalog:set_detail', args=[lego_set.pk])}#set-inventory"
    target = request.POST.get("next", "").strip()
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return fallback


@login_required
def dashboard(request):
    sets = LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True)
    parts = Part.objects.filter(owner=request.user, deleted_at__isnull=True)
    normal_set_parts_total = SetInventoryItem.objects.filter(
        lego_set__owner=request.user,
        lego_set__deleted_at__isnull=True,
        is_spare=False,
        required_quantity__gt=0,
    ).aggregate(
        total=Sum(
            Case(
                When(owned_quantity__lt=F("required_quantity"), then=F("owned_quantity")),
                default=F("required_quantity"),
                output_field=IntegerField(),
            )
        )
    )["total"] or 0
    minifigure_parts_total = MinifigurePart.objects.filter(
        minifigure__owner=request.user,
        minifigure__lego_set__owner=request.user,
        minifigure__lego_set__deleted_at__isnull=True,
        is_spare=False,
        quantity__gt=0,
    ).aggregate(
        total=Sum(
            Case(
                When(owned_quantity__lt=F("quantity"), then=F("owned_quantity")),
                default=F("quantity"),
                output_field=IntegerField(),
            )
        )
    )["total"] or 0
    query = request.GET.get("q", "").strip()[:200]
    search_sets = search_parts = search_minifigures = None
    if query:
        search_sets = sets.filter(Q(set_number__icontains=query) | Q(name__icontains=query)).order_by("set_number", "pk")[:10]
        search_parts = parts.filter(
            Q(element_id__icontains=query) | Q(design_id__icontains=query)
            | Q(part_number__icontains=query) | Q(name__icontains=query)
        ).select_related("lego_set").order_by("name", "pk")[:10]
        search_minifigures = SetMinifigure.objects.filter(
            owner=request.user, lego_set__deleted_at__isnull=True,
        ).filter(Q(figure_number__icontains=query) | Q(name__icontains=query)).select_related("lego_set").order_by("figure_number", "pk")[:10]
    return render(
        request,
        "catalog/dashboard.html",
        {
            "set_count": sets.count(),
            "part_count": parts.count(),
            "lego_parts_total": normal_set_parts_total + minifigure_parts_total,
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
            "query": query,
            "search_sets": search_sets,
            "search_parts": search_parts,
            "search_minifigures": search_minifigures,
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
    sync_sets = []
    for lego_set in LegoSet.objects.filter(
        owner=request.user, deleted_at__isnull=True
    ).order_by("set_number", "pk"):
        try:
            normalize_rebrickable_set_number(lego_set.set_number)
        except ValueError:
            continue
        sync_sets.append(lego_set)
    return render(request, "catalog/set_list.html", {
        "page_obj": _page(request, queryset), "query": query, "theme": theme,
        "sort": ordering, "sync_sets": sync_sets,
    })


@login_required
def set_detail(request, pk):
    lego_set = get_object_or_404(
        LegoSet.objects.prefetch_related("parts", "copies", "minifigures_inventory__parts"),
        pk=pk,
        owner=request.user,
        deleted_at__isnull=True,
    )
    record_recent(
        request.user, "set", lego_set.pk, f"{lego_set.set_number} · {lego_set.name}",
        request.path,
    )
    # Use the established parts-based completeness record for the initial
    # render; the parent owned quantity may be stale after part updates.
    from apps.organizer.views import _minifigure_record

    minifigure_records = [
        _minifigure_record(figure)
        for figure in lego_set.minifigures_inventory.all()
    ]
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
    inventory = inventory.annotate(
        missing_amount=F("required_quantity") - F("owned_quantity")
    )
    if sort == "color" and len(selected_colors) > 1:
        inventory = inventory.annotate(
            selected_color_order=Case(
                *[
                    When(color_name=color, then=Value(position))
                    for position, color in enumerate(selected_colors)
                ],
                default=Value(len(selected_colors)),
                output_field=IntegerField(),
            )
        ).order_by("selected_color_order", "name", "pk")
    else:
        inventory = inventory.order_by(*inventory_sorting[sort])
    page_obj = Paginator(inventory, 50).get_page(request.GET.get("page"))
    all_inventory = lego_set.inventory_items.all()
    colors = list(all_inventory.exclude(color_name="").values_list("color_name", flat=True).distinct().order_by("color_name"))
    stats = all_inventory.aggregate(positions=Count("pk"), required=Sum("required_quantity"), owned=Sum("owned_quantity"))
    stats = {key: value or 0 for key, value in stats.items()}
    stats["missing"] = max(stats["required"] - stats["owned"], 0)
    stats["percent"] = min(round(stats["owned"] * 100 / stats["required"]), 100) if stats["required"] else 0
    return render(request, "catalog/set_detail.html", {"lego_set": lego_set, "page_obj": page_obj, "inventory_stats": stats, "inventory_kind": kind, "inventory_query": query, "inventory_stock": stock, "inventory_sort": sort, "color_groups": grouped_colors(colors), "selected_colors": selected_colors, "color_summary": f"{len(selected_colors)} Farben" if selected_colors else "Alle Farben", "derived_completeness": _set_completeness(lego_set), "minifigure_records": minifigure_records})


@login_required
def set_edit(request, pk=None):
    lego_set = (
        get_object_or_404(LegoSet, pk=pk, owner=request.user, deleted_at__isnull=True)
        if pk
        else None
    )
    form = LegoSetForm(request.POST or None, instance=lego_set)
    if request.method == "GET" and lego_set is None and request.GET.get("preset") == "neu":
        form.initial["condition"] = "neu"
    if request.method == "POST" and form.is_valid():
        instance = form.save(commit=False)
        instance.owner = request.user
        instance.save()
        if request.POST.get("newly_purchased") == "1":
            pending = set(request.session.get("newly_purchased_pending", []))
            pending.add(str(instance.pk))
            request.session["newly_purchased_pending"] = list(pending)
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
            "newly_purchased": request.GET.get("preset") == "neu",
        },
    )


def parse_batch_set_numbers(raw):
    """Normalize newline/comma/semicolon/whitespace separated set numbers."""
    import re

    values = [value.strip() for value in re.split(r"[\s,;]+", raw or "") if value.strip()]
    normalized = []
    invalid = []
    for value in values:
        if not re.fullmatch(r"\d+(?:-\d+)?", value):
            invalid.append(value)
            continue
        try:
            candidate = normalize_rebrickable_set_number(value)
        except ValueError:
            invalid.append(value)
            continue
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized, invalid, len(values) - len(normalized) - len(invalid)


@login_required
def batch_set_import(request):
    return render(request, "catalog/set_batch_import.html")


@login_required
@require_POST
def batch_set_import_preview(request):
    from apps.accounts.totp import decrypt_secret
    from apps.integrations.services import rebrickable_set_preview

    numbers, invalid, duplicate_count = parse_batch_set_numbers(request.POST.get("set_numbers"))
    previews = []
    api_key = decrypt_secret(request.user.rebrickable_api_key_encrypted) if request.user.rebrickable_api_key_encrypted else ""
    for number in numbers:
        existing = LegoSet.objects.filter(owner=request.user, active_set_number=number, deleted_at__isnull=True).first()
        if existing:
            previews.append({"number": number, "status": "existing", "name": existing.name})
            continue
        if not api_key:
            previews.append({"number": number, "status": "error", "message": "Rebrickable ist nicht eingerichtet."})
            continue
        try:
            data = rebrickable_set_preview(number, api_key)
            previews.append({"number": number, "status": "ready", "name": data.get("name", ""), "data": data})
        except ValueError as exc:
            previews.append({"number": number, "status": "not_found" if getattr(exc, "code", "") == "not_found" else "error", "message": str(exc)})
    return JsonResponse({"ok": True, "sets": previews, "invalid": invalid, "duplicates": duplicate_count})


@login_required
@require_POST
def batch_set_import_preview_one(request):
    from apps.accounts.totp import decrypt_secret
    from apps.integrations.services import rebrickable_set_preview

    try:
        number = normalize_rebrickable_set_number(request.POST.get("set_number", ""))
    except ValueError as exc:
        return JsonResponse({"ok": False, "status": "invalid", "message": str(exc)}, status=400)
    existing = LegoSet.objects.filter(owner=request.user, active_set_number=number, deleted_at__isnull=True).first()
    if existing:
        return JsonResponse({"ok": True, "set": {"number": number, "status": "existing", "name": existing.name}})
    if not request.user.rebrickable_api_key_encrypted:
        return JsonResponse({"ok": True, "set": {"number": number, "status": "error", "message": "Rebrickable ist nicht eingerichtet."}})
    try:
        data = rebrickable_set_preview(number, decrypt_secret(request.user.rebrickable_api_key_encrypted))
    except ValueError as exc:
        status = "not_found" if getattr(exc, "code", "") == "not_found" else "error"
        return JsonResponse({"ok": True, "set": {"number": number, "status": status, "message": str(exc)}})
    return JsonResponse({"ok": True, "set": {"number": number, "status": "ready", "name": data.get("name", ""), "data": data}})


def _batch_purchase_metadata(data):
    """Validate the whitelisted purchase fields for one batch row."""
    raw_date = (data.get("purchase_date") or "").strip()
    purchase_date = None
    if raw_date:
        try:
            purchase_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError("Kaufdatum ist ungültig.") from exc
    raw_price = (data.get("purchase_price") or "").strip().replace(",", ".")
    try:
        purchase_price = Decimal(raw_price) if raw_price else Decimal("0")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Kaufpreis ist ungültig.") from exc
    if purchase_price < 0 or purchase_price.as_tuple().exponent < -2:
        raise ValueError("Kaufpreis ist ungültig.")
    condition = data.get("condition") or "neu"
    if condition not in {"neu", "gebraucht"}:
        raise ValueError("Zustand ist ungültig.")
    notes = (data.get("notes") or "").strip()
    if len(notes) > 10000:
        raise ValueError("Notizen sind zu lang.")
    return {"purchase_date": purchase_date, "purchase_price": purchase_price, "condition": condition, "notes": notes}


@login_required
@require_POST
@transaction.atomic
def batch_set_import_one(request):
    from apps.accounts.totp import decrypt_secret
    from apps.integrations.rebrickable_sync import (
        initialize_newly_purchased_inventory,
        synchronize_set,
    )
    from apps.integrations.services import rebrickable_minifigures, rebrickable_set

    try:
        number = normalize_rebrickable_set_number(request.POST.get("set_number", ""))
    except ValueError as exc:
        return JsonResponse({"ok": False, "status": "invalid", "message": str(exc)}, status=400)
    existing = LegoSet.objects.filter(owner=request.user, active_set_number=number, deleted_at__isnull=True).first()
    if existing:
        return JsonResponse({"ok": True, "status": "existing", "set": {"number": number, "id": str(existing.pk)}})
    if not request.user.rebrickable_api_key_encrypted:
        return JsonResponse({"ok": False, "status": "error", "message": "Rebrickable ist nicht eingerichtet."}, status=400)
    try:
        metadata = _batch_purchase_metadata(request.POST)
    except ValueError as exc:
        return JsonResponse({"ok": False, "status": "error", "message": str(exc)}, status=400)
    lego_set = LegoSet.objects.create(
        owner=request.user, set_number=number, name=number,
        condition=metadata["condition"], purchase_date=metadata["purchase_date"],
        purchase_price=metadata["purchase_price"], notes=metadata["notes"],
        build_status="gebaut",
    )
    try:
        result = synchronize_set(
            lego_set,
            decrypt_secret(request.user.rebrickable_api_key_encrypted),
            set_fetcher=rebrickable_set,
            minifigure_fetcher=rebrickable_minifigures,
        )
    except ValueError as exc:
        lego_set.delete()
        return JsonResponse({"ok": False, "status": "error", "message": str(exc)}, status=400)
    initialize_newly_purchased_inventory(lego_set)
    return JsonResponse({"ok": True, "status": "imported", "set": {"number": number, "name": lego_set.name}, "counts": result.__dict__})


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
        quantity__gt=F("owned_quantity"),
    ).select_related("lego_set")
    query = request.GET.get("q", "").strip()
    selected_colors = [value for value in request.GET.getlist("color") if value]
    status = request.GET.get("status", "")
    if status in Part.Status.values:
        queryset = queryset.filter(status=status)
    else:
        status = ""
    stock = request.GET.get("stock", "all")
    if stock not in {"all", "complete", "partial", "none"}:
        stock = "all"
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
    if part_kind == "normal":
        queryset = queryset.filter(lego_set__isnull=False)
    elif part_kind == "minifigure":
        queryset = queryset.none()
    elif part_kind == "assigned":
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
    colors = set()
    if part_kind != "minifigure":
        colors.update(
            Part.objects.filter(owner=request.user, deleted_at__isnull=True)
            .exclude(color="")
            .values_list("color", flat=True)
            .distinct()
        )
    if part_kind in {"all", "minifigure"}:
        colors.update(
            MinifigurePart.objects.filter(minifigure__owner=request.user)
            .exclude(color_name="")
            .values_list("color_name", flat=True)
            .distinct()
        )
    colors = sorted(colors, key=str.casefold)
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
    if part_kind in {"all", "minifigure"}:
        minifigure_parts = MinifigurePart.objects.filter(
            minifigure__owner=request.user,
            minifigure__lego_set__deleted_at__isnull=True,
        ).select_related("minifigure", "minifigure__lego_set")
        if query:
            minifigure_parts = minifigure_parts.filter(
                Q(part_number__icontains=query)
                | Q(element_id__icontains=query)
                | Q(name__icontains=query)
                | Q(minifigure__name__icontains=query)
                | Q(minifigure__lego_set__set_number__icontains=query)
            )
        if selected_colors:
            minifigure_parts = minifigure_parts.filter(color_name__in=selected_colors)
        if set_filter:
            minifigure_parts = minifigure_parts.filter(
                minifigure__lego_set_id=set_filter,
                minifigure__lego_set__owner=request.user,
            )
        if rarity == "single":
            minifigure_parts = minifigure_parts.filter(quantity=1)
        elif rarity == "multiple":
            minifigure_parts = minifigure_parts.filter(quantity__gte=2)
        minifigure_parts = minifigure_parts.filter(
            quantity__gt=F("owned_quantity")
        ).order_by(
            "minifigure_id", "part_number", "color_id", "is_spare",
            "-quantity", "-owned_quantity", "pk",
        )
        seen_minifigure_parts = set()
        for part in minifigure_parts:
            identity = (part.element_id or part.part_number).strip().casefold()
            duplicate_key = (
                part.minifigure.lego_set_id,
                part.minifigure_id,
                identity,
                part.color_id if part.color_id is not None else part.color_name.strip().casefold(),
                part.is_spare,
            )
            if duplicate_key in seen_minifigure_parts:
                continue
            seen_minifigure_parts.add(duplicate_key)
            missing = part.missing_quantity
            stock_key = (
                "complete" if missing == 0 else "partial" if part.owned_quantity else "none"
            )
            groups.append(
                {
                    "element_id": part.element_id,
                    "design_id": part.part_number,
                    "part_number": part.part_number,
                    "name": part.name,
                    "color": part.color_name,
                    "image_url": part.image_url,
                    "required": part.quantity,
                    "owned": part.owned_quantity,
                    "missing": missing,
                    "allocations": [part],
                    "statuses": set(),
                    "cost": 0,
                    "status": Part.Status.MISSING,
                    "status_label": Part.Status.MISSING.label,
                    "stock": stock_key,
                    "stock_label": stock_state(part.quantity, part.owned_quantity)[1],
                    "first_set": part.minifigure.lego_set.set_number,
                    "bulk_value": "",
                    "is_minifigure": True,
                }
            )
    minifigure_origins = {
        (
            part.minifigure.lego_set_id,
            (part.element_id or part.part_number).strip().casefold(),
            part.color_name.strip().casefold(),
        )
        for group in groups if group.get("is_minifigure")
        for part in group["allocations"]
    }
    normalized_groups = []
    for group in groups:
        if not group.get("is_minifigure"):
            allocations = [
                part for part in group["allocations"]
                if (
                    part.lego_set_id,
                    (part.element_id or part.design_id or part.part_number).strip().casefold(),
                    part.color.strip().casefold(),
                ) not in minifigure_origins
            ]
            if not allocations:
                continue
            group["allocations"] = allocations
            group["required"] = sum(part.quantity for part in allocations)
            group["owned"] = sum(part.owned_quantity for part in allocations)
            group["missing"] = sum(part.missing_quantity for part in allocations)
            group["statuses"] = {part.status for part in allocations}
            group["cost"] = sum(part.unit_price * part.quantity for part in allocations)
        normalized_groups.append(group)
    groups = normalized_groups
    for group in groups:
        if not group.get("is_minifigure"):
            group["status"], group["status_label"] = group_workflow_status(group["statuses"])
            group["stock"], group["stock_label"] = stock_state(
                group["required"], group["owned"]
            )
            group["first_set"] = min(
                (item.lego_set.set_number for item in group["allocations"] if item.lego_set),
                default="",
            )
            group["bulk_value"] = ",".join(str(item.pk) for item in group["allocations"])
    if status:
        groups = [
            group for group in groups
            if not group.get("is_minifigure") or status == Part.Status.MISSING
        ]
    if stock != "all":
        groups = [group for group in groups if group["stock"] == stock]
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
            "statuses": Part.Status.choices,
            "stock": stock,
            "part_statuses": Part.Status.choices,
            "minimum": minimum,
            "sort": ordering,
            "set_filter": set_filter,
            "sets": LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True).order_by("set_number"),
            "part_kind": part_kind,
            "rarity": rarity,
            "saved_views": SavedView.objects.filter(owner=request.user, area="missing_parts").order_by("name"),
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
    if action not in Part.Status.values:
        return HttpResponse("Ungültige Aktion", status=400)
    records = Part.objects.select_for_update().filter(
        owner=request.user, pk__in=identifiers, deleted_at__isnull=True
    )
    changed = 0
    for part in records:
        part.status = action
        part.full_clean()
        part.save(update_fields=["status", "updated_at"])
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
    synchronize_presence_marker(part)
    part.full_clean()
    part.save(update_fields=["owned_quantity", "is_present", "updated_at"])
    part.refresh_from_db()
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="missing_part.quantity_changed", entity_type="part", entity_id=str(part.pk), details={"owned_quantity": quantity}, request_id=request.request_id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        stock_key, stock_label = stock_state(part.quantity, part.owned_quantity)
        return JsonResponse({"ok": True, "part": {
            "id": str(part.pk), "owned": part.owned_quantity,
            "missing": part.missing_quantity, "status": part.status,
            "status_label": workflow_status_label(part.status),
            "stock": stock_key, "stock_label": stock_label,
        }})
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
    part.full_clean()
    part.save(update_fields=["status", "updated_at"])
    part.refresh_from_db()
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="missing_part.status_changed", entity_type="part", entity_id=str(part.pk), details={"status": status}, request_id=request.request_id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "part": {
            "id": str(part.pk), "owned": part.owned_quantity,
            "missing": part.missing_quantity, "status": part.status,
            "status_label": workflow_status_label(part.status),
        }})
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
        added = 0
        for item in records.filter(owned_quantity__lt=F("required_quantity"), is_spare=False):
            quantity = item.required_quantity - item.owned_quantity
            part, created = Part.objects.get_or_create(owner=request.user, lego_set=lego_set, element_id=item.element_id or item.part_number, color=item.color_name, deleted_at__isnull=True, defaults={"part_number": item.part_number, "name": item.name, "quantity": quantity, "owned_quantity": 0, "status": Part.Status.MISSING, "image_url": item.image_url})
            if not created:
                if part.missing_quantity <= 0:
                    part.quantity = max(part.quantity, part.owned_quantity + quantity)
                    part.save(update_fields=["quantity", "updated_at"])
            added += 1
        added += MinifigurePart.objects.filter(
            minifigure__lego_set=lego_set,
            minifigure__owner=request.user,
            quantity__gt=F("owned_quantity"),
            is_spare=False,
        ).count()
        if added:
            messages.success(request, f"{added} fehlende Positionen wurden zur Fehlliste hinzugefügt.")
        else:
            messages.info(request, "Für dieses Set gibt es keine offenen fehlenden Teile.")
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
    return redirect(_set_inventory_return_url(request, lego_set))
