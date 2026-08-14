from __future__ import annotations

import platform
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from brickmissing.version import APP_VERSION


class Pro7Service:
    """Geschäftslogik der 7.0-Module, unabhängig vom HTTP-Transport."""

    MOVEMENT_TYPES = {
        "Zugang", "Abgang", "Korrektur", "Reservierung",
        "Reservierung aufgehoben", "Set zugewiesen", "MOC zugewiesen",
        "verkauft", "beschädigt", "verschoben", "Wareneingang", "Import",
    }

    @staticmethod
    def _integer(value: Any, name: str, minimum: int = 0) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} muss eine ganze Zahl sein.") from exc
        if result < minimum:
            raise ValueError(f"{name} darf nicht kleiner als {minimum} sein.")
        return result

    def adjust_inventory(
        self,
        conn: sqlite3.Connection,
        item_id: int,
        *,
        quantity: Any,
        reserved: Any,
        movement_type: str,
        user_id: int,
        note: str = "",
        source: str = "",
        destination: str = "",
        order_id: int | None = None,
        set_id: int | None = None,
        moc_id: int | None = None,
    ) -> dict[str, int]:
        if movement_type not in self.MOVEMENT_TYPES:
            raise ValueError("Ungültige Bewegungsart.")
        row = conn.execute(
            "SELECT quantity,reserved_quantity FROM inventory_items WHERE id=?",
            (item_id,),
        ).fetchone()
        if not row:
            raise ValueError("Inventarteil wurde nicht gefunden.")
        new_quantity = self._integer(quantity, "Menge")
        new_reserved = self._integer(reserved, "Reservierte Menge")
        if new_reserved > new_quantity:
            raise ValueError("Die reservierte Menge darf den Bestand nicht übersteigen.")
        old_quantity = int(row["quantity"])
        old_reserved = int(row["reserved_quantity"])
        conn.execute(
            """UPDATE inventory_items
               SET quantity=?,reserved_quantity=?,updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (new_quantity, new_reserved, item_id),
        )
        conn.execute(
            """INSERT INTO inventory_movements(
                   inventory_item_id,movement_type,old_quantity,new_quantity,
                   difference,old_reserved,new_reserved,source,destination,
                   user_id,note,order_id,set_id,moc_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item_id, movement_type, old_quantity, new_quantity,
                new_quantity - old_quantity, old_reserved, new_reserved,
                source[:200], destination[:200], user_id, note[:1000],
                order_id, set_id, moc_id,
            ),
        )
        return {
            "quantity": new_quantity,
            "reserved_quantity": new_reserved,
            "available_quantity": new_quantity - new_reserved,
        }

    def receive_order(
        self,
        conn: sqlite3.Connection,
        order_id: int,
        positions: list[dict[str, Any]],
        user_id: int,
    ) -> dict[str, int | str]:
        order = conn.execute(
            "SELECT id,user_id FROM orders WHERE id=? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()
        if not order:
            raise ValueError("Bestellung wurde nicht gefunden.")
        received_total = 0
        incomplete = False
        for received in positions:
            line_id = self._integer(received.get("id"), "Positions-ID", 1)
            line = conn.execute(
                "SELECT * FROM order_items WHERE id=? AND order_id=?",
                (line_id, order_id),
            ).fetchone()
            if not line:
                raise ValueError(f"Bestellposition {line_id} wurde nicht gefunden.")
            previously_received = int(line["received_quantity"] or 0)
            amount = self._integer(received.get("received_quantity", 0), "Gelieferte Menge")
            damaged = self._integer(received.get("damaged_quantity", 0), "Beschädigte Menge")
            wrong = self._integer(received.get("wrong_quantity", 0), "Falsche Menge")
            if amount > int(line["quantity"]):
                raise ValueError("Die gelieferte Menge übersteigt die Bestellmenge.")
            usable = max(amount - damaged - wrong, 0)
            conn.execute(
                """UPDATE order_items SET received_quantity=?,damaged_quantity=?,
                   wrong_quantity=?,target_location_id=COALESCE(?,target_location_id)
                   WHERE id=?""",
                (amount, damaged, wrong, received.get("target_location_id"), line_id),
            )
            item_id = line["inventory_item_id"]
            if not item_id:
                cursor = conn.execute(
                    """INSERT INTO inventory_items(
                           user_id,part_number,name,color,quantity,location_id
                       ) VALUES(?,?,?,?,0,?)""",
                    (
                        order["user_id"], line["part_number"], line["name"],
                        line["color"], received.get("target_location_id") or line["target_location_id"],
                    ),
                )
                item_id = cursor.lastrowid
                conn.execute(
                    "UPDATE order_items SET inventory_item_id=? WHERE id=?",
                    (item_id, line_id),
                )
            stock = conn.execute(
                "SELECT quantity,reserved_quantity FROM inventory_items WHERE id=?",
                (item_id,),
            ).fetchone()
            delta = max(usable - previously_received, 0)
            self.adjust_inventory(
                conn, int(item_id),
                quantity=int(stock["quantity"]) + delta,
                reserved=int(stock["reserved_quantity"]),
                movement_type="Wareneingang", user_id=user_id,
                note=f"Bestellung #{order_id}, Position #{line_id}",
                order_id=order_id,
            )
            received_total += delta
            incomplete = incomplete or amount < int(line["quantity"])
        status = "teilweise geliefert" if incomplete else "geliefert"
        conn.execute(
            """UPDATE orders SET status=?,delivery_date=CASE WHEN ?='geliefert'
                   THEN CURRENT_TIMESTAMP ELSE delivery_date END,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (status, status, order_id),
        )
        return {"received": received_total, "status": status}

    @staticmethod
    def scan_quality(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
        checks = [
            ("set_without_number", "set", "warning", "Set ohne Setnummer",
             "SELECT id FROM sets WHERE user_id=? AND deleted_at IS NULL AND trim(set_number)=''"),
            ("set_without_image", "set", "info", "Set ohne Bild",
             "SELECT id FROM sets WHERE user_id=? AND deleted_at IS NULL AND trim(COALESCE(image_url,''))=''"),
            ("part_without_number", "inventory", "warning", "Teil ohne Teilenummer",
             "SELECT id FROM inventory_items WHERE user_id=? AND archived_at IS NULL AND trim(part_number)=''"),
            ("negative_or_overreserved", "inventory", "error", "Bestand oder Reservierung ist unplausibel",
             "SELECT id FROM inventory_items WHERE user_id=? AND (quantity<0 OR reserved_quantity>quantity)"),
            ("order_without_items", "order", "warning", "Bestellung ohne Positionen",
             """SELECT o.id FROM orders o WHERE o.user_id=? AND o.deleted_at IS NULL
                AND NOT EXISTS(SELECT 1 FROM order_items i WHERE i.order_id=o.id)"""),
            ("location_without_name", "location", "error", "Lagerort ohne Namen",
             "SELECT id FROM warehouse_locations WHERE user_id=? AND trim(name)=''"),
        ]
        conn.execute(
            "DELETE FROM data_quality_issues WHERE user_id=? AND status='open'", (user_id,)
        )
        for key, entity_type, severity, message, sql in checks:
            for row in conn.execute(sql, (user_id,)):
                conn.execute(
                    """INSERT OR IGNORE INTO data_quality_issues(
                           user_id,issue_key,entity_type,entity_id,severity,message
                       ) VALUES(?,?,?,?,?,?)""",
                    (user_id, key, entity_type, row["id"], severity, message),
                )
        return [
            dict(row) for row in conn.execute(
                """SELECT * FROM data_quality_issues WHERE user_id=? AND status='open'
                   ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                            detected_at DESC""",
                (user_id,),
            )
        ]

    @staticmethod
    def system_status(root: Path, conn: sqlite3.Connection) -> dict[str, Any]:
        usage = shutil.disk_usage(root)
        return {
            "application_version": APP_VERSION,
            "python_version": platform.python_version(),
            "database": "MariaDB" if getattr(conn, "is_mariadb", False) else "SQLite",
            "database_ok": bool(conn.execute("SELECT 1").fetchone()),
            "free_space": usage.free,
            "uploads_writable": (root / "data").exists(),
            "backups_writable": (root / "backups").exists(),
            "schema_version": int(
                conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            ),
            "settings": {
                row["key"]: row["value"]
                for row in conn.execute(
                    "SELECT `key`,value FROM settings WHERE `key` IN "
                    "('maintenance_mode','trash_retention_days','max_upload_mb','page_size')"
                )
            },
        }


PRO7 = Pro7Service()
