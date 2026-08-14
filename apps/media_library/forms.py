import csv
import io
import json
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError

from .models import PrivateDocument

MAX_UPLOAD_SIZE = 5 * 1024 * 1024
ALLOWED = {
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".csv": ("text/csv", ()),
    ".json": ("application/json", (b"{", b"[")),
    ".txt": ("text/plain", ()),
}
EXECUTABLE_SIGNATURES = (b"MZ", b"\x7fELF", b"#!")


class PrivateDocumentForm(forms.ModelForm):
    class Meta:
        model = PrivateDocument
        fields = ("entity_type", "entity_id", "document_type", "title", "file")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > MAX_UPLOAD_SIZE:
            raise ValidationError("Die Datei ist größer als 5 MiB.")
        suffix = Path(upload.name).suffix.lower()
        if suffix not in ALLOWED:
            raise ValidationError("Dieser Dateityp ist nicht erlaubt.")
        expected_mime, signatures = ALLOWED[suffix]
        if upload.content_type and upload.content_type != expected_mime:
            raise ValidationError("MIME-Typ und Dateiendung stimmen nicht überein.")
        if upload.size == 0:
            raise ValidationError("Leere Dateien sind nicht erlaubt.")
        header = upload.read(16)
        upload.seek(0)
        if any(header.startswith(signature) for signature in EXECUTABLE_SIGNATURES):
            raise ValidationError("Ausführbare Dateiinhalte sind nicht erlaubt.")
        if signatures and not any(header.startswith(signature) for signature in signatures):
            raise ValidationError("Dateiendung und Dateiinhalt stimmen nicht überein.")
        if suffix in {".csv", ".json", ".txt"}:
            raw = upload.read()
            upload.seek(0)
            if b"\x00" in raw:
                raise ValidationError("Binäre Inhalte sind nicht erlaubt.")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValidationError("Textdateien müssen UTF-8-kodiert sein.") from exc
            if suffix == ".json":
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValidationError("JSON-Inhalt ist ungültig.") from exc
                if not isinstance(parsed, (dict, list)):
                    raise ValidationError("JSON muss ein Objekt oder eine Liste enthalten.")
            elif suffix == ".csv":
                try:
                    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
                    rows = list(csv.reader(io.StringIO(text), dialect=dialect))
                except csv.Error as exc:
                    raise ValidationError("CSV-Inhalt ist ungültig.") from exc
                if not rows or len(rows[0]) > 100 or len(rows) > 100_001:
                    raise ValidationError("CSV-Struktur oder Zeilenanzahl ist ungültig.")
            elif any(ord(character) < 9 for character in text):
                raise ValidationError("TXT enthält unzulässige Steuerzeichen.")
        upload.validated_mime = expected_mime
        return upload
