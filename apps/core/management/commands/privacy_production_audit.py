from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q


class Command(BaseCommand):
    help = "Gibt eine read-only Datenschutz-/Security-Konfigurationsübersicht ohne Secrets aus."

    def handle(self, *args, **options):
        user_model = get_user_model()
        legal_status = {
            name: "OK" if getattr(settings, name, "") else "FEHLT"
            for name in (
                "LEGAL_OPERATOR_NAME",
                "LEGAL_OPERATOR_ADDRESS",
                "LEGAL_OPERATOR_EMAIL",
                "LEGAL_OPERATOR_COUNTRY",
            )
        }
        checks = {
            "DB-Backend": connection.vendor,
            "DEBUG": settings.DEBUG,
            "Session-Engine": settings.SESSION_ENGINE,
            "Session-Cookie Secure": settings.SESSION_COOKIE_SECURE,
            "Session-Cookie HttpOnly": settings.SESSION_COOKIE_HTTPONLY,
            "Session-Cookie SameSite": settings.SESSION_COOKIE_SAMESITE,
            "CSRF-Cookie Secure": settings.CSRF_COOKIE_SECURE,
            "CSRF-Cookie SameSite": settings.CSRF_COOKIE_SAMESITE,
            "HSTS Sekunden": settings.SECURE_HSTS_SECONDS,
            "PUBLIC_URL konfiguriert": bool(getattr(settings, "PUBLIC_URL", "")),
            "Backup Root": str(settings.BACKUP_ROOT),
            "Backup Retention Count": settings.BACKUP_RETENTION_COUNT,
            "Image-Proxy Hosts": ", ".join(settings.IMAGE_PROXY_ALLOWED_HOSTS),
            "Mail-Backend-Klasse": settings.EMAIL_BACKEND,
            "Pending E-Mail Retention Tage": settings.PENDING_EMAIL_RETENTION_DAYS,
            "Recovery-Code Retention Tage": settings.RECOVERY_CODE_RETENTION_DAYS,
            "ImportBatch Retention Tage": settings.IMPORT_BATCH_RETENTION_DAYS,
            "Security-Audit Retention Tage": settings.AUDIT_SECURITY_RETENTION_DAYS,
            "Activity-Audit Retention Tage": settings.AUDIT_ACTIVITY_RETENTION_DAYS,
            "Notification Retention Tage": settings.NOTIFICATION_RETENTION_DAYS,
            "Soft-Delete Retention Tage": settings.SOFT_DELETE_RETENTION_DAYS,
            "PrivateDocument Retention Tage": settings.PRIVATE_DOCUMENT_DELETED_RETENTION_DAYS,
            "Legacy Retention": (
                "unbegrenzt/idempotenzgesichert"
                if settings.LEGACY_DATA_RETENTION_DAYS == 0
                else f"{settings.LEGACY_DATA_RETENTION_DAYS} Tage"
            ),
            "Legal Basis Status": ", ".join(
                f"{name.removeprefix('LEGAL_')}={status}"
                for name, status in legal_status.items()
            ),
            "Staff Anzahl": user_model.objects.filter(is_staff=True).count(),
            "Superuser Anzahl": user_model.objects.filter(is_superuser=True).count(),
            "Staff mit Backup-Permission": user_model.objects.filter(
                Q(is_superuser=True)
                | Q(user_permissions__codename="manage_backup")
                | Q(groups__permissions__codename="manage_backup"),
                is_staff=True,
            ).distinct().count(),
        }
        self.stdout.write("Privacy Production Audit – READ-ONLY")
        for label, value in checks.items():
            self.stdout.write(f"{label}: {value}")
        self.stdout.write(
            "MANUAL SERVER FACT: Nginx tägliche Rotation/rotate 14; journald ohne "
            "festgestellte MaxRetentionSec; MariaDB general_log OFF/slow_query_log OFF. "
            "MANUELL: SMTP-Provider/Region/AV-Vertrag; Serverstandort; "
            "VM-/Offsite-Backups; DNS/CDN/WAF/Cloudflare; "
            "externe APIs; Admin-/Staff-Zuweisungen."
        )
        self.stdout.write("Keine Secrets oder personenbezogenen Inhalte ausgegeben.")
