import csv
import io

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.forms import PersonalDataExportForm
from apps.audit.models import AuditEvent
from apps.catalog.colors import grouped_colors
from apps.catalog.models import LegoSet, Part
from apps.catalog.services import (
    authoritative_lego_export_parts,
    authoritative_lego_export_rows,
    set_part_owned_quantity,
)
from apps.core.rate_limit import limited
from apps.organizer.models import MinifigurePart, SetMinifigure

from .lego_unavailable import analyze_lego_unavailable, parse_lego_unavailable_upload
from .models import ImportBatch
from .personal_export import build_personal_data_export
from .services import parse_csv_upload, parse_json_upload


def _csv_safe(value):
    text = str(value or "")
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


def _eligible_missing_parts(user):
    return authoritative_lego_export_parts(user)


def _export_color_values(user):
    from apps.organizer.models import MinifigurePart

    loose_colors = MinifigurePart.objects.filter(
        minifigure__owner=user, minifigure__lego_set__isnull=True,
        is_spare=False, quantity__gt=models.F("owned_quantity"),
    ).exclude(element_id="").exclude(color_name="").values_list("color_name", flat=True)
    return sorted(set(
        _eligible_missing_parts(user).exclude(color="").values_list("color", flat=True)
    ).union(loose_colors), key=str.casefold)


def _import_page_context(user, *, error=None, selected_colors=(), colors=None):
    color_values = _export_color_values(user) if colors is None else colors
    selected_colors = list(selected_colors)
    return {
        "error": error,
        "color_groups": grouped_colors(color_values),
        "selected_colors": selected_colors,
        "color_summary": (
            f"{len(selected_colors)} Farben" if selected_colors else "Alle Farben"
        ),
    }


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
    figures = [
        {
            "source_id": figure.pk,
            "lego_set__set_number": figure.lego_set.set_number if figure.lego_set_id else None,
            "figure_number": figure.figure_number,
            "name": figure.name,
            "quantity": figure.quantity,
            "owned_quantity": figure.owned_quantity,
            "image_url": figure.image_url,
            "notes": figure.notes,
            "parts": [
                {
                    "part_number": part.part_number, "element_id": part.element_id,
                    "name": part.name, "color_id": part.color_id,
                    "color_name": part.color_name, "quantity": part.quantity,
                    "owned_quantity": part.owned_quantity, "is_spare": part.is_spare,
                    "image_url": part.image_url,
                }
                for part in figure.parts.all()
            ],
        }
        for figure in SetMinifigure.objects.filter(owner=request.user)
        .select_related("lego_set").prefetch_related("parts").order_by("pk")
    ]
    response = JsonResponse(
        {"format": "brickmissing-8", "sets": sets, "parts": parts,
         "minifigures": figures},
        json_dumps_params={"ensure_ascii": False, "indent": 2},
    )
    response["Content-Disposition"] = 'attachment; filename="brickmissing-8-export.json"'
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="export.json",
        details={"sets": len(sets), "parts": len(parts), "minifigures": len(figures)},
        request_id=request.request_id,
    )
    return response


@login_required
def export_missing_csv(request):
    requested_colors = list(
        dict.fromkeys(color for color in request.GET.getlist("color") if color)
    )
    if requested_colors:
        available_colors = _export_color_values(request.user)
        if any(color not in available_colors for color in requested_colors):
            return render(
                request,
                "data_portability/import.html",
                _import_page_context(
                    request.user,
                    error="Die Farbauswahl ist ungültig. Bitte wähle verfügbare Farben aus.",
                    selected_colors=[
                        color for color in requested_colors if color in available_colors
                    ],
                    colors=available_colors,
                ),
                status=400,
            )

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["elementId", "quantity"])
    records = authoritative_lego_export_rows(
        request.user,
        colors=requested_colors,
    )
    if requested_colors and not records:
        return render(
            request,
            "data_portability/import.html",
            _import_page_context(
                request.user,
                error="Für die ausgewählten Farben gibt es keine exportierbaren Teile.",
                selected_colors=requested_colors,
            ),
            status=400,
        )
    for record in records:
        writer.writerow([_csv_safe(record["element_id"]), record["export_quantity"]])
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="brickmissing-fehlteile.csv"'
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="export.csv",
        details={"rows": len(records)},
        request_id=request.request_id,
    )
    return response


@login_required
def personal_export_page(request):
    return render(
        request,
        "data_portability/personal_export.html",
        {"form": PersonalDataExportForm(user=request.user)},
    )


