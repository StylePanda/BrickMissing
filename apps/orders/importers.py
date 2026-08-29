import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

MAX_IMPORT_SIZE = 5 * 1024 * 1024


def _value(row, *names):
    lowered = {str(key or "").strip().casefold(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _price(value, row):
    if not value:
        return "0.00"
    text = value.replace("€", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"Zeile {row}: Preis ist ungültig.") from exc
    if amount < 0:
        raise ValidationError(f"Zeile {row}: Preis darf nicht negativ sein.")
    return str(amount)


def parse_order_csv(upload):
    if not upload or upload.size > MAX_IMPORT_SIZE:
        raise ValidationError("Datei fehlt oder ist größer als 5 MiB.")
    raw = upload.read()
    if b"\x00" in raw:
        raise ValidationError("Binärdaten sind nicht als CSV erlaubt.")
    try:
        text = raw.decode("utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValidationError("Ungültige UTF-8-CSV-Datei.") from exc
    if not rows:
        raise ValidationError("Die Datei enthält keine erkennbaren Positionen.")
    items, errors = [], []
    for number, row in enumerate(rows, 2):
        part = _value(row, "part number", "part_number", "item no", "item number", "teilenummer", "element id", "element-id")
        quantity_text = _value(row, "quantity", "qty", "menge", "ordered")
        if not part:
            errors.append(f"Zeile {number}: Teilenummer fehlt.")
            continue
        if not quantity_text:
            errors.append(f"Zeile {number}: Menge fehlt.")
            continue
        try:
            quantity = int(quantity_text)
            if quantity < 1:
                raise ValueError
        except ValueError:
            errors.append(f"Zeile {number}: Menge ist ungültig.")
            continue
        try:
            price = _price(_value(row, "unit price", "unit_price", "price", "preis"), number)
        except ValidationError as exc:
            errors.extend(exc.messages)
            continue
        items.append({
            "part_number": part,
            "name": _value(row, "name", "item name", "bezeichnung"),
            "color": _value(row, "color", "farbe", "color id"),
            "quantity": quantity,
            "unit_price": price,
            "notes": _value(row, "notes", "notizen"),
        })
    if not items and errors:
        raise ValidationError(errors[0])
    return items, errors
