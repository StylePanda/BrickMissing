from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.totp import decrypt_secret
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part
from apps.core.rate_limit import limited

from .models import PriceObservation
from .rebrickable_sync import initialize_newly_purchased_inventory, synchronize_set
from .services import (
    RebrickableError,
    brickeconomy_set,
    bricklink_price,
    brickset_set,
    fetch_image,
    lego_pick_a_brick_url,
    rebrickable_instructions,
    rebrickable_minifigures,
    rebrickable_set,
    rebrickable_set_metadata,
)


@login_required
@require_POST
@transaction.atomic
def sync_rebrickable(request, pk):
    json_response = request.headers.get("Accept") == "application/json"
    limit = 250 if request.POST.get("bulk") == "1" else 20
    if limited(request, "integration-rebrickable", limit, 3600, per_user=True):
        if json_response:
            return JsonResponse({"ok": False, "message": "Zu viele Synchronisationsanfragen."}, status=429)
        return HttpResponse("Rate limit exceeded", status=429)
    lego_set = get_object_or_404(LegoSet.objects.select_for_update(), pk=pk, owner=request.user, deleted_at__isnull=True)
    if not request.user.rebrickable_api_key_encrypted:
        if json_response:
            return JsonResponse({"ok": False, "message": "Rebrickable ist nicht eingerichtet."}, status=400)
        messages.error(request, "Bitte richte Rebrickable zuerst in deinen Kontoeinstellungen ein.")
        return redirect("catalog:set_detail", pk=pk)
    api_key = decrypt_secret(request.user.rebrickable_api_key_encrypted)
    try:
        result = synchronize_set(
            lego_set, api_key, set_fetcher=rebrickable_set,
            minifigure_fetcher=rebrickable_minifigures,
        )
    except ValueError as exc:
        if json_response:
            return JsonResponse({"ok": False, "message": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect("catalog:set_detail", pk=pk)
    pending = set(request.session.get("newly_purchased_pending", []))
    if str(lego_set.pk) in pending:
        initialize_newly_purchased_inventory(lego_set)
        pending.discard(str(lego_set.pk))
        request.session["newly_purchased_pending"] = list(pending)
        request.session.modified = True
    if not result.minifigures_available:
        messages.warning(request, "Minifiguren konnten nicht synchronisiert werden.")
    AuditEvent.objects.create(actor=request.user, target_user=request.user, action="integration.rebrickable_sync", entity_type="set", entity_id=str(pk), details={"parts": result.parts, "minifigures": result.minifigures, "minifigure_parts": result.minifigure_parts}, request_id=request.request_id)
    messages.success(request, f"Rebrickable: {result.parts} Teile, {result.minifigures} Minifiguren und {result.minifigure_parts} Figuren-Teile synchronisiert.")
    if json_response:
        return JsonResponse({
            "ok": True,
            "set": {"id": str(lego_set.pk), "number": lego_set.set_number, "name": lego_set.name},
            "counts": {"parts": result.parts, "minifigures": result.minifigures, "minifigure_parts": result.minifigure_parts},
        })
    return redirect("catalog:set_detail", pk=pk)


@login_required
@require_GET
def instructions(request, pk):
    lego_set = get_object_or_404(LegoSet, pk=pk, owner=request.user, deleted_at__isnull=True)
    return render(
        request, "integrations/instructions.html",
        {"lego_set": lego_set, "instructions": rebrickable_instructions(
            lego_set.set_number,
            decrypt_secret(request.user.rebrickable_api_key_encrypted)
            if request.user.rebrickable_api_key_encrypted else "",
        )},
    )


@login_required
@require_GET
def rebrickable_set_lookup(request):
    if limited(request, "rebrickable-set-lookup", 60, 3600, per_user=True):
        return JsonResponse({"ok": False, "code": "rate_limit", "message": "Zu viele Anfragen. Bitte später erneut versuchen."}, status=429)
    if not request.user.rebrickable_api_key_encrypted:
        return JsonResponse({"ok": False, "code": "missing_key", "message": "Für das automatische Laden von LEGO-Setinformationen musst du zuerst Rebrickable mit deinem BrickMissing-Konto verbinden."}, status=400)
    try:
        api_key = decrypt_secret(request.user.rebrickable_api_key_encrypted)
        data = rebrickable_set_metadata(request.GET.get("set_number", ""), api_key)
    except RebrickableError as exc:
        messages_by_code = {
            "authentication": "Der Rebrickable API-Key ist ungültig.",
            "not_found": "Unter dieser Setnummer wurde bei Rebrickable kein Set gefunden.",
            "rate_limit": "Rebrickable hat zu viele Anfragen erhalten. Bitte versuche es später erneut.",
            "invalid_set_number": "Bitte gib eine gültige Setnummer ein.",
        }
        status = 404 if exc.code == "not_found" else 400 if exc.code in {"authentication", "invalid_set_number"} else 503
        return JsonResponse({"ok": False, "code": exc.code, "message": messages_by_code.get(exc.code, "Rebrickable ist momentan nicht erreichbar. Bitte versuche es später erneut.")}, status=status)
    return JsonResponse({"ok": True, "message": "Setinformationen gefunden.", "set": data})


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
