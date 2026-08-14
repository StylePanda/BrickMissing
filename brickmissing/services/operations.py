from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Any, Callable


class OperationalService:
    """Periodic maintenance, notifications, statistics and retention."""

    def run(self, conn: sqlite3.Connection) -> dict[str, int]:
        notifications = self._notifications(conn)
        snapshots = self._snapshots(conn)
        retained = self._audit_retention(conn)
        conn.execute(
            """INSERT INTO system_health(`key`,status,details,checked_at)
               VALUES('operations','ok',?,CURRENT_TIMESTAMP)
               ON CONFLICT(`key`) DO UPDATE SET status='ok',details=excluded.details,
                   checked_at=CURRENT_TIMESTAMP""",
            (f"notifications={notifications};snapshots={snapshots}",),
        )
        return {"notifications": notifications, "snapshots": snapshots, "audit_deleted": retained}

    @staticmethod
    def _notifications(conn: sqlite3.Connection) -> int:
        before = conn.total_changes
        conn.execute(
            """INSERT OR IGNORE INTO notifications(
                   user_id,kind,title,message,entity_type,entity_id)
               SELECT user_id,'overdue_order','Bestellung prüfen',
                      'Diese Bestellung ist seit mehr als 14 Tagen offen.',
                      'order',id
               FROM orders
               WHERE status IN ('ordered','shipped')
                 AND created_at < datetime('now','-14 days')"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO notifications(
                   user_id,kind,title,message,entity_type,entity_id)
               SELECT user_id,'long_missing','Teil lange nicht verfügbar',
                      'Dieses Teil fehlt seit mehr als 30 Tagen.',
                      'part',id
               FROM parts
               WHERE status='missing' AND deleted_at IS NULL
                 AND created_at < datetime('now','-30 days')"""
        )
        return conn.total_changes - before

    @staticmethod
    def _snapshots(conn: sqlite3.Connection) -> int:
        before = conn.total_changes
        conn.execute(
            """INSERT INTO value_snapshots(
                   user_id,collection_value,missing_cost,warehouse_quantity)
               SELECT u.id,
                      COALESCE((SELECT SUM(current_value) FROM sets s
                                WHERE s.user_id=u.id AND s.deleted_at IS NULL),0),
                      COALESCE((SELECT SUM(quantity*unit_price) FROM parts p
                                WHERE p.user_id=u.id AND p.deleted_at IS NULL
                                  AND p.status='missing'),0),
                      COALESCE((SELECT SUM(quantity) FROM warehouse w
                                WHERE w.user_id=u.id),0)
               FROM users u
               WHERE u.deleted_at IS NULL
                 AND NOT EXISTS(
                     SELECT 1 FROM value_snapshots v
                     WHERE v.user_id=u.id AND date(v.captured_at)=date('now')
                 )"""
        )
        return conn.total_changes - before

    @staticmethod
    def _audit_retention(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT value FROM settings WHERE `key`='audit_retention_days'"
        ).fetchone()
        days = max(30, min(3650, int(row[0] if row else 365)))
        before = conn.total_changes
        if getattr(conn, "is_mariadb", False):
            conn.execute(
                f"DELETE FROM audit_log "
                f"WHERE created_at < DATE_SUB(NOW(), INTERVAL {days} DAY)"
            )
        else:
            conn.execute(
                "DELETE FROM audit_log WHERE created_at < datetime('now',?)",
                (f"-{days} days",),
            )
        return conn.total_changes - before


class MaintenanceScheduler:
    """Runs idempotent maintenance periodically without blocking HTTP threads."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        operation: Callable[[Any], Any],
        interval_seconds: float = 3600,
    ):
        self.connection_factory = connection_factory
        self.operation = operation
        self.interval_seconds = max(float(interval_seconds), 60.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="brickmissing-maintenance", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                with self.connection_factory() as conn:
                    self.operation(conn)
            except Exception as exc:
                # Maintenance failures must not terminate the local web server.
                print(f"BrickMissing-Wartung fehlgeschlagen: {exc!r}")
