from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.totp import qr_svg
from apps.audit.models import AuditEvent
from apps.core.services import record_recent

from .forms import InventoryItemForm, WarehouseLocationForm
from .models import InventoryItem, WarehouseLocation
from .services import adjust_inventory, create_inventory


@login_required
def inventory_list(request):
    items = InventoryItem.objects.filter(owner=request.user, archived_at__isnull=True).select_related("location")
    query = request.GET.get("q", "").strip()
    if query:
        items = items.filter(Q(part_number__icontains=query) | Q(element_id__icontains=query) | Q(name__icontains=query) | Q(color__icontains=query))
    location = request.GET.get("location", "")
    if location.isdigit():
        items = items.filter(location_id=location, location__owner=request.user)
    ordering = request.GET.get("sort", "name")
    ordering = ordering if ordering in {"name", "part_number", "-quantity", "color"} else "name"
    locations = WarehouseLocation.objects.filter(owner=request.user, archived_at__isnull=True).order_by("name")
    return render(request, "inventory/list.html", {"page_obj": Paginator(items.order_by(ordering), 50).get_page(request.GET.get("page")), "query": query, "sort": ordering, "location": location, "locations": locations})


@login_required
def inventory_edit(request, pk=None):
    item = get_object_or_404(InventoryItem, pk=pk, owner=request.user) if pk else None
    form = InventoryItemForm(request.POST or None, instance=item, owner=request.user)
    if request.method == "GET" and item:
        record_recent(request.user, "inventory", item.pk, item.name, request.path)
    if request.method == "POST" and form.is_valid():
        candidate = form.save(commit=False)
        metadata = {
            field.name: getattr(candidate, field.name)
            for field in InventoryItem._meta.fields
            if field.name not in {
                "id", "owner", "legacy_id", "quantity", "reserved_quantity",
                "archived_at", "created_at", "updated_at",
            }
        }
        if item:
            adjust_inventory(
                item,
                request.user,
                form.cleaned_data["quantity"],
                form.cleaned_data["reserved_quantity"],
                "manual_edit",
                request_id=request.request_id,
                metadata=metadata,
            )
        else:
            create_inventory(
                request.user,
                form.cleaned_data["quantity"],
                form.cleaned_data["reserved_quantity"],
                request_id=request.request_id,
                **metadata,
            )
        return redirect("inventory:list")
    return render(request, "inventory/form.html", {"form": form, "title": "Inventarteil bearbeiten" if item else "Inventarteil hinzufügen", "kind": "item"})


@login_required
def locations(request):
    records = WarehouseLocation.objects.filter(owner=request.user, archived_at__isnull=True).select_related("parent")
    return render(request, "inventory/locations.html", {"locations": records})


@login_required
def location_edit(request, pk=None):
    item = get_object_or_404(WarehouseLocation, pk=pk, owner=request.user) if pk else None
    form = WarehouseLocationForm(request.POST or None, instance=item, owner=request.user)
    if request.method == "GET" and item:
        record_recent(request.user, "location", item.pk, item.name, request.path)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.owner = request.user
        saved.full_clean()
        saved.save()
        AuditEvent.objects.create(actor=request.user, target_user=request.user, action="location.saved", entity_type="warehouse_location", entity_id=str(saved.pk), request_id=request.request_id)
        return redirect("inventory:locations")
    return render(request, "inventory/form.html", {"form": form, "title": "Lagerort bearbeiten" if item else "Lagerort hinzufügen", "kind": "location"})


@login_required
def location_qr(request, pk):
    location = get_object_or_404(WarehouseLocation, pk=pk, owner=request.user)
    target = request.build_absolute_uri(f"/inventar/?location={location.pk}")
    return HttpResponse(qr_svg(target), content_type="image/svg+xml")


@login_required
@require_POST
def location_delete(request, pk):
    location = get_object_or_404(
        WarehouseLocation.objects.prefetch_related("children"),
        pk=pk, owner=request.user, archived_at__isnull=True,
    )
    item_count = InventoryItem.objects.filter(
        owner=request.user, location=location, archived_at__isnull=True,
    ).count()
    child_count = location.children.filter(archived_at__isnull=True).count()
    if item_count or child_count:
        from django.contrib import messages
        messages.error(request, "Lagerort kann nicht gelöscht werden, solange Bestand oder Unterlagerorte zugeordnet sind.")
        return redirect("inventory:locations")
    location.archived_at = timezone.now()
    location.active = False
    location.save(update_fields=["archived_at", "active", "updated_at"])
    from django.contrib import messages
    messages.success(request, "Lagerort wurde archiviert.")
    return redirect("inventory:locations")
