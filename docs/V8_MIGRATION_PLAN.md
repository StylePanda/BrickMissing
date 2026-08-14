# BrickMissing 8.0 – Migrationsplan

## Zielarchitektur

Nginx terminiert TLS und ist der einzige öffentliche Listener. Gunicorn bindet
nur an `127.0.0.1:8000` und lädt Django 5.2 LTS. Production verwendet
ausschließlich MariaDB. Development darf eine separate SQLite-Datenbank nutzen;
die Legacy-Datenbank ist niemals die Development-Datenbank.

## Modulgrenzen

- `config`: Settings, URL-Routing, WSGI/ASGI und Middleware
- `apps.accounts`: Custom User, Registrierung, Verifikation, Passwortflüsse, 2FA
- `apps.catalog`: Sets, Exemplare, Setinventar, Teile und Minifiguren
- `apps.inventory`: zentrales Inventar, Bewegungen, Lagerorte
- `apps.orders`: Bestellungen und Wareneingang
- `apps.core`: Dashboard, Einstellungen, Health, Request IDs
- `apps.audit`: Audit und sicherheitsrelevante Ereignisse
- `apps.backups`: sichere MariaDB-Backups/Restore-Orchestrierung
- `apps.integrations`: Rebrickable, Bilder, Preise und E-Mail-Anbindung
- `apps.data_portability`: Legacy-Migration, Import und Export

Businesslogik liegt in Services; Views validieren HTTP-Eingaben, erzwingen Login,
Permissions und Ownership und delegieren transaktionale Änderungen.

## Datenmigration

Der Management Command `migrate_legacy_brickmissing` öffnet SQLite über eine
read-only URI, erkennt Schema/Felder, validiert Referenzen und importiert in
einer atomaren Transaktion. `--dry-run` führt dieselbe Validierung und alle
Writes innerhalb einer zurückgerollten Transaktion aus. Primärschlüssel werden
nicht als öffentliche IDs wiederverwendet; eine Import-Mapping-Tabelle sichert
Idempotenz und Beziehungen. Duplikate werden anhand fachlicher Constraints
gemeldet und deterministisch zusammengeführt. Die Quelle wird nie verändert.

Legacy-Passworthashes erhalten einen eigenen Django-Hasher. Nach erfolgreichem
Login rehasht Django automatisch mit Argon2. Unlesbare oder unbekannte Hashes
führen sicher zu einem Passwort-Reset, nicht zu einem Default-Passwort.

## Reihenfolge und Gates

1. Inventar und Legacy-Schema erfassen.
2. Django-Grundgerüst, Custom User und Settings anlegen.
3. Modelle/Migrationen mit Constraints und Indizes implementieren.
4. Legacy-Import samt Dry-Run und Integritätstests implementieren.
5. Authentifizierung, E-Mail-Verifikation, Reset und 2FA implementieren.
6. Sets/Parts/Missing/Trash mit Ownership-Tests implementieren.
7. Inventar, Lager, Bestellungen, Import/Export und Integrationen migrieren.
8. Django-Templates und vorhandenes Design komponentenweise migrieren.
9. Admin, Audit, Backups, Health und Betriebsjobs ergänzen.
10. Security-Hardening und Debian-13-Deployment erstellen.
11. Unit-, Integration-, Security- und Browser-Flows ausführen.
12. Feature-Inventar final auf `MIGRATED`, `REPLACED`, `DEPRECATED` oder
    `NOT_APPLICABLE` setzen; kein `PENDING` darf unkommentiert bleiben.

Nach jeder Phase müssen Systemcheck, betroffene Tests und Ruff erfolgreich sein.
Legacy-Production-Code bleibt bestehen, bis der jeweilige Ersatz getestet ist.

