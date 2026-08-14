import csv
import io

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part
from apps.core.rate_limit import limited

from .models import ImportBatch
from .services import parse_csv_upload, parse_json_upload


def _csv_safe(value):
    text = str(value or "")
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


@login_required
def export_json(request):
    sets = list(
        LegoSet.objects.filter(owner=request.user).values(
            "set_number",
            "name",
            "theme",
            "year",
            "total_parts",
            "favorite",
            "image_url",
            "notes",
            "deleted_at",
        )
    )
    parts = list(
        Part.objects.filter(owner=request.user).values(
            "element_id",
            "design_id",
            "part_number",
            "name",
            "color",
            "quantity",
            "owned_quantity",
            "status",
            "priority",
            "unit_price",
            "supplier",
            "notes",
            "image_url",
            "deleted_at",
            "lego_set__set_number",
        )
    )
    response = JsonResponse(
        {"format": "brickmissing-8", "sets": sets, "parts": parts},
        json_dumps_params={"ensure_ascii": False, "indent": 2},
    )
    response["Content-Disposition"] = 'attachment; filename="brickmissing-8-export.json"'
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="export.json",
        details={"sets": len(sets), "parts": len(parts)},
        request_id=request.request_id,
    )
    return response


@login_required
def export_missing_csv(request):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["Element-ID", "Part Number", "Name", "Farbe", "BenÃ¶tigt", "Vorhanden", "Fehlt", "Set"]
    )
    records = Part.objects.filter(
        owner=request.user, status=Part.Status.MISSING, deleted_at__isnull=True
    ).select_related("lego_set")
    for part in records:
        writer.writerow(
            [
                _csv_safe(part.element_id),
                _csv_safe(part.part_number),
                _csv_safe(part.name),
                _csv_safe(part.color),
                part.quantity,
                part.owned_quantity,
                part.missing_quantity,
                _csv_safe(part.lego_set.set_number if part.lego_set else ""),
            ]
        )
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="brickmissing-fehlteile.csv"'
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="export.csv",
        details={"rows": records.count()},
        request_id=request.request_id,
    )
    return response


@login_required
def import_page(request):
    return render(request, "data_portability/import.html")


def _preview(request, source_format):
    if limited(request, "mass-import", 20, 3600, per_user=True):
        return HttpResponse("Rate limit exceeded", status=429)
    try:
        payload, errors = (
            parse_json_upload(request.FILES.get("file"))
            if source_format == "json"
            else parse_csv_upload(request.FILES.get("file"))
        )
    except ValidationError as exc:
        return render(
            request, "data_portability/import.html", {"error": exc.messages[0]}, status=400
        )
    new = duplicates = 0
    for raw in payload["sets"]:
        exists = LegoSet.objects.filter(
            owner=request.user, set_number=raw["set_number"], deleted_at__isnull=True
        ).exists()
        duplicates += int(exists)
        new += int(not exists)
    for raw in payload["parts"]:
        exists = Part.objects.filter(
            owner=request.user, element_id=raw["element_id"], color=raw["color"],
            lego_set__set_number=raw["set_number"] or None, deleted_at__isnull=True,
        ).exists()
        duplicates += int(exists)
        new += int(not exists)
    report = {
        "total": len(payload["sets"]) + len(payload["parts"]),
        "new": new, "duplicates": duplicates, "errors": errors,
        "sets": len(payload["sets"]), "parts": len(payload["parts"]),
    }
    batch = ImportBatch.objects.create(
        owner=request.user, source_format=source_format, payload=payload, report=report
    )
    return render(request, "data_portability/preview.html", {"batch": batch, "report": report})


@login_required
@require_POST
def import_json(request):
    return _preview(request, "json")


@login_required
@require_POST
def import_csv(request):
    return _preview(request, "csv")


@login_required
@require_POST
def import_confirm(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, owner=request.user, committed_at__isnull=True)
    strategy = request.POST.get("strategy", "skip")
    if strategy not in {"skip", "update", "merge", "error"}:
        return render(request, "data_portability/import.html", {"error": "UngÃ¼ltige Duplikatstrategie."}, status=400)
    if batch.report.get("errors"):
        return render(request, "data_portability/preview.html", {"batch": batch, "report": batch.report}, status=400)
    if strategy == "error" and batch.report.get("duplicates"):
        report = {**batch.report, "commit_errors": ["Import enthÃ¤lt Duplikate; Strategie ERROR bricht vollstÃ¤ndig ab."]}
        return render(request, "data_portability/preview.html", {"batch": batch, "report": report}, status=400)
    counters = {"total": batch.report["total"], "created": 0, "updated": 0, "skipped": 0, "duplicates": 0, "errors": []}
    with transaction.atomic():
        locked = ImportBatch.objects.select_for_update().get(pk=batch.pk, owner=request.user, committed_at__isnull=True)
        set_map = {}
        for raw in locked.payload["sets"]:
            existing = LegoSet.objects.filter(owner=request.user, set_number=raw["set_number"], deleted_at__isnull=True).first()
            values = {key: value for key, value in raw.items() if key not in {"row", "set_number"}}
            if existing:
                counters["duplicates"] += 1
                if strategy == "skip":
                    counters["skipped"] += 1
                else:
                    for key, value in values.items():
                        if strategy != "merge" or value not in {"", None}:
                            setattr(existing, key, value)
                    existing.full_clean()
                    existing.save()
                    counters["updated"] += 1
                item = existing
            else:
                item = LegoSet.objects.create(owner=request.user, set_number=raw["set_number"], **values)
                counters["created"] += 1
            set_map[raw["set_number"]] = item
        for raw in locked.payload["parts"]:
            lego_set = set_map.get(raw["set_number"])
            if lego_set is None and raw["set_number"]:
                lego_set = LegoSet.objects.filter(owner=request.user, set_number=raw["set_number"], deleted_at__isnull=True).first()
            existing = Part.objects.filter(owner=request.user, element_id=raw["element_id"], color=raw["color"], lego_set=lego_set, deleted_at__isnull=True).first()
            values = {key: value for key, value in raw.items() if key not in {"row", "set_number"}}
            if existing:
                counters["duplicates"] += 1
                if strategy == "skip":
                    counters["skipped"] += 1
                    continue
                if strategy == "merge":
                    values["quantity"] += existing.quantity
                    values["owned_quantity"] += existing.owned_quantity
                    values["owned_quantity"] = min(values["owned_quantity"], values["quantity"])
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.status = Part.Status.MISSING if existing.owned_quantity < existing.quantity else Part.Status.FOUND
                existing.full_clean()
                existing.save()
                counters["updated"] += 1
            else:
                item = Part(owner=request.user, lego_set=lego_set, **values)
                item.full_clean()
                item.save()
                counters["created"] += 1
        locked.committed_at = timezone.now()
        locked.report = counters
        locked.save(update_fields=["committed_at", "report"])
        AuditEvent.objects.create(
            actor=request.user, target_user=request.user, action=f"import.{locked.source_format}",
            details=counters, request_id=request.request_id,
        )
    return render(request, "data_portability/report.html", {"report": counters})


