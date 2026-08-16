from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Gibt eine read-only Datenschutz-/Security-Konfigurationsübersicht ohne Secrets aus."

    def handle(self, *args, **options):
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
        }
        self.stdout.write("Privacy Production Audit – READ-ONLY")
        for label, value in checks.items():
            self.stdout.write(f"{label}: {value}")
        self.stdout.write(
            "MANUELL: SMTP-Provider/Region/AV-Vertrag; Nginx/journald/logrotate; "
            "Serverstandort; MariaDB-Logs; VM-/Offsite-Backups; DNS/CDN/WAF/Cloudflare; "
            "externe APIs; Admin-/Staff-Zuweisungen."
        )
        self.stdout.write("Keine Secrets oder personenbezogenen Inhalte ausgegeben.")
