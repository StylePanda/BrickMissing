import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import PrivateDocument


class OrphanPrivateFileAuditTests(TestCase):
    def test_command_reports_all_categories_without_changes(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=directory, PRIVATE_MEDIA_ROOT=directory
        ):
            user = get_user_model().objects.create_user(
                "orphan-audit", "orphan@example.test", "A-very-long-password-123"
            )
            soft = PrivateDocument(
                owner=user, entity_type="other", entity_id="1", title="Soft",
                original_name="soft.txt", mime_type="text/plain", size=4,
                deleted_at=timezone.now(),
            )
            soft.file.save("soft.txt", SimpleUploadedFile("soft.txt", b"soft"), save=True)
            missing = PrivateDocument.objects.create(
                owner=user, entity_type="other", entity_id="2", title="Missing",
                file="users/missing.txt", original_name="missing.txt", mime_type="text/plain",
                size=1,
            )
            orphan = Path(directory) / "users" / "orphan.txt"
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan.write_text("orphan", encoding="utf-8")
            output = io.StringIO()

            call_command("audit_orphan_private_files", stdout=output)

            text = output.getvalue()
            self.assertIn("A Datei ohne DB-Datensatz: 1", text)
            self.assertIn("B DB-Datensatz ohne Datei: 1", text)
            self.assertIn("C Soft-gelöscht mit Datei: 1", text)
            self.assertTrue(orphan.exists())
            self.assertTrue(Path(soft.file.path).exists())
            self.assertTrue(PrivateDocument.objects.filter(pk=missing.pk).exists())
