import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet
from apps.data_portability.models import ImportBatch
from apps.inventory.models import InventoryItem, InventoryMovement
from apps.media_library.models import PrivateDocument
from apps.organizer.models import Collection, CollectionMember, PersonalNote

from .account_deletion import AccountDeletionFileError, delete_account_and_data
from .models import AccountSession, PendingEmailChange, RecoveryCode

PASSWORD = "A-very-long-password-123"  # noqa: S105 - isolated test credential


class AccountDeletionLifecycleTests(TestCase):
    def create_user(self, username):
        return get_user_model().objects.create_user(
            username, f"{username}@example.test", PASSWORD, email_verified=True
        )

    def test_deactivation_preserves_content_and_removes_all_security_credentials(self):
        user = self.create_user("deactivate-lifecycle")
        lego_set = LegoSet.objects.create(owner=user, set_number="1", name="Bleibt")
        PendingEmailChange.objects.create(
            user=user, email="new@example.test", token_digest="a" * 64,
            expires_at="2099-01-01T00:00:00Z",
        )
        RecoveryCode.generate_for(user, count=1)
        store = SessionStore()
        store["_auth_user_id"] = str(user.pk)
        store.save()
        AccountSession.objects.create(user=user, session_key=store.session_key, user_agent="Test")
        user.totp_enabled = True
        user.totp_secret_encrypted = "encrypted"  # noqa: S105 - inert test ciphertext
        user.rebrickable_api_key_encrypted = "encrypted-key"
        user.save()
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:deactivate"),
            {"password": PASSWORD, "confirmation": "DEAKTIVIEREN"},
        )

        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.totp_secret_encrypted, "")
        self.assertEqual(user.rebrickable_api_key_encrypted, "")
        self.assertFalse(user.totp_enabled)
        self.assertFalse(PendingEmailChange.objects.filter(user=user).exists())
        self.assertFalse(RecoveryCode.objects.filter(user=user).exists())
        self.assertFalse(AccountSession.objects.filter(user=user).exists())
        self.assertTrue(LegoSet.objects.filter(pk=lego_set.pk, owner=user).exists())

    def test_permanent_delete_removes_owned_content_imports_and_protected_movements(self):
        user = self.create_user("delete-lifecycle")
        other = self.create_user("delete-other")
        owned_set = LegoSet.objects.create(owner=user, set_number="own", name="Eigene Notiz")
        foreign_set = LegoSet.objects.create(owner=other, set_number="other", name="Fremd")
        PersonalNote.objects.create(owner=user, title="Privat", content="Personenbezogen")
        ImportBatch.objects.create(owner=user, source_format="json", payload={"notes": "privat"})
        item = InventoryItem.objects.create(owner=user, part_number="1", name="Teil")
        InventoryMovement.objects.create(
            item=item, movement_type="adjustment", old_quantity=0, new_quantity=1,
            difference=1, actor=user, note="privat",
        )
        AuditEvent.objects.create(
            actor=user, target_user=user, action="private.action", details={"note": "privat"},
            remote_address="192.0.2.1",
        )

        delete_account_and_data(user)

        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertFalse(LegoSet.objects.filter(pk=owned_set.pk).exists())
        self.assertFalse(PersonalNote.objects.filter(owner_id=user.pk).exists())
        self.assertFalse(ImportBatch.objects.filter(owner_id=user.pk).exists())
        self.assertFalse(InventoryMovement.objects.filter(item_id=item.pk).exists())
        self.assertTrue(LegoSet.objects.filter(pk=foreign_set.pk, owner=other).exists())
        audit = AuditEvent.objects.get(action="private.action")
        self.assertIsNone(audit.actor_id)
        self.assertIsNone(audit.target_user_id)
        self.assertEqual(audit.actor_email_hash, "")
        self.assertEqual(audit.details, {})
        self.assertIsNone(audit.remote_address)

    def test_shared_collection_transfers_to_oldest_other_member(self):
        owner = self.create_user("shared-owner")
        successor = self.create_user("shared-successor")
        other = self.create_user("shared-other")
        collection = Collection.objects.create(owner=owner, name="Gemeinsam", is_shared=True)
        CollectionMember.objects.create(collection=collection, user=successor, role="editor")
        CollectionMember.objects.create(collection=collection, user=other, role="viewer")

        result = delete_account_and_data(owner)

        collection.refresh_from_db()
        self.assertEqual(collection.owner, successor)
        self.assertEqual(result.transferred_collections, 1)
        self.assertTrue(CollectionMember.objects.filter(collection=collection, user=other).exists())

    def test_private_and_soft_deleted_documents_are_physically_deleted(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=directory, PRIVATE_MEDIA_ROOT=directory
        ):
            user = self.create_user("delete-files")
            paths = []
            for index, deleted in enumerate((False, True)):
                document = PrivateDocument(
                    owner=user, entity_type="other", entity_id=str(index), title="Privat",
                    original_name="private.txt", mime_type="text/plain", size=6,
                )
                document.file.save(
                    f"private-{index}.txt",
                    SimpleUploadedFile(f"private-{index}.txt", b"secret"),
                    save=True,
                )
                if deleted:
                    from django.utils import timezone

                    document.deleted_at = timezone.now()
                    document.save(update_fields=["deleted_at"])
                paths.append(Path(document.file.path))
            self.assertTrue(all(path.exists() for path in paths))

            result = delete_account_and_data(user)

            self.assertEqual(result.deleted_private_files, 2)
            self.assertTrue(all(not path.exists() for path in paths))

    def test_database_failure_rolls_back_and_restores_staged_file(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=directory, PRIVATE_MEDIA_ROOT=directory
        ):
            user = self.create_user("rollback-files")
            document = PrivateDocument(
                owner=user, entity_type="other", entity_id="1", title="Privat",
                original_name="private.txt", mime_type="text/plain", size=6,
            )
            document.file.save("private.txt", SimpleUploadedFile("private.txt", b"secret"), save=True)
            path = Path(document.file.path)
            with patch.object(get_user_model(), "delete", side_effect=RuntimeError("controlled")):
                with self.assertRaises(RuntimeError):
                    delete_account_and_data(user)
            self.assertTrue(path.exists())
            self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
            self.assertTrue(PrivateDocument.objects.filter(pk=document.pk).exists())

    def test_file_delete_failure_is_reported_after_database_delete(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=directory, PRIVATE_MEDIA_ROOT=directory
        ):
            user = self.create_user("unlink-failure")
            document = PrivateDocument(
                owner=user, entity_type="other", entity_id="1", title="Privat",
                original_name="private.txt", mime_type="text/plain", size=6,
            )
            document.file.save("private.txt", SimpleUploadedFile("private.txt", b"secret"), save=True)
            with patch("apps.accounts.account_deletion.Path.unlink", side_effect=OSError("controlled")):
                with self.assertRaises(AccountDeletionFileError):
                    delete_account_and_data(user)
            self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())

    def test_permanent_delete_endpoint_requires_post_password_confirmation_csrf_and_logs_out(self):
        user = self.create_user("endpoint-delete")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:permanent_delete")).status_code, 405)
        self.assertEqual(
            self.client.post(
                reverse("accounts:permanent_delete"),
                {"password": "wrong", "confirmation": "ACCOUNT LÖSCHEN"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                reverse("accounts:permanent_delete"),
                {"password": PASSWORD, "confirmation": "falsch"},
            ).status_code,
            400,
        )
        response = self.client.post(
            reverse("accounts:permanent_delete"),
            {"password": PASSWORD, "confirmation": "ACCOUNT LÖSCHEN"},
        )
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())

        csrf_user = self.create_user("csrf-permanent-delete")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(csrf_user)
        self.assertEqual(
            csrf_client.post(
                reverse("accounts:permanent_delete"),
                {"password": PASSWORD, "confirmation": "ACCOUNT LÖSCHEN"},
            ).status_code,
            403,
        )
        self.assertTrue(get_user_model().objects.filter(pk=csrf_user.pk).exists())

    def test_read_only_account_audit_command_changes_nothing(self):
        user = self.create_user("audit-command")
        lego_set = LegoSet.objects.create(owner=user, set_number="audit", name="Bleibt")
        call_command("audit_account_deletion", str(user.pk), verbosity=0)
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertTrue(LegoSet.objects.filter(pk=lego_set.pk).exists())
