from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Erstellt ein konsistentes MariaDB-Dump ohne Passwort in der Prozessliste."

    def add_arguments(self, parser):
        parser.add_argument("--destination", type=Path, default=Path("/var/backups/brickmissing"))

    def handle(self, *args, **options):
        required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise CommandError("Fehlende Environment-Variablen: " + ", ".join(missing))
        folder = options["destination"].resolve()
        folder.mkdir(parents=True, exist_ok=True, mode=0o750)
        target = folder / f"brickmissing-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.sql"
        env = os.environ.copy()
        env["MYSQL_PWD"] = env["DB_PASSWORD"]
        command = [
            "mariadb-dump",
            "--single-transaction",
            "--quick",
            "--routines",
            "--triggers",
            "--host",
            env["DB_HOST"],
            "--port",
            env["DB_PORT"],
            "--user",
            env["DB_USER"],
            env["DB_NAME"],
        ]
        try:
            with target.open("xb") as stream:
                # Arguments are a fixed executable plus administrator-owned env values;
                # no shell is involved and web users cannot reach this command.
                subprocess.run(  # noqa: S603
                    command,
                    check=True,
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    env=env,
                )
            target.chmod(0o640)
        except (OSError, subprocess.CalledProcessError) as exc:
            target.unlink(missing_ok=True)
            raise CommandError("Datenbank-Backup fehlgeschlagen") from exc
        self.stdout.write(self.style.SUCCESS(str(target)))
