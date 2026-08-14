from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pymysql
from cryptography.fernet import Fernet, InvalidToken

DATABASE = "brickmissing_v8_migration_rehearsal"


def _version_tuple(raw: str) -> tuple[int, int]:
    version = raw.split("-", 1)[0]
    major, minor, *_ = version.split(".")
    return int(major), int(minor)


def run_rehearsal(
    project: Path,
    config_path: Path,
    source: Path,
    report: Path,
    *,
    run_tests=True,
    test_labels: tuple[str, ...] = (),
) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    host = str(config.get("host", ""))
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Rehearsal only permits a local MariaDB server")
    password = str(config["password"])
    if password.startswith("fernet:"):
        key_path = config_path.parent / ".master.key"
        try:
            password = Fernet(key_path.read_bytes().strip()).decrypt(
                password.removeprefix("fernet:").encode("ascii")
            ).decode("utf-8")
        except (OSError, InvalidToken, ValueError) as exc:
            raise RuntimeError("MariaDB rehearsal credential cannot be decrypted") from exc
    connection = pymysql.connect(
        host=host,
        port=int(config.get("port", 3306)),
        user=config["user"],
        password=password,
        charset="utf8mb4",
        autocommit=True,
    )
    created = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            detected = str(cursor.fetchone()[0])
            print(f"MariaDB detected:\n{detected}\n\nRequired:\n>= 10.5")
            if _version_tuple(detected) < (10, 5):
                print("\nResult:\nUNSUPPORTED")
                raise RuntimeError(
                    f"MariaDB {detected} is unsupported; server upgrade to >= 10.5 required"
                )
            print("\nResult:\nSUPPORTED")
            cursor.execute("SHOW DATABASES LIKE %s", (DATABASE,))
            if cursor.fetchone():
                raise RuntimeError("Refusing to reuse an existing rehearsal database")
            cursor.execute(
                f"CREATE DATABASE `{DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"  # noqa: S608 -- fixed constant
            )
            created = True
        environment = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
            "BACKUP_ENCRYPTION_KEY": secrets.token_urlsafe(64),
            "TOTP_ENCRYPTION_KEY": secrets.token_urlsafe(64),
            "DJANGO_ALLOWED_HOSTS": "rehearsal.invalid",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://rehearsal.invalid",
            "DJANGO_PUBLIC_URL": "https://rehearsal.invalid",
            "DB_HOST": host,
            "DB_PORT": str(config.get("port", 3306)),
            "DB_NAME": DATABASE,
            "DB_USER": str(config["user"]),
            "DB_PASSWORD": password,
        }
        commands = [
            [sys.executable, "manage.py", "migrate", "--noinput"],
            [sys.executable, "manage.py", "migrate_legacy_brickmissing", "--source", str(source)],
            [sys.executable, "manage.py", "validate_legacy_migration", "--source", str(source), "--output", str(report)],
            [sys.executable, "manage.py", "check"],
        ]
        if run_tests:
            commands.append([sys.executable, "manage.py", "test", *test_labels])
            if not test_labels:
                commands.append([sys.executable, "manage.py", "verify_mariadb_locking"])
        for command in commands:
            try:
                subprocess.run(  # noqa: S603 -- fixed interpreter/manage.py command family
                    command, cwd=project, env=environment, check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"Rehearsal command {command[2]} failed:\n{exc.stdout}"
                ) from exc
    finally:
        if created:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP DATABASE `{DATABASE}`")  # noqa: S608 -- fixed constant
        connection.close()


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=project / "data" / "mariadb.json")
    parser.add_argument("--source", type=Path, default=project / "data" / "brickmissing.db")
    parser.add_argument(
        "--report", type=Path, default=project / "var" / "reports" / "legacy_reconciliation.json"
    )
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument(
        "--test-label",
        action="append",
        default=[],
        help="Run selected Django test labels for diagnostics; omit for the full suite.",
    )
    args = parser.parse_args()
    try:
        run_rehearsal(
            project, args.config.resolve(), args.source.resolve(), args.report.resolve(),
            run_tests=not args.skip_tests,
            test_labels=tuple(args.test_label),
        )
    except (RuntimeError, pymysql.MySQLError) as exc:
        print(f"MariaDB rehearsal: BLOCKED\n{exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print("MariaDB rehearsal: PASS")


if __name__ == "__main__":
    main()
