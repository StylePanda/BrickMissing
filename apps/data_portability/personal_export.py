from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.backups.models import BackupArtifact
from apps.catalog.models import LegoSet, Part, PartHistory, SetCopy, SetInventoryItem
from apps.core.models import DataQualityIssue, Notification, RecentItem, SavedView
from apps.data_portability.models import ImportBatch, LegacyArchiveRecord
from apps.integrations.models import PriceObservation, ValueSnapshot
from apps.inventory.models import InventoryItem, InventoryMovement, WarehouseLocation
from apps.media_library.models import PrivateDocument
from apps.orders.models import Order, OrderItem
from apps.organizer.models import (
    Collection,
    CollectionMember,
    LabelTemplate,
    Loan,
    MinifigurePart,
    Moc,
    MocPart,
    MocVersion,
    PersonalNote,
    SetMinifigure,
    WishlistItem,
    WorkshopDocument,
)

EXPORT_FORMAT_VERSION = "1.0"
JSON_FILES = (
    "account.json",
    "collections.json",
    "inventory.json",
    "organizer.json",
    "orders.json",
    "notifications.json",
    "audit.json",
    "imports.json",
    "private_documents.json",
)
EXCLUDED_FIELD_NAMES = {
    "owner",
    "user",
    "actor",
    "target_user",
    "created_by",
    "imported_by",
    "password",
    "session_key",
    "digest",
    "token_digest",
    "totp_secret_encrypted",
    "rebrickable_api_key_encrypted",
    "source_fingerprint",
    "sha256",
    "payload",
}


@dataclass(frozen=True)
class PersonalExportResult:
    content: bytes
    counts: dict[str, int]
    private_files: int
    missing_files: tuple[str, ...]


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")


def _serialize_queryset(queryset: QuerySet, *, extra_excluded: set[str] | None = None) -> list:
    excluded = EXCLUDED_FIELD_NAMES | (extra_excluded or set())
    fields = [
        field.attname
        for field in queryset.model._meta.fields
        if field.name not in excluded and field.attname not in excluded
    ]
    return list(queryset.order_by(queryset.model._meta.pk.attname).values(*fields))


def _section(**querysets: QuerySet) -> dict[str, list]:
    return {name: _serialize_queryset(queryset) for name, queryset in querysets.items()}


