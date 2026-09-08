from __future__ import annotations

import csv
import io
import json
from pathlib import PurePath

from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.catalog.models import Part

MAX_UPLOAD_SIZE = 2 * 1024 * 1024
MAX_ROWS = 10_000
MAX_ERROR_LENGTH = 5_000
REQUIRED_FIELDS = ("elementId", "quantity", "error")


def _quantity(value, row_number):
    if isinstance(value, bool):
        raise ValidationError(f"Zeile {row_number}: quantity ist keine ganze Zahl.")
    try:
        quantity = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Zeile {row_number}: quantity ist keine ganze Zahl."
        ) from exc
    if isinstance(value, float) or str(value).strip() != str(quantity):
        raise ValidationError(f"Zeile {row_number}: quantity ist keine ganze Zahl.")
    if quantity < 0:
        raise ValidationError(f"Zeile {row_number}: quantity darf nicht negativ sein.")
    if quantity > 2_147_483_647:
        raise ValidationError(f"Zeile {row_number}: quantity ist zu groß.")
    return quantity


def _row(raw, row_number):
    if not isinstance(raw, dict):
        raise ValidationError(f"Zeile {row_number}: Eintrag ist kein Objekt.")
    if set(raw) != set(REQUIRED_FIELDS):
        raise ValidationError(
            f"Zeile {row_number}: Erwartet werden genau elementId, quantity und error."
        )
    element_id = raw["elementId"]
    error = raw["error"]
    if not isinstance(element_id, str) or not element_id.strip():
        raise ValidationError(f"Zeile {row_number}: elementId fehlt.")
    element_id = element_id.strip()
    if len(element_id) > Part._meta.get_field("element_id").max_length:
        raise ValidationError(f"Zeile {row_number}: elementId ist zu lang.")
    if not isinstance(error, str):
        raise ValidationError(f"Zeile {row_number}: error muss Text sein.")
    if len(error) > MAX_ERROR_LENGTH:
        raise ValidationError(f"Zeile {row_number}: error ist zu lang.")
    return {
        "source_index": row_number,
        "element_id": element_id,
        "quantity": _quantity(raw["quantity"], row_number),
        "error": error,
    }


def _parse_csv(raw_bytes):
    try:
        text = raw_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), dialect="excel", strict=True)
        if tuple(reader.fieldnames or ()) != REQUIRED_FIELDS:
            raise ValidationError(
                "CSV-Kopfzeile muss genau elementId,quantity,error enthalten."
            )
        rows = []
        for row_number, raw in enumerate(reader, 2):
            if row_number - 1 > MAX_ROWS:
                raise ValidationError("Die Datei enthält zu viele Einträge.")
            if None in raw:
                raise ValidationError(f"Zeile {row_number}: CSV-Zeile ist ungültig.")
            rows.append(_row(raw, row_number))
    except UnicodeDecodeError as exc:
        raise ValidationError("Die CSV-Datei ist nicht gültig UTF-8-kodiert.") from exc
    except csv.Error as exc:
        raise ValidationError("Die CSV-Datei ist ungültig.") from exc
    return rows


def _parse_json(raw_bytes):
    try:
        payload = json.loads(raw_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError("Die JSON-Datei ist ungültig.") from exc
    if not isinstance(payload, list):
        raise ValidationError("Die JSON-Wurzel muss eine Liste sein.")
    if len(payload) > MAX_ROWS:
        raise ValidationError("Die Datei enthält zu viele Einträge.")
    return [_row(raw, row_number) for row_number, raw in enumerate(payload, 1)]


def parse_lego_unavailable_upload(upload):
    if not upload:
        raise ValidationError("Bitte wähle eine CSV- oder JSON-Datei aus.")
    if upload.size > MAX_UPLOAD_SIZE:
        raise ValidationError("Die Datei ist größer als 2 MiB.")
    extension = PurePath(str(upload.name or "")).suffix.lower()
    if extension not in {".csv", ".json"}:
        raise ValidationError("Nur CSV- und JSON-Dateien werden unterstützt.")
    raw_bytes = upload.read()
    if not raw_bytes:
        raise ValidationError("Die Datei ist leer.")
    if b"\x00" in raw_bytes:
        raise ValidationError("Die Datei enthält ungültige Binärdaten.")
    rows = _parse_csv(raw_bytes) if extension == ".csv" else _parse_json(raw_bytes)
    if not rows:
        raise ValidationError("Die Datei enthält keine Einträge.")
    return rows


def analyze_lego_unavailable(rows, user):
    element_ids = {row["element_id"] for row in rows}
    parts = (
        Part.objects.filter(
            Q(lego_set__isnull=True) | Q(lego_set__owner=user),
            owner=user,
            deleted_at__isnull=True,
            element_id__in=element_ids,
        )
        .select_related("lego_set")
        .order_by("element_id", "created_at", "pk")
    )
    parts_by_element = {}
    for part in parts:
        parts_by_element.setdefault(part.element_id, []).append(part)

    results = []
    matched_entries = 0
    for row in rows:
        matches = parts_by_element.get(row["element_id"], [])
        matched_entries += bool(matches)
        results.append({**row, "matches": matches, "matched": bool(matches)})
    return {
        "results": results,
        "summary": {
            "entries": len(rows),
            "matched": matched_entries,
            "unmatched": len(rows) - matched_entries,
            "quantity": sum(row["quantity"] for row in rows),
        },
    }
