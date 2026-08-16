import os
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import resolve, reverse

from apps.backups.models import BackupArtifact


class Command(BaseCommand):
    help = "Prüft Phase 11 read-only auf technische Vollständigkeit und Publication-Blocker."

    def handle(self, *args, **options):
        results = []

        def add(level, label, detail=""):
            results.append((level, label, detail))

        required_operator = {
            "LEGAL_OPERATOR_NAME": settings.LEGAL_OPERATOR_NAME,
            "LEGAL_OPERATOR_ADDRESS": settings.LEGAL_OPERATOR_ADDRESS,
            "LEGAL_OPERATOR_EMAIL": settings.LEGAL_OPERATOR_EMAIL,
            "LEGAL_OPERATOR_COUNTRY": settings.LEGAL_OPERATOR_COUNTRY,
        }
        missing = [name for name, value in required_operator.items() if not value]
        placeholders = [
            name
            for name, value in required_operator.items()
            if "[" in value or value.endswith(".invalid")
        ]
        if missing:
            add("ERROR", "Betreiberbasisdaten", ", ".join(missing))
        elif placeholders:
            level = "WARNING" if settings.DEBUG else "ERROR"
            add(level, "Betreiberbasisdaten enthalten Platzhalter", ", ".join(placeholders))
        else:
            add("PASS", "Betreiberbasisdaten")

        for name in ("legal:imprint", "legal:privacy"):
            url = reverse(name)
            resolve(url)
            add("PASS", f"Öffentliche Route {url}")

        templates_root = Path(settings.BASE_DIR) / "templates"
        base = (templates_root / "base.html").read_text(encoding="utf-8")
        register = (templates_root / "accounts" / "register.html").read_text(encoding="utf-8")
        profile = (templates_root / "accounts" / "profile.html").read_text(encoding="utf-8")
        required_template_checks = {
            "Footer verlinkt Impressum und Datenschutz": all(
                item in base for item in ("legal:imprint", "legal:privacy")
            ),
            "Registrierung verlinkt Datenschutz": "legal:privacy" in register,
            "Account-Löschung vorhanden": "accounts:delete_account" in profile,
            "Personenbezogener Export vorhanden": "data_portability:personal_export" in profile,
            "Private-File-Lifecycle vorhanden": (
                Path(settings.BASE_DIR) / "apps" / "accounts" / "account_deletion.py"
            ).exists(),
            "Orphan-File-Audit vorhanden": (
                Path(settings.BASE_DIR)
                / "apps"
                / "media_library"
                / "management"
                / "commands"
                / "audit_orphan_private_files.py"
            ).exists(),
            "Retention-Cleanup vorhanden": (
                Path(settings.BASE_DIR)
                / "apps"
                / "accounts"
                / "management"
                / "commands"
                / "cleanup_expired_personal_data.py"
            ).exists(),
            "Image Proxy vorhanden": reverse("integrations:image_proxy").startswith("/"),
        }
        for label, passed in required_template_checks.items():
            add("PASS" if passed else "ERROR", label)

        backup_permission = "manage_backup" in dict(BackupArtifact._meta.permissions)
        add("PASS" if backup_permission else "ERROR", "Backup Permission backups.manage_backup")

        tracked_patterns = ("google-analytics.com", "googletagmanager.com", "gtag(", "segment.com")
        scan_text = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for root in (templates_root, Path(settings.BASE_DIR) / "static")
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".html", ".js"}
        ).lower()
        tracking = [pattern for pattern in tracked_patterns if pattern in scan_text]
        add("ERROR" if tracking else "PASS", "Keine Tracking-Technologien erkannt", ", ".join(tracking))
        add("INFO", "Cookiebestand", "sessionid, csrftoken; localStorage: brickmissing-theme")

        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        add("ERROR" if pending else "PASS", "Angewandte Migrationen", f"offen: {len(pending)}")
        try:
            call_command("makemigrations", check=True, dry_run=True, verbosity=0)
        except (CommandError, SystemExit) as exc:
            add("ERROR", "Migration Drift", str(exc))
        else:
            add("PASS", "Migration Drift")

        production_checks = {
            "DEBUG deaktiviert": not settings.DEBUG,
            "Session-Cookie HttpOnly": settings.SESSION_COOKIE_HTTPONLY,
            "Session-Cookie Secure": settings.SESSION_COOKIE_SECURE,
            "CSRF-Cookie Secure": settings.CSRF_COOKIE_SECURE,
            "HSTS aktiviert": settings.SECURE_HSTS_SECONDS > 0,
        }
        settings_module = getattr(settings, "SETTINGS_MODULE", None) or os.getenv(
            "DJANGO_SETTINGS_MODULE", ""
        )
        production_mode = settings_module.endswith(".production")
        for label, passed in production_checks.items():
            level = "PASS" if passed else ("ERROR" if production_mode else "INFO")
            add(level, label)

        self.stdout.write("Privacy Final Check – READ-ONLY")
        for level, label, detail in results:
            suffix = f": {detail}" if detail else ""
            self.stdout.write(f"{level} {label}{suffix}")
        blockers = [item for item in results if item[0] in {"CRITICAL", "ERROR"}]
        status = "READY" if not blockers else "NOT READY"
        self.stdout.write(f"PHASE 11 STATUS: {status}")
        if blockers:
            raise CommandError("Phase 11 enthält CRITICAL/ERROR-Prüfergebnisse.")
