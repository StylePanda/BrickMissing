from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from django.db import connections


class LegacySourceError(RuntimeError):
    pass


class LegacyRow(dict):
    """Backend-neutral mapping with sqlite3.Row-compatible integer access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class LegacySource:
    READ_ONLY_SQL = re.compile(r"^\s*SELECT\b", re.IGNORECASE)

    def execute(self, sql: str, params=()):
        if not self.READ_ONLY_SQL.match(sql) or ";" in sql.rstrip().rstrip(";"):
            raise LegacySourceError("Legacy source accepts SELECT statements only")
        return self._execute(sql, params)

    def _execute(self, sql, params):
        raise NotImplementedError

    def table_names(self) -> set[str]:
        raise NotImplementedError

    def columns(self, table: str) -> list[str]:
        raise NotImplementedError

    def validate(self) -> None:
        self.execute("SELECT 1")

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for table in sorted(self.table_names()):
            columns = self.columns(table)
            digest.update(json.dumps([table, columns], separators=(",", ":")).encode())
            serialized_rows = []
            # Table names are obtained exclusively through backend introspection.
            for row in self.execute(f"SELECT * FROM `{table}`"):  # noqa: S608
                serialized_rows.append(
                    json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
                )
            for serialized in sorted(serialized_rows):
                digest.update(serialized.encode())
        return digest.hexdigest()

    def close(self) -> None:
        pass


class SQLiteLegacySource(LegacySource):
    def __init__(self, path: Path):
        self.path = path.resolve()
        if not self.path.is_file():
            raise LegacySourceError(f"Legacy database not found: {self.path}")
        self.connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row

    def validate(self):
        if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise LegacySourceError("SQLite quick_check failed")

    def _execute(self, sql, params):
        return [LegacyRow(dict(row)) for row in self.connection.execute(sql, params)]

    def table_names(self):
        return {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    def columns(self, table):
        return [row[1] for row in self.connection.execute(f"PRAGMA table_info(`{table}`)")]

    def fingerprint(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def close(self):
        self.connection.close()


class DjangoAliasLegacySource(LegacySource):
    SUPPORTED_VENDORS = {"mysql"}

    def __init__(self, alias: str):
        if alias == "default" or alias not in connections:
            raise LegacySourceError("A configured non-default legacy database alias is required")
        self.alias = alias
        self.connection = connections[alias]
        if self.connection.vendor not in self.SUPPORTED_VENDORS:
            raise LegacySourceError("Legacy alias must use the MariaDB/MySQL backend")
        self.connection.ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")

    def _execute(self, sql, params):
        with self.connection.cursor() as cursor:
            cursor.execute(sql.replace("?", "%s"), params)
            columns = [column[0] for column in cursor.description]
            return [LegacyRow(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def table_names(self):
        return set(self.connection.introspection.table_names())

    def columns(self, table):
        with self.connection.cursor() as cursor:
            return [column.name for column in self.connection.introspection.get_table_description(cursor, table)]

    def close(self):
        self.connection.close()


def open_legacy_source(*, path: Path | None = None, alias: str | None = None) -> LegacySource:
    if bool(path) == bool(alias):
        raise LegacySourceError("Specify exactly one of --source or --source-db-alias")
    return SQLiteLegacySource(path) if path else DjangoAliasLegacySource(alias)
