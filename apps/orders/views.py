from datetime import date

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.catalog.models import Part
from apps.core.services import record_recent
from apps.inventory.models import InventoryItem
from apps.inventory.services import change_inventory
from apps.organizer.models import MinifigurePart

from .forms import OrderForm, OrderItemForm
from .importers import parse_order_csv
from .models import Order, OrderItem


@login_required
def order_list(request):
    records = Order.objects.filter(owner=request.user, deleted_at__isnull=True).prefetch_related("items")
    status = request.GET.get("status", "")
    valid_statuses = set(Order.STATUS_LABELS)
    if status in valid_statuses:
        records = records.filter(status=status)
    else:
        status = ""
    counts = [(key, Order.STATUS_LABELS[key], Order.objects.filter(owner=request.user, deleted_at__isnull=True, status=key).count()) for key in Order.STATUS_LABELS]
    return render(request, "orders/list.html", {"page_obj": Paginator(records.order_by("-created_at"), 30).get_page(request.GET.get("page")), "status": status, "status_counts": counts})


@login_required
def order_import(request):
    if request.method == "GET":
        return render(request, "orders/import.html")
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        items, errors = parse_order_csv(request.FILES.get("file"))
    except ValidationError as exc:
        return render(request, "orders/import.html", {"error": exc.messages[0]}, status=400)
    order_date = request.POST.get("order_date", "").strip()
    if order_date:
        try:
            date.fromisoformat(order_date)
        except ValueError:
            return render(request, "orders/import.html", {"error": "Das Bestelldatum ist ungültig."}, status=400)
    payload = {"source": request.POST.get("source", "generic"), "order_number": request.POST.get("order_number", "").strip()[:100], "order_date": order_date, "supplier": request.POST.get("supplier", "").strip()[:100], "items": items, "errors": errors}
    matches = []
    for item in items:
        part_qs = Part.objects.filter(owner=request.user, deleted_at__isnull=True, status=Part.Status.MISSING, part_number=item["part_number"], quantity__gt=models.F("owned_quantity")).select_related("lego_set").order_by("lego_set_id", "pk")
        mini_qs = MinifigurePart.objects.filter(minifigure__owner=request.user, minifigure__lego_set__deleted_at__isnull=True, part_number=item["part_number"], quantity__gt=models.F("owned_quantity"), is_spare=False).select_related("minifigure", "minifigure__lego_set").order_by("minifigure__lego_set_id", "minifigure_id", "pk")
        candidates = []
        for candidate in part_qs:
            color_match = bool(item["color"]) and candidate.color.strip().casefold() == item["color"].strip().casefold()
            if item["color"] and not color_match:
                continue
            candidates.append({"kind": "part", "id": str(candidate.pk), "set_name": candidate.lego_set.set_number if candidate.lego_set else "", "open": candidate.missing_quantity, "quality": "EXACT" if color_match else "POSSIBLE"})
        for candidate in mini_qs:
            color_match = bool(item["color"]) and candidate.color_name.strip().casefold() == item["color"].strip().casefold()
            if item["color"] and not color_match:
                continue
            candidates.append({"kind": "minifigure_part", "id": candidate.pk, "set_name": candidate.minifigure.lego_set.set_number, "open": candidate.missing_quantity, "quality": "EXACT" if color_match else "POSSIBLE"})
        quality = "EXACT" if any(c["quality"] == "EXACT" for c in candidates) else ("POSSIBLE" if candidates else "NONE")
        remaining = item["quantity"]
        allocations = []
        for candidate in candidates:
            if candidate["quality"] != "EXACT" or remaining <= 0:
                continue
            allocated = min(candidate["open"], remaining)
            if allocated:
                candidate["allocated"] = allocated
                allocations.append(candidate)
                remaining -= allocated
        item["match_quality"] = quality
        item["allocations"] = allocations
        item["match_part_ids"] = [c["id"] for c in allocations if c["kind"] == "part" and c["allocated"] >= c["open"]]
        matches.append({"part_number": item["part_number"], "count": len(candidates), "quality": quality, "allocated": item["quantity"] - remaining, "remaining": remaining, "allocations": allocations})
    token = signing.dumps(payload, salt="order-import")
    return render(request, "orders/import_preview.html", {"payload": payload, "token": token, "matches": matches})


