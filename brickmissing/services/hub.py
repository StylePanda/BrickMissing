from __future__ import annotations

from pathlib import Path
from typing import Any


class HubIntegrationService:
    """Read-only projection exposed to the authenticated local Media Hub."""

    def __init__(self, backup_dir: Path):
        self.backup_dir = backup_dir

    @staticmethod
    def _rows(cursor: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in cursor.fetchall()]

    def summary(self, conn: Any) -> dict[str, Any]:
        users = self._rows(conn.execute(
            """SELECT id,name,role,disabled,last_login
               FROM users WHERE deleted_at IS NULL ORDER BY name"""
        ))
        tasks = self._rows(conn.execute(
            """SELECT p.id,p.name,p.element_id,p.color,p.quantity,
                      p.priority,s.name AS set_name
               FROM parts p LEFT JOIN sets s ON s.id=p.set_id
               WHERE p.deleted_at IS NULL AND p.status='missing'
               ORDER BY CASE p.priority WHEN 'high' THEN 0 ELSE 1 END,
                        p.created_at LIMIT 12"""
        ))
        orders = self._rows(conn.execute(
            """SELECT id,supplier,order_number,status,total,created_at
               FROM orders WHERE status IN ('ordered','shipped')
               ORDER BY created_at LIMIT 12"""
        ))
        backups = sorted(
            self.backup_dir.glob("brickmissing_*"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return {
            "ok": True,
            "service": "BrickMissing",
            "counts": {
                "sets": conn.execute(
                    "SELECT COUNT(*) AS c FROM sets WHERE deleted_at IS NULL"
                ).fetchone()["c"],
                "missing_parts": conn.execute(
                    """SELECT COALESCE(SUM(quantity),0) AS c FROM parts
                       WHERE deleted_at IS NULL AND status='missing'"""
                ).fetchone()["c"],
                "open_orders": len(orders),
            },
            "tasks": tasks,
            "orders": orders,
            "users": users,
            "backups": {
                "count": len(backups),
                "latest": backups[0].name if backups else "",
            },
        }
