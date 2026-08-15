from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.audit.models import AuditEvent
from apps.backups.models import BackupArtifact
from apps.data_portability.models import ImportBatch, LegacyArchiveRecord, LegacyImportRecord
from apps.inventory.models import InventoryMovement
from apps.media_library.models import PrivateDocument
from apps.organizer.models import Collection


class Command(BaseCommand):
    help = "Prüft read-only, welche Daten bei einer Account-Löschung betroffen wären."

    def add_arguments(self, parser):
        parser.add_argument("user", help="UUID oder exakter Benutzername")

    def handle(self, *args, **options):
        selector = options["user"].strip()
        try:
            user = get_user_model().objects.filter(pk=selector).first()
        except (ValueError, ValidationError):
            user = None
        user = user or get_user_model().objects.filter(username=selector).first()
        if not user:
            raise CommandError("Benutzerkonto wurde nicht gefunden.")
        self.stdout.write(f"Account-ID: {user.pk}")
        relations = user._meta.related_objects
        for relation in sorted(relations, key=lambda item: item.related_model._meta.label):
            accessor = relation.get_accessor_name()
            if not accessor:
                continue
            count = relation.related_model._default_manager.filter(
                **{relation.field.name: user}
            ).count()
            self.stdout.write(f"Direkt {relation.related_model._meta.label}: {count}")
        self.stdout.write(
            f"Indirekt InventoryMovement(PROTECT): "
            f"{InventoryMovement.objects.filter(item__owner=user).count()}"
        )
        self.stdout.write(
            f"Private Dateien: {PrivateDocument.objects.filter(owner=user).count()}"
        )
        self.stdout.write(
            f"Geteilte eigene Collections: "
            f"{Collection.objects.filter(owner=user, members__isnull=False).distinct().count()}"
        )
        self.stdout.write(
            f"AuditEvents: {AuditEvent.objects.filter(Q(actor=user) | Q(target_user=user)).count()}"
        )
        self.stdout.write(f"ImportBatch: {ImportBatch.objects.filter(owner=user).count()}")
        self.stdout.write(
            "Security Records: "
            f"PendingEmailChange={user.pending_email_changes.count()}, "
            f"RecoveryCode={user.recovery_codes.count()}, "
            f"AccountSession={user.account_sessions.count()}"
        )
        self.stdout.write(
            "Erhalten/SET_NULL: "
            f"BackupArtifact={BackupArtifact.objects.filter(created_by=user).count()}, "
            f"LegacyImportRecord={LegacyImportRecord.objects.filter(imported_by=user).count()}, "
            f"LegacyArchiveRecord={LegacyArchiveRecord.objects.filter(owner=user).count()}"
        )
        self.stdout.write(self.style.WARNING("READ-ONLY: Es wurden keine Daten verändert."))
