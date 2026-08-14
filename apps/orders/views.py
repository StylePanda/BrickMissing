from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.core.services import record_recent
from apps.inventory.models import InventoryItem
from apps.inventory.services import change_inventory

from .forms import OrderForm, OrderItemForm
from .models import Order, OrderItem


@login_required
def order_list(request):
    records = Order.objects.filter(owner=request.user, deleted_at__isnull=True).prefetch_related("items")
    return render(request, "orders/list.html", {"page_obj": Paginator(records.order_by("-created_at"), 30).get_page(request.GET.get("page"))})


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
    return render(request, "catalog/form.html", {"form": form, "title": "Bestellung bearbeiten" if item else "Bestellung hinzufügen"})


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
