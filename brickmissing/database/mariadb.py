from __future__ import annotations

import json
import sqlite3
import sys
import threading
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PyMySqlCursor:
    """Expose the MariaDB Connector cursor interface on top of PyMySQL."""

    def __init__(self, cursor: Any):
        self._cursor = cursor

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        return self._cursor.execute(self._sql(sql), tuple(parameters))

    def executemany(self, sql: str, parameters: Any) -> Any:
        return self._cursor.executemany(self._sql(sql), parameters)

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> Any:
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class PyMySqlConnection:
    """Adapt PyMySQL to the cursor(dictionary=True) API used by the app."""

    def __init__(self, connection: Any, module: Any):
        self._connection = connection
        self._module = module

    def cursor(self, dictionary: bool = False) -> PyMySqlCursor:
        cursor_class = self._module.cursors.DictCursor if dictionary else None
        cursor = (
            self._connection.cursor(cursor_class)
            if cursor_class is not None
            else self._connection.cursor()
        )
        return PyMySqlCursor(cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class PyMySqlDriver:
    """Driver facade used when the native MariaDB extension is unavailable."""

    def __init__(self, module: Any):
        self._module = module

    def connect(self, **options: Any) -> PyMySqlConnection:
        ssl_enabled = bool(options.pop("ssl", True))
        options.pop("autocommit", None)
        options["autocommit"] = False
        options["charset"] = "utf8mb4"
        options["cursorclass"] = self._module.cursors.Cursor
        if ssl_enabled:
            options["ssl"] = {}
        connection = self._module.connect(**options)
        return PyMySqlConnection(connection, self._module)


class HybridRow(dict):
    """Mapping row that also supports sqlite3.Row-style numeric indexing."""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class MariaCursor:
    """SQLite-like cursor facade used by the existing application services."""

    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def lastrowid(self) -> int:
        return int(self._cursor.lastrowid or 0)

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount or 0)

    def fetchone(self) -> Any:
        row = self._cursor.fetchone()
        return HybridRow(row) if isinstance(row, dict) else row

    def fetchall(self) -> list[Any]:
        return [
            HybridRow(row) if isinstance(row, dict) else row
            for row in self._cursor.fetchall()
        ]

    def __iter__(self):
        for row in self._cursor:
            yield HybridRow(row) if isinstance(row, dict) else row


class MariaConnection:
    """Small DB-API compatibility layer translating the remaining SQLite SQL."""

    is_mariadb = True

    def __init__(self, connection: Any):
        self._connection = connection
        self._total_changes = 0

    @staticmethod
    def _sql(sql: str) -> str:
        value = sql.replace(" COLLATE NOCASE", "")
        value = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT IGNORE", value, flags=re.I)
        value = value.replace("datetime('now','-14 days')", "DATE_SUB(NOW(), INTERVAL 14 DAY)")
        value = value.replace("datetime('now','-30 days')", "DATE_SUB(NOW(), INTERVAL 30 DAY)")
        value = value.replace("date('now')", "CURRENT_DATE")
        value = re.sub(r"\bdate\(([^)]+)\)", r"DATE(\1)", value, flags=re.I)
        value = value.replace("MAX(required_quantity-owned_quantity,0)", "GREATEST(required_quantity-owned_quantity,0)")
        value = value.replace("MIN(owned_quantity,required_quantity)", "LEAST(owned_quantity,required_quantity)")
        if " ON CONFLICT(" in value.upper():
            match = re.search(
                r"\s+ON\s+CONFLICT\s*\([^)]*\)\s+DO\s+UPDATE\s+SET\s+(.+)$",
                value, flags=re.I | re.S,
            )
            if match:
                assignments = re.sub(
                    r"excluded\.([A-Za-z_][A-Za-z0-9_]*)",
                    r"VALUES(\1)",
                    match.group(1),
                    flags=re.I,
                )
                value = value[:match.start()] + " ON DUPLICATE KEY UPDATE " + assignments
        return value

    def execute(self, sql: str, parameters: Any = ()) -> MariaCursor:
        cursor = self._connection.cursor(dictionary=True)
        cursor.execute(self._sql(sql), tuple(parameters))
        self._total_changes += max(int(cursor.rowcount or 0), 0)
        return MariaCursor(cursor)

    def executemany(self, sql: str, parameters: Any) -> MariaCursor:
        cursor = self._connection.cursor()
        cursor.executemany(self._sql(sql), parameters)
        self._total_changes += max(int(cursor.rowcount or 0), 0)
        return MariaCursor(cursor)

    @property
    def total_changes(self) -> int:
        return self._total_changes

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MariaConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