def _safe_document_path(document: PrivateDocument) -> Path | None:
    name = document.file.name
    if not name:
        return None
    relative = PurePosixPath(name.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return candidate


def _safe_file_name(document: PrivateDocument) -> str:
    original = Path(document.original_name or document.file.name or "dokument").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._") or "dokument"
    return f"files/{document.pk}-{cleaned[:120]}"


def build_personal_data_export(user) -> PersonalExportResult:
    sets = LegoSet.objects.filter(owner=user)
    parts = Part.objects.filter(owner=user)
    mocs = Moc.objects.filter(owner=user)
    figures = SetMinifigure.objects.filter(owner=user)
    orders = Order.objects.filter(owner=user)
    inventory_items = InventoryItem.objects.filter(owner=user)

    account = {
        "account": {
            "id": user.pk,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email_verified": user.email_verified,
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "totp_enabled": user.totp_enabled,
            "has_rebrickable_api_key": user.has_rebrickable_api_key,
            "last_login": user.last_login,
            "date_joined": user.date_joined,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "deactivated_at": user.deactivated_at,
            "legacy_id": user.legacy_id,
            "groups": list(user.groups.order_by("name").values_list("name", flat=True)),
            "direct_permissions": list(
                user.user_permissions.order_by("content_type__app_label", "codename")
                .values_list("content_type__app_label", "codename")
            ),
        },
        "security_exclusions": [
            "Passwort und Passwort-Hash",
            "2FA-Geheimnis und Recovery Codes",
            "Session-Keys",
            "E-Mail-Verifikationstokens",
            "verschlüsselte API-Schlüssel",
        ],
    }
    collections = _section(
        owned_collections=Collection.objects.filter(owner=user),
        own_memberships=CollectionMember.objects.filter(user=user),
    )
    collections["shared_data_note"] = (
        "Mitgliedschaften enthalten nur die eigene Benutzer-ID; Identitäten anderer Mitglieder "
        "werden nicht exportiert."
    )
    inventory = _section(
        sets=sets,
        set_copies=SetCopy.objects.filter(owner=user),
        set_inventory_items=SetInventoryItem.objects.filter(lego_set__owner=user),
        parts=parts,
        part_history=PartHistory.objects.filter(part__owner=user),
        warehouse_locations=WarehouseLocation.objects.filter(owner=user),
        inventory_items=inventory_items,
        inventory_movements=InventoryMovement.objects.filter(item__owner=user),
        price_observations=PriceObservation.objects.filter(owner=user),
        value_snapshots=ValueSnapshot.objects.filter(owner=user),
    )
    organizer = _section(
        mocs=mocs,
        moc_parts=MocPart.objects.filter(moc__owner=user),
        moc_versions=MocVersion.objects.filter(moc__owner=user),
        wishlist_items=WishlistItem.objects.filter(owner=user),
        loans=Loan.objects.filter(owner=user),
        personal_notes=PersonalNote.objects.filter(owner=user),
        workshop_documents=WorkshopDocument.objects.filter(owner=user),
        label_templates=LabelTemplate.objects.filter(owner=user),
        set_minifigures=figures,
        minifigure_parts=MinifigurePart.objects.filter(minifigure__owner=user),
    )
    order_data = _section(
        orders=orders,
        order_items=OrderItem.objects.filter(order__owner=user),
    )
    notifications = _section(
        notifications=Notification.objects.filter(owner=user),
        saved_views=SavedView.objects.filter(owner=user),
        recent_items=RecentItem.objects.filter(owner=user),
        data_quality_issues=DataQualityIssue.objects.filter(owner=user),
    )
    audit = {
        "events": _serialize_queryset(
            AuditEvent.objects.filter(Q(actor=user) | Q(target_user=user)).distinct(),
            extra_excluded={
                "actor_identifier",
                "actor_username_snapshot",
                "actor_email_hash",
                "target_identifier",
                "target_repr_snapshot",
                "details",
            },
        ),
        "note": "Freitext-Details und Identitätssnapshots sind aus Sicherheitsgründen ausgeschlossen.",
    }
    imports = {
        "import_batches": _serialize_queryset(ImportBatch.objects.filter(owner=user)),
        "legacy_import_records": [],
        "legacy_archive_records": _serialize_queryset(
            LegacyArchiveRecord.objects.filter(owner=user)
        ),
        "note": (
            "Rohe Import- und Legacy-Archiv-Payloads, Quell-Fingerprints und globale "
            "LegacyImportRecord-Zuordnungen sind ausgeschlossen."
        ),
    }
    backup_metadata = _serialize_queryset(
        BackupArtifact.objects.filter(created_by=user), extra_excluded={"filename"}
    )
    if backup_metadata:
        imports["backup_attribution"] = backup_metadata

    documents = list(PrivateDocument.objects.filter(owner=user).order_by("pk"))
    document_records = []
    available_files: list[tuple[PrivateDocument, Path]] = []
    missing_files = []
    for document in documents:
        record = _serialize_queryset(PrivateDocument.objects.filter(pk=document.pk))[0]
        record.pop("file", None)
        path = _safe_document_path(document)
        record["file_included"] = path is not None
        if path is None:
            record["file_status"] = "fehlt_oder_unsicher"
            missing_files.append(str(document.pk))
        else:
            record["archive_path"] = _safe_file_name(document)
            available_files.append((document, path))
        document_records.append(record)
    private_documents = {
        "documents": document_records,
        "missing_or_unsafe_file_document_ids": missing_files,
    }

    payloads = {
        "account.json": account,
        "collections.json": collections,
        "inventory.json": inventory,
        "organizer.json": organizer,
        "orders.json": order_data,
        "notifications.json": notifications,
        "audit.json": audit,
        "imports.json": imports,
        "private_documents.json": private_documents,
    }
    counts = {
        filename: sum(len(value) for value in payload.values() if isinstance(value, list))
        for filename, payload in payloads.items()
    }
    manifest = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "created_at": timezone.now(),
        "brickmissing_version": getattr(settings, "BRICKMISSING_VERSION", "8.0"),
        "user_id": user.pk,
        "files": [
            "manifest.json",
            *JSON_FILES,
            *[_safe_file_name(document) for document, _path in available_files],
        ],
        "categories": {
            "account.json": "Account- und Statusdaten ohne Authentifizierungsgeheimnisse",
            "collections.json": "Eigene Sammlungen und eigene Mitgliedschaften",
            "inventory.json": "Sets, Teile, Lager und Wertdaten",
            "organizer.json": "Organisation, Notizen, MOCs und Minifiguren",
            "orders.json": "Eigene Bestellungen und Positionen",
            "notifications.json": "Benachrichtigungen, Ansichten und zuletzt verwendete Inhalte",
            "audit.json": "Eigene sicherheitsrelevante Ereignisse in minimierter Form",
            "imports.json": "Import-Metadaten ohne rohe Legacy-Payloads",
            "private_documents.json": "Metadaten und Status eigener privater Dokumente",
        },
        "record_counts": counts,
        "private_files_included": len(available_files),
        "private_files_missing_or_unsafe": len(missing_files),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for filename, payload in payloads.items():
            archive.writestr(filename, _json_bytes(payload))
        for document, path in available_files:
            with path.open("rb") as private_file:
                archive.writestr(_safe_file_name(document), private_file.read())
    return PersonalExportResult(
        content=output.getvalue(),
        counts=counts,
        private_files=len(available_files),
        missing_files=tuple(missing_files),
    )


def personal_export_diagnostics(user) -> dict[str, Any]:
    documents = list(PrivateDocument.objects.filter(owner=user).order_by("pk"))
    missing_files = tuple(
        str(document.pk) for document in documents if _safe_document_path(document) is None
    )
    available_size = sum(
        path.stat().st_size
        for document in documents
        if (path := _safe_document_path(document)) is not None
    )
    return {
        "counts": {
            "collections": Collection.objects.filter(Q(owner=user) | Q(members__user=user))
            .distinct()
            .count(),
            "sets_and_parts": LegoSet.objects.filter(owner=user).count()
            + Part.objects.filter(owner=user).count(),
            "inventory": InventoryItem.objects.filter(owner=user).count()
            + WarehouseLocation.objects.filter(owner=user).count(),
            "organizer": Moc.objects.filter(owner=user).count()
            + PersonalNote.objects.filter(owner=user).count()
            + WishlistItem.objects.filter(owner=user).count(),
            "orders": Order.objects.filter(owner=user).count(),
            "notifications": Notification.objects.filter(owner=user).count(),
            "audit": AuditEvent.objects.filter(Q(actor=user) | Q(target_user=user))
            .distinct()
            .count(),
            "imports": ImportBatch.objects.filter(owner=user).count()
            + LegacyArchiveRecord.objects.filter(owner=user).count(),
            "private_documents": len(documents),
        },
        "private_files": len(documents) - len(missing_files),
        "missing_files": missing_files,
        "estimated_private_file_bytes": available_size,
    }