@login_required
@require_POST
def personal_export_download(request):
    if limited(request, "personal-data-export", 3, 3600, per_user=True):
        return HttpResponse("Zu viele Exportanfragen. Bitte später erneut versuchen.", status=429)
    form = PersonalDataExportForm(request.POST, user=request.user)
    if not form.is_valid():
        return render(
            request,
            "data_portability/personal_export.html",
            {"form": form},
            status=400,
        )
    result = build_personal_data_export(request.user)
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="account.personal_data_exported",
        entity_type="personal_data_export",
        details={
            "format_version": "1.0",
            "private_files": result.private_files,
            "missing_private_files": len(result.missing_files),
        },
        request_id=request.request_id,
    )
    response = HttpResponse(result.content, content_type="application/zip")
    response["Content-Disposition"] = (
        'attachment; filename="brickmissing-personenbezogene-daten.zip"'
    )
    response["Cache-Control"] = "no-store, private"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def import_page(request):
    return render(
        request,
        "data_portability/import.html",
        _import_page_context(request.user),
    )


@login_required
@require_http_methods(["GET", "POST"])
def lego_unavailable(request):
    context = {}
    status = 200
    if request.method == "POST":
        try:
            rows = parse_lego_unavailable_upload(request.FILES.get("file"))
            context.update(analyze_lego_unavailable(rows, request.user))
        except ValidationError as exc:
            context["error"] = exc.messages[0]
            status = 400
    return render(
        request,
        "data_portability/lego_unavailable.html",
        context,
        status=status,
    )


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
            request,
            "data_portability/import.html",
            _import_page_context(request.user, error=exc.messages[0]),
            status=400,
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
    for raw in payload.get("minifigures", []):
        if raw["set_number"]:
            exists = SetMinifigure.objects.filter(
                owner=request.user, lego_set__set_number=raw["set_number"],
                figure_number=raw["figure_number"],
            ).exists()
        else:
            exists = SetMinifigure.objects.filter(
                owner=request.user, lego_set__isnull=True, pk=raw["source_id"],
                figure_number=raw["figure_number"],
            ).exists() or SetMinifigure.objects.filter(
                owner=request.user, lego_set__isnull=True, legacy_id=raw["source_id"],
            ).exists()
        duplicates += int(exists)
        new += int(not exists)
    report = {
        "total": len(payload["sets"]) + len(payload["parts"]) + len(payload.get("minifigures", [])),
        "new": new, "duplicates": duplicates, "errors": errors,
        "sets": len(payload["sets"]), "parts": len(payload["parts"]),
        "minifigures": len(payload.get("minifigures", [])),
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
                set_part_owned_quantity(
                    existing, existing.owned_quantity, request.user
                )
                counters["updated"] += 1
            else:
                item = Part(owner=request.user, lego_set=lego_set, **values)
                item.full_clean()
                item.save()
                set_part_owned_quantity(item, item.owned_quantity, request.user)
                counters["created"] += 1
        for raw in locked.payload.get("minifigures", []):
            lego_set = None
            if raw["set_number"]:
                lego_set = set_map.get(raw["set_number"])
                if lego_set is None:
                    lego_set = LegoSet.objects.filter(
                        owner=request.user, set_number=raw["set_number"], deleted_at__isnull=True,
                    ).first()
                if lego_set is None:
                    raise ValidationError("Ein Minifiguren-Set fehlt im Import.")
                existing = SetMinifigure.objects.filter(
                    owner=request.user, lego_set=lego_set, figure_number=raw["figure_number"],
                ).first()
            else:
                existing = SetMinifigure.objects.filter(
                    owner=request.user, lego_set__isnull=True, pk=raw["source_id"],
                    figure_number=raw["figure_number"],
                ).first() or SetMinifigure.objects.filter(
                    owner=request.user, lego_set__isnull=True, legacy_id=raw["source_id"],
                ).first()
            if existing and strategy == "skip":
                counters["duplicates"] += 1
                counters["skipped"] += 1
                continue
            values = {key: raw[key] for key in (
                "figure_number", "name", "quantity", "owned_quantity", "image_url", "notes"
            )}
            if existing:
                counters["duplicates"] += 1
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.full_clean()
                existing.save()
                figure = existing
                counters["updated"] += 1
            else:
                figure = SetMinifigure(
                    owner=request.user, lego_set=lego_set,
                    legacy_id=raw["source_id"] if lego_set is None else None,
                    **values,
                )
                figure.full_clean()
                figure.save()
                counters["created"] += 1
            seen = set()
            for component in raw["parts"]:
                lookup = {key: component[key] for key in ("part_number", "color_id", "is_spare")}
                key = tuple(lookup.values())
                if key in seen:
                    raise ValidationError("Doppelte Minifigurenteile im Import.")
                seen.add(key)
                component_values = {key: value for key, value in component.items() if key not in lookup}
                item, _ = MinifigurePart.objects.update_or_create(
                    minifigure=figure, **lookup, defaults=component_values,
                )
                item.full_clean()
        locked.committed_at = timezone.now()
        locked.report = counters
        locked.save(update_fields=["committed_at", "report"])
        AuditEvent.objects.create(
            actor=request.user, target_user=request.user, action=f"import.{locked.source_format}",
            details=counters, request_id=request.request_id,
        )
    return render(request, "data_portability/report.html", {"report": counters})
