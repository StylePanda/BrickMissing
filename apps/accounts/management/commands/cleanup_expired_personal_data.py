from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from apps.accounts.account_deletion import (
    AccountDeletionFileError,
    permanently_delete_private_document,
)
from apps.accounts.models import AccountSession, PendingEmailChange, RecoveryCode
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part, SetCopy
from apps.core.models import Notification
from apps.data_portability.models import (
    ImportBatch,
    LegacyArchiveRecord,
    LegacyImportRecord,
)
from apps.media_library.models import PrivateDocument
from apps.orders.models import Order
from apps.organizer.models import Moc

SECURITY_AUDIT_FILTER = (
    Q(action__startswith="account.")
    | Q(action__startswith="auth.")
    | Q(action__startswith="login")
    | Q(action__startswith="logout")
    | Q(action__startswith="password")
    | Q(action__startswith="email")
    | Q(action__startswith="two_factor")
    | Q(action__startswith="2fa")
    | Q(action__startswith="recovery")
    | Q(action__startswith="session")
    | Q(action__startswith="export")
    | Q(action__startswith="backup")
)


class Command(BaseCommand):
    help = "Prüft und bereinigt Daten nach der konfigurierten Retention-Policy."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        expired_sessions = Session.objects.filter(expire_date__lte=now)
        valid_keys = Session.objects.filter(expire_date__gt=now).values("session_key")
        orphan_sessions = AccountSession.objects.exclude(session_key__in=valid_keys)

        def cutoff(days):
            return now - timedelta(days=days)

        selections = [
            ("Sessions / abgelaufen", "Ablaufdatum", "AUTO-SAFE", expired_sessions),
            (
                "AccountSessions / verwaist",
                "keine aktive Django-Session",
                "AUTO-SAFE",
                orphan_sessions,
            ),
            (
                "PendingEmailChange / verwendet oder abgelaufen",
                f"{settings.PENDING_EMAIL_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                PendingEmailChange.objects.filter(
                    Q(used_at__lte=cutoff(settings.PENDING_EMAIL_RETENTION_DAYS))
                    | Q(expires_at__lte=cutoff(settings.PENDING_EMAIL_RETENTION_DAYS))
                ),
            ),
            (
                "RecoveryCodes / verwendet",
                f"{settings.RECOVERY_CODE_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                RecoveryCode.objects.filter(
                    used_at__lte=cutoff(settings.RECOVERY_CODE_RETENTION_DAYS)
                ),
            ),
            (
                "ImportBatch",
                f"{settings.IMPORT_BATCH_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                ImportBatch.objects.filter(
                    created_at__lte=cutoff(settings.IMPORT_BATCH_RETENTION_DAYS)
                ),
            ),
            (
                "AuditEvents / Security",
                f"{settings.AUDIT_SECURITY_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                AuditEvent.objects.filter(SECURITY_AUDIT_FILTER).filter(
                    created_at__lte=cutoff(settings.AUDIT_SECURITY_RETENTION_DAYS)
                ),
            ),
            (
                "AuditEvents / Fachaktivität",
                f"{settings.AUDIT_ACTIVITY_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                AuditEvent.objects.exclude(SECURITY_AUDIT_FILTER).filter(
                    created_at__lte=cutoff(settings.AUDIT_ACTIVITY_RETENTION_DAYS)
                ),
            ),
            (
                "Notifications / gelesen",
                f"{settings.NOTIFICATION_RETENTION_DAYS} Tage nach Lesen",
                "POLICY-BASED",
                Notification.objects.filter(
                    read_at__lte=cutoff(settings.NOTIFICATION_RETENTION_DAYS)
                ),
            ),
            (
                "Soft Deletes / LegoSet",
                f"{settings.SOFT_DELETE_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                LegoSet.objects.filter(
                    deleted_at__lte=cutoff(settings.SOFT_DELETE_RETENTION_DAYS)
                ),
            ),
            (
                "Soft Deletes / SetCopy",
                f"{settings.SOFT_DELETE_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                SetCopy.objects.filter(
                    deleted_at__lte=cutoff(settings.SOFT_DELETE_RETENTION_DAYS)
                ),
            ),
            (
                "Soft Deletes / Part",
                f"{settings.SOFT_DELETE_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                Part.objects.filter(
                    deleted_at__lte=cutoff(settings.SOFT_DELETE_RETENTION_DAYS)
                ),
            ),
            (
                "Soft Deletes / Order",
                f"{settings.SOFT_DELETE_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                Order.objects.filter(
                    deleted_at__lte=cutoff(settings.SOFT_DELETE_RETENTION_DAYS)
                ),
            ),
            (
                "Soft Deletes / Moc",
                f"{settings.SOFT_DELETE_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                Moc.objects.filter(
                    deleted_at__lte=cutoff(settings.SOFT_DELETE_RETENTION_DAYS)
                ),
            ),
        ]
        private_documents = PrivateDocument.objects.filter(
            deleted_at__lte=cutoff(settings.PRIVATE_DOCUMENT_DELETED_RETENTION_DAYS)
        )
        selections.append(
            (
                "PrivateDocuments / Soft Delete und physische Datei",
                f"{settings.PRIVATE_DOCUMENT_DELETED_RETENTION_DAYS} Tage",
                "POLICY-BASED",
                private_documents,
            )
        )

        legacy_selections = []
        if settings.LEGACY_DATA_RETENTION_DAYS == 0:
            self.stdout.write(
                "Legacy Data: Frist=unbegrenzt; Treffer=0; Status=SKIPPED; "
                "Grund=Import-Idempotenz und Migrationsnachweis"
            )
        else:
            legacy_cutoff = cutoff(settings.LEGACY_DATA_RETENTION_DAYS)
            legacy_selections = [
                LegacyImportRecord.objects.filter(imported_at__lte=legacy_cutoff),
                LegacyArchiveRecord.objects.filter(imported_at__lte=legacy_cutoff),
            ]
            legacy_count = sum(queryset.count() for queryset in legacy_selections)
            self.stdout.write(
                f"Legacy Data: Frist={settings.LEGACY_DATA_RETENTION_DAYS} Tage; "
                f"Treffer={legacy_count}; Status=POLICY-BASED"
            )

        for label, retention, status, queryset in selections:
            self.stdout.write(
                f"{label}: Frist={retention}; Treffer={queryset.count()}; Status={status}"
            )

        if not options["apply"]:
            self.stdout.write("DRY-RUN: Keine Daten und keine Dateien wurden verändert.")
            return

        deleted = 0
        for label, _retention, _status, queryset in selections:
            if label.startswith("PrivateDocuments"):
                continue
            count, _details = queryset.delete()
            deleted += count
        for queryset in legacy_selections:
            count, _details = queryset.delete()
            deleted += count

        file_failures = 0
        for document in private_documents.iterator():
            try:
                permanently_delete_private_document(document)
            except AccountDeletionFileError as exc:
                file_failures += 1
                self.stderr.write(f"PrivateDocument {document.pk}: SKIPPED ({exc})")
            else:
                deleted += 1
        self.stdout.write(f"APPLY: {deleted} Datensätze/Dateien policy-konform bereinigt.")
        if file_failures:
            raise CommandError(
                f"{file_failures} private Dokument(e) blieben aus Sicherheitsgründen erhalten."
            )
