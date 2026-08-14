import csv
import io
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from apps.catalog.models import Part

MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_SETS = 10_000
MAX_PARTS = 100_000


def _integer(value, field, row, *, minimum=0, maximum=2_147_483_647):
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Zeile {row}: {field} ist keine ganze Zahl.") from exc
    if result < minimum:
        raise ValidationError(f"Zeile {row}: {field} darf nicht kleiner als {minimum} sein.")
    if result > maximum:
        raise ValidationError(f"Zeile {row}: {field} ist zu groß.")
    return result


def _decimal(value, field, row):
    try:
        result = Decimal(str(value if value is not None and value != "" else 0))
        result = result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"Zeile {row}: {field} ist keine gültige Dezimalzahl.") from exc
    if result < 0 or result > Decimal("9999999999.99"):
        raise ValidationError(f"Zeile {row}: {field} liegt außerhalb des erlaubten Bereichs.")
    return str(result)


def _date(value, field, row):
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValidationError(f"Zeile {row}: {field} ist kein gültiges ISO-Datum.") from exc


def _text(value, field, row, maximum, required=False):
    if value is None or isinstance(value, (dict, list)):
        raise ValidationError(f"Zeile {row}: {field} ist ungültig.")
    result = str(value).strip()
    if required and not result:
        raise ValidationError(f"Zeile {row}: {field} fehlt.")
    if len(result) > maximum:
        raise ValidationError(f"Zeile {row}: {field} ist zu lang.")
    return result


def _normal_part(raw, row):
    element = _text(raw.get("element_id"), "Element-ID", row, 100, required=True)
    name = _text(raw.get("name"), "Name", row, 255, required=True)
    quantity = _integer(raw.get("quantity", 0), "Menge", row)
    owned = _integer(raw.get("owned_quantity", 0), "Vorhanden", row)
    if owned > quantity:
        raise ValidationError(f"Zeile {row}: Vorhanden übersteigt die benötigte Menge.")
    status = raw.get("status") or (Part.Status.MISSING if owned < quantity else Part.Status.FOUND)
    if status not in Part.Status.values:
        raise ValidationError(f"Zeile {row}: Status ist ungültig.")
    return {
        "element_id": element, "design_id": _text(raw.get("design_id", ""), "Design-ID", row, 100),
        "part_number": _text(raw.get("part_number", ""), "Part Number", row, 100),
        "name": name, "color": _text(raw.get("color", ""), "Farbe", row, 150),
        "quantity": quantity, "owned_quantity": owned, "status": status,
        "unit_price": _decimal(raw.get("unit_price", 0), "Stückpreis", row),
        "priority": _text(raw.get("priority", "normal"), "Priorität", row, 16),
        "supplier": _text(raw.get("supplier", ""), "Lieferant", row, 255),
        "notes": _text(raw.get("notes", ""), "Notizen", row, 10_000),
        "image_url": _text(raw.get("image_url", ""), "Bild-URL", row, 1000),
        "set_number": _text(raw.get("lego_set__set_number", ""), "Setnummer", row, 100),
        "row": row,
    }


