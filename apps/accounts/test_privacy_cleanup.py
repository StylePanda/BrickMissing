from datetime import timedelta
from io import StringIO

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AccountSession, PendingEmailChange, RecoveryCode, User
from apps.core.models import Notification
from apps.data_portability.models import ImportBatch, LegacyArchiveRecord


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

    def test_dry_run_changes_nothing_and_reports_manual_policy(self):
        output = StringIO()
        call_command("cleanup_expired_personal_data", stdout=output)
        self.assertTrue(Session.objects.filter(session_key=self.expired_key).exists())
        self.assertTrue(AccountSession.objects.filter(pk=self.orphan.pk).exists())
        self.assertIn("DRY-RUN", output.getvalue())
        self.assertIn("MANUAL POLICY REQUIRED", output.getvalue())

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
