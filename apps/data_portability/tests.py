import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import LegoSet, Part
from apps.core.models import Notification
from apps.data_portability.legacy_source import LegacySource, LegacySourceError, SQLiteLegacySource
from apps.data_portability.management.commands.migrate_legacy_brickmissing import (
    legacy_password,
)
from apps.data_portability.models import LegacyArchiveRecord
from apps.integrations.models import PriceObservation, ValueSnapshot


class ImportExportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "portable", "portable@example.test", "A-very-long-password-123", email_verified=True
        )
        self.client.force_login(self.user)

    def test_json_import_is_owned(self):
        payload = {
            "format": "brickmissing-8",
            "sets": [{"set_number": "100", "name": "Test"}],
            "parts": [
                {
                    "element_id": "3001",
                    "name": "Brick",
                    "quantity": 2,
                    "owned_quantity": 1,
                    "lego_set__set_number": "100",
                }
            ],
        }
        upload = SimpleUploadedFile(
            "import.json", json.dumps(payload).encode(), content_type="application/json"
        )
        preview = self.client.post(reverse("data_portability:import_json"), {"file": upload})
        self.assertContains(preview, "Importvorschau")
        batch = preview.context["batch"]
        self.client.post(
            reverse("data_portability:import_confirm", args=[batch.pk]),
            {"strategy": "error"},
        )
        self.assertEqual(LegoSet.objects.get().owner, self.user)
        self.assertEqual(Part.objects.get().owner, self.user)

    def test_semantic_errors_are_reported_without_500_or_partial_write(self):
        payload = {
            "format": "brickmissing-8",
            "sets": [{"set_number": "100", "name": "Valid"}],
            "parts": [{"element_id": "3001", "name": "Bad", "quantity": "not-a-number"}],
        }
        upload = SimpleUploadedFile(
            "bad.json", json.dumps(payload).encode(), content_type="application/json"
        )
        response = self.client.post(
            reverse("data_portability:import_json"), {"file": upload}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "keine ganze Zahl")
        batch = response.context["batch"]
        commit = self.client.post(
            reverse("data_portability:import_confirm", args=[batch.pk]),
            {"strategy": "update"},
        )
        self.assertEqual(commit.status_code, 400)
        self.assertFalse(LegoSet.objects.exists())
        self.assertFalse(Part.objects.exists())

    def test_duplicate_strategies_are_explicit(self):
        Part.objects.create(owner=self.user, element_id="3001", name="Old", quantity=1)
        payload = {
            "format": "brickmissing-8", "sets": [],
            "parts": [{"element_id": "3001", "name": "New", "quantity": 2}],
        }
        upload = SimpleUploadedFile("duplicate.json", json.dumps(payload).encode())
        preview = self.client.post(reverse("data_portability:import_json"), {"file": upload})
        self.assertEqual(preview.context["report"]["duplicates"], 1)
        batch = preview.context["batch"]
        response = self.client.post(
            reverse("data_portability:import_confirm", args=[batch.pk]), {"strategy": "error"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Part.objects.get().name, "Old")

    def test_csv_injection_is_escaped(self):
        Part.objects.create(owner=self.user, element_id="=CMD()", name="@evil", quantity=1)
        response = self.client.get(reverse("data_portability:export_csv"))
        body = b"".join(response.streaming_content) if response.streaming else response.content
        self.assertIn(b"'=CMD()", body)
        self.assertIn(b"'@evil", body)

    def test_adversarial_import_matrix_never_returns_500(self):
        cases = [
            ("json", SimpleUploadedFile("bad.json", b"\xff", content_type="application/json")),
            ("json", SimpleUploadedFile("root.json", b"[]", content_type="application/json")),
            ("json", SimpleUploadedFile("empty.json", b"", content_type="application/json")),
            ("json", SimpleUploadedFile("oversize.json", b"x" * (5 * 1024 * 1024 + 1), content_type="application/json")),
            ("json", SimpleUploadedFile("date.json", json.dumps({"format": "brickmissing-8", "sets": [{"set_number": "1", "name": "x", "purchase_date": "2026-99-99"}]}).encode(), content_type="application/json")),
            ("json", SimpleUploadedFile("enum.json", json.dumps({"format": "brickmissing-8", "parts": [{"element_id": "1", "name": "x", "status": "impossible"}]}).encode(), content_type="application/json")),
            ("json", SimpleUploadedFile("decimal.json", json.dumps({"format": "brickmissing-8", "parts": [{"element_id": "1", "name": "x", "unit_price": "1e999999"}]}).encode(), content_type="application/json")),
            ("json", SimpleUploadedFile("many.json", json.dumps({"format": "brickmissing-8", "sets": [{"set_number": str(index), "name": "x"} for index in range(10_001)]}).encode(), content_type="application/json")),
            ("json", SimpleUploadedFile("deep.json", json.dumps({"format": "brickmissing-8", "parts": [{"element_id": {"nested": 1}, "name": "x"}]}).encode(), content_type="application/json")),
            ("csv", SimpleUploadedFile("bad.csv", b"\xff", content_type="text/csv")),
            ("csv", SimpleUploadedFile("empty.csv", b"", content_type="text/csv")),
            ("csv", SimpleUploadedFile("missing.csv", b"Name,Qty\nBrick,1\n", content_type="text/csv")),
            ("csv", SimpleUploadedFile("duplicate.csv", b"Name,Name\na,b\n", content_type="text/csv")),
            ("csv", SimpleUploadedFile("unexpected.csv", b"Name,Evil\na,b\n", content_type="text/csv")),
            ("csv", SimpleUploadedFile("negative.csv", "Element-ID,Name,Qty\n3001,Brick,-1\n".encode(), content_type="text/csv")),
            ("csv", SimpleUploadedFile("bom.csv", b"\xef\xbb\xbfElement-ID,Name,Qty\n3001,Brick,1\n", content_type="text/csv")),
        ]
        for kind, upload in cases:
            response = self.client.post(reverse(f"data_portability:import_{kind}"), {"file": upload})
            self.assertLess(response.status_code, 500)


class LegacyActualMigrationTests(TestCase):
    def test_sqlite_dry_run_rolls_back_every_target_write(self):
        source = Path(__file__).resolve().parents[2] / "data" / "brickmissing.db"
        output = io.StringIO()
        call_command(
            "migrate_legacy_brickmissing", source=source, dry_run=True, stdout=output
        )
        self.assertIn("DRY-RUN", output.getvalue())
        self.assertFalse(get_user_model().objects.filter(legacy_id__isnull=False).exists())
        self.assertFalse(LegacyArchiveRecord.objects.exists())

    def test_repeated_sqlite_import_is_idempotent(self):
        source = Path(__file__).resolve().parents[2] / "data" / "brickmissing.db"
        call_command("migrate_legacy_brickmissing", source=source, stdout=io.StringIO())
        first = (get_user_model().objects.count(), LegoSet.objects.count(), Part.objects.count())
        call_command("migrate_legacy_brickmissing", source=source, stdout=io.StringIO())
        self.assertEqual(
            (get_user_model().objects.count(), LegoSet.objects.count(), Part.objects.count()),
            first,
        )

    def test_repeated_import_preserves_manual_legacy_verification_and_real_email(self):
        source = Path(__file__).resolve().parents[2] / "data" / "brickmissing.db"
        call_command("migrate_legacy_brickmissing", source=source, stdout=io.StringIO())
        user = get_user_model().objects.filter(legacy_id__isnull=False, email__endswith="@invalid.local").first()
        self.assertIsNotNone(user)
        user.email = "onboarded@example.test"
        user.email_verified = True
        user.save(update_fields=["email", "email_verified", "updated_at"])
        call_command("migrate_legacy_brickmissing", source=source, stdout=io.StringIO())
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertEqual(user.email, "onboarded@example.test")

    def test_import_failure_rolls_back_partial_target_state(self):
        source = Path(__file__).resolve().parents[2] / "data" / "brickmissing.db"

        def fail_after_write(command, legacy, fingerprint):
            get_user_model().objects.create_user("partial", "partial@example.test")
            raise CommandError("intentional")

        with patch(
            "apps.data_portability.management.commands.migrate_legacy_brickmissing.Command._import",
            autospec=True,
            side_effect=fail_after_write,
        ), self.assertRaisesRegex(CommandError, "intentional"):
            call_command("migrate_legacy_brickmissing", source=source, stdout=io.StringIO())
        self.assertFalse(get_user_model().objects.filter(username="partial").exists())

    def test_real_source_imports_into_isolated_test_database_without_source_mutation(self):
        source = Path(__file__).resolve().parents[2] / "data" / "brickmissing.db"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        call_command("migrate_legacy_brickmissing", source=source, stdout=io.StringIO())
        user_model = get_user_model()
        self.assertEqual(user_model.objects.filter(legacy_id__isnull=False).count(), 3)
        self.assertEqual(LegoSet.objects.filter(legacy_id__isnull=False).count(), 78)
        self.assertEqual(Part.objects.filter(legacy_id__isnull=False).count(), 1679)
        self.assertEqual(Notification.objects.filter(legacy_id__isnull=False).count(), 1677)
        self.assertEqual(PriceObservation.objects.filter(legacy_id__isnull=False).count(), 328)
        self.assertEqual(ValueSnapshot.objects.filter(legacy_id__isnull=False).count(), 194)
        with tempfile.TemporaryDirectory(prefix="bm8-reconciliation-") as temporary:
            output = Path(temporary) / "report.json"
            call_command(
                "validate_legacy_migration", source=source, output=output,
                stdout=io.StringIO(),
            )
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["source_unchanged"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_reconciliation_detects_value_relation_missing_extra_and_orphan_corruption(self):
        source = Path(__file__).resolve().parents[2] / "data" / "brickmissing.db"
        call_command("migrate_legacy_brickmissing", source=source, stdout=io.StringIO())
        part = Part.objects.filter(legacy_id__isnull=False).exclude(lego_set=None).first()
        other_set = LegoSet.objects.filter(legacy_id__isnull=False).exclude(pk=part.lego_set_id).first()
        other_user = get_user_model().objects.filter(legacy_id__isnull=False).exclude(pk=part.owner_id).first()
        Part.objects.filter(pk=part.pk).update(
            owner=other_user,
            lego_set=other_set,
            name="deliberately changed",
            quantity=part.quantity + 1,
            status=Part.Status.RECEIVED if part.status != Part.Status.RECEIVED else Part.Status.MISSING,
            is_present=not part.is_present,
            unit_price=part.unit_price + 1,
            deleted_at=timezone.now(),
        )
        missing = Notification.objects.filter(legacy_id__isnull=False).first()
        Notification.objects.filter(pk=missing.pk).update(legacy_id=None)
        owner = get_user_model().objects.filter(legacy_id__isnull=False).first()
        LegoSet.objects.create(
            owner=owner, legacy_id=9_999_999_999, set_number="extra-target", name="Extra"
        )
        orphan = LegacyArchiveRecord.objects.filter(
            source_table="history", classification="orphaned_relation_preserved"
        ).first()
        if orphan:
            orphan.payload = {"corrupted": True}
            orphan.save(update_fields=["payload"])
        with tempfile.TemporaryDirectory(prefix="bm8-negative-reconciliation-") as temporary:
            output = Path(temporary) / "report.json"
            with self.assertRaises(CommandError):
                call_command(
                    "validate_legacy_migration", source=source, output=output,
                    stdout=io.StringIO(),
                )
            mismatches = json.loads(output.read_text(encoding="utf-8"))["mismatches"]
        fields = {item["field"] for item in mismatches}
        self.assertTrue(
            {"owner", "lego_set", "name", "quantity", "status", "is_present", "unit_price", "deleted_at", "legacy_id"}.issubset(fields)
        )
        self.assertTrue(any(item["reason"] == "unexplained extra target row" for item in mismatches))
        if orphan:
            self.assertTrue(any(item["table"] == "history_orphans" for item in mismatches))


class LegacySourceSafetyTests(TestCase):
    class FakeSource(LegacySource):
        def _execute(self, sql, params):
            return []

        def table_names(self):
            return set()

        def columns(self, table):
            return []

    def test_source_abstraction_rejects_every_non_select_statement(self):
        source = self.FakeSource()
        for sql in (
            "INSERT INTO users VALUES (1)", "UPDATE users SET name='x'",
            "DELETE FROM users", "ALTER TABLE users ADD x INT", "CREATE TABLE x (id INT)",
            "DROP TABLE users", "TRUNCATE TABLE users", "SELECT 1; DELETE FROM users",
        ):
            with self.subTest(sql=sql), self.assertRaises(LegacySourceError):
                source.execute(sql)

    def test_only_supported_v7_password_hashes_are_adopted(self):
        compatible = "pbkdf2_sha256$310000$c2FsdA==$ZGlnZXN0"
        self.assertEqual(legacy_password(compatible), f"brickmissing_{compatible}")
        for unsafe in (None, "", "plaintext", "bcrypt$payload", "pbkdf2_sha256$bad"):
            self.assertIsNone(legacy_password(unsafe))

    def test_source_and_target_identity_is_rejected_before_connection(self):
        same = {"HOST": "127.0.0.1", "PORT": "3306", "NAME": "brickmissing"}

        class Connections(dict):
            pass

        fake_connections = Connections(default=type("C", (), {"settings_dict": same})())
        fake_connections["legacy_v7"] = type("C", (), {"settings_dict": dict(same)})()
        with patch(
            "apps.data_portability.management.commands.migrate_legacy_brickmissing.connections",
            fake_connections,
        ), self.assertRaisesRegex(CommandError, "must be different"):
            call_command(
                "migrate_legacy_brickmissing",
                source_db_alias="legacy_v7",
                stdout=io.StringIO(),
            )

    def test_database_alias_uses_the_same_mapping_pipeline(self):
        source_path = Path(__file__).resolve().parents[2] / "data" / "brickmissing.db"

        class Connections(dict):
            pass

        fake = Connections(default=type("C", (), {"settings_dict": {"NAME": "target"}})())
        fake["legacy_v7"] = type("C", (), {"settings_dict": {"NAME": "legacy"}})()
        source = SQLiteLegacySource(source_path)
        with patch(
            "apps.data_portability.management.commands.migrate_legacy_brickmissing.connections",
            fake,
        ), patch(
            "apps.data_portability.management.commands.migrate_legacy_brickmissing.open_legacy_source",
            return_value=source,
        ), patch(
            "apps.data_portability.management.commands.validate_legacy_migration.open_legacy_source",
            return_value=source,
        ):
            call_command(
                "migrate_legacy_brickmissing", source_db_alias="legacy_v7", dry_run=True,
                stdout=io.StringIO(),
            )
        self.assertFalse(get_user_model().objects.filter(legacy_id__isnull=False).exists())
