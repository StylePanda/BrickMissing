import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
import zipfile
from base64 import urlsafe_b64encode
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet, InvalidToken
from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.db import connection, transaction
from django.utils import timezone

from .models import BackupArtifact

EXCLUDED_APP_LABELS = {"backups", "audit", "admin", "sessions", "contenttypes"}
SNAPSHOT_SEMANTICS = "business-state-with-append-only-security-audit"
EXECUTABLE_SUFFIXES = {
    ".bat", ".cmd", ".com", ".exe", ".js", ".msi", ".ps1", ".py", ".sh",
}
MAX_ARCHIVE_MEMBER_SIZE = 100 * 1024 * 1024
MAX_ARCHIVE_SIZE = 2 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


def _root() -> Path:
    root = Path(settings.BACKUP_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.BACKUP_ENCRYPTION_KEY.encode()).digest()
    return Fernet(urlsafe_b64encode(key))


def _safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=False)
    except OSError:
        # Cleanup failure must not corrupt or reverse an already committed restore.
        pass


def _snapshot_models():
    return [
        model for model in apps.get_models()
        if model._meta.app_label not in EXCLUDED_APP_LABELS
    ]


@transaction.atomic
def create_backup(user, *, enforce_retention=True) -> BackupArtifact:
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(str(timezone.now()).encode()).hexdigest()[:8]
    filename = f"brickmissing-{stamp}-{digest}.bm8"
    payload = io.BytesIO()
    all_objects = []
    for model in _snapshot_models():
        all_objects.extend(model.objects.all().iterator())
    fixture = serializers.serialize("json", all_objects).encode()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("database.json", fixture)
        private_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        if private_root.exists():
            for path in private_root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    archive.write(path, Path("private") / path.relative_to(private_root))
        archive.writestr(
            "manifest.json",
            json.dumps({
                "version": 3,
                "created_at": timezone.now().isoformat(),
                "semantics": SNAPSHOT_SEMANTICS,
                "excluded_runtime_apps": sorted(EXCLUDED_APP_LABELS),
            }),
        )
    encrypted = _fernet().encrypt(payload.getvalue())
    destination = _root() / filename
    destination.write_bytes(encrypted)
    artifact = BackupArtifact.objects.create(
        created_by=user,
        filename=filename,
        sha256=hashlib.sha256(encrypted).hexdigest(),
        size=len(encrypted),
    )
    if enforce_retention:
        apply_retention()
    return artifact


def verify_backup(artifact: BackupArtifact) -> bytes:
    root = _root()
    path = (root / artifact.filename).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("Backup file is missing")
    encrypted = path.read_bytes()
    if hashlib.sha256(encrypted).hexdigest() != artifact.sha256:
        raise ValueError("Backup integrity check failed")
    try:
        return _fernet().decrypt(encrypted)
    except InvalidToken as exc:
        raise ValueError("Backup decryption failed") from exc


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    path = PurePosixPath(info.filename)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in info.filename
        or (path.parts and path.parts[0].endswith(":"))
    ):
        raise ValueError("Unsafe archive path")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ValueError("Archive symlinks are not allowed")
    if info.file_size > MAX_ARCHIVE_MEMBER_SIZE:
        raise ValueError("Archive member is too large")
    if info.file_size and info.file_size > max(info.compress_size, 1) * MAX_COMPRESSION_RATIO:
        raise ValueError("Archive member compression ratio is unsafe")
    return path


def _stage_archive(payload: bytes, parent: Path):
    if len(payload) > MAX_ARCHIVE_SIZE:
        raise ValueError("Backup archive is too large")
    stage = Path(tempfile.mkdtemp(prefix="bm8-restore-stage-", dir=parent))
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            paths = {_safe_member(info): info for info in infos}
            if len(paths) != len(infos):
                raise ValueError("Duplicate archive paths are not allowed")
            if PurePosixPath("database.json") not in paths or PurePosixPath("manifest.json") not in paths:
                raise ValueError("Invalid backup archive")
            if sum(info.file_size for info in infos) > MAX_ARCHIVE_SIZE:
                raise ValueError("Backup archive is too large")
            manifest = json.loads(archive.read(paths[PurePosixPath("manifest.json")]))
            if manifest.get("version") not in {1, 2, 3}:
                raise ValueError("Unsupported backup version")
            if manifest.get("version") == 3 and manifest.get("semantics") != SNAPSHOT_SEMANTICS:
                raise ValueError("Unsupported snapshot semantics")
            fixture = archive.read(paths[PurePosixPath("database.json")])
            restored_objects = list(serializers.deserialize("json", fixture))
            files = stage / "private"
            files.mkdir()
            for path, info in paths.items():
                if len(path.parts) < 2 or path.parts[0] != "private" or info.is_dir():
                    continue
                relative = Path(*path.parts[1:])
                if relative.suffix.lower() in EXECUTABLE_SUFFIXES:
                    raise ValueError("Executable private files are not allowed")
                target = (files / relative).resolve()
                if files.resolve() not in target.parents:
                    raise ValueError("Unsafe archive path")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
        return stage, restored_objects
    except Exception:
        _safe_rmtree(stage)
        raise


def _replace_database(restored_objects):
    from apps.audit.models import AuditEvent

    for event in AuditEvent.objects.select_related("actor", "target_user").iterator():
        changed = event.preserve_attribution()
        if changed:
            event.save(update_fields=changed)
    models = _snapshot_models()
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    restored_user_ids = {
        item.object.pk for item in restored_objects if isinstance(item.object, user_model)
    }
    with connection.constraint_checks_disabled():
        for model in reversed(models):
            if model is user_model:
                continue
            model.objects.all().delete()
        user_model.objects.exclude(pk__in=restored_user_ids).delete()
        for deserialized in restored_objects:
            if deserialized.object._meta.app_label in EXCLUDED_APP_LABELS:
                raise ValueError("Backup contains excluded runtime data")
            deserialized.save()
    connection.check_constraints()


def _before_database_commit() -> None:
    """Test seam immediately after activation and before the atomic block commits."""


def restore_backup(artifact: BackupArtifact) -> None:
    """Restore database and private files with replacement and recovery semantics."""
    payload = verify_backup(artifact)
    private_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    parent = private_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    current_size = sum(
        path.stat().st_size
        for path in private_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    ) if private_root.exists() else 0
    if shutil.disk_usage(parent).free < len(payload) + current_size:
        raise OSError("Insufficient free space for safe restore")
    stage, restored_objects = _stage_archive(payload, parent)
    staged_files = stage / "private"
    previous = Path(tempfile.mkdtemp(prefix="bm8-restore-previous-", dir=parent))
    previous.rmdir()
    swapped = False
    previous_moved = False
    try:
        with transaction.atomic():
            if private_root.exists():
                os.replace(private_root, previous)
                previous_moved = True
            os.replace(staged_files, private_root)
            swapped = True
            _replace_database(restored_objects)
            _before_database_commit()
        if previous.exists():
            _safe_rmtree(previous)
    except Exception:
        if swapped:
            failed = stage / "failed-private"
            if private_root.exists():
                os.replace(private_root, failed)
        if previous_moved and previous.exists():
            os.replace(previous, private_root)
        raise
    finally:
        _safe_rmtree(stage)
        if previous.exists():
            _safe_rmtree(previous)


def apply_retention() -> None:
    keep = settings.BACKUP_RETENTION_COUNT
    for artifact in BackupArtifact.objects.filter(status="ready")[keep:]:
        path = _root() / artifact.filename
        if path.exists():
            path.unlink()
        artifact.status = "expired"
        artifact.save(update_fields=["status"])
