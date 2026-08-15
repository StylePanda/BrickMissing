import io
import json
import tempfile
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import AccountSession, RecoveryCode
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet
from apps.media_library.models import PrivateDocument
from apps.organizer.models import Collection, CollectionMember, PersonalNote

PASSWORD = "A-very-long-password-123"  # noqa: S105 - isolated test credential


class PersonalDataExportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            "export-user", "export@example.test", PASSWORD, email_verified=True
        )
        self.other = get_user_model().objects.create_user(
            "foreign-user", "foreign@example.test", PASSWORD, email_verified=True
        )

    def _download(self, user=None, password=PASSWORD, confirmation="EXPORTIEREN"):
        self.client.force_login(user or self.user)
        return self.client.post(
            reverse("data_portability:personal_export_download"),
            {"password": password, "confirmation": confirmation},
        )

    @staticmethod
    def _archive(response):
        return zipfile.ZipFile(io.BytesIO(response.content))

    def test_anonymous_user_cannot_open_or_download_export(self):
        self.assertEqual(
            self.client.get(reverse("data_portability:personal_export")).status_code, 302
        )
        self.assertEqual(
            self.client.post(reverse("data_portability:personal_export_download")).status_code,
            302,
        )

    def test_wrong_password_and_confirmation_are_rejected(self):
        self.assertEqual(
            self._download(password="wrong").status_code,  # noqa: S106 - negative test
            400,
        )
        cache.clear()
        self.assertEqual(self._download(confirmation="wrong").status_code, 400)

    def test_valid_zip_has_required_json_and_safe_serialization(self):
        LegoSet.objects.create(
            owner=self.user,
            set_number="123",
            name="Mein Set",
            purchase_date=date(2025, 1, 2),
            purchase_price=Decimal("12.34"),
        )
        response = self._download()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("attachment", response["Content-Disposition"])
        with self._archive(response) as archive:
            required = {
                "manifest.json",
                "account.json",
                "collections.json",
                "inventory.json",
                "organizer.json",
                "orders.json",
                "notifications.json",
                "audit.json",
                "imports.json",
                "private_documents.json",
            }
            self.assertTrue(required.issubset(archive.namelist()))
            for name in required:
                payload = json.loads(archive.read(name).decode("utf-8"))
                self.assertIsNotNone(payload)
            inventory = json.loads(archive.read("inventory.json"))
            exported_set = inventory["sets"][0]
            self.assertEqual(exported_set["purchase_price"], "12.34")
            self.assertEqual(exported_set["purchase_date"], "2025-01-02")
            self.assertIsInstance(exported_set["id"], str)

    def test_secrets_and_other_users_are_never_exported(self):
        self.user.totp_secret_encrypted = "TOP-SECRET-TOTP"  # noqa: S105
        self.user.rebrickable_api_key_encrypted = "TOP-SECRET-API"  # noqa: S105
        self.user.save()
        RecoveryCode.generate_for(self.user, count=1)
        code_digest = RecoveryCode.objects.get(user=self.user).digest
        AccountSession.objects.create(
            user=self.user, session_key="TOP-SECRET-SESSION", user_agent="Browser"
        )
        LegoSet.objects.create(owner=self.other, set_number="FOREIGN", name="FREMDE DATEN")
        PersonalNote.objects.create(
            owner=self.other, title="FREMDER TITEL", content="FREMDES GEHEIMNIS"
        )
        response = self._download()
        with self._archive(response) as archive:
            raw = "\n".join(
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()
            )
        for forbidden in (
            self.user.password,
            "TOP-SECRET-TOTP",
            "TOP-SECRET-API",
            "TOP-SECRET-SESSION",
            code_digest,
            "foreign@example.test",
            "FREMDE DATEN",
            "FREMDES GEHEIMNIS",
        ):
            self.assertNotIn(forbidden, raw)

    def test_shared_collection_exports_only_own_membership(self):
        collection = Collection.objects.create(
            owner=self.other, name="Gemeinsam", is_shared=True
        )
        CollectionMember.objects.create(collection=collection, user=self.user, role="viewer")
        CollectionMember.objects.create(collection=collection, user=self.other, role="owner")
        response = self._download()
        with self._archive(response) as archive:
            data = json.loads(archive.read("collections.json"))
        self.assertEqual(len(data["own_memberships"]), 1)
        self.assertNotIn(str(self.other.pk), json.dumps(data))
        self.assertNotIn(self.other.username, json.dumps(data))

    def test_private_files_are_owner_scoped_missing_safe_and_traversal_protected(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=directory, PRIVATE_MEDIA_ROOT=directory
        ):
            own = PrivateDocument(
                owner=self.user,
                entity_type="other",
                entity_id="1",
                title="Eigen",
                original_name="../../mein dokument.txt",
                mime_type="text/plain",
                size=6,
            )
            own.file.save(
                "own.txt", SimpleUploadedFile("own.txt", b"OWN-FILE"), save=True
            )
            missing = PrivateDocument.objects.create(
                owner=self.user,
                entity_type="other",
                entity_id="2",
                title="Fehlt",
                file="private_documents/missing.txt",
                original_name="missing.txt",
                mime_type="text/plain",
                size=1,
            )
            foreign = PrivateDocument(
                owner=self.other,
                entity_type="other",
                entity_id="3",
                title="Fremd",
                original_name="foreign.txt",
                mime_type="text/plain",
                size=7,
            )
            foreign.file.save(
                "foreign.txt", SimpleUploadedFile("foreign.txt", b"FOREIGN"), save=True
            )
            traversal = PrivateDocument.objects.create(
                owner=self.user,
                entity_type="other",
                entity_id="4",
                title="Unsicher",
                file="../outside.txt",
                original_name="../outside.txt",
                mime_type="text/plain",
                size=1,
            )
            Path(directory, "outside.txt").write_bytes(b"OUTSIDE")

            response = self._download()
            with self._archive(response) as archive:
                names = archive.namelist()
                self.assertTrue(any(name.startswith(f"files/{own.pk}-") for name in names))
                self.assertFalse(any(".." in name for name in names))
                self.assertNotIn("FOREIGN", response.content.decode("latin-1"))
                metadata = json.loads(archive.read("private_documents.json"))
            self.assertIn(str(missing.pk), metadata["missing_or_unsafe_file_document_ids"])
            self.assertIn(str(traversal.pk), metadata["missing_or_unsafe_file_document_ids"])

    def test_symlink_private_file_is_not_exported(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=directory, PRIVATE_MEDIA_ROOT=directory
        ):
            document = PrivateDocument(
                owner=self.user,
                entity_type="other",
                entity_id="symlink",
                title="Symbolischer Link",
                original_name="linked.txt",
                mime_type="text/plain",
                size=6,
            )
            document.file.save(
                "linked.txt", SimpleUploadedFile("linked.txt", b"SECRET"), save=True
            )
            with patch(
                "apps.data_portability.personal_export.Path.is_symlink", return_value=True
            ):
                response = self._download()
            with self._archive(response) as archive:
                metadata = json.loads(archive.read("private_documents.json"))
                self.assertFalse(any(name.startswith("files/") for name in archive.namelist()))
            self.assertIn(
                str(document.pk), metadata["missing_or_unsafe_file_document_ids"]
            )

    def test_success_creates_minimal_audit_event(self):
        response = self._download()
        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.get(action="account.personal_data_exported")
        self.assertEqual(event.actor, self.user)
        self.assertNotIn("content", event.details)

    def test_unusable_password_account_uses_authenticated_confirmation_flow(self):
        self.user.set_unusable_password()
        self.user.save()
        response = self._download(password="")
        self.assertEqual(response.status_code, 200)

    def test_read_only_audit_command_does_not_create_export_or_change_data(self):
        item = LegoSet.objects.create(owner=self.user, set_number="audit", name="Bleibt")
        before_events = AuditEvent.objects.count()
        call_command("audit_personal_data_export", str(self.user.pk), verbosity=0)
        self.assertTrue(LegoSet.objects.filter(pk=item.pk).exists())
        self.assertEqual(AuditEvent.objects.count(), before_events)

    def test_csrf_is_required_for_download(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            reverse("data_portability:personal_export_download"),
            {"password": PASSWORD, "confirmation": "EXPORTIEREN"},
        )
        self.assertEqual(response.status_code, 403)

    def test_existing_set_export_still_works(self):
        LegoSet.objects.create(owner=self.user, set_number="old-export", name="Bestehend")
        self.client.force_login(self.user)
        response = self.client.get(reverse("data_portability:export_json"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "old-export")
