from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


class MigrationManager:
    """Applies ordered, transactional and auditable schema migrations."""

    def __init__(self, migrations: list[Migration]):
        self.migrations = sorted(migrations, key=lambda item: item.version)

    def migrate(self, conn: sqlite3.Connection) -> int:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations(
                   version INTEGER PRIMARY KEY,
                   name TEXT NOT NULL,
                   applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        applied = {
            int(row[0])
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
        for migration in self.migrations:
            if migration.version in applied:
                continue
            with conn:
                migration.apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version,name) VALUES(?,?)",
                    (migration.version, migration.name),
                )
        return self.current_version(conn)

    @staticmethod
    def current_version(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
        ).fetchone()
        return int(row[0])


def _security_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS account_tokens(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            purpose TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS account_tokens_lookup
            ON account_tokens(token_hash,purpose,expires_at);
        CREATE TABLE IF NOT EXISTS trusted_devices(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            label TEXT DEFAULT '',
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    additions = {
        "email_verified_at": "TEXT",
        "totp_secret": "TEXT",
        "totp_enabled": "INTEGER NOT NULL DEFAULT 0",
        "recovery_codes": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")


def _operations_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS background_jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            run_after TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS background_jobs_queue
            ON background_jobs(status,run_after);
        CREATE TABLE IF NOT EXISTS email_deliveries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            recipient TEXT NOT NULL,
            template TEXT NOT NULL,
            provider TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT DEFAULT '',
            provider_id TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            entity_type TEXT DEFAULT '',
            entity_id INTEGER,
            read_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,kind,entity_type,entity_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS entity_changes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            actor_id INTEGER,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            before_json TEXT DEFAULT '',
            after_json TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS entity_changes_lookup
            ON entity_changes(entity_type,entity_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS value_snapshots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            collection_value REAL NOT NULL DEFAULT 0,
            missing_cost REAL NOT NULL DEFAULT 0,
            warehouse_quantity INTEGER NOT NULL DEFAULT 0,
            captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS import_batches(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            payload TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'preview',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            applied_at TEXT,
            undone_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )


def _views_and_maintenance(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS saved_views(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            area TEXT NOT NULL,
            name TEXT NOT NULL,
            configuration TEXT NOT NULL DEFAULT '{}',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,area,name),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS system_health(
            key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            details TEXT DEFAULT '',
            checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        """INSERT OR IGNORE INTO settings(key,value)
           VALUES('maintenance_mode','false')"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO settings(key,value)
           VALUES('audit_retention_days','365')"""
    )


def _add_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _pro7_collections_and_catalog(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS collections(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            owner_id INTEGER NOT NULL,
            is_shared INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS collection_members(
            collection_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(collection_id,user_id),
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS set_copies(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id INTEGER NOT NULL,
            collection_id INTEGER,
            inventory_number TEXT DEFAULT '',
            serial_number TEXT DEFAULT '',
            condition TEXT NOT NULL DEFAULT 'gebraucht',
            completeness TEXT NOT NULL DEFAULT 'unbekannt',
            build_status TEXT NOT NULL DEFAULT 'zerlegt vollständig',
            location_id INTEGER,
            purchase_date TEXT,
            purchase_price REAL NOT NULL DEFAULT 0 CHECK(purchase_price>=0),
            notes TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            deleted_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(set_id) REFERENCES sets(id) ON DELETE CASCADE,
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE SET NULL,
            FOREIGN KEY(location_id) REFERENCES warehouse_locations(id) ON DELETE SET NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS set_copies_inventory_number
            ON set_copies(inventory_number) WHERE inventory_number!='';
        CREATE TABLE IF NOT EXISTS mocs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            collection_id INTEGER,
            name TEXT NOT NULL,
            project_code TEXT DEFAULT '',
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Planung',
            version TEXT NOT NULL DEFAULT '1.0',
            progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
            location_id INTEGER,
            instruction_url TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            deleted_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE SET NULL,
            FOREIGN KEY(location_id) REFERENCES warehouse_locations(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS moc_versions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            moc_id INTEGER NOT NULL,
            version TEXT NOT NULL,
            description TEXT DEFAULT '',
            parts_snapshot TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(moc_id,version),
            FOREIGN KEY(moc_id) REFERENCES mocs(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS moc_parts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            moc_id INTEGER NOT NULL,
            inventory_item_id INTEGER,
            part_number TEXT NOT NULL,
            name TEXT DEFAULT '',
            color TEXT DEFAULT '',
            required_quantity INTEGER NOT NULL DEFAULT 1 CHECK(required_quantity>=0),
            allocated_quantity INTEGER NOT NULL DEFAULT 0 CHECK(allocated_quantity>=0),
            notes TEXT DEFAULT '',
            FOREIGN KEY(moc_id) REFERENCES mocs(id) ON DELETE CASCADE
        );
        """
    )
    for column, definition in {
        "purchase_price": "REAL NOT NULL DEFAULT 0",
        "collection_id": "INTEGER",
        "subtheme": "TEXT DEFAULT ''",
        "minifigures": "INTEGER NOT NULL DEFAULT 0",
        "description": "TEXT DEFAULT ''",
        "condition": "TEXT NOT NULL DEFAULT 'gebraucht'",
        "completeness": "TEXT NOT NULL DEFAULT 'unbekannt'",
        "build_status": "TEXT NOT NULL DEFAULT 'zerlegt vollständig'",
        "location_id": "INTEGER",
        "purchase_date": "TEXT",
        "has_box": "INTEGER NOT NULL DEFAULT 0",
        "has_instructions": "INTEGER NOT NULL DEFAULT 0",
        "has_stickers": "INTEGER NOT NULL DEFAULT 0",
        "notes": "TEXT DEFAULT ''",
        "created_by": "INTEGER",
        "updated_by": "INTEGER",
    }.items():
        _add_column(conn, "sets", column, definition)
    conn.execute(
        """INSERT INTO collections(name,description,owner_id,is_shared)
           SELECT 'Meine Sammlung','Automatisch aus BrickMissing 6.x übernommen',u.id,0
           FROM users u
           WHERE NOT EXISTS(SELECT 1 FROM collections c WHERE c.owner_id=u.id)"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO collection_members(collection_id,user_id,role)
           SELECT id,owner_id,'manager' FROM collections"""
    )
    conn.execute(
        """UPDATE sets SET collection_id=(
               SELECT id FROM collections c WHERE c.owner_id=sets.user_id ORDER BY id LIMIT 1
           ) WHERE collection_id IS NULL"""
    )
    conn.execute(
        """INSERT INTO set_copies(set_id,collection_id,inventory_number,condition,
                                  completeness,build_status,purchase_price,notes)
           SELECT s.id,s.collection_id,'SET-'||s.id,s.condition,s.completeness,
                  s.build_status,COALESCE(s.purchase_price,0),COALESCE(s.notes,'')
           FROM sets s
           WHERE NOT EXISTS(SELECT 1 FROM set_copies c WHERE c.set_id=s.id)"""
    )


def _pro7_inventory_and_orders(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS inventory_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            collection_id INTEGER,
            part_number TEXT NOT NULL,
            design_id TEXT DEFAULT '',
            element_id TEXT DEFAULT '',
            name TEXT NOT NULL,
            color TEXT DEFAULT '',
            category TEXT DEFAULT '',
            subcategory TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity>=0),
            reserved_quantity INTEGER NOT NULL DEFAULT 0
                CHECK(reserved_quantity>=0 AND reserved_quantity<=quantity),
            condition TEXT NOT NULL DEFAULT 'gebraucht',
            location_id INTEGER,
            image_url TEXT DEFAULT '',
            source TEXT DEFAULT '',
            purchase_price REAL NOT NULL DEFAULT 0 CHECK(purchase_price>=0),
            unit_price REAL NOT NULL DEFAULT 0 CHECK(unit_price>=0),
            notes TEXT DEFAULT '',
            archived_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE SET NULL,
            FOREIGN KEY(location_id) REFERENCES warehouse_locations(id) ON DELETE SET NULL,
            UNIQUE(user_id,collection_id,part_number,color,condition,location_id)
        );
        CREATE INDEX IF NOT EXISTS inventory_items_search
            ON inventory_items(user_id,part_number,color,name);
        CREATE TABLE IF NOT EXISTS inventory_movements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_item_id INTEGER NOT NULL,
            movement_type TEXT NOT NULL,
            old_quantity INTEGER NOT NULL,
            new_quantity INTEGER NOT NULL,
            difference INTEGER NOT NULL,
            old_reserved INTEGER NOT NULL DEFAULT 0,
            new_reserved INTEGER NOT NULL DEFAULT 0,
            source TEXT DEFAULT '',
            destination TEXT DEFAULT '',
            user_id INTEGER,
            note TEXT DEFAULT '',
            order_id INTEGER,
            set_id INTEGER,
            moc_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(inventory_item_id) REFERENCES inventory_items(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE SET NULL,
            FOREIGN KEY(set_id) REFERENCES sets(id) ON DELETE SET NULL,
            FOREIGN KEY(moc_id) REFERENCES mocs(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS inventory_movements_item
            ON inventory_movements(inventory_item_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS order_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            inventory_item_id INTEGER,
            part_number TEXT NOT NULL,
            name TEXT DEFAULT '',
            color TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>0),
            received_quantity INTEGER NOT NULL DEFAULT 0 CHECK(received_quantity>=0),
            damaged_quantity INTEGER NOT NULL DEFAULT 0 CHECK(damaged_quantity>=0),
            wrong_quantity INTEGER NOT NULL DEFAULT 0 CHECK(wrong_quantity>=0),
            unit_price REAL NOT NULL DEFAULT 0 CHECK(unit_price>=0),
            target_set_id INTEGER,
            target_location_id INTEGER,
            notes TEXT DEFAULT '',
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY(inventory_item_id) REFERENCES inventory_items(id) ON DELETE SET NULL,
            FOREIGN KEY(target_set_id) REFERENCES sets(id) ON DELETE SET NULL,
            FOREIGN KEY(target_location_id) REFERENCES warehouse_locations(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS price_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            price REAL NOT NULL CHECK(price>=0),
            shipping REAL NOT NULL DEFAULT 0 CHECK(shipping>=0),
            currency TEXT NOT NULL DEFAULT 'EUR',
            source TEXT DEFAULT '',
            supplier TEXT DEFAULT '',
            is_estimate INTEGER NOT NULL DEFAULT 1,
            note TEXT DEFAULT '',
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    for column, definition in {
        "order_date": "TEXT",
        "expected_delivery": "TEXT",
        "delivery_date": "TEXT",
        "shipping_cost": "REAL NOT NULL DEFAULT 0",
        "goods_total": "REAL NOT NULL DEFAULT 0",
        "currency": "TEXT NOT NULL DEFAULT 'EUR'",
        "payment_status": "TEXT DEFAULT ''",
        "shipping_status": "TEXT DEFAULT ''",
        "tracking_number": "TEXT DEFAULT ''",
        "tracking_url": "TEXT DEFAULT ''",
        "deleted_at": "TEXT",
    }.items():
        _add_column(conn, "orders", column, definition)
    for column, definition in {
        "short_code": "TEXT DEFAULT ''",
        "description": "TEXT DEFAULT ''",
        "room": "TEXT DEFAULT ''",
        "color": "TEXT DEFAULT ''",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "locked": "INTEGER NOT NULL DEFAULT 0",
        "archived_at": "TEXT",
    }.items():
        _add_column(conn, "warehouse_locations", column, definition)
    conn.execute(
        """INSERT OR IGNORE INTO inventory_items(
               user_id,collection_id,part_number,design_id,element_id,name,color,
               quantity,location_id,image_url
           )
           SELECT w.user_id,
                  (SELECT id FROM collections c WHERE c.owner_id=w.user_id ORDER BY id LIMIT 1),
                  CASE WHEN w.design_id!='' THEN w.design_id ELSE w.element_id END,
                  w.design_id,w.element_id,w.name,w.color,MAX(w.quantity,0),
                  w.location_id,w.image_url
           FROM warehouse w"""
    )


def _pro7_documents_preferences_quality(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS media_assets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size INTEGER NOT NULL CHECK(size>=0),
            caption TEXT DEFAULT '',
            is_primary INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            document_type TEXT NOT NULL DEFAULT 'sonstiges',
            title TEXT NOT NULL,
            file_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size INTEGER NOT NULL CHECK(size>=0),
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS favorites(
            user_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,entity_type,entity_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS recent_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            label TEXT DEFAULT '',
            action TEXT NOT NULL DEFAULT 'opened',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS search_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS wishlist(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            collection_id INTEGER,
            entity_type TEXT NOT NULL DEFAULT 'set',
            reference TEXT NOT NULL,
            name TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal',
            target_price REAL NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS loans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            borrower TEXT NOT NULL,
            loaned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            due_at TEXT,
            returned_at TEXT,
            notes TEXT DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS label_templates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            width_mm REAL NOT NULL DEFAULT 50,
            height_mm REAL NOT NULL DEFAULT 30,
            orientation TEXT NOT NULL DEFAULT 'landscape',
            configuration TEXT NOT NULL DEFAULT '{}',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,name),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS data_quality_issues(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            issue_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            severity TEXT NOT NULL DEFAULT 'warning',
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            UNIQUE(issue_key,entity_type,entity_id,user_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    for key, value in (
        ("application_version", "7.0.0"),
        ("trash_retention_days", "30"),
        ("max_upload_mb", "15"),
        ("page_size", "50"),
        ("automatic_daily_backup", "true"),
        ("qr_base_url", "http://127.0.0.1:8088"),
    ):
        conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value)
        )


def _minifigure_inventory(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS set_minifigures(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            set_id INTEGER NOT NULL,
            fig_number TEXT NOT NULL,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>=1),
            owned_quantity INTEGER NOT NULL DEFAULT 0 CHECK(owned_quantity>=0),
            image_url TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,set_id,fig_number),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(set_id) REFERENCES sets(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS set_minifigures_user_set
            ON set_minifigures(user_id,set_id,name);
        """
    )


def _minifigure_parts(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS minifigure_parts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            minifigure_id INTEGER NOT NULL,
            part_num TEXT NOT NULL,
            element_id TEXT DEFAULT '',
            name TEXT NOT NULL,
            color_id INTEGER,
            color_name TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>=1),
            is_spare INTEGER NOT NULL DEFAULT 0,
            image_url TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(minifigure_id,part_num,color_id,is_spare),
            FOREIGN KEY(minifigure_id) REFERENCES set_minifigures(id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS minifigure_parts_figure
            ON minifigure_parts(minifigure_id,name);
        """
    )


def _minifigure_part_inventory(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(minifigure_parts)")
    }
    if "owned_quantity" not in columns:
        conn.execute(
            """ALTER TABLE minifigure_parts
               ADD COLUMN owned_quantity INTEGER NOT NULL DEFAULT 0"""
        )


def _user_content_and_query_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS personal_notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS personal_notes_user_updated
            ON personal_notes(user_id,updated_at DESC);
        CREATE TABLE IF NOT EXISTS workshop_documents(
            user_id INTEGER PRIMARY KEY,
            payload TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    index_specs = (
        ("sets", "sets_user_updated", "user_id,deleted_at,updated_at DESC"),
        ("parts", "parts_user_status", "user_id,deleted_at,status,updated_at DESC"),
        ("parts", "parts_set_lookup", "set_id,element_id,color"),
        ("set_inventory", "set_inventory_set_lookup", "set_id,is_spare,name"),
        ("sessions", "sessions_user_expiry", "user_id,expires_at"),
        ("audit_log", "audit_log_created", "created_at DESC"),
    )
    for table, name, columns in index_specs:
        available = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        required = {
            item.strip().split()[0] for item in columns.split(",")
        }
        if required <= available:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})")


MIGRATIONS = MigrationManager(
    [
        Migration(1, "security_and_account_tokens", _security_tables),
        Migration(2, "jobs_notifications_history", _operations_tables),
        Migration(3, "saved_views_and_maintenance", _views_and_maintenance),
        Migration(4, "pro7_collections_catalog_and_copies", _pro7_collections_and_catalog),
        Migration(5, "pro7_inventory_movements_and_orders", _pro7_inventory_and_orders),
        Migration(6, "pro7_documents_preferences_and_quality", _pro7_documents_preferences_quality),
        Migration(7, "minifigure_inventory", _minifigure_inventory),
        Migration(8, "minifigure_parts", _minifigure_parts),
        Migration(9, "minifigure_part_inventory", _minifigure_part_inventory),
        Migration(10, "user_content_and_query_indexes", _user_content_and_query_indexes),
    ]
)
