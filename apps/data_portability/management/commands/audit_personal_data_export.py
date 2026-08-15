from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.data_portability.personal_export import personal_export_diagnostics


class Command(BaseCommand):
    help = "Prüft read-only, welche Kategorien ein personenbezogener Export enthalten würde."

    def add_arguments(self, parser):
        parser.add_argument("user_uuid")

    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(pk=options["user_uuid"])
        except (get_user_model().DoesNotExist, ValueError) as exc:
            raise CommandError("Benutzer nicht gefunden.") from exc
        result = personal_export_diagnostics(user)
        self.stdout.write("Personenbezogener Datenexport – Read-only-Audit")
        self.stdout.write(f"Benutzer-ID: {user.pk}")
        for category, count in result["counts"].items():
            self.stdout.write(f"{category}: {count}")
        self.stdout.write(f"Private Dateien: {result['private_files']}")
        self.stdout.write(
            f"Geschätzte Größe privater Dateien: {result['estimated_private_file_bytes']} Bytes"
        )
        self.stdout.write(f"Fehlende/unsichere Dateien: {len(result['missing_files'])}")
        for document_id in result["missing_files"]:
            self.stdout.write(f"WARNUNG PrivateDocument-ID {document_id}: Datei fehlt/unsicher")
        self.stdout.write("Keine Daten oder Dateien wurden verändert; kein Export wurde erzeugt.")
