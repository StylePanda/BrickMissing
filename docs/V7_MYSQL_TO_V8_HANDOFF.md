# V7 MySQL/MariaDB to BrickMissing 8 handoff

## 1. Geänderte Dateien

- `apps/data_portability/legacy_source.py`
- `apps/data_portability/management/commands/migrate_legacy_brickmissing.py`
- `apps/data_portability/management/commands/validate_legacy_migration.py`
- `apps/data_portability/tests.py`
- `config/settings/production.py`
- `.env.example`
- `docs/DEPLOYMENT_DEBIAN13.md`
- `docs/CHATGPT_HANDOFF_V8.md`
- `docs/V7_MYSQL_TO_V8_HANDOFF.md`
- `CHANGELOG.md`

## 2. Neue Environment-Variablen

| Name | Zweck | Beispiel ohne echtes Secret |
|---|---|---|
| `LEGACY_DB_HOST` | Host der read-only V7-Quelldatenbank | `127.0.0.1` |
| `LEGACY_DB_PORT` | MariaDB-Port der V7-Quelle | `3306` |
| `LEGACY_DB_NAME` | Name der V7-Quelldatenbank; aktiviert Alias `legacy_v7` | `brickmissing_v7_source` |
| `LEGACY_DB_USER` | MariaDB-Benutzer mit ausschließlich `SELECT` | `brickmissing_v7_reader` |
| `LEGACY_DB_PASSWORD` | Extern gespeichertes Passwort des read-only Benutzers | `<READ_ONLY_PASSWORD>` |

## 3. Production Dry-run

```bash
sudo -u brickmissing bash -lc 'set -a; source /etc/brickmissing/brickmissing.env; set +a; cd /var/www/brickmissing/current && .venv/bin/python manage.py migrate_legacy_brickmissing --source-db-alias legacy_v7 --dry-run'
```

## 4. Reconciliation

```bash
sudo -u brickmissing bash -lc 'set -a; source /etc/brickmissing/brickmissing.env; set +a; cd /var/www/brickmissing/current && mkdir -p /var/www/brickmissing/shared/var/reports && .venv/bin/python manage.py validate_legacy_migration --source-db-alias legacy_v7 --output /var/www/brickmissing/shared/var/reports/legacy_reconciliation.json'
```

Vor dem echten Import existieren Target-Datensätze nur innerhalb des Dry-run; der Dry-run führt seine eigene Reconciliation vor dem Rollback aus. Der separate Reconciliation-Befehl ist nach dem echten Import maßgeblich.

## 5. Echter Import

```bash
sudo -u brickmissing bash -lc 'set -a; source /etc/brickmissing/brickmissing.env; set +a; cd /var/www/brickmissing/current && .venv/bin/python manage.py migrate_legacy_brickmissing --source-db-alias legacy_v7'
```

## 6. Prüfung nach dem Import

```bash
sudo -u brickmissing bash -lc 'set -a; source /etc/brickmissing/brickmissing.env; set +a; cd /var/www/brickmissing/current && .venv/bin/python manage.py check && .venv/bin/python manage.py validate_legacy_migration --source-db-alias legacy_v7 --output /var/www/brickmissing/shared/var/reports/legacy_reconciliation.json'
```

## 7. Typisiert importierte V7-Tabellen

- `users`
- `sets`
- `set_copies`
- `parts`
- `set_inventory`
- `history` (gültige Beziehungen)
- `collections`
- `collection_members`
- `warehouse_locations`
- `inventory_items`
- `inventory_movements`
- `set_minifigures`
- `minifigure_parts`
- `personal_notes`
- `orders`
- `order_items`
- `mocs`
- `moc_parts`
- `moc_versions`
- `wishlist`
- `loans`
- `price_history`
- `value_snapshots`
- `notifications`
- `workshop_documents`
- `audit_log`
- `label_templates`
- `saved_views`
- `recent_items`
- `data_quality_issues` (offene Einträge)

## 8. Bewusst nicht typisiert importierte Tabellen

### Technische Laufzeitdaten: übersprungen

- `account_tokens`
- `sessions`
- `trusted_devices`
- `background_jobs`
- `schema_migrations`
- `system_health`

Grund: V7-Sicherheits-, Session-, Job-, Health- und Schema-Runtimezustand darf nicht in Django 8 übernommen werden.

### Nicht typisiert abgebildet: als `LegacyArchiveRecord` erhalten

- `settings`
- `user_settings`
- `documents`
- `media_assets`
- `favorites`
- `entity_changes`
- `search_history`
- `email_deliveries`
- `import_batches`
- `warehouse`
- alle weiteren erkannten, nicht gemappten Tabellen
- verwaiste `history`-Zeilen

Grund: keine passende verifizierte V8-Zielabbildung; Payload wird mit Source-Fingerprint verlustfrei archiviert, nicht still verworfen.

## 9. User- und Passwortmigration

- User werden über `legacy_id` gemappt; neue Django-Primärschlüssel werden nicht mit V7-IDs gleichgesetzt.
- Owner/FKs verwenden explizite In-Memory-ID-Mappings.
- V7 `pbkdf2_sha256$iterations$salt$digest` wird als `brickmissing_pbkdf2_sha256` übernommen.
- Django verifiziert den Legacy-Hash und aktualisiert ihn nach erfolgreichem Login auf Argon2.
- Fehlende, ungültige oder unbekannte Hashformate erhalten ein unbrauchbares Passwort; Passwortreset ist erforderlich.
- Keine Klartextpasswörter werden erzeugt oder rekonstruiert.

