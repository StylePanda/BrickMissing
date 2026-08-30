import hashlib

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.models import LegoSet, Part
from apps.integrations.models import PriceObservation
from apps.inventory.models import InventoryItem
from apps.orders.models import Order

from .email import send_templated_email
from .models import DataQualityIssue, SavedView


@require_GET
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "version": "8.0.0", "database": "ok"})


@require_GET
def service_worker(request):
    response = FileResponse(
        open(settings.BASE_DIR / "static" / "service-worker.js", "rb"),
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@staff_member_required
@require_POST
def test_email(request):
    recipient = request.POST.get("recipient", "").strip()
    if "@" not in recipient or any(char in recipient for char in "\r\n"):
        messages.error(request, "Ungültige Empfängeradresse.")
    else:
        send_templated_email(
            to=[recipient],
            subject="BrickMissing – E-Mail-Test",
            template_name="test_email",
            request=request,
        )
        from apps.audit.models import AuditEvent
        recipient_hash = hashlib.sha256(recipient.casefold().encode("utf-8")).hexdigest()
        AuditEvent.objects.create(
            actor=request.user,
            action="email.test",
            details={"recipient_present": True, "recipient_sha256": recipient_hash},
            request_id=request.request_id,
        )
        messages.success(request, "Testmail wurde an das konfigurierte Backend übergeben.")
    return redirect("backups:list")


@login_required
def global_search(request):
    query = request.GET.get("q", "").strip()[:200]
    target = "/"
    if query:
        from urllib.parse import quote
        target = f"/?q={quote(query)}"
    return redirect(target)


@login_required
def saved_views(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()[:191]
        area = request.POST.get("area", "").strip()[:50]
        path = request.POST.get("path", "").strip()[:255]
        query = request.POST.get("query", "").strip()[:2000]
        pk = request.POST.get("pk")
        if name and area and path.startswith("/") and not path.startswith("//"):
            if pk:
                item = get_object_or_404(SavedView, pk=pk, owner=request.user)
                item.name, item.area, item.path = name, area, path
                item.configuration = {"query": query}
                item.save()
            else:
                SavedView.objects.update_or_create(
                    owner=request.user, area=area, name=name,
                    defaults={"path": path, "configuration": {"query": query}},
                )
            messages.success(request, "Ansicht gespeichert.")
        else:
            messages.error(request, "Ansicht ist ungültig.")
        return redirect("saved_views")
    return render(
        request, "core/saved_views.html",
        {"saved_views": SavedView.objects.filter(owner=request.user).order_by("area", "name")},
    )


@login_required
@require_POST
def saved_view_delete(request, pk):
    get_object_or_404(SavedView, pk=pk, owner=request.user).delete()
    next_url = request.POST.get("next", "")
    if next_url.startswith("/") and not next_url.startswith("//"):
        messages.success(request, "Ansicht wurde gelöscht.")
        return redirect(next_url)
    return redirect("saved_views")


@login_required
@require_GET
def saved_view_load(request, pk):
    item = get_object_or_404(SavedView, pk=pk, owner=request.user)
    configuration = item.configuration if isinstance(item.configuration, dict) else {}
    query = configuration.get("query", "")
    target = item.path
    if query:
        target = f"{target}?{query}"
    return redirect(target)


@login_required
@require_POST
def quality_scan(request):
    issues = []
    for item in LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True):
        if not item.set_number.strip():
            issues.append(("set_without_number", "set", item.pk, "warning", "Set ohne Setnummer"))
        if not item.image_url.strip():
            issues.append(("set_without_image", "set", item.pk, "info", "Set ohne Bild"))
    for item in InventoryItem.objects.filter(owner=request.user, archived_at__isnull=True):
        if not item.part_number.strip():
            issues.append(("part_without_number", "inventory", item.pk, "warning", "Teil ohne Teilenummer"))
        if item.reserved_quantity > item.quantity:
            issues.append(("overreserved", "inventory", item.pk, "error", "Reservierung übersteigt Bestand"))
    for item in Order.objects.filter(owner=request.user, deleted_at__isnull=True):
        if not item.items.exists():
            issues.append(("order_without_items", "order", item.pk, "warning", "Bestellung ohne Positionen"))
    for duplicate in LegoSet.objects.filter(owner=request.user, deleted_at__isnull=True).values("set_number").annotate(total=Count("pk")).filter(total__gt=1):
        issues.append(("duplicate_set_number", "set", duplicate["set_number"], "warning", f"Setnummer {duplicate['set_number']} ist doppelt"))
    for duplicate in Part.objects.filter(owner=request.user, deleted_at__isnull=True).values("element_id", "color", "lego_set_id").annotate(total=Count("pk")).filter(total__gt=1):
        issues.append(("duplicate_part", "part", duplicate["element_id"], "warning", f"Teil {duplicate['element_id']} ist im selben Kontext doppelt"))
    for duplicate in InventoryItem.objects.filter(owner=request.user, archived_at__isnull=True).values("part_number", "color", "location_id").annotate(total=Count("pk")).filter(total__gt=1):
        issues.append(("duplicate_inventory", "inventory", duplicate["part_number"], "warning", f"Inventarteil {duplicate['part_number']} ist am selben Lagerort doppelt"))
    for part in Part.objects.filter(owner=request.user, deleted_at__isnull=True).select_related("lego_set"):
        if not part.element_id.strip() or any(char.isspace() for char in part.element_id):
            issues.append(("invalid_element_id", "part", part.pk, "warning", "Element-ID fehlt oder enthält Leerzeichen"))
        if part.lego_set_id and part.lego_set.owner_id != request.user.pk:
            issues.append(("broken_owner_relation", "part", part.pk, "error", "Teil verweist auf ein fremdes Set"))
    known_sources = {"rebrickable", "brickeconomy", "brickset", "bricklink", "legacy"}
    for item in InventoryItem.objects.filter(
        owner=request.user, archived_at__isnull=True
    ).select_related("location"):
        if item.purchase_price < 0 or item.unit_price < 0:
            issues.append(("invalid_inventory_price", "inventory", item.pk, "error", "Inventarpreis ist negativ"))
        if item.location_id and item.location.owner_id != request.user.pk:
            issues.append(("broken_inventory_owner", "inventory", item.pk, "error", "Inventar verweist auf fremden Lagerort"))
    for part in Part.objects.filter(owner=request.user, deleted_at__isnull=True):
        if part.unit_price < 0:
            issues.append(("invalid_part_price", "part", part.pk, "error", "Teilepreis ist negativ"))
    for observation in PriceObservation.objects.filter(owner=request.user):
        if observation.price < 0 or observation.shipping < 0:
            issues.append(("invalid_price_data", "price", observation.pk, "error", "Preisbeobachtung enthält negative Werte"))
        if observation.source and observation.source.casefold() not in known_sources:
            issues.append(("unknown_price_source", "price", observation.pk, "warning", "Preisbeobachtung hat eine unbekannte Quelle"))
    if request.user.is_staff:
        for observation in PriceObservation.objects.filter(owner__isnull=True):
            issues.append(("missing_price_owner", "price", observation.pk, "warning", "Historische Preisbeobachtung ohne Eigentümer (Legacy-Import)"))
    DataQualityIssue.objects.filter(owner=request.user).delete()
    DataQualityIssue.objects.bulk_create(
        [DataQualityIssue(owner=request.user, issue_key=key, entity_type=kind, entity_id=str(pk), severity=severity, message=message) for key, kind, pk, severity, message in issues]
    )
    messages.success(request, f"Datenprüfung abgeschlossen: {len(issues)} Hinweise.")
    return redirect("quality")


@login_required
def quality(request):
    issues = DataQualityIssue.objects.filter(owner=request.user).order_by("severity", "issue_key", "entity_id")
    groups = []
    for issue in issues:
        key = (issue.severity, issue.issue_key, issue.message)
        if not groups or groups[-1]["key"] != key:
            groups.append({"key": key, "severity": issue.severity, "issue_key": issue.issue_key, "message": issue.message, "count": 0, "details": []})
        group = groups[-1]
        group["count"] += 1
        if len(group["details"]) < 50:
            group["details"].append(issue)
    return render(
        request, "core/quality.html",
        {"issues": issues, "issue_groups": groups, "error_count": issues.filter(severity="error").count(), "warning_count": issues.filter(severity="warning").count(), "issue_count": issues.count()},
    )
