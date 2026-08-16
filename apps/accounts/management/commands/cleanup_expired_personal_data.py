from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import AccountSession, PendingEmailChange, RecoveryCode
from apps.data_portability.models import ImportBatch


class Command(BaseCommand):
    help = "Erkennt und bereinigt abgelaufene personenbezogene technische Daten."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        expired_sessions = Session.objects.filter(expire_date__lte=now)
        valid_keys = Session.objects.filter(expire_date__gt=now).values("session_key")
        orphan_sessions = AccountSession.objects.exclude(session_key__in=valid_keys)
        selections = {
            "Abgelaufene Django-Sessions": expired_sessions,
            "Verwaiste AccountSessions": orphan_sessions,
        }
        policies = (
            (
                "PendingEmailChange",
                settings.PENDING_EMAIL_RETENTION_DAYS,
                lambda cutoff: PendingEmailChange.objects.filter(
                    Q(used_at__lte=cutoff) | Q(expires_at__lte=cutoff)
                ),
            ),
            (
                "Verwendete RecoveryCodes",
                settings.RECOVERY_CODE_RETENTION_DAYS,
                lambda cutoff: RecoveryCode.objects.filter(used_at__lte=cutoff),
            ),
            (
                "ImportBatch",
                settings.IMPORT_BATCH_RETENTION_DAYS,
                lambda cutoff: ImportBatch.objects.filter(created_at__lte=cutoff),
            ),
        )
        for label, days, queryset_factory in policies:
            if days is None:
                self.stdout.write(f"{label}: MANUAL POLICY REQUIRED")
            else:
                selections[label] = queryset_factory(now - timedelta(days=days))
        counts = {label: queryset.count() for label, queryset in selections.items()}
        for label, count in counts.items():
            self.stdout.write(f"{label}: {count}")
        self.stdout.write(
            "AuditEvent, Notifications, Legacy-Datensätze, Soft Deletes und private Dateien: "
            "MANUAL POLICY REQUIRED"
        )
        if not options["apply"]:
            self.stdout.write("DRY-RUN: Keine Daten wurden verändert.")
            return
        with transaction.atomic():
            for queryset in selections.values():
                queryset.delete()
        self.stdout.write(f"APPLY: {sum(counts.values())} Datensätze sicher bereinigt.")
