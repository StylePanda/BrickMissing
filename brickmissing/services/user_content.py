from __future__ import annotations

import json
from datetime import datetime
from typing import Any


class UserContentService:
    """Persistence and validation for user-owned notes and workshop data."""

    @staticmethod
    def _load(conn: Any, user_id: int, key: str, default: Any) -> Any:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id=? AND `key`=?",
            (user_id, key),
        ).fetchone()
        if not row:
            return default
        try:
            value = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return default
        return value if isinstance(value, type(default)) else default

    @staticmethod
    def _save(conn: Any, user_id: int, key: str, value: Any) -> None:
        conn.execute(
            "INSERT INTO user_settings(user_id,`key`,value) VALUES(?,?,?) "
            "ON CONFLICT(user_id,`key`) DO UPDATE SET value=excluded.value",
            (user_id, key, json.dumps(value, ensure_ascii=False)),
        )

    def notes(self, conn: Any, user_id: int) -> list[dict[str, Any]]:
        stored = conn.execute(
            """SELECT id,title,content,created_at,updated_at FROM personal_notes
               WHERE user_id=? ORDER BY updated_at DESC,id DESC""",
            (user_id,),
        ).fetchall()
        if stored:
            return [dict(item) for item in stored]
        legacy = self._load(conn, user_id, "personal_notes", [])
        for item in reversed(legacy):
            conn.execute(
                """INSERT INTO personal_notes(user_id,title,content,created_at,updated_at)
                   VALUES(?,?,?,?,?)""",
                (
                    user_id, str(item.get("title", ""))[:120],
                    str(item.get("content", ""))[:20_000],
                    str(item.get("created_at", "")) or datetime.now().isoformat(),
                    str(item.get("updated_at", "")) or datetime.now().isoformat(),
                ),
            )
        if legacy:
            conn.execute(
                "DELETE FROM user_settings WHERE user_id=? AND `key`='personal_notes'",
                (user_id,),
            )
            return self.notes(conn, user_id)
        return []

    def save_note(
        self, conn: Any, user_id: int, note_id: Any, title: Any, content: Any
    ) -> list[dict[str, Any]]:
        clean_title = str(title or "").strip()[:120]
        clean_content = str(content or "").strip()[:20_000]
        if not clean_title or not clean_content:
            raise ValueError("Titel und Notiztext dürfen nicht leer sein.")
        requested_id = str(note_id or "").strip()
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        existing = conn.execute(
            "SELECT id FROM personal_notes WHERE id=? AND user_id=?",
            (int(requested_id or 0), user_id),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE personal_notes SET title=?,content=?,updated_at=?
                   WHERE id=? AND user_id=?""",
                (clean_title, clean_content, now, int(requested_id), user_id),
            )
        else:
            conn.execute(
                """INSERT INTO personal_notes(user_id,title,content,created_at,updated_at)
                   VALUES(?,?,?,?,?)""",
                (user_id, clean_title, clean_content, now, now),
            )
        stale = conn.execute(
            """SELECT id FROM personal_notes WHERE user_id=?
               ORDER BY updated_at DESC,id DESC""",
            (user_id,),
        ).fetchall()[250:]
        if stale:
            conn.executemany(
                "DELETE FROM personal_notes WHERE id=? AND user_id=?",
                [(item["id"], user_id) for item in stale],
            )
        return self.notes(conn, user_id)

    def delete_note(self, conn: Any, user_id: int, note_id: int) -> list[dict[str, Any]]:
        conn.execute(
            "DELETE FROM personal_notes WHERE id=? AND user_id=?", (note_id, user_id)
        )
        return self.notes(conn, user_id)

    def workshop(self, conn: Any, user_id: int) -> dict[str, Any]:
        row = conn.execute(
            "SELECT payload FROM workshop_documents WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            try:
                value = json.loads(row["payload"])
                return value if isinstance(value, dict) else {}
            except (TypeError, json.JSONDecodeError):
                return {}
        legacy = self._load(conn, user_id, "workshop_data", {})
        if legacy:
            self.save_workshop(conn, user_id, legacy)
            conn.execute(
                "DELETE FROM user_settings WHERE user_id=? AND `key`='workshop_data'",
                (user_id,),
            )
        return legacy

    def save_workshop(self, conn: Any, user_id: int, workshop: Any) -> None:
        if not isinstance(workshop, dict):
            raise ValueError("Die Werkstattdaten sind ungültig.")
        if len(json.dumps(workshop, ensure_ascii=False).encode("utf-8")) > 1_000_000:
            raise ValueError("Die Werkstattdaten sind zu groß.")
        conn.execute(
            """INSERT INTO workshop_documents(user_id,payload,updated_at)
               VALUES(?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                   payload=excluded.payload,updated_at=CURRENT_TIMESTAMP""",
            (user_id, json.dumps(workshop, ensure_ascii=False)),
        )
