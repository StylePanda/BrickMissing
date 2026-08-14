from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path

from brickmissing.core.services import (
    BackupCoordinator,
    PasswordHasher,
    SecretCipher,
)
from brickmissing.database.mariadb import MariaConnection, MariaDbAdminService
from brickmissing.database.migrations import MIGRATIONS
from brickmissing.integrations.email import EmailService
from brickmissing.security.account import AccountSecurityService
from brickmissing.security.authorization import AuthorizationPolicy
from brickmissing.services.pro7 import Pro7Service
from brickmissing.services.user_content import UserContentService
from brickmissing.web.api import ApiError, RequestValidator, SlidingWindowRateLimiter
from brickmissing.web.assets import AssetService


class PlatformTests(unittest.TestCase):
    def test_request_validator_rejects_wrong_content_type_and_size(self) -> None:
        headers = Message()
        headers["Content-Length"] = "12"
        headers["Content-Type"] = "text/plain"
        self.assertEqual(RequestValidator.content_length(headers, 20), 12)
        with self.assertRaises(ApiError):
            RequestValidator.require_json(headers, True)
        with self.assertRaises(ApiError):
            RequestValidator.content_length(headers, 5)

    def test_local_qr_generation_returns_svg(self) -> None:
        data = AssetService.qr_svg("http://127.0.0.1:8088/?set_id=1")
        self.assertIn(b"<svg", data)

    def test_user_content_is_persistent_and_user_scoped(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE user_settings(user_id INTEGER, `key` TEXT, value TEXT, "
            "PRIMARY KEY(user_id, `key`))"
        )
        conn.executescript(
            """CREATE TABLE personal_notes(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,
                   title TEXT,content TEXT,created_at TEXT,updated_at TEXT);
               CREATE TABLE workshop_documents(
                   user_id INTEGER PRIMARY KEY,payload TEXT,updated_at TEXT);"""
        )
        service = UserContentService()
        notes = service.save_note(conn, 1, None, "Einkauf", "Zwei Teile suchen")
        service.save_workshop(conn, 1, {"projects": [{"name": "Falcon"}]})
        self.assertEqual(notes[0]["title"], "Einkauf")
        self.assertEqual(service.notes(conn, 1)[0]["content"], "Zwei Teile suchen")
        self.assertEqual(service.workshop(conn, 1)["projects"][0]["name"], "Falcon")
        self.assertEqual(service.notes(conn, 2), [])
        self.assertEqual(service.delete_note(conn, 1, notes[0]["id"]), [])

    def test_backup_coordinator_debounces_mutation_bursts(self) -> None:
        completed = threading.Event()
        calls = []

        def create_backup() -> int:
            calls.append(1)
            completed.set()
            return len(calls)

        coordinator = BackupCoordinator(create_backup, delay=0.03)
        coordinator.schedule()
        coordinator.schedule()
        coordinator.schedule()
        self.assertTrue(completed.wait(1))
        self.assertEqual(calls, [1])

    def test_authorization_policy_checks_ownership(self) -> None:
        user = {"id": 4, "role": "user"}
        self.assertTrue(AuthorizationPolicy.owns(user, 4))
        self.assertFalse(AuthorizationPolicy.owns(user, 5))
        with self.assertRaises(PermissionError):
            AuthorizationPolicy.require_owner(user, 5, "diese Bestellung")

    def test_image_cache_rejects_untrusted_hosts(self) -> None:
        with self.assertRaises(ValueError):
            AssetService(Path("cache")).cached_image(
                "https://example.invalid/private-image.jpg"
            )

    def test_mariadb_sql_translation(self) -> None:
        translated = MariaConnection._sql(
            """INSERT INTO user_settings(user_id,key,value) VALUES(?,?,?)
               ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value"""
        )
        self.assertIn("ON DUPLICATE KEY UPDATE", translated)
        self.assertIn("value=VALUES(value)", translated)
        self.assertNotIn("ON CONFLICT", translated)

    def test_mariadb_runtime_schema_contains_operational_tables(self) -> None:
        schema = "\n".join(
            MariaDbAdminService.runtime_schema_statements()
        ).lower()
        for table in (
            "notifications",
            "value_snapshots",
            "system_health",
            "background_jobs",
            "saved_views",
            "personal_notes",
            "workshop_documents",
        ):
            self.assertIn(f"create table if not exists {table}", schema)
        source = Path("brickmissing/database/mariadb.py").read_text(encoding="utf-8")
        self.assertIn('(10, "user_content_and_query_indexes")', source)

    def test_mariadb_read_only_migration_table_uses_safe_fallback(self) -> None:
        class ReadOnlyMigrationConnection:
            def __init__(self):
                self.statements = []
                self.rollbacks = 0

            def execute(self, sql, parameters=()):
                self.statements.append((sql, parameters))
                if (
                    "INSERT IGNORE INTO schema_migrations" in sql
                    and "write_probe" in sql
                ):
                    raise RuntimeError("Table 'schema_migrations' is read only")
                return self

            def rollback(self):
                self.rollbacks += 1

        connection = ReadOnlyMigrationConnection()
        table = MariaDbAdminService.migration_tracking_table(connection)
        self.assertEqual(table, "brickmissing_schema_migrations")
        self.assertEqual(connection.rollbacks, 1)
        executed = "\n".join(statement for statement, _ in connection.statements)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS brickmissing_schema_migrations",
            executed,
        )
        self.assertIn("migration_tracking", executed)

    def test_mariadb_non_read_only_migration_errors_are_not_hidden(self) -> None:
        class BrokenConnection:
            def execute(self, _sql, _parameters=()):
                raise RuntimeError("Access denied for user")

            def rollback(self):
                pass

        with self.assertRaisesRegex(RuntimeError, "Access denied"):
            MariaDbAdminService.migration_tracking_table(BrokenConnection())

    def test_missing_master_key_recovers_without_deleting_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "smtp.json").write_text(
                '{"password":"fernet:old-secret"}', encoding="utf-8"
            )
            SecretCipher(root / ".master.key")
            self.assertTrue((root / ".master.key").exists())
            self.assertTrue((root / "smtp.json.missing-key.bak").exists())
            self.assertTrue((root / "KEY_RECOVERY_REQUIRED.json").exists())
            recovered = (root / "smtp.json").read_text(encoding="utf-8")
            self.assertNotIn("fernet:old-secret", recovered)

    def test_password_hash_is_salted_and_verifiable(self) -> None:
        hasher = PasswordHasher(iterations=10_000)
        first = hasher.hash("Sicher123")
        second = hasher.hash("Sicher123")
        self.assertNotEqual(first, second)
        self.assertTrue(hasher.verify("Sicher123", first))
        self.assertFalse(hasher.verify("Falsch123", first))
        for weak in ("kurz", "nurklein123", "NURGROSS123", "OhneZahl"):
            with self.assertRaises(ValueError):
                hasher.hash(weak)

    def test_rate_limiter_blocks_after_limit(self) -> None:
        limiter = SlidingWindowRateLimiter()
        limiter.check("login", 2, 60)
        limiter.check("login", 2, 60)
        with self.assertRaises(ApiError):
            limiter.check("login", 2, 60)

    def test_migrations_are_idempotent(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """CREATE TABLE users(
                   id INTEGER PRIMARY KEY,name TEXT,email TEXT,deleted_at TEXT);
               CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
               CREATE TABLE parts(id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,
                   deleted_at TEXT,created_at TEXT,quantity INTEGER,unit_price REAL);
               CREATE TABLE sets(id INTEGER PRIMARY KEY,user_id INTEGER,set_number TEXT,
                   name TEXT,deleted_at TEXT,current_value REAL,purchase_price REAL);
               CREATE TABLE warehouse(id INTEGER PRIMARY KEY,user_id INTEGER,element_id TEXT,
                   design_id TEXT,name TEXT,color TEXT,quantity INTEGER,location_id INTEGER,
                   image_url TEXT);
               CREATE TABLE warehouse_locations(id INTEGER PRIMARY KEY,user_id INTEGER,
                   parent_id INTEGER,name TEXT,location_type TEXT,capacity INTEGER,
                   photo_url TEXT,notes TEXT);
               CREATE TABLE orders(id INTEGER PRIMARY KEY,user_id INTEGER,supplier TEXT,
                   status TEXT,created_at TEXT);"""
        )
        self.assertEqual(MIGRATIONS.migrate(conn), 10)
        self.assertEqual(MIGRATIONS.migrate(conn), 10)
        self.assertIsNotNone(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='inventory_movements'"
        ).fetchone())
        self.assertIsNotNone(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='set_minifigures'"
        ).fetchone())
        self.assertIsNotNone(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='minifigure_parts'"
        ).fetchone())
        minifigure_part_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(minifigure_parts)")
        }
        self.assertIn("owned_quantity", minifigure_part_columns)
    def test_pro7_inventory_rejects_overreservation_and_logs_movement(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """CREATE TABLE inventory_items(
                   id INTEGER PRIMARY KEY,user_id INTEGER,quantity INTEGER,
                   reserved_quantity INTEGER,updated_at TEXT);
               CREATE TABLE inventory_movements(
                   id INTEGER PRIMARY KEY,inventory_item_id INTEGER,movement_type TEXT,
                   old_quantity INTEGER,new_quantity INTEGER,difference INTEGER,
                   old_reserved INTEGER,new_reserved INTEGER,source TEXT,destination TEXT,
                   user_id INTEGER,note TEXT,order_id INTEGER,set_id INTEGER,moc_id INTEGER,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP);
               INSERT INTO inventory_items VALUES(1,1,10,2,CURRENT_TIMESTAMP);"""
        )
        service = Pro7Service()
        with self.assertRaises(ValueError):
            service.adjust_inventory(
                conn, 1, quantity=5, reserved=6, movement_type="Korrektur", user_id=1
            )
        result = service.adjust_inventory(
            conn, 1, quantity=12, reserved=3, movement_type="Zugang", user_id=1
        )
        self.assertEqual(result["available_quantity"], 9)
        self.assertEqual(conn.execute(
            "SELECT difference FROM inventory_movements"
        ).fetchone()["difference"], 2)

    def test_tokens_are_single_use_and_totp_works(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """CREATE TABLE account_tokens(
                   id INTEGER PRIMARY KEY,user_id INTEGER,purpose TEXT,token_hash TEXT UNIQUE,
                   expires_at TEXT,used_at TEXT,created_at TEXT);"""
        )
        service = AccountSecurityService(None)
        token = service.issue_token(conn, 7, "reset", 10)
        self.assertEqual(service.consume_token(conn, token, "reset"), 7)
        with self.assertRaises(ValueError):
            service.consume_token(conn, token, "reset")
        secret = service.new_totp_secret()
        self.assertFalse(service.verify_totp(secret, "000"))

    def test_email_public_config_never_exposes_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cipher = SecretCipher(root / "key")
            service = EmailService(root / "email.json", cipher)
            service.save(
                {
                    "mode": "resend",
                    "sender": "mail@example.com",
                    "api_key": "re_secret",
                    "enabled": True,
                }
            )
            public = service.public_config()
            self.assertTrue(public["api_key_configured"])
            self.assertNotIn("api_key", public)
            self.assertNotIn("password", public)

if __name__ == "__main__":
    unittest.main()