class MariaDbAdminService:
    """Stores and validates the central MariaDB target without exposing secrets."""

    def __init__(self, profile_file: Path, cipher: Any):
        self.profile_file = profile_file
        self.cipher = cipher
        self._sync_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()

    def save(self, profile: dict[str, Any]) -> None:
        port = int(profile.get("port", 3306))
        database = str(profile.get("database", "")).strip()
        user = str(profile.get("user", "")).strip()
        host = str(profile.get("host", "")).strip()
        if not host or not database or not user:
            raise ValueError("Host, Datenbank und Benutzer sind erforderlich.")
        current = self._raw()
        password = str(profile.get("password", ""))
        encrypted = self.cipher.encrypt(password) if password else current.get("password", "")
        data = {
            "engine": str(profile.get("engine", "sqlite")),
            "host": host, "port": port, "database": database, "user": user,
            "password": encrypted,
            "ssl": bool(profile.get("ssl", True)),
            "active": False,
        }
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def public_profile(self) -> dict[str, Any]:
        raw = self._raw()
        return {
            "configured": bool(raw),
            "engine": raw.get("engine", "sqlite"),
            "host": raw.get("host", ""),
            "port": raw.get("port", 3306),
            "database": raw.get("database", ""),
            "user": raw.get("user", ""),
            "ssl": bool(raw.get("ssl", True)),
            "password_configured": bool(raw.get("password")),
            "active": bool(raw.get("active", False)),
            "last_sync": raw.get("last_sync", ""),
            "last_sync_error": raw.get("last_sync_error", ""),
        }

    def save_sqlite_choice(self) -> None:
        raw = self._raw()
        raw["engine"] = "sqlite"
        raw["active"] = False
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def activate(self) -> None:
        raw = self._raw()
        raw["engine"] = "mariadb"
        raw["active"] = True
        self.profile_file.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def connect_primary(self) -> MariaConnection:
        profile = self.connection_profile()
        connection = self._driver().connect(
            host=profile["host"], port=int(profile["port"]), user=profile["user"],
            password=profile["password"], database=profile["database"],
            ssl=profile.get("ssl", True), connect_timeout=10, autocommit=False,
        )
        return MariaConnection(connection)

    @staticmethod
    def is_read_only_table_error(exc: Exception) -> bool:
        """Recognize MariaDB's table-level read-only failures across drivers."""
        message = str(exc).casefold()
        return (
            "read only" in message
            or "read-only" in message
            or "table is readonly" in message
        )

    @classmethod
    def migration_tracking_table(cls, conn: MariaConnection) -> str:
        """Return a writable migration ledger without destroying legacy data.

        Some MariaDB installations retain a damaged Aria/MyISAM version of the
        original schema_migrations table. Replacing or dropping that table at
        application startup would be unsafe. A dedicated InnoDB ledger keeps
        startup idempotent while leaving the legacy table available for repair.
        """
        try:
            conn.execute(
                """INSERT IGNORE INTO schema_migrations(version,name)
                   VALUES(-1,'brickmissing_write_probe')"""
            )
            conn.execute("DELETE FROM schema_migrations WHERE version=-1")
            return "schema_migrations"
        except Exception as exc:
            conn.rollback()
            if not cls.is_read_only_table_error(exc):
                raise
        conn.execute(
            """CREATE TABLE IF NOT EXISTS brickmissing_schema_migrations(
                   version BIGINT PRIMARY KEY,
                   name VARCHAR(191) NOT NULL,
                   applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )
        conn.execute(
            """INSERT INTO system_health(`key`,status,details,checked_at)
               VALUES('migration_tracking','warning',
                      'Legacy-Tabelle schema_migrations ist schreibgeschützt; '
                      'sicheres InnoDB-Ersatzprotokoll ist aktiv.',CURRENT_TIMESTAMP)
               ON DUPLICATE KEY UPDATE status=VALUES(status),
                 details=VALUES(details),checked_at=CURRENT_TIMESTAMP"""
        )
        return "brickmissing_schema_migrations"

    @staticmethod
    def runtime_schema_statements() -> tuple[str, ...]:
        """Idempotent MariaDB schema for tables introduced after initial sync."""
        return (
            """CREATE TABLE IF NOT EXISTS settings(
                   `key` VARCHAR(191) PRIMARY KEY,
                   value LONGTEXT NOT NULL
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS schema_migrations(
                   version BIGINT PRIMARY KEY,name VARCHAR(191) NOT NULL,
                   applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS account_tokens(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   purpose VARCHAR(64) NOT NULL,token_hash VARCHAR(191) NOT NULL UNIQUE,
                   expires_at VARCHAR(64) NOT NULL,used_at VARCHAR(64) NULL,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_account_tokens_user(user_id),
                   KEY ix_account_tokens_lookup(token_hash,purpose,expires_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS trusted_devices(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   token_hash VARCHAR(191) NOT NULL UNIQUE,label VARCHAR(191) NOT NULL DEFAULT '',
                   expires_at VARCHAR(64) NOT NULL,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_trusted_devices_user(user_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS background_jobs(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,kind VARCHAR(100) NOT NULL,
                   payload LONGTEXT NOT NULL,status VARCHAR(40) NOT NULL DEFAULT 'queued',
                   attempts BIGINT NOT NULL DEFAULT 0,max_attempts BIGINT NOT NULL DEFAULT 5,
                   run_after TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,last_error LONGTEXT,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_background_jobs_queue(status,run_after)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS email_deliveries(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NULL,
                   recipient VARCHAR(254) NOT NULL,template VARCHAR(100) NOT NULL,
                   provider VARCHAR(100) NOT NULL DEFAULT '',status VARCHAR(40) NOT NULL DEFAULT 'queued',
                   attempts BIGINT NOT NULL DEFAULT 0,last_error LONGTEXT,
                   provider_id VARCHAR(191) NOT NULL DEFAULT '',
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,sent_at VARCHAR(64) NULL,
                   KEY ix_email_deliveries_user(user_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS notifications(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   kind VARCHAR(100) NOT NULL,title VARCHAR(191) NOT NULL,message LONGTEXT NOT NULL,
                   entity_type VARCHAR(100) NOT NULL DEFAULT '',entity_id BIGINT NULL,
                   read_at VARCHAR(64) NULL,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE KEY uq_notifications_entity(user_id,kind,entity_type,entity_id),
                   KEY ix_notifications_user(user_id,created_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS entity_changes(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NULL,actor_id BIGINT NULL,
                   entity_type VARCHAR(100) NOT NULL,entity_id BIGINT NOT NULL,
                   action VARCHAR(100) NOT NULL,before_json LONGTEXT,after_json LONGTEXT,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_entity_changes_lookup(entity_type,entity_id,created_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS value_snapshots(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   collection_value DOUBLE NOT NULL DEFAULT 0,missing_cost DOUBLE NOT NULL DEFAULT 0,
                   warehouse_quantity BIGINT NOT NULL DEFAULT 0,
                   captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_value_snapshots_user(user_id,captured_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS import_batches(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   payload LONGTEXT NOT NULL,summary LONGTEXT NOT NULL,
                   status VARCHAR(40) NOT NULL DEFAULT 'preview',
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   applied_at VARCHAR(64) NULL,undone_at VARCHAR(64) NULL,
                   KEY ix_import_batches_user(user_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS saved_views(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   area VARCHAR(100) NOT NULL,name VARCHAR(191) NOT NULL,
                   configuration LONGTEXT NOT NULL,is_default BIGINT NOT NULL DEFAULT 0,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE KEY uq_saved_views(user_id,area,name)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS system_health(
                   `key` VARCHAR(191) PRIMARY KEY,status VARCHAR(40) NOT NULL,
                   details LONGTEXT,checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS personal_notes(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   title VARCHAR(191) NOT NULL,content LONGTEXT NOT NULL,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_personal_notes_user(user_id,updated_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS workshop_documents(
                   user_id BIGINT PRIMARY KEY,payload LONGTEXT NOT NULL,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS warehouse_locations(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   parent_id BIGINT NULL,name VARCHAR(191) NOT NULL,
                   location_type VARCHAR(64) NOT NULL DEFAULT 'Box',
                   capacity BIGINT NOT NULL DEFAULT 0,photo_url LONGTEXT,notes LONGTEXT,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE KEY uq_warehouse_location(user_id,parent_id,name),
                   KEY ix_warehouse_location_user(user_id),
                   KEY ix_warehouse_location_parent(parent_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            "ALTER TABLE warehouse ADD COLUMN IF NOT EXISTS location_id BIGINT NULL",
            "ALTER TABLE warehouse ADD COLUMN IF NOT EXISTS slot_usage BIGINT NOT NULL DEFAULT 1",
            "ALTER TABLE sets ADD COLUMN IF NOT EXISTS collection_id BIGINT NULL",
            "ALTER TABLE sets ADD COLUMN IF NOT EXISTS `condition` VARCHAR(64) NOT NULL DEFAULT 'gebraucht'",
            "ALTER TABLE sets ADD COLUMN IF NOT EXISTS completeness VARCHAR(64) NOT NULL DEFAULT 'unbekannt'",
            "ALTER TABLE sets ADD COLUMN IF NOT EXISTS build_status VARCHAR(64) NOT NULL DEFAULT 'zerlegt vollständig'",
            "ALTER TABLE sets ADD COLUMN IF NOT EXISTS notes LONGTEXT",
            "ALTER TABLE parts ADD COLUMN IF NOT EXISTS is_present BIGINT NOT NULL DEFAULT 0",
            "ALTER TABLE parts ADD COLUMN IF NOT EXISTS owned_quantity BIGINT NOT NULL DEFAULT 0",
            "ALTER TABLE parts ADD COLUMN IF NOT EXISTS unassigned_found_quantity BIGINT NOT NULL DEFAULT 0",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS deleted_at VARCHAR(64) NULL",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS goods_total DOUBLE NOT NULL DEFAULT 0",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_date VARCHAR(64) NULL",
            "ALTER TABLE warehouse_locations ADD COLUMN IF NOT EXISTS short_code VARCHAR(100) NOT NULL DEFAULT ''",
            "ALTER TABLE warehouse_locations ADD COLUMN IF NOT EXISTS archived_at VARCHAR(64) NULL",
            """CREATE TABLE IF NOT EXISTS collections(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,name VARCHAR(191) NOT NULL,
                   description LONGTEXT,owner_id BIGINT NOT NULL,is_shared BIGINT NOT NULL DEFAULT 0,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_collections_owner(owner_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS collection_members(
                   collection_id BIGINT NOT NULL,user_id BIGINT NOT NULL,
                   role VARCHAR(40) NOT NULL DEFAULT 'viewer',
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   PRIMARY KEY(collection_id,user_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS set_copies(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,set_id BIGINT NOT NULL,
                   collection_id BIGINT NULL,inventory_number VARCHAR(191) NOT NULL DEFAULT '',
                   serial_number VARCHAR(191) NOT NULL DEFAULT '',
                   `condition` VARCHAR(64) NOT NULL DEFAULT 'gebraucht',
                   completeness VARCHAR(64) NOT NULL DEFAULT 'unbekannt',
                   build_status VARCHAR(100) NOT NULL DEFAULT 'zerlegt vollständig',
                   location_id BIGINT NULL,purchase_date VARCHAR(64) NULL,
                   purchase_price DOUBLE NOT NULL DEFAULT 0,notes LONGTEXT,image_url LONGTEXT,
                   deleted_at VARCHAR(64) NULL,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_set_copies_set(set_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS mocs(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   collection_id BIGINT NULL,name VARCHAR(191) NOT NULL,project_code VARCHAR(191) NOT NULL DEFAULT '',
                   description LONGTEXT,status VARCHAR(64) NOT NULL DEFAULT 'Planung',
                   version VARCHAR(64) NOT NULL DEFAULT '1.0',progress BIGINT NOT NULL DEFAULT 0,
                   location_id BIGINT NULL,instruction_url LONGTEXT,image_url LONGTEXT,notes LONGTEXT,
                   deleted_at VARCHAR(64) NULL,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_mocs_user(user_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS moc_parts(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,moc_id BIGINT NOT NULL,
                   inventory_item_id BIGINT NULL,part_number VARCHAR(191) NOT NULL,
                   name VARCHAR(191) NOT NULL DEFAULT '',color VARCHAR(100) NOT NULL DEFAULT '',
                   required_quantity BIGINT NOT NULL DEFAULT 1,allocated_quantity BIGINT NOT NULL DEFAULT 0,
                   notes LONGTEXT,KEY ix_moc_parts_moc(moc_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS inventory_items(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,collection_id BIGINT NULL,
                   part_number VARCHAR(191) NOT NULL,design_id VARCHAR(191) NOT NULL DEFAULT '',
                   element_id VARCHAR(191) NOT NULL DEFAULT '',name VARCHAR(191) NOT NULL,
                   color VARCHAR(100) NOT NULL DEFAULT '',category VARCHAR(100) NOT NULL DEFAULT '',
                   subcategory VARCHAR(100) NOT NULL DEFAULT '',quantity BIGINT NOT NULL DEFAULT 0,
                   reserved_quantity BIGINT NOT NULL DEFAULT 0,`condition` VARCHAR(100) NOT NULL DEFAULT 'gebraucht',
                   location_id BIGINT NULL,image_url LONGTEXT,source VARCHAR(191) NOT NULL DEFAULT '',
                   purchase_price DOUBLE NOT NULL DEFAULT 0,unit_price DOUBLE NOT NULL DEFAULT 0,
                   notes LONGTEXT,archived_at VARCHAR(64) NULL,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_inventory_user(user_id),KEY ix_inventory_search(part_number,color)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS inventory_movements(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,inventory_item_id BIGINT NOT NULL,
                   movement_type VARCHAR(64) NOT NULL,old_quantity BIGINT NOT NULL,new_quantity BIGINT NOT NULL,
                   difference BIGINT NOT NULL,old_reserved BIGINT NOT NULL DEFAULT 0,
                   new_reserved BIGINT NOT NULL DEFAULT 0,source VARCHAR(191) NOT NULL DEFAULT '',
                   destination VARCHAR(191) NOT NULL DEFAULT '',user_id BIGINT NULL,note LONGTEXT,
                   order_id BIGINT NULL,set_id BIGINT NULL,moc_id BIGINT NULL,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_inventory_movements(inventory_item_id,created_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS order_items(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,order_id BIGINT NOT NULL,
                   inventory_item_id BIGINT NULL,part_number VARCHAR(191) NOT NULL,
                   name VARCHAR(191) NOT NULL DEFAULT '',color VARCHAR(100) NOT NULL DEFAULT '',
                   quantity BIGINT NOT NULL DEFAULT 1,received_quantity BIGINT NOT NULL DEFAULT 0,
                   damaged_quantity BIGINT NOT NULL DEFAULT 0,wrong_quantity BIGINT NOT NULL DEFAULT 0,
                   unit_price DOUBLE NOT NULL DEFAULT 0,target_set_id BIGINT NULL,target_location_id BIGINT NULL,
                   notes LONGTEXT,KEY ix_order_items_order(order_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS price_history(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,entity_type VARCHAR(64) NOT NULL,
                   entity_id BIGINT NOT NULL,price DOUBLE NOT NULL,shipping DOUBLE NOT NULL DEFAULT 0,
                   currency VARCHAR(8) NOT NULL DEFAULT 'EUR',source VARCHAR(100) NOT NULL DEFAULT '',
                   supplier VARCHAR(191) NOT NULL DEFAULT '',is_estimate BIGINT NOT NULL DEFAULT 1,
                   note LONGTEXT,recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_price_history_entity(entity_type,entity_id,recorded_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS data_quality_issues(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NULL,
                   issue_key VARCHAR(100) NOT NULL,entity_type VARCHAR(100) NOT NULL,
                   entity_id BIGINT NULL,severity VARCHAR(40) NOT NULL DEFAULT 'warning',
                   message LONGTEXT NOT NULL,status VARCHAR(40) NOT NULL DEFAULT 'open',
                   detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,resolved_at VARCHAR(64) NULL,
                   UNIQUE KEY uq_quality(user_id,issue_key,entity_type,entity_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS search_history(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   query VARCHAR(255) NOT NULL,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   KEY ix_search_history_user(user_id,created_at)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS set_minifigures(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,
                   set_id BIGINT NOT NULL,fig_number VARCHAR(100) NOT NULL,
                   name VARCHAR(191) NOT NULL,quantity BIGINT NOT NULL DEFAULT 1,
                   owned_quantity BIGINT NOT NULL DEFAULT 0,image_url LONGTEXT,
                   notes LONGTEXT,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE KEY uq_set_minifigure(user_id,set_id,fig_number),
                   KEY ix_set_minifigures_set(set_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS minifigure_parts(
                   id BIGINT PRIMARY KEY AUTO_INCREMENT,minifigure_id BIGINT NOT NULL,
                   part_num VARCHAR(191) NOT NULL,element_id VARCHAR(191) NOT NULL DEFAULT '',
                   name VARCHAR(191) NOT NULL,color_id BIGINT NULL,
                   color_name VARCHAR(100) NOT NULL DEFAULT '',
                   quantity BIGINT NOT NULL DEFAULT 1,is_spare BIGINT NOT NULL DEFAULT 0,
                   owned_quantity BIGINT NOT NULL DEFAULT 0,image_url LONGTEXT,
                   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE KEY uq_minifigure_part(minifigure_id,part_num,color_id,is_spare),
                   KEY ix_minifigure_parts_figure(minifigure_id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            "ALTER TABLE minifigure_parts ADD COLUMN IF NOT EXISTS owned_quantity BIGINT NOT NULL DEFAULT 0",
        )

    def ensure_runtime_schema(self) -> None:
        """Bring an already active MariaDB database up to the current schema."""
        conn = self.connect_primary()
        try:
            for statement in self.runtime_schema_statements():
                conn.execute(statement)
            conn.execute(
                "UPDATE parts SET owned_quantity=quantity WHERE is_present=1 AND owned_quantity=0"
            )
            migration_table = self.migration_tracking_table(conn)
            for version, name in (
                (1, "security_and_account_tokens"),
                (2, "jobs_notifications_history"),
                (3, "saved_views_and_maintenance"),
                (4, "pro7_collections_catalog_and_copies"),
                (5, "pro7_inventory_movements_and_orders"),
                (6, "pro7_documents_preferences_and_quality"),
                (7, "minifigure_inventory"),
                (8, "minifigure_parts"),
                (9, "minifigure_part_inventory"),
                (10, "user_content_and_query_indexes"),
            ):
                conn.execute(
                    f"INSERT IGNORE INTO `{migration_table}`(version,name) VALUES(?,?)",
                    (version, name),
                )
            conn.execute(
                "INSERT IGNORE INTO settings(`key`,value) VALUES('maintenance_mode','false')"
            )
            conn.execute(
                "INSERT IGNORE INTO settings(`key`,value) VALUES('audit_retention_days','365')"
            )
            conn.execute(
                """INSERT INTO collections(name,description,owner_id,is_shared)
                   SELECT 'Meine Sammlung','Automatisch aus BrickMissing 6.x übernommen',u.id,0
                   FROM users u
                   WHERE NOT EXISTS(SELECT 1 FROM collections c WHERE c.owner_id=u.id)"""
            )
            conn.execute(
                """INSERT IGNORE INTO collection_members(collection_id,user_id,role)
                   SELECT id,owner_id,'manager' FROM collections"""
            )
            conn.execute(
                """UPDATE sets s JOIN collections c ON c.owner_id=s.user_id
                   SET s.collection_id=c.id WHERE s.collection_id IS NULL"""
            )
            conn.execute(
                """INSERT INTO set_copies(
                       set_id,collection_id,inventory_number,`condition`,
                       completeness,build_status,purchase_price,notes
                   )
                   SELECT s.id,s.collection_id,CONCAT('SET-',s.id),
                          COALESCE(s.`condition`,'gebraucht'),
                          COALESCE(s.completeness,'unbekannt'),
                          COALESCE(s.build_status,'zerlegt vollständig'),
                          COALESCE(s.purchase_price,0),COALESCE(s.notes,'')
                   FROM sets s
                   WHERE s.deleted_at IS NULL
                     AND NOT EXISTS(SELECT 1 FROM set_copies c WHERE c.set_id=s.id)"""
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def missing_core_tables(self) -> list[str]:
        """Return essential tables missing from an active MariaDB database."""
        required = {
            "users", "settings", "user_settings", "sessions", "audit_log",
            "sets", "parts", "history", "warehouse", "orders",
            "set_inventory", "warehouse_locations",
        }
        conn = self.connect_primary()
        try:
            existing = {
                str(row[0])
                for row in conn.execute("SHOW TABLES").fetchall()
            }
            return sorted(required - existing)
        finally:
            conn.close()

    def test(self, override: dict[str, Any] | None = None) -> dict[str, Any]:
        profile = self.connection_profile(override)
        mariadb = self._driver()
        conn = mariadb.connect(
            host=profile["host"], port=int(profile["port"]), user=profile["user"],
            password=profile["password"], database=profile["database"],
            ssl=profile.get("ssl", True), connect_timeout=8,
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT VERSION(), DATABASE(), CURRENT_USER()")
            version, database, user = cur.fetchone()
            cur.execute(
                """SELECT COUNT(*),COALESCE(SUM(data_length+index_length),0)
                   FROM information_schema.tables WHERE table_schema=?""",
                (profile["database"],),
            )
            table_count, bytes_used = cur.fetchone()
            writable = True
            write_error = ""
            probe = "brickmissing_write_probe"
            try:
                cur.execute(f"DROP TABLE IF EXISTS `{probe}`")
                cur.execute(
                    f"""CREATE TABLE `{probe}`(
                            id BIGINT PRIMARY KEY,value VARCHAR(32) NOT NULL
                        ) ENGINE=InnoDB"""
                )
                cur.execute(
                    f"INSERT INTO `{probe}`(id,value) VALUES(1,'ok')"
                )
                cur.execute(f"DROP TABLE `{probe}`")
                conn.commit()
            except Exception as exc:
                writable = False
                write_error = str(exc)
                conn.rollback()
                try:
                    cur.execute(f"DROP TABLE IF EXISTS `{probe}`")
                    conn.commit()
                except Exception:
                    conn.rollback()
            return {
                "ok": True, "version": version, "database": database, "user": user,
                "table_count": int(table_count), "bytes": int(bytes_used),
                "writable": writable,
                "write_error": write_error[:300],
                "message": (
                    "MariaDB ist vollständig beschreibbar."
                    if writable else
                    "Die Verbindung funktioniert, aber die MariaDB ist "
                    "schreibgeschützt. SQLite bleibt aus Sicherheitsgründen aktiv."
                ),
            }
        finally:
            conn.close()

    def tables(self) -> list[dict[str, Any]]:
        profile = self.connection_profile()
        conn = self._driver().connect(
            host=profile["host"], port=int(profile["port"]), user=profile["user"],
            password=profile["password"], database=profile["database"],
            ssl=profile.get("ssl", True), connect_timeout=8,
        )
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                """SELECT table_name,table_rows,data_length,index_length,engine
                   FROM information_schema.tables WHERE table_schema=?
                   ORDER BY table_name""",
                (profile["database"],),
            )
            return list(cur.fetchall())
        finally:
            conn.close()

    def sync_from_sqlite(self, sqlite_path: Path) -> dict[str, Any]:
        """Create the MariaDB schema and atomically refresh all application tables."""
        status = self.test()
        if not status.get("writable"):
            self._set_sync_status(status.get("message", "MariaDB ist schreibgeschützt."), 0)
            self.save_sqlite_choice()
            raise ValueError(
                "MariaDB ist momentan nur lesbar. Die Synchronisierung wurde "
                "vor der ersten Änderung sicher abgebrochen; SQLite bleibt aktiv. "
                "Bitte Schreibrechte des MariaDB-Datenordners reparieren."
            )
        if not self._sync_lock.acquire(blocking=False):
            return {"ok": True, "skipped": True, "message": "Synchronisierung läuft bereits."}
        try:
            profile = self.connection_profile()
            source = sqlite3.connect(sqlite_path)
            source.row_factory = sqlite3.Row
            target = self._driver().connect(
                host=profile["host"], port=int(profile["port"]), user=profile["user"],
                password=profile["password"], database=profile["database"],
                ssl=profile.get("ssl", True), connect_timeout=10,
                autocommit=False,
            )
            try:
                tables = [
                    row["name"] for row in source.execute(
                        """SELECT name FROM sqlite_master
                           WHERE type='table' AND name NOT LIKE 'sqlite_%'
                           ORDER BY name"""
                    )
                ]
                cursor = target.cursor()
                cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                cursor.execute("SHOW TABLES")
                existing_tables = {
                    str(row[0]) for row in cursor.fetchall()
                }
                copied_rows = 0
                unique_keys = {
                    "users": [("name",), ("email",)],
                    "settings": [("key",)],
                    "user_settings": [("user_id", "key")],
                    "sessions": [("token_hash",)],
                    "sets": [("user_id", "set_number")],
                    "warehouse": [("user_id", "element_id", "color")],
                    "warehouse_locations": [("user_id", "parent_id", "name")],
                    "set_inventory": [("set_id", "part_num", "color_id", "is_spare")],
                    "account_tokens": [("token_hash",)],
                    "trusted_devices": [("token_hash",)],
                    "notifications": [("user_id", "kind", "entity_type", "entity_id")],
                    "saved_views": [("user_id", "area", "name")],
                    "system_health": [("key",)],
                    "schema_migrations": [("version",)],
                }
                ordinary_keys = {
                    "sessions": [("user_id", "expires_at")],
                    "sets": [("user_id", "deleted_at", "updated_at")],
                    "parts": [
                        ("user_id", "deleted_at", "updated_at"),
                        ("user_id", "status"),
                        ("set_id",),
                    ],
                    "history": [("part_id", "created_at")],
                    "warehouse": [("user_id",)],
                    "warehouse_locations": [("user_id",), ("parent_id",)],
                    "orders": [("user_id", "updated_at")],
                    "set_inventory": [("set_id",)],
                    "audit_log": [("created_at",)],
                }
                for table in tables:
                    # The SQLite sessions must be transferred as well. During the
                    # first activation the request that triggered the switch still
                    # uses an SQLite session; keeping an empty/pre-existing MariaDB
                    # sessions table would log that administrator out immediately.
                    columns = list(source.execute(f"PRAGMA table_info(`{table}`)"))
                    definitions = []
                    indexed_names = {
                        name
                        for key in (
                            unique_keys.get(table, []) + ordinary_keys.get(table, [])
                        )
                        for name in key
                    }
                    primary = sorted(
                        ((int(col["pk"]), col["name"]) for col in columns if col["pk"]),
                        key=lambda item: item[0],
                    )
                    for col in columns:
                        name = col["name"]
                        declared = str(col["type"] or "TEXT").upper()
                        if "INT" in declared:
                            sql_type = "BIGINT"
                        elif any(kind in declared for kind in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL")):
                            sql_type = "DOUBLE"
                        elif col["pk"] or name in indexed_names:
                            sql_type = "VARCHAR(191)"
                        else:
                            sql_type = "LONGTEXT"
                        auto = (
                            " AUTO_INCREMENT"
                            if len(primary) == 1 and primary[0][1] == name and "INT" in declared
                            else ""
                        )
                        nullable = " NOT NULL" if col["notnull"] or col["pk"] else ""
                        definitions.append(f"`{name}` {sql_type}{nullable}{auto}")
                    if primary:
                        definitions.append(
                            "PRIMARY KEY (" + ",".join(f"`{name}`" for _, name in primary) + ")"
                        )
                    for index, names in enumerate(unique_keys.get(table, []), 1):
                        if tuple(name for _, name in primary) == names:
                            continue
                        definitions.append(
                            f"UNIQUE KEY `uq_{table}_{index}` ("
                            + ",".join(f"`{name}`" for name in names) + ")"
                        )
                    for index, names in enumerate(ordinary_keys.get(table, []), 1):
                        definitions.append(
                            f"KEY `ix_{table}_{index}` ("
                            + ",".join(f"`{name}`" for name in names) + ")"
                        )
                    # Activation is an explicit one-time SQLite -> MariaDB
                    # migration. Recreate target tables so stale replica-era
                    # schemas cannot survive as the new primary schema.
                    cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
                    cursor.execute(
                        f"CREATE TABLE IF NOT EXISTS `{table}` ({','.join(definitions)}) "
                        "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                    )
                    cursor.execute(f"DELETE FROM `{table}`")
                    rows = list(source.execute(f"SELECT * FROM `{table}`"))
                    if rows:
                        names = [col["name"] for col in columns]
                        placeholders = ",".join("?" for _ in names)
                        cursor.executemany(
                            f"INSERT INTO `{table}` ({','.join(f'`{name}`' for name in names)}) "
                            f"VALUES ({placeholders})",
                            [tuple(row[name] for name in names) for row in rows],
                        )
                        copied_rows += len(rows)
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")
                target.commit()
                self.activate()
                self._set_sync_status("", copied_rows)
                return {"ok": True, "tables": len(tables), "rows": copied_rows}
            except Exception:
                target.rollback()
                raise
            finally:
                target.close()
                source.close()
        except Exception as exc:
            self._set_sync_status(str(exc), 0)
            # Never leave a partially rebuilt MariaDB marked as primary.
            # The local SQLite source remains complete and startable.
            self.save_sqlite_choice()
            raise
        finally:
            self._sync_lock.release()

    def snapshot_to_sqlite(self, sqlite_path: Path) -> dict[str, int]:
        """Refresh the local fallback/backup database from the MariaDB primary."""
        with self._snapshot_lock:
            return self._snapshot_to_sqlite_locked(sqlite_path)

    def _snapshot_to_sqlite_locked(self, sqlite_path: Path) -> dict[str, int]:
        """Internal snapshot implementation; caller owns the snapshot lock."""
        source = self.connect_primary()
        target = sqlite3.connect(sqlite_path)
        target.row_factory = sqlite3.Row
        try:
            target.execute("PRAGMA foreign_keys=OFF")
            local_tables = [
                row[0] for row in target.execute(
                    """SELECT name FROM sqlite_master
                       WHERE type='table' AND name NOT LIKE 'sqlite_%'
                       ORDER BY name"""
                )
            ]
            remote_tables = {
                str(row[0])
                for row in source.execute("SHOW TABLES").fetchall()
            }
            tables = [table for table in local_tables if table in remote_tables]
            missing = sorted(set(local_tables) - remote_tables)
            copied = 0
            with target:
                for table in tables:
                    columns = [
                        row["name"] for row in target.execute(
                            f"PRAGMA table_info(`{table}`)"
                        )
                    ]
                    if not columns:
                        continue
                    target.execute(f"DELETE FROM `{table}`")
                    source_rows = source.execute(
                        f"SELECT {','.join(f'`{name}`' for name in columns)} "
                        f"FROM `{table}`"
                    ).fetchall()
                    if source_rows:
                        target.executemany(
                            f"INSERT INTO `{table}` "
                            f"({','.join(f'`{name}`' for name in columns)}) "
                            f"VALUES ({','.join('?' for _ in columns)})",
                            [tuple(row[name] for name in columns) for row in source_rows],
                        )
                        copied += len(source_rows)
            target.execute("PRAGMA foreign_keys=ON")
            return {
                "tables": len(tables),
                "rows": copied,
                "missing_tables": len(missing),
            }
        finally:
            source.close()
            target.close()

    def _set_sync_status(self, error: str, rows: int) -> None:
        raw = self._raw()
        raw["last_sync"] = datetime.now(timezone.utc).isoformat()
        raw["last_sync_error"] = error[:500]
        raw["last_sync_rows"] = rows
        self.profile_file.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def connection_profile(self, override: dict[str, Any] | None = None) -> dict[str, Any]:
        changes = dict(override or {})
        if changes.get("password", None) == "":
            changes.pop("password")
        raw = {**self._raw(), **changes}
        password = str(raw.get("password", ""))
        if password.startswith("fernet:"):
            password = self.cipher.decrypt(password)
        raw["password"] = password
        if not raw.get("host") or not raw.get("database") or not raw.get("user"):
            raise ValueError("MariaDB ist noch nicht vollständig konfiguriert.")
        return raw

    def _raw(self) -> dict[str, Any]:
        if not self.profile_file.exists():
            return {}
        return json.loads(self.profile_file.read_text(encoding="utf-8"))

    def _driver(self):
        try:
            vendor = self.profile_file.parent.parent / ".vendor"
            # The bundled native extension is compiled for CPython 3.12.
            # Python 3.14 must use the connector installed via requirements.txt.
            if (
                sys.version_info[:2] == (3, 12)
                and vendor.exists()
                and str(vendor) not in sys.path
            ):
                sys.path.insert(0, str(vendor))
            import mariadb
            if not callable(getattr(mariadb, "connect", None)):
                raise ImportError(
                    "Der installierte MariaDB-Treiber passt nicht zur Python-Version."
                )
            return mariadb
        except (ImportError, OSError):
            try:
                import pymysql
                return PyMySqlDriver(pymysql)
            except ImportError as exc:
                raise RuntimeError(
                    "MariaDB-Treiber fehlt. Bitte INSTALL_REQUIREMENTS.bat ausführen."
                ) from exc
