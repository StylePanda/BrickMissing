from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from cryptography.fernet import Fernet, InvalidToken
from brickmissing.core.time import utc_now


@dataclass(frozen=True)
class AppConfig:
    root: Path
    host: str
    port: int
    session_hours: int = 8
    login_limit: int = 5
    lock_minutes: int = 15

    @classmethod
    def load(cls, root: Path) -> "AppConfig":
        return cls(
            root=root,
            # Deliberately fixed to loopback: the application must never listen
            # on a LAN, VPN or public network interface.
            host="127.0.0.1",
            port=int(os.environ.get("BRICKMISSING_PORT", "8088")),
            session_hours=int(os.environ.get("BRICKMISSING_SESSION_HOURS", "8")),
        )


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def transaction(self):
        """Open one explicit transaction with guaranteed rollback and cleanup."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class PasswordHasher:
    algorithm = "pbkdf2_sha256"

    def __init__(self, iterations: int = 310_000):
        self.iterations = iterations

    def hash(self, password: str) -> str:
        if len(password) < 8:
            raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")
        if not re.search(r"[A-ZÄÖÜ]", password):
            raise ValueError("Das Passwort benötigt mindestens einen Großbuchstaben.")
        if not re.search(r"[a-zäöüß]", password):
            raise ValueError("Das Passwort benötigt mindestens einen Kleinbuchstaben.")
        if not re.search(r"\d", password):
            raise ValueError("Das Passwort benötigt mindestens eine Zahl.")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, self.iterations
        )
        return (
            f"{self.algorithm}${self.iterations}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
        )

    def verify(self, password: str, encoded: str | None) -> bool:
        try:
            algorithm, iterations, salt, expected = (encoded or "").split("$", 3)
            if algorithm != self.algorithm:
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                base64.b64decode(salt),
                int(iterations),
            )
            return hmac.compare_digest(actual, base64.b64decode(expected))
        except (ValueError, TypeError):
            return False


class AuditLogger:
    _secret_pattern = re.compile(
        r"(?i)(password|passwort|token|api[_-]?key|secret)\s*[:=]\s*[^,;\s]+"
    )

    def record(
        self,
        conn: sqlite3.Connection,
        action: str,
        actor_id: int | None = None,
        target_user_id: int | None = None,
        details: str = "",
        remote_address: str = "",
    ) -> None:
        safe_details = self._secret_pattern.sub(r"\1=[geschützt]", str(details))
        conn.execute(
            """INSERT INTO audit_log(actor_id,target_user_id,action,details,remote_address)
               VALUES(?,?,?,?,?)""",
            (actor_id, target_user_id, action, safe_details[:500], remote_address[:100]),
        )

    @staticmethod
    def purge(conn: sqlite3.Connection, retention_days: int = 365) -> int:
        days = min(max(int(retention_days), 30), 3650)
        cursor = conn.execute(
            "DELETE FROM audit_log WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        return max(int(cursor.rowcount or 0), 0)


class SecretCipher:
    prefix = "fernet:"

    def __init__(self, key_file: Path):
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if not key_file.exists():
            encrypted_configs: list[Path] = []
            for name in ("smtp.json", "mariadb.json"):
                config = key_file.parent / name
                if config.exists() and "fernet:" in config.read_text(encoding="utf-8"):
                    encrypted_configs.append(config)
            encrypted_backups = list(
                (key_file.parent.parent / "backups").glob("*.db.enc")
            )
            if encrypted_configs or encrypted_backups:
                recovery = {
                    "reason": "missing_master_key",
                    "encrypted_configs": [path.name for path in encrypted_configs],
                    "encrypted_backups": [path.name for path in encrypted_backups],
                    "action": (
                        "Alte verschlüsselte Dateien wurden nicht gelöscht. "
                        "MariaDB- und E-Mail-Geheimnisse müssen neu eingegeben werden."
                    ),
                    "created_at": utc_now().isoformat(),
                }
                for config in encrypted_configs:
                    backup = config.with_name(config.name + ".missing-key.bak")
                    if not backup.exists():
                        shutil.copy2(config, backup)
                    data = json.loads(config.read_text(encoding="utf-8"))
                    for field in ("password", "api_key"):
                        if str(data.get(field, "")).startswith(self.prefix):
                            data[field] = ""
                    if config.name == "mariadb.json":
                        data["engine"] = "sqlite"
                        data["active"] = False
                        data["last_sync_error"] = (
                            "Master-Key fehlte; MariaDB-Passwort bitte neu eingeben."
                        )
                    if config.name == "smtp.json":
                        data["enabled"] = False
                        data["mode"] = "disabled"
                    config.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                (key_file.parent / "KEY_RECOVERY_REQUIRED.json").write_text(
                    json.dumps(recovery, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            key_file.write_bytes(Fernet.generate_key())
        self._fernet = Fernet(key_file.read_bytes().strip())

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        if value.startswith(self.prefix):
            return value
        return self.prefix + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        if not value.startswith(self.prefix):
            return value
        try:
            return self._fernet.decrypt(value[len(self.prefix):].encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Der Sicherheitsschlüssel passt nicht zu den verschlüsselten Daten.") from exc

    def encrypt_bytes(self, value: bytes) -> bytes:
        return self._fernet.encrypt(value)

    def decrypt_bytes(self, value: bytes) -> bytes:
        return self._fernet.decrypt(value)


class BackupManager:
    def __init__(self, database: Database, folder: Path, cipher: SecretCipher, maximum: int = 30):
        self.database = database
        self.folder = folder
        self.cipher = cipher
        self.maximum = maximum

    def create(self) -> int:
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        target = self.folder / f"brickmissing_{stamp}.db.enc"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            source = self.database.connect()
            destination = sqlite3.connect(temp_path)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            target.write_bytes(self.cipher.encrypt_bytes(temp_path.read_bytes()))
        finally:
            temp_path.unlink(missing_ok=True)
        files = sorted(self.folder.glob("brickmissing_*.db.enc"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[self.maximum:]:
            old.unlink(missing_ok=True)
        return len(files[: self.maximum])

    def list_verified(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(
            self.folder.glob("brickmissing_*.db.enc"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            valid = False
            error = ""
            try:
                raw = self.cipher.decrypt_bytes(path.read_bytes())
                valid = raw.startswith(b"SQLite format 3\x00")
                if not valid:
                    error = "Ungültiges SQLite-Format"
            except Exception as exc:
                error = str(exc)
            result.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        path.stat().st_mtime, timezone.utc
                    ).isoformat(),
                    "valid": valid,
                    "error": error,
                }
            )
        return result

    def import_encrypted(self, data: bytes) -> dict[str, Any]:
        if not data:
            raise ValueError("Die hochgeladene Sicherung ist leer.")
        if len(data) > 100 * 1024 * 1024:
            raise ValueError("Die Sicherung darf höchstens 100 MB groß sein.")
        try:
            raw = self.cipher.decrypt_bytes(data)
        except Exception as exc:
            raise ValueError(
                "Die Sicherung kann mit diesem BrickMissing-Schlüssel nicht entschlüsselt werden."
            ) from exc
        if not raw.startswith(b"SQLite format 3\x00"):
            raise ValueError("Die Sicherung enthält keine gültige SQLite-Datenbank.")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(raw)
        try:
            test = sqlite3.connect(temp_path)
            try:
                result = test.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise ValueError("Die Integritätsprüfung der Sicherung ist fehlgeschlagen.")
            finally:
                test.close()
        finally:
            temp_path.unlink(missing_ok=True)
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        target = self.folder / f"brickmissing_import_{stamp}.db.enc"
        target.write_bytes(data)
        return {"name": target.name, "size": target.stat().st_size, "valid": True}

    def restore(self, name: str) -> None:
        if Path(name).name != name or not name.startswith("brickmissing_"):
            raise ValueError("Ungültiger Sicherungsname.")
        source = self.folder / name
        if not source.exists():
            raise ValueError("Sicherung nicht gefunden.")
        raw = self.cipher.decrypt_bytes(source.read_bytes())
        if not raw.startswith(b"SQLite format 3\x00"):
            raise ValueError("Die Sicherung ist keine gültige SQLite-Datenbank.")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(raw)
        try:
            test = sqlite3.connect(temp_path)
            try:
                result = test.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise ValueError("Integritätsprüfung der Sicherung fehlgeschlagen.")
            finally:
                test.close()
            self.create()
            # Replace the database atomically so a crash cannot leave a partial file.
            staged = self.database.path.with_suffix(".restore.tmp")
            staged.write_bytes(temp_path.read_bytes())
            with sqlite3.connect(staged) as restored:
                result = restored.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise ValueError("Integritätsprüfung der Wiederherstellung fehlgeschlagen.")
            staged.replace(self.database.path)
            for suffix in ("-wal", "-shm"):
                Path(str(self.database.path) + suffix).unlink(missing_ok=True)
        finally:
            temp_path.unlink(missing_ok=True)


class BackupCoordinator:
    """Serializes backups and combines bursts of mutations into one run."""

    def __init__(self, create_backup: Callable[[], int], delay: float = 1.0):
        self.create_backup = create_backup
        self.delay = delay
        self._backup_lock = threading.Lock()
        self._timer_lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def run(self) -> int:
        with self._backup_lock:
            return self.create_backup()

    def schedule(self) -> None:
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._run_scheduled)
            self._timer.daemon = True
            self._timer.start()

    def _run_scheduled(self) -> None:
        with self._timer_lock:
            self._timer = None
        self.run()


class SessionManager:
    def __init__(self, config: AppConfig):
        self.config = config

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def create(self, conn: sqlite3.Connection, user: sqlite3.Row) -> tuple[str, dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        expires = utc_now() + timedelta(hours=self.config.session_hours)
        conn.execute(
            """INSERT INTO sessions(token_hash,user_id,csrf_token,selected_user_id,expires_at,last_activity)
               VALUES(?,?,?,?,?,?)""",
            (self._digest(token), user["id"], csrf, user["id"], expires.isoformat(), utc_now().isoformat()),
        )
        return token, {
            "id": int(user["id"]),
            "name": user["name"],
            "role": user["role"],
            "selected_user_id": int(user["id"]),
            "csrf_token": csrf,
            "must_change_password": bool(user["must_change_password"]),
        }

    def get(self, conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
        now = utc_now()
        conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now.isoformat(),))
        row = conn.execute(
            """SELECT s.*,u.name,u.role,u.disabled,u.deleted_at,u.must_change_password
               FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""",
            (self._digest(token),),
        ).fetchone()
        if not row or row["disabled"] or row["deleted_at"]:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= now:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (self._digest(token),))
            return None
        conn.execute(
            "UPDATE sessions SET last_activity=? WHERE token_hash=?",
            (now.isoformat(), self._digest(token)),
        )
        return {
            "id": int(row["user_id"]),
            "name": row["name"],
            "role": row["role"],
            "selected_user_id": int(row["selected_user_id"] or row["user_id"]),
            "csrf_token": row["csrf_token"],
            "must_change_password": bool(row["must_change_password"]),
        }

    def select_user(self, conn: sqlite3.Connection, token: str, user_id: int) -> None:
        conn.execute(
            "UPDATE sessions SET selected_user_id=? WHERE token_hash=?",
            (user_id, self._digest(token)),
        )

    def delete(self, conn: sqlite3.Connection, token: str) -> None:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (self._digest(token),))

    def delete_for_user(self, conn: sqlite3.Connection, user_id: int) -> None:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


class LoginGuard:
    def __init__(self, config: AppConfig):
        self.config = config

    def assert_allowed(self, user: sqlite3.Row) -> None:
        if user["disabled"] or user["deleted_at"]:
            raise PermissionError("Dieses Konto ist deaktiviert.")
        if user["locked_until"]:
            until = datetime.fromisoformat(user["locked_until"])
            if until > utc_now():
                raise PermissionError("Konto vorübergehend gesperrt. Bitte später erneut versuchen.")

    def failed(self, conn: sqlite3.Connection, user_id: int) -> None:
        row = conn.execute(
            "SELECT failed_login_attempts FROM users WHERE id=?", (user_id,)
        ).fetchone()
        attempts = int(row["failed_login_attempts"] or 0) + 1
        locked = (
            (utc_now() + timedelta(minutes=self.config.lock_minutes)).isoformat()
            if attempts >= self.config.login_limit else None
        )
        conn.execute(
            "UPDATE users SET failed_login_attempts=?,locked_until=? WHERE id=?",
            (attempts, locked, user_id),
        )

    @staticmethod
    def succeeded(conn: sqlite3.Connection, user_id: int) -> None:
        conn.execute(
            """UPDATE users SET failed_login_attempts=0,locked_until=NULL,
               last_login=CURRENT_TIMESTAMP WHERE id=?""",
            (user_id,),
        )


class ApplicationServices:
    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.database = database
        self.passwords = PasswordHasher()
        self.secrets = SecretCipher(config.root / "data" / ".master.key")
        self.backups = BackupManager(database, config.root / "backups", self.secrets)
        self.sessions = SessionManager(config)
        self.audit = AuditLogger()
        self.login_guard = LoginGuard(config)