## 10. Schreibschutz der V7-Quelle

- MariaDB-Zugriff erfolgt über Django-Alias `legacy_v7`.
- Source-Session setzt `TRANSACTION READ ONLY`.
- `DATABASES["legacy_v7"]` setzt `init_command` auf read-only.
- `LegacySource.execute()` akzeptiert nur einzelne `SELECT`-Statements.
- Schreibende und Mehrfachstatements werden abgewiesen.
- Server-Benutzer muss ausschließlich `SELECT` auf `brickmissing_v7_source` besitzen.
- SQLite bleibt über URI `mode=ro` read-only.

## 11. Source == Target

- Alias `default` ist als Source verboten.
- Vor Verbindungsaufbau werden normalisierte Host-, Port- und Datenbanknamen verglichen.
- `localhost`, `127.0.0.1` und `::1` gelten als dieselbe Loopback-Identität.
- Bei Gleichheit beendet der Importer mit `CommandError`.

## 12. Idempotenz

- Typisierte Datensätze verwenden `legacy_id` plus `update_or_create`.
- Beziehungen verwenden explizite Legacy-ID-Mappings.
- `LegacyImportRecord` ist eindeutig über Source-Fingerprint, Tabelle und Source-PK.
- `LegacyArchiveRecord` besitzt dieselbe eindeutige Source-Bindung.
- Wiederholter Import aktualisiert vorhandene Legacy-Datensätze statt sie zu duplizieren.
- Gesamter Target-Import läuft in `transaction.atomic(using="default")`.

## 13. Testergebnisse

| Prüfung | Ergebnis |
|---|---|
| Gesamtsuite | 113 Tests |
| Passed | 113 |
| Failed | 0 |
| Skipped | 0 |
| Portability/Legacy-Source | 14/14 PASS |
| MariaDB 11.8.6 Full Rehearsal | PASS |
| MariaDB Migration/Import/Reconciliation | PASS |
| MariaDB Locking/Concurrency | PASS |
| Read-only SQL Guard | PASS |
| Source == Target Guard | PASS |
| SQLite Dry-run/Reconciliation/Rollback | PASS |
| Idempotenz | PASS |
| Fehlerrollback | PASS |
| Release-/Deploymenttests | 6/6 PASS |
| Ruff | PASS |
| Django Check | PASS |
| Migration Drift | PASS |

Die vollständige Gesamtsuite nach der MariaDB-Source-Erweiterung lief lokal gegen die Development-Testdatenbank. Der zuvor abgeschlossene MariaDB-11.8.6-Rehearsal deckte die gemeinsame V8-Zielpipeline und echte Locking-/Concurrency-Prüfungen ab; ein echter Produktionsimport wurde nicht ausgeführt.

## 14. SQLite-Kompatibilität

Ja. Bestehender Aufruf bleibt unterstützt:

```bash
python manage.py migrate_legacy_brickmissing --source /path/to/database.sqlite3
```

SQLite-Import, Dry-run, Idempotenz, Source-SHA-256 und Reconciliation sind getestet.

## 15. Server-Voraussetzungen

- Debian 13
- aktuelles BrickMissing-8.0.0-Release unter `/var/www/brickmissing/current`
- Python-Venv unter `/var/www/brickmissing/current/.venv`
- Django-Production-Environment in `/etc/brickmissing/brickmissing.env`
- leere/migrierte V8-Zieldatenbank `brickmissing`
- V7-Quelldatenbank `brickmissing_v7_source`
- getrennte Source- und Target-Datenbanknamen
- MariaDB-Source-Benutzer mit ausschließlich `SELECT`
- fünf konfigurierte `LEGACY_DB_*`-Variablen
- vollständiger SQL-Dump der V8-Zieldatenbank vor echtem Import
- Schreibrecht für `brickmissing` auf `/var/www/brickmissing/shared/var/reports`
- ausreichend Wartungsfenster; während des echten Imports keine konkurrierenden V8-Schreibzugriffe

## 16. Empfohlene Reihenfolge

1. Backup: vollständigen MariaDB-Dump der V8-Zieldatenbank erstellen und extern prüfen.
2. Config: `LEGACY_DB_*` setzen; Source-User serverseitig auf `SELECT` beschränken.
3. Dry-run: Befehl aus Abschnitt 3 ausführen; `Reconciliation: PASS` verlangen.
4. Reconciliation: Dry-run-Ausgabe prüfen; separater Report ist erst nach persistentem Import maßgeblich.
5. Echter Import: Wartungsmodus aktivieren und Befehl aus Abschnitt 5 ausführen.
6. Reconciliation: Befehl aus Abschnitt 4 ausführen; Status `PASS` und 0 Mismatches verlangen.
7. Counts: Report und Command-Zusammenfassung gegen bekannte V7-Counts prüfen.
8. Production-Test: `manage.py check`, Dienstrestart und HTTPS-Smoke-Test ausführen.

## CHATGPT NEXT ACTION

ChatGPT soll dem Benutzer als nächsten Server-Befehl ausschließlich den read-only Dry-run geben:

```bash
sudo -u brickmissing bash -lc 'set -a; source /etc/brickmissing/brickmissing.env; set +a; cd /var/www/brickmissing/current && .venv/bin/python manage.py migrate_legacy_brickmissing --source-db-alias legacy_v7 --dry-run'
```

Danach soll ChatGPT die vollständige Dry-run-Ausgabe prüfen und vor einem echten Import ausdrücklich auf `Reconciliation: PASS`, plausible Counts und das vorhandene Target-Backup bestehen.