@login_required
@require_POST
@transaction.atomic
def order_import_confirm(request):
    try:
        payload = signing.loads(request.POST.get("token", ""), salt="order-import", max_age=3600)
    except signing.BadSignature:
        return HttpResponseBadRequest("Importvorschau ist abgelaufen oder ungültig.")
    order_number = payload.get("order_number", "")
    if order_number and Order.objects.filter(owner=request.user, supplier=payload.get("supplier", "Import"), order_number=order_number, deleted_at__isnull=True).exists():
        return render(request, "orders/import.html", {"error": "Diese Bestellung scheint bereits vorhanden zu sein."}, status=400)
    order = Order.objects.create(owner=request.user, supplier=payload.get("supplier") or payload.get("source") or "Import", order_number=order_number, order_date=payload.get("order_date") or None, status="ordered")
    selected_allocations = set(request.POST.getlist("allocation"))
    has_selection = bool(selected_allocations)
    for item in payload.get("items", []):
        OrderItem.objects.create(order=order, part_number=item["part_number"], name=item.get("name", ""), color=item.get("color", ""), quantity=item["quantity"], unit_price=item.get("unit_price", "0"), notes=item.get("notes", ""))
        if item.get("match_part_ids"):
            match_ids = item["match_part_ids"] if not has_selection else [pk for pk in item["match_part_ids"] if pk in selected_allocations]
            Part.objects.filter(owner=request.user, pk__in=match_ids, status=Part.Status.MISSING).update(status=Part.Status.ORDERED)
    return redirect("orders:detail", pk=order.pk)


@login_required
def order_edit(request, pk=None):
    item = get_object_or_404(Order, pk=pk, owner=request.user) if pk else None
    form = OrderForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.owner = request.user
        saved.save()
        AuditEvent.objects.create(actor=request.user, target_user=request.user, action="order.saved", entity_type="order", entity_id=str(saved.pk), request_id=request.request_id)
        return redirect("orders:detail", pk=saved.pk)
    return render(request, "orders/form.html", {"form": form, "title": "Bestellung bearbeiten" if item else "Bestellung hinzufügen"})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related("items"), pk=pk, owner=request.user)
    record_recent(
        request.user, "order", order.pk,
        order.order_number or order.supplier, request.path,
    )
    return render(request, "orders/detail.html", {"order": order})


@login_required
def item_edit(request, order_pk, pk=None):
    order = get_object_or_404(Order, pk=order_pk, owner=request.user)
    item = get_object_or_404(OrderItem, pk=pk, order=order) if pk else None
    form = OrderItemForm(request.POST or None, instance=item, owner=request.user)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.order = order
        saved.full_clean()
        saved.save()
        AuditEvent.objects.create(actor=request.user, target_user=request.user, action="order_item.saved", entity_type="order_item", entity_id=str(saved.pk), request_id=request.request_id)
        return redirect("orders:detail", pk=order.pk)
    return render(request, "catalog/form.html", {"form": form, "title": "Bestellposition bearbeiten" if item else "Bestellposition hinzufügen"})


@login_required
@require_POST
@transaction.atomic
def receive_item(request, order_pk, pk):
    order = get_object_or_404(Order, pk=order_pk, owner=request.user, deleted_at__isnull=True)
    item = get_object_or_404(OrderItem.objects.select_for_update(), pk=pk, order=order)
    outstanding = item.quantity - item.received_quantity
    try:
        amount = int(request.POST.get("quantity", outstanding))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Ungültige Menge")
    if amount < 1 or amount > outstanding:
        return HttpResponseBadRequest("Menge überschreitet die offene Bestellmenge")
    inventory = item.inventory_item
    if inventory:
        inventory = get_object_or_404(InventoryItem.objects.select_for_update(), pk=inventory.pk, owner=request.user)
    else:
        inventory, _ = InventoryItem.objects.select_for_update().get_or_create(
            owner=request.user, part_number=item.part_number, color=item.color,
            condition="neu", location=item.target_location,
            defaults={"name": item.name or item.part_number, "quantity": 0, "source": order.supplier},
        )
        item.inventory_item = inventory
    inventory = change_inventory(
        inventory,
        request.user,
        quantity_delta=amount,
        movement_type="order_receipt",
        source=f"order:{order.pk}",
        request_id=request.request_id,
    )
    item.received_quantity += amount
    item.save(update_fields=["received_quantity", "inventory_item"])
    if not order.items.exclude(received_quantity__gte=models.F("quantity")).exists():
        order.status = "received"
        order.save(update_fields=["status", "updated_at"])
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="order.received", entity_type="order_item", entity_id=str(item.pk), details={"quantity": amount, "inventory_item": inventory.pk}, request_id=request.request_id)
    return redirect("orders:detail", pk=order.pk)
