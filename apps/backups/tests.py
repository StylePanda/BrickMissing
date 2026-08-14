import hashlib
import io
import json
import stat
import tempfile
import zipfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core import serializers
from django.core.files.base import ContentFile
from django.db import DatabaseError, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part
from apps.core.models import Notification, RecentItem, SavedView
from apps.integrations.models import PriceObservation, ValueSnapshot
from apps.inventory.models import InventoryItem, InventoryMovement, WarehouseLocation
from apps.media_library.models import PrivateDocument
from apps.orders.models import Order, OrderItem
from apps.organizer.models import (
    Collection,
    LabelTemplate,
    Loan,
    MinifigurePart,
    Moc,
    MocVersion,
    PersonalNote,
    SetMinifigure,
    WishlistItem,
    WorkshopDocument,
)

from .models import BackupArtifact
from .services import _fernet, _snapshot_models, create_backup, restore_backup, verify_backup


class BackupTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bm8-backup-tests-")
        root = Path(self.temp.name)
        self.settings_override = self.settings(
            BACKUP_ROOT=root / "backups",
            PRIVATE_MEDIA_ROOT=root / "private",
            MEDIA_ROOT=root / "private",
            BACKUP_ENCRYPTION_KEY="test-only-backup-key",
        )
        self.settings_override.enable()
        self.staff = User.objects.create_user(
            "admin",
            "admin@example.test",
            "A-long-safe-password-123",
            is_staff=True,
            email_verified=True,
        )
        self.user = User.objects.create_user(
            "user", "user@example.test", "A-long-safe-password-123",
            email_verified=True,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.temp.cleanup()

    def test_non_staff_cannot_access_backups(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("backups:list")).status_code, 302)

    def test_encrypted_backup_integrity_and_download(self):
        artifact = create_backup(self.staff)
        self.assertTrue(verify_backup(artifact).startswith(b"PK"))
        self.client.force_login(self.staff)
        response = self.client.get(reverse("backups:download", args=[artifact.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_restore_requires_current_password(self):
        artifact = create_backup(self.staff)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("backups:restore", args=[artifact.pk]), {"password": "wrong"}
        )
        self.assertRedirects(response, reverse("backups:list"))
        self.assertIsNone(BackupArtifact.objects.get(pk=artifact.pk).restored_at)

    def test_business_snapshot_restores_rows_and_private_files(self):
        private = Path(self.temp.name) / "private"
        private.mkdir()
        (private / "document.txt").write_text("snapshot", encoding="utf-8")
        original = InventoryItem.objects.create(
            owner=self.user, part_number="3001", name="Original", quantity=2
        )
        artifact = create_backup(self.staff)
        original.name = "Changed"
        original.quantity = 99
        original.save()
        InventoryItem.objects.create(
            owner=self.user, part_number="9999", name="After backup", quantity=1
        )
        (private / "document.txt").write_text("changed", encoding="utf-8")
        (private / "later.txt").write_text("later", encoding="utf-8")

        restore_backup(artifact)

        restored = InventoryItem.objects.get(pk=original.pk)
        self.assertEqual((restored.name, restored.quantity), ("Original", 2))
        self.assertEqual(InventoryItem.objects.count(), 1)
        self.assertEqual((private / "document.txt").read_text(encoding="utf-8"), "snapshot")
        self.assertFalse((private / "later.txt").exists())

    def test_business_snapshot_restores_all_business_domains_exactly(self):
        now = timezone.now().replace(microsecond=0)
        lego_set = LegoSet.objects.create(owner=self.user, set_number="restore-1", name="Set")
        Part.objects.create(
            owner=self.user, lego_set=lego_set, element_id="3001", name="Part", quantity=2
        )
        location = WarehouseLocation.objects.create(owner=self.user, name="Shelf")
        inventory = InventoryItem.objects.create(
            owner=self.user, location=location, part_number="3001", name="Inventory", quantity=3
        )
        InventoryMovement.objects.create(
            item=inventory, movement_type="initial", old_quantity=0, new_quantity=3,
            difference=3, actor=self.user,
        )
        order = Order.objects.create(owner=self.user, supplier="Supplier", total=Decimal("4.20"))
        OrderItem.objects.create(order=order, inventory_item=inventory, part_number="3001")
        collection = Collection.objects.create(owner=self.user, name="Collection")
        moc = Moc.objects.create(owner=self.user, collection=collection, name="MOC")
        MocVersion.objects.create(moc=moc, version="1", parts_snapshot=[])
        WishlistItem.objects.create(owner=self.user, collection=collection, reference="100", name="Wish")
        Loan.objects.create(
            owner=self.user, entity_type="set", entity_id=str(lego_set.pk),
            borrower="Friend", loaned_at=now, due_at=now + timedelta(days=7),
        )
        PersonalNote.objects.create(owner=self.user, title="Note", content="Content")
        WorkshopDocument.objects.create(owner=self.user, payload={"project": "restore"})
        LabelTemplate.objects.create(owner=self.user, name="Label")
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-1", name="Figure"
        )
        MinifigurePart.objects.create(minifigure=figure, part_number="973", name="Torso")
        Notification.objects.create(owner=self.user, kind="info", title="Notice", message="Text")
        SavedView.objects.create(owner=self.user, area="parts", name="View", path="/teile/")
        RecentItem.objects.create(
            owner=self.user, entity_type="set", entity_id=str(lego_set.pk),
            label="Recent", path="/sets/",
        )
        PriceObservation.objects.create(
            owner=self.user, entity_type="set", entity_id=str(lego_set.pk),
            price=Decimal("12.34"), source="legacy",
        )
        ValueSnapshot.objects.create(
            owner=self.user, collection_value=Decimal("12.34"), captured_at=now
        )
        document = PrivateDocument(
            owner=self.user, entity_type="set", entity_id=str(lego_set.pk),
            title="Document", original_name="document.txt", mime_type="text/plain", size=8,
        )
        document.file.save("document.txt", ContentFile(b"snapshot"), save=True)

        def state():
            objects = []
            for model in _snapshot_models():
                objects.extend(model.objects.order_by("pk"))
            payload = json.loads(serializers.serialize("json", objects))
            return sorted(payload, key=lambda row: (row["model"], str(row["pk"])))

        expected = state()
        artifact = create_backup(self.staff)
        lego_set.name = "Changed"
        lego_set.save(update_fields=["name", "updated_at"])
        Notification.objects.create(owner=self.user, kind="later", title="Later", message="Later")
        with document.file.storage.open(document.file.name, "wb") as handle:
            handle.write(b"changed!")

        restore_backup(artifact)

        self.assertEqual(state(), expected)
        restored_document = PrivateDocument.objects.get(pk=document.pk)
        with restored_document.file.storage.open(restored_document.file.name, "rb") as handle:
            self.assertEqual(handle.read(), b"snapshot")

    def test_restore_preserves_append_only_audit_attribution(self):
        event = AuditEvent.objects.create(
            actor=self.user, target_user=self.user, action="security.before_snapshot"
        )
        original_identifier = str(self.user.pk)
        artifact = create_backup(self.staff)
        self.user.username = "changed-after-snapshot"
        self.user.save(update_fields=["username", "updated_at"])

        restore_backup(artifact)

        event.refresh_from_db()
        self.assertEqual(event.actor_identifier, original_identifier)
        self.assertEqual(event.target_identifier, original_identifier)
        self.assertEqual(event.actor_username_snapshot, "user")
        self.assertEqual(event.target_repr_snapshot, "user")
        self.assertEqual(len(event.actor_email_hash), 64)
        self.assertEqual(event.actor_id, self.user.pk)

    def _current_state_fixture(self):
        private = Path(self.temp.name) / "private"
        private.mkdir(exist_ok=True)
        (private / "state.txt").write_text("snapshot", encoding="utf-8")
        item = InventoryItem.objects.create(
            owner=self.user, part_number="3001", name="Snapshot", quantity=2
        )
        artifact = create_backup(self.staff)
        item.name = "Current"
        item.save(update_fields=["name", "updated_at"])
        (private / "state.txt").write_text("current", encoding="utf-8")
        return private, item, artifact

    def _assert_current_state(self, private, item):
        item.refresh_from_db()
        self.assertEqual(item.name, "Current")
        self.assertEqual((private / "state.txt").read_text(encoding="utf-8"), "current")

    def test_restore_failure_rolls_back_database_and_files(self):
        private = Path(self.temp.name) / "private"
        private.mkdir()
        (private / "state.txt").write_text("before", encoding="utf-8")
        item = InventoryItem.objects.create(
            owner=self.user, part_number="3001", name="Before", quantity=2
        )
        artifact = create_backup(self.staff)
        item.name = "Current"
        item.save()
        (private / "state.txt").write_text("current", encoding="utf-8")
        with patch(
            "apps.backups.services._replace_database",
            side_effect=RuntimeError("intentional restore failure"),
        ):
            with self.assertRaises(RuntimeError):
                restore_backup(artifact)
        item.refresh_from_db()
        self.assertEqual(item.name, "Current")
        self.assertEqual((private / "state.txt").read_text(encoding="utf-8"), "current")

    def test_failure_after_first_swap_restores_database_and_files(self):
        private, item, artifact = self._current_state_fixture()
        real_replace = __import__("os").replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("failure after first swap")
            return real_replace(source, destination)

        with patch("apps.backups.services.os.replace", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "first swap"):
                restore_backup(artifact)
        self._assert_current_state(private, item)

    def test_failure_after_second_swap_restores_database_and_files(self):
        private, item, artifact = self._current_state_fixture()
        with patch(
            "apps.backups.services._replace_database",
            side_effect=RuntimeError("failure after second swap"),
        ):
            with self.assertRaisesRegex(RuntimeError, "second swap"):
                restore_backup(artifact)
        self._assert_current_state(private, item)

    def test_database_commit_barrier_failure_rolls_back_database_and_files(self):
        private, item, artifact = self._current_state_fixture()
        with patch(
            "apps.backups.services._before_database_commit",
            side_effect=RuntimeError("database commit failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "database commit"):
                restore_backup(artifact)
        self._assert_current_state(private, item)

    def test_insufficient_disk_space_is_rejected_before_restore(self):
        private, item, artifact = self._current_state_fixture()
        usage = __import__("collections").namedtuple("usage", "total used free")(1, 1, 0)
        with patch("apps.backups.services.shutil.disk_usage", return_value=usage):
            with self.assertRaisesRegex(OSError, "Insufficient"):
                restore_backup(artifact)
        self._assert_current_state(private, item)

    def test_executable_private_file_is_rejected(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("database.json", "[]")
            archive.writestr("manifest.json", '{"version": 2}')
            archive.writestr("private/run.py", "print('unsafe')")
        encrypted = _fernet().encrypt(payload.getvalue())
        root = Path(self.temp.name) / "backups"
        root.mkdir(exist_ok=True)
        path = root / "executable.bm8"
        path.write_bytes(encrypted)
        artifact = BackupArtifact.objects.create(
            created_by=self.staff, filename=path.name,
            sha256=hashlib.sha256(encrypted).hexdigest(), size=len(encrypted),
        )
        with self.assertRaisesRegex(ValueError, "Executable"):
            restore_backup(artifact)

    def test_corrupted_or_wrong_key_backup_is_rejected(self):
        artifact = create_backup(self.staff)
        path = Path(self.temp.name) / "backups" / artifact.filename
        path.write_bytes(path.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            restore_backup(artifact)
        artifact.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        artifact.save(update_fields=["sha256"])
        with self.settings(BACKUP_ENCRYPTION_KEY="wrong-key"):
            with self.assertRaisesRegex(ValueError, "decryption"):
                restore_backup(artifact)

    def test_path_traversal_archive_is_rejected(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("database.json", "[]")
            archive.writestr("manifest.json", '{"version": 2}')
            archive.writestr("private/../../escape.txt", "escape")
        encrypted = _fernet().encrypt(payload.getvalue())
        filename = "traversal.bm8"
        path = Path(self.temp.name) / "backups" / filename
        path.parent.mkdir()
        path.write_bytes(encrypted)
        artifact = BackupArtifact.objects.create(
            created_by=self.staff,
            filename=filename,
            sha256=hashlib.sha256(encrypted).hexdigest(),
            size=len(encrypted),
        )
        with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
            restore_backup(artifact)
        self.assertFalse((Path(self.temp.name) / "escape.txt").exists())

    def test_archive_symlink_is_rejected(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("database.json", "[]")
            archive.writestr("manifest.json", '{"version": 2}')
            link = zipfile.ZipInfo("private/link")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "../../escape")
        encrypted = _fernet().encrypt(payload.getvalue())
        root = Path(self.temp.name) / "backups"
        root.mkdir(exist_ok=True)
        path = root / "symlink.bm8"
        path.write_bytes(encrypted)
        artifact = BackupArtifact.objects.create(created_by=self.staff, filename=path.name, sha256=hashlib.sha256(encrypted).hexdigest(), size=len(encrypted))
        with self.assertRaisesRegex(ValueError, "symlinks"):
            restore_backup(artifact)

    def test_windows_absolute_and_duplicate_archive_paths_are_rejected(self):
        for filename, members, message in (
            ("windows.bm8", [("C:/escape.txt", "escape")], "Unsafe archive path"),
            ("duplicate.bm8", [("private/repeated.txt", "one"), ("private/repeated.txt", "two")], "Duplicate archive paths"),
        ):
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("database.json", "[]")
                archive.writestr("manifest.json", '{"version": 2}')
                for name, content in members:
                    archive.writestr(name, content)
            encrypted = _fernet().encrypt(payload.getvalue())
            root = Path(self.temp.name) / "backups"
            root.mkdir(exist_ok=True)
            path = root / filename
            path.write_bytes(encrypted)
            artifact = BackupArtifact.objects.create(
                created_by=self.staff, filename=filename,
                sha256=hashlib.sha256(encrypted).hexdigest(), size=len(encrypted),
            )
            with self.assertRaisesRegex(ValueError, message):
                restore_backup(artifact)

    def test_cleanup_failure_does_not_reverse_committed_restore(self):
        private, _item, artifact = self._current_state_fixture()
        with patch("apps.backups.services.shutil.rmtree", side_effect=OSError("cleanup")):
            restore_backup(artifact)
        self.assertEqual((private / "state.txt").read_text(encoding="utf-8"), "snapshot")


class RestoreCommitFailureTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bm8-commit-failure-")
        root = Path(self.temp.name)
        self.settings_override = self.settings(
            BACKUP_ROOT=root / "backups",
            PRIVATE_MEDIA_ROOT=root / "private",
            MEDIA_ROOT=root / "private",
            BACKUP_ENCRYPTION_KEY="test-only-backup-key",
        )
        self.settings_override.enable()
        self.user = User.objects.create_user(
            "commit-user", "commit@example.test", "A-long-safe-password-123",
            email_verified=True,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.temp.cleanup()

    def test_actual_transaction_commit_failure_rolls_back_database_and_files(self):
        private = Path(self.temp.name) / "private"
        private.mkdir()
        (private / "state.txt").write_text("snapshot", encoding="utf-8")
        item = InventoryItem.objects.create(
            owner=self.user, part_number="3001", name="Snapshot", quantity=2
        )
        artifact = create_backup(self.user)
        item.name = "Current"
        item.save(update_fields=["name", "updated_at"])
        (private / "state.txt").write_text("current", encoding="utf-8")
        real_commit = connection.commit
        commit_calls = 0

        def fail_first_commit():
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 1:
                raise DatabaseError("commit failed")
            return real_commit()

        with patch.object(connection, "commit", side_effect=fail_first_commit):
            with self.assertRaisesRegex(DatabaseError, "commit failed"):
                restore_backup(artifact)
        item.refresh_from_db()
        self.assertEqual(item.name, "Current")
        self.assertEqual((private / "state.txt").read_text(encoding="utf-8"), "current")
