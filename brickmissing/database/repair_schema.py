from __future__ import annotations

from brickmissing.web.server import MARIADB_ADMIN


def main() -> None:
    profile = MARIADB_ADMIN.public_profile()
    if profile.get("engine") != "mariadb" or not profile.get("active"):
        print("MariaDB ist nicht als aktive Datenbank konfiguriert.")
        return
    MARIADB_ADMIN.ensure_runtime_schema()
    connection = MARIADB_ADMIN.connect_primary()
    try:
        health = connection.execute(
            """SELECT status,details FROM system_health
               WHERE `key`='migration_tracking'"""
        ).fetchone()
        if health:
            fallback = connection.execute(
                """SELECT COALESCE(MAX(version),0) AS version
                   FROM brickmissing_schema_migrations"""
            ).fetchone()
            print(f"Migrationsstatus: {health['status']} – {health['details']}")
            print(f"Sicheres Ersatzprotokoll: Version {fallback['version']}")
        else:
            primary = connection.execute(
                """SELECT COALESCE(MAX(version),0) AS version
                   FROM schema_migrations"""
            ).fetchone()
            print(f"Migrationsstatus: OK – Version {primary['version']}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