def parse_json_upload(upload):
    if not upload or upload.size > MAX_FILE_SIZE:
        raise ValidationError("Datei fehlt oder ist größer als 5 MiB.")
    raw_bytes = upload.read()
    if b"\x00" in raw_bytes:
        raise ValidationError("Binäre Daten sind nicht als JSON erlaubt.")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError("Ungültige UTF-8-JSON-Datei.") from exc
    if not isinstance(payload, dict) or payload.get("format") not in {"brickmissing-8", "brickmissing"}:
        raise ValidationError("Unbekanntes Importformat.")
    if not isinstance(payload.get("sets", []), list) or not isinstance(payload.get("parts", []), list):
        raise ValidationError("Sets und Parts müssen Listen sein.")
    if len(payload.get("sets", [])) > MAX_SETS or len(payload.get("parts", [])) > MAX_PARTS:
        raise ValidationError("Import enthält zu viele Datensätze.")
    sets, parts, errors = [], [], []
    for row, raw in enumerate(payload.get("sets", []), 1):
        try:
            if not isinstance(raw, dict):
                raise ValidationError(f"Zeile {row}: Set ist kein Objekt.")
            sets.append({
                "set_number": _text(raw.get("set_number"), "Setnummer", row, 100, True),
                "name": _text(raw.get("name"), "Name", row, 255, True),
                "theme": _text(raw.get("theme", ""), "Thema", row, 150),
                "year": _integer(raw["year"], "Jahr", row, minimum=1900) if raw.get("year") not in {None, ""} else None,
                "total_parts": _integer(raw.get("total_parts", 0), "Teilezahl", row),
                "purchase_date": _date(raw.get("purchase_date"), "Kaufdatum", row),
                "purchase_price": _decimal(raw.get("purchase_price", 0), "Kaufpreis", row),
                "current_value": _decimal(raw.get("current_value", 0), "Aktueller Wert", row),
                "favorite": bool(raw.get("favorite")), "image_url": _text(raw.get("image_url", ""), "Bild-URL", row, 1000),
                "notes": _text(raw.get("notes", ""), "Notizen", row, 10_000), "row": row,
            })
        except ValidationError as exc:
            errors.extend(exc.messages)
    for row, raw in enumerate(payload.get("parts", []), 1):
        try:
            if not isinstance(raw, dict):
                raise ValidationError(f"Zeile {row}: Part ist kein Objekt.")
            parts.append(_normal_part(raw, row))
        except ValidationError as exc:
            errors.extend(exc.messages)
    return {"sets": sets, "parts": parts}, errors


def parse_csv_upload(upload):
    if not upload or upload.size > MAX_FILE_SIZE:
        raise ValidationError("CSV fehlt oder ist größer als 5 MiB.")
    raw_bytes = upload.read()
    if b"\x00" in raw_bytes:
        raise ValidationError("Binäre Daten sind nicht als CSV erlaubt.")
    try:
        text = raw_bytes.decode("utf-8-sig")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames or len(reader.fieldnames) > 100:
            raise ValidationError("CSV-Kopfzeile ist ungültig.")
        normalized_headers = [str(value or "").strip().casefold() for value in reader.fieldnames]
        if len(normalized_headers) != len(set(normalized_headers)):
            raise ValidationError("CSV enthält doppelte Spaltennamen.")
        allowed_headers = {
            "element-id", "element id", "item no", "part_number", "part number",
            "name", "farbe", "color", "color id", "benötigt", "qty", "quantity",
            "vorhanden", "owned_quantity",
            "unit price", "unit_price",
        }
        if any(header not in allowed_headers for header in normalized_headers):
            raise ValidationError("CSV enthält unerwartete Spalten.")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValidationError("Ungültige UTF-8-CSV-Datei.") from exc
    if len(rows) > MAX_PARTS:
        raise ValidationError("CSV enthält zu viele Zeilen.")
    parts, errors = [], []
    for row_number, raw in enumerate(rows, 2):
        mapped = {
            "element_id": raw.get("Element-ID") or raw.get("Element ID") or raw.get("Item No") or raw.get("part_number"),
            "part_number": raw.get("Part Number") or raw.get("part_number") or "",
            "name": raw.get("Name") or raw.get("name") or raw.get("Item No"),
            "color": raw.get("Farbe") or raw.get("Color") or raw.get("Color ID") or "",
            "quantity": raw.get("Benötigt") or raw.get("Qty") or raw.get("quantity") or 1,
            "owned_quantity": raw.get("Vorhanden") or raw.get("owned_quantity") or 0,
            "unit_price": raw.get("Unit Price") or raw.get("unit_price") or 0,
        }
        try:
            parts.append(_normal_part(mapped, row_number))
        except ValidationError as exc:
            errors.extend(exc.messages)
    return {"sets": [], "parts": parts}, errors
