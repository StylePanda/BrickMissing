from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.media_library.models import PrivateDocument


class Command(BaseCommand):
    help = "Prüft private Uploads read-only auf verwaiste oder fehlende Dateien."

    def handle(self, *args, **options):
        root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        records = list(PrivateDocument.objects.only("file", "deleted_at"))
        referenced = {Path(record.file.name).as_posix(): record for record in records}
        existing = set()
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    existing.add(path.relative_to(root).as_posix())
        orphan_files = sorted(existing - set(referenced))
        missing_records = sorted(name for name in referenced if name not in existing)
        soft_deleted_existing = sorted(
            name
            for name, record in referenced.items()
            if record.deleted_at is not None and name in existing
        )
        categories = (
            ("A Datei ohne DB-Datensatz", orphan_files),
            ("B DB-Datensatz ohne Datei", missing_records),
            ("C Soft-gelöscht mit Datei", soft_deleted_existing),
        )
        for label, paths in categories:
            self.stdout.write(f"{label}: {len(paths)}")
            for path in paths:
                self.stdout.write(f"  {path}")
        self.stdout.write(self.style.WARNING("READ-ONLY: Es wurden keine Dateien verändert."))
