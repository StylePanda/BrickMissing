from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.data_portability.models import LegacyArchiveRecord
from apps.inventory.models import InventoryMovement
from apps.media_library.models import PrivateDocument
from apps.organizer.models import Collection

from .models import User

logger = logging.getLogger(__name__)


class AccountDeletionFileError(RuntimeError):
    def __init__(self, message: str, *, database_deleted: bool = False):
        super().__init__(message)
        self.database_deleted = database_deleted


@dataclass(frozen=True)
class DeletionResult:
    user_id: str
    transferred_collections: int
    deleted_private_files: int


def _revoke_all_sessions(user: User) -> None:
    session_keys = list(user.account_sessions.values_list("session_key", flat=True))
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        try:
            session_user_id = session.get_decoded().get("_auth_user_id")
        except Exception:  # Invalid session payloads are not relevant to account ownership.
            logger.warning("Invalid Django session payload skipped during account cleanup")
            continue
        if str(session_user_id) == str(user.pk):
            session_keys.append(session.session_key)
    if session_keys:
        Session.objects.filter(session_key__in=session_keys).delete()
    user.account_sessions.all().delete()


@transaction.atomic
def anonymize_account(user: User, *, request_id=None) -> None:
    locked = User.objects.select_for_update().get(pk=user.pk)
    AuditEvent.objects.create(
        actor=locked,
        target_user=locked,
        action="account.anonymized",
        request_id=request_id,
    )
    _revoke_all_sessions(locked)
    locked.pending_email_changes.all().delete()
    locked.recovery_codes.all().delete()
    marker = locked.pk.hex
    locked.username = f"deleted-{marker}"
    locked.email = f"deleted-{marker}@invalid.local"
    locked.first_name = ""
    locked.last_name = ""
    locked.is_active = False
    locked.is_staff = False
    locked.is_superuser = False
    locked.email_verified = False
    locked.deactivated_at = timezone.now()
    locked.totp_enabled = False
    locked.totp_secret_encrypted = ""
    locked.rebrickable_api_key_encrypted = ""
    locked.set_unusable_password()
    locked.groups.clear()
    locked.user_permissions.clear()
    locked.save()
    _minimize_audit_events(locked)


def _private_root() -> Path:
    return Path(settings.PRIVATE_MEDIA_ROOT).resolve()


def _safe_private_path(name: str) -> Path:
    root = _private_root()
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise AccountDeletionFileError("Ungültiger privater Dateipfad.")
    raw_candidate = root / relative
    if raw_candidate.is_symlink() or any(
        parent.is_symlink() for parent in raw_candidate.parents if parent != root.parent
    ):
        raise AccountDeletionFileError("Symbolische Links werden bei der Kontolöschung nicht verarbeitet.")
    candidate = raw_candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AccountDeletionFileError("Private Datei liegt außerhalb des erlaubten Bereichs.") from exc
    return candidate


def _stage_private_file_names(names) -> tuple[Path, list[tuple[Path, Path]]]:
    root = _private_root()
    quarantine = root / ".deletion-quarantine" / uuid.uuid4().hex
    staged: list[tuple[Path, Path]] = []
    try:
        for name in names:
            source = _safe_private_path(name)
            if not source.exists():
                continue
            relative = source.relative_to(root)
            target = quarantine / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            staged.append((source, target))
    except OSError as exc:
        _restore_staged_files(staged)
        raise AccountDeletionFileError("Private Dateien konnten nicht sicher vorbereitet werden.") from exc
    return quarantine, staged


def _stage_private_files(user: User) -> tuple[Path, list[tuple[Path, Path]]]:
    return _stage_private_file_names(user.privatedocument_set.values_list("file", flat=True))


def _restore_staged_files(staged: list[tuple[Path, Path]]) -> None:
    for original, staged_path in reversed(staged):
        if staged_path.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, original)


def _delete_staged_files(quarantine: Path, staged: list[tuple[Path, Path]]) -> int:
    deleted = 0
    failures = 0
    for _original, staged_path in staged:
        try:
            staged_path.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            failures += 1
            logger.exception("Quarantined private file could not be deleted")
    for directory in sorted(
        (path for path in quarantine.rglob("*") if path.is_dir()), reverse=True
    ) if quarantine.exists() else []:
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        quarantine.rmdir()
        quarantine.parent.rmdir()
    except OSError:
        pass
    if failures:
        raise AccountDeletionFileError(
            f"{failures} private Datei(en) blieben in der geschützten Löschquarantäne.",
            database_deleted=True,
        )
    return deleted


def _transfer_shared_collections(user: User) -> int:
    transferred = 0
    for collection in Collection.objects.select_for_update().filter(owner=user):
        successor = (
            collection.members.exclude(user=user)
            .select_related("user")
            .order_by("created_at", "pk")
            .first()
        )
        if successor:
            collection.owner = successor.user
            collection.save(update_fields=["owner", "updated_at"])
            transferred += 1
    return transferred


def _minimize_audit_events(user: User) -> None:
    related = AuditEvent.objects.filter(actor=user) | AuditEvent.objects.filter(target_user=user)
    related.update(
        actor_identifier="",
        actor_username_snapshot="Gelöschtes Konto",
        actor_email_hash="",
        target_identifier="",
        target_repr_snapshot="Gelöschtes Konto",
        remote_address=None,
        details={},
    )


def delete_account_and_data(user: User, *, request_id=None) -> DeletionResult:
    user_id = str(user.pk)
    quarantine, staged = _stage_private_files(user)
    transferred = 0
    try:
        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=user.pk)
            transferred = _transfer_shared_collections(locked)
            _revoke_all_sessions(locked)
            locked.pending_email_changes.all().delete()
            locked.recovery_codes.all().delete()
            LegacyArchiveRecord.objects.filter(owner=locked).delete()
            InventoryMovement.objects.filter(item__owner=locked).delete()
            AuditEvent.objects.create(
                actor=locked,
                target_user=locked,
                action="account.deleted",
                request_id=request_id,
            )
            _minimize_audit_events(locked)
            locked.delete()
    except Exception:
        try:
            _restore_staged_files(staged)
        except OSError:
            logger.exception("Private files could not be restored after account deletion rollback")
        raise
    deleted_files = _delete_staged_files(quarantine, staged)
    return DeletionResult(user_id, transferred, deleted_files)


def permanently_delete_private_document(document: PrivateDocument) -> None:
    quarantine, staged = _stage_private_file_names([document.file.name])
    try:
        with transaction.atomic():
            PrivateDocument.objects.select_for_update().get(pk=document.pk).delete()
    except Exception:
        _restore_staged_files(staged)
        raise
    _delete_staged_files(quarantine, staged)
