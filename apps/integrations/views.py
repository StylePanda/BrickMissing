from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.core.rate_limit import limited
from apps.organizer.models import MinifigurePart, SetMinifigure

from .models import PriceObservation
from .services import (
    brickeconomy_set,
    bricklink_price,
    brickset_set,
    fetch_image,
    lego_pick_a_brick_url,
    rebrickable_instructions,
    rebrickable_minifigures,
    rebrickable_set,
)


@login_required
@require_POST
@transaction.atomic
def sync_rebrickable(request, pk):
    if limited(request, "integration-rebrickable", 20, 3600, per_user=True):
        return HttpResponse("Rate limit exceeded", status=429)
    lego_set = get_object_or_404(LegoSet.objects.select_for_update(), pk=pk, owner=request.user, deleted_at__isnull=True)
    try:
        metadata, parts = rebrickable_set(lego_set.set_number)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("catalog:set_detail", pk=pk)
    lego_set.name = metadata.get("name") or lego_set.name
    lego_set.year = metadata.get("year") or lego_set.year
    lego_set.total_parts = max(int(metadata.get("num_parts") or 0), 0)
    lego_set.image_url = metadata.get("set_img_url") or lego_set.image_url
    lego_set.save(update_fields=["name", "year", "total_parts", "image_url", "updated_at"])
    for row in parts:
        part = row.get("part") or {}
        color = row.get("color") or {}
        SetInventoryItem.objects.update_or_create(
            lego_set=lego_set, part_number=str(part.get("part_num") or ""), color_id=color.get("id"), is_spare=bool(row.get("is_spare")),
            defaults={"element_id": str(row.get("element_id") or ""), "name": part.get("name") or "Unbenannt", "color_name": color.get("name") or "", "required_quantity": max(int(row.get("quantity") or 0), 0), "image_url": part.get("part_img_url") or ""},
        )
    figure_count = component_count = 0
    try:
        figures = rebrickable_minifigures(lego_set.set_number)
    except ValueError:
        figures = []
        messages.warning(request, "Minifiguren konnten nicht synchronisiert werden.")
    seen_figures = set()
    for figure, components in figures:
        number = str(figure.get("set_num") or "")[:100]
        if not number:
            continue
        seen_figures.add(number)
        minifigure, _ = SetMinifigure.objects.update_or_create(
            owner=request.user, lego_set=lego_set, figure_number=number,
            defaults={
                "name": str(figure.get("name") or number)[:191],
                "quantity": max(int(figure.get("quantity") or 1), 1),
                "image_url": figure.get("set_img_url") or "",
            },
        )
        figure_count += 1
        seen_components = set()
        for row in components:
            part = row.get("part") or {}
            color = row.get("color") or {}
            part_number = str(part.get("part_num") or "")[:100]
            key = (part_number, color.get("id"), bool(row.get("is_spare")))
            if not part_number or key in seen_components:
                continue
            seen_components.add(key)
            MinifigurePart.objects.update_or_create(
                minifigure=minifigure, part_number=part_number,
                color_id=color.get("id"), is_spare=bool(row.get("is_spare")),
                defaults={
                    "element_id": str(row.get("element_id") or "")[:100],
                    "name": str(part.get("name") or part_number)[:191],
                    "color_name": str(color.get("name") or "")[:100],
                    "quantity": max(int(row.get("quantity") or 1), 1),
                    "image_url": part.get("part_img_url") or "",
                },
            )
            component_count += 1
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="integration.rebrickable_sync", entity_type="set", entity_id=str(pk), details={"parts": len(parts), "minifigures": figure_count, "minifigure_parts": component_count}, request_id=request.request_id)
    messages.success(request, f"Rebrickable: {len(parts)} Teile, {figure_count} Minifiguren und {component_count} Figuren-Teile synchronisiert.")
    return redirect("catalog:set_detail", pk=pk)


@login_required
@require_GET
def instructions(request, pk):
    lego_set = get_object_or_404(LegoSet, pk=pk, owner=request.user, deleted_at__isnull=True)
    return render(
        request, "integrations/instructions.html",
        {"lego_set": lego_set, "instructions": rebrickable_instructions(lego_set.set_number)},
    )


@login_required
@require_GET
def image_proxy(request):
    try:
        data, content_type = fetch_image(request.GET.get("url", ""))
    except (ValueError, OSError):
        return HttpResponseBadRequest("Ungültige Bildadresse")
    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = "private, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_GET
def pick_a_brick(request, pk):
    part = get_object_or_404(Part, pk=pk, owner=request.user, deleted_at__isnull=True)
    return redirect(lego_pick_a_brick_url(part.part_number or part.element_id))


@login_required
@require_POST
def sync_price(request, pk):
    if limited(request, "integration-price", 30, 3600, per_user=True):
        return HttpResponse("Rate limit exceeded", status=429)
    lego_set = get_object_or_404(LegoSet, pk=pk, owner=request.user, deleted_at__isnull=True)
    source = request.POST.get("source", "brickeconomy")
    try:
        if source == "brickset":
            data = brickset_set(lego_set.set_number)
            lego = data.get("LEGOCom") or {}
            market = data.get("bricklink") or data.get("market") or {}
            value = lego.get("retailPrice") or market.get("usedValue") or data.get("retailPrice")
        elif source == "bricklink":
            data = bricklink_price("SET", lego_set.set_number)
            value = data.get("avg_price") or data.get("qty_avg_price") or data.get("min_price")
        elif source == "brickeconomy":
            data = brickeconomy_set(lego_set.set_number)
            value = data.get("current_value") or data.get("used_value") or data.get("value") or data.get("price")
        else:
            raise ValueError("Unbekannte Preisquelle")
        price = max(Decimal(str(value)), Decimal("0"))
    except (ValueError, TypeError, InvalidOperation):
        messages.error(request, f"Keine gültigen Preisdaten von {source} verfügbar.")
        return redirect("catalog:set_detail", pk=pk)
    lego_set.current_value = price
    lego_set.save(update_fields=["current_value", "updated_at"])
    PriceObservation.objects.create(owner=request.user, entity_type="set", entity_id=str(lego_set.pk), price=price, currency="EUR", source=source, is_estimate=True)
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="integration.price_sync", entity_type="set", entity_id=str(pk), details={"source": source}, request_id=request.request_id)
    messages.success(request, "Marktwert wurde aktualisiert.")
    return redirect("catalog:set_detail", pk=pk)
