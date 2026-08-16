import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AccountSession, PendingEmailChange, RecoveryCode, User
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part
from apps.core.models import Notification
from apps.data_portability.models import (
    ImportBatch,
    LegacyArchiveRecord,
    LegacyImportRecord,
)
from apps.media_library.models import PrivateDocument
from apps.orders.models import Order
from apps.organizer.models import Moc


class PrivacyCleanupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "cleanup", "cleanup@example.test", "A-long-safe-password-123"
        )
        self.active_store = SessionStore()
        self.active_store["_auth_user_id"] = str(self.user.pk)
        self.active_store.save()
        self.active_account_session = AccountSession.objects.create(
            user=self.user, session_key=self.active_store.session_key
        )
        expired_store = SessionStore()
        expired_store["_auth_user_id"] = str(self.user.pk)
        expired_store.save()
        Session.objects.filter(session_key=expired_store.session_key).update(
            expire_date=timezone.now() - timedelta(days=1)
        )
        self.expired_key = expired_store.session_key
        AccountSession.objects.create(user=self.user, session_key=self.expired_key)
        self.orphan = AccountSession.objects.create(user=self.user, session_key="orphan-key")

    def test_dry_run_changes_nothing_and_reports_complete_policy(self):
        output = StringIO()
        call_command("cleanup_expired_personal_data", stdout=output)
        self.assertTrue(Session.objects.filter(session_key=self.expired_key).exists())
        self.assertTrue(AccountSession.objects.filter(pk=self.orphan.pk).exists())
        self.assertIn("DRY-RUN", output.getvalue())
        self.assertIn("Status=AUTO-SAFE", output.getvalue())
        self.assertIn("Status=POLICY-BASED", output.getvalue())
        self.assertNotIn("MANUAL POLICY REQUIRED", output.getvalue())

    def test_apply_removes_only_expired_and_orphan_sessions(self):
        call_command("cleanup_expired_personal_data", "--apply", stdout=StringIO())
        self.assertTrue(Session.objects.filter(session_key=self.active_store.session_key).exists())
        self.assertTrue(
            AccountSession.objects.filter(pk=self.active_account_session.pk).exists()
        )
        self.assertFalse(Session.objects.filter(session_key=self.expired_key).exists())
        self.assertFalse(AccountSession.objects.filter(pk=self.orphan.pk).exists())

    @override_settings(
        PENDING_EMAIL_RETENTION_DAYS=7,
        RECOVERY_CODE_RETENTION_DAYS=7,
        IMPORT_BATCH_RETENTION_DAYS=7,
    )
    def test_configured_ttls_remove_only_eligible_records(self):
        old = timezone.now() - timedelta(days=10)
        pending = PendingEmailChange.objects.create(
            user=self.user,
            email="new@example.test",
            token_digest="a" * 64,
            expires_at=old,
        )
        used_code = RecoveryCode.objects.create(
            user=self.user, digest="b" * 64, used_at=old
        )
        active_code = RecoveryCode.objects.create(user=self.user, digest="c" * 64)
        old_batch = ImportBatch.objects.create(owner=self.user, source_format="json")
        ImportBatch.objects.filter(pk=old_batch.pk).update(created_at=old)
        recent_batch = ImportBatch.objects.create(owner=self.user, source_format="json")
        notification = Notification.objects.create(
            owner=self.user, kind="info", title="Bleibt", message="Bleibt"
        )
        legacy = LegacyArchiveRecord.objects.create(
            owner=self.user,
            source_fingerprint="f" * 64,
            source_table="table",
            source_pk="1",
            payload={"private": "bleibt"},
        )

        call_command("cleanup_expired_personal_data", "--apply", stdout=StringIO())

        self.assertFalse(PendingEmailChange.objects.filter(pk=pending.pk).exists())
        self.assertFalse(RecoveryCode.objects.filter(pk=used_code.pk).exists())
        self.assertTrue(RecoveryCode.objects.filter(pk=active_code.pk).exists())
        self.assertFalse(ImportBatch.objects.filter(pk=old_batch.pk).exists())
        self.assertTrue(ImportBatch.objects.filter(pk=recent_batch.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())
        self.assertTrue(LegacyArchiveRecord.objects.filter(pk=legacy.pk).exists())

    @override_settings(
        AUDIT_SECURITY_RETENTION_DAYS=7,
        AUDIT_ACTIVITY_RETENTION_DAYS=7,
        NOTIFICATION_RETENTION_DAYS=7,
        SOFT_DELETE_RETENTION_DAYS=7,
        PRIVATE_DOCUMENT_DELETED_RETENTION_DAYS=7,
        LEGACY_DATA_RETENTION_DAYS=0,
    )
    def test_apply_enforces_audit_notification_soft_delete_file_and_legacy_policy(self):
        old = timezone.now() - timedelta(days=10)
        recent = timezone.now() - timedelta(days=2)
        other = User.objects.create_user(
            "cleanup-other", "cleanup-other@example.test", "A-long-safe-password-123"
        )
        old_security = AuditEvent.objects.create(actor=self.user, action="login_success")
        old_activity = AuditEvent.objects.create(actor=self.user, action="set.updated")
        recent_security = AuditEvent.objects.create(actor=self.user, action="password_changed")
        AuditEvent.objects.filter(pk__in=[old_security.pk, old_activity.pk]).update(created_at=old)
        AuditEvent.objects.filter(pk=recent_security.pk).update(created_at=recent)

        read_old = Notification.objects.create(
            owner=self.user, kind="info", title="Alt", message="Alt", read_at=old
        )
        unread_old = Notification.objects.create(
            owner=self.user, kind="info", title="Ungelesen", message="Ungelesen"
        )
        read_recent = Notification.objects.create(
            owner=self.user, kind="info", title="Neu", message="Neu", read_at=recent
        )

        old_set = LegoSet.objects.create(
            owner=self.user, set_number="cleanup-old", name="Alt", deleted_at=old
        )
        recent_set = LegoSet.objects.create(
            owner=self.user, set_number="cleanup-recent", name="Neu", deleted_at=recent
        )
        foreign_set = LegoSet.objects.create(
            owner=other, set_number="cleanup-foreign", name="Fremd", deleted_at=recent
        )
        old_part = Part.objects.create(
            owner=self.user, element_id="old", name="Alt", deleted_at=old
        )
        old_order = Order.objects.create(owner=self.user, supplier="Alt", deleted_at=old)
        old_moc = Moc.objects.create(owner=self.user, name="Alt", deleted_at=old)

        legacy_import = LegacyImportRecord.objects.create(
            source_fingerprint="i" * 64,
            source_table="users",
            source_pk="1",
            target_model="accounts.User",
            target_pk=str(self.user.pk),
        )
        legacy_archive = LegacyArchiveRecord.objects.create(
            owner=self.user,
            source_fingerprint="a" * 64,
            source_table="history",
            source_pk="1",
            payload={"retained": True},
        )
        LegacyImportRecord.objects.filter(pk=legacy_import.pk).update(imported_at=old)
        LegacyArchiveRecord.objects.filter(pk=legacy_archive.pk).update(imported_at=old)

        with tempfile.TemporaryDirectory(prefix="bm8-retention-") as directory:
            root = Path(directory)
            with self.settings(MEDIA_ROOT=root, PRIVATE_MEDIA_ROOT=root):
                document = PrivateDocument(
                    owner=self.user,
                    entity_type="other",
                    entity_id="retention",
                    title="Alt",
                    original_name="old.txt",
                    mime_type="text/plain",
                    size=3,
                    deleted_at=old,
                )
                document.file.save("old.txt", ContentFile(b"old"), save=True)
                path = Path(document.file.path)
                call_command("cleanup_expired_personal_data", "--apply", stdout=StringIO())
                self.assertFalse(path.exists())
                self.assertFalse(PrivateDocument.objects.filter(pk=document.pk).exists())

        for model, pk in (
            (AuditEvent, old_security.pk),
            (AuditEvent, old_activity.pk),
            (Notification, read_old.pk),
            (LegoSet, old_set.pk),
            (Part, old_part.pk),
            (Order, old_order.pk),
            (Moc, old_moc.pk),
        ):
            self.assertFalse(model.objects.filter(pk=pk).exists())
        self.assertTrue(AuditEvent.objects.filter(pk=recent_security.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=unread_old.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=read_recent.pk).exists())
        self.assertTrue(LegoSet.objects.filter(pk=recent_set.pk).exists())
        self.assertTrue(LegoSet.objects.filter(pk=foreign_set.pk).exists())
        self.assertTrue(LegacyImportRecord.objects.filter(pk=legacy_import.pk).exists())
        self.assertTrue(LegacyArchiveRecord.objects.filter(pk=legacy_archive.pk).exists())

    @override_settings(LEGACY_DATA_RETENTION_DAYS=7)
    def test_explicit_legacy_retention_removes_only_old_ledgers(self):
        old = timezone.now() - timedelta(days=10)
        old_record = LegacyImportRecord.objects.create(
            source_fingerprint="o" * 64,
            source_table="parts",
            source_pk="1",
            target_model="catalog.Part",
            target_pk="old",
        )
        recent_record = LegacyImportRecord.objects.create(
            source_fingerprint="r" * 64,
            source_table="parts",
            source_pk="2",
            target_model="catalog.Part",
            target_pk="recent",
        )
        LegacyImportRecord.objects.filter(pk=old_record.pk).update(imported_at=old)

        call_command("cleanup_expired_personal_data", "--apply", stdout=StringIO())

        self.assertFalse(LegacyImportRecord.objects.filter(pk=old_record.pk).exists())
        self.assertTrue(LegacyImportRecord.objects.filter(pk=recent_record.pk).exists())
