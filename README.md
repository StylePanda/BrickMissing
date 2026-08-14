# BrickMissing 8.0

BrickMissing 8.0 ist der abgeschlossene Django-Neuaufbau der LEGO-Sammlungs- und
Fehlteileverwaltung. Production verwendet Nginx → Gunicorn → Django → MariaDB.
Der alte Python-HTTP-Server ist nur noch Legacy-Referenz und kein V8-Server.

> Release-Status: **8.0.0 – Production Sign-off ausstehend**. Der V8-Runtimepfad
> ist Django-only. Der vollständige MariaDB-11.8.6-Rehearsal einschließlich
> Reconciliation, 106 Tests, echten Locking-Tests und Cleanup ist PASS.

## Bereits implementiert

- Custom User, UUID, eindeutige normalisierte E-Mail, Argon2 und Legacy-Hash-Upgrade
- Registrierung, Verifikation, Login/Logout, Passwortreset und Profil
- Sets, Setdetails, Teile, Fehlteile, Suche, Filter, Pagination und Papierkorb
- konsequente serverseitige Ownership-Prüfung und Audit Events
- read-only Legacy-SQLite-Import mit Transaktion, Mapping und `--dry-run`
- getrennte Development-/Production-Settings ohne Production-Fallback
- CSP/Security Header, CSRF, sichere Cookies, Request IDs und Healthcheck
- Gunicorn/Nginx/systemd, Maintenance, Smoke-Test und MariaDB-Backup
- atomare Releases über `/var/www/brickmissing/current` mit Smoke-Test-Rollback
- Brickset, BrickLink, BrickEconomy und offizieller Pick-a-Brick-Suchlink
- normalisierte Feld-, Ownership- und Relationship-Reconciliation

## Development

Python 3.12 bis 3.14:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\development.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Development verwendet ausschließlich `var/development.sqlite3`. Die echte
Legacy-Datei `data/brickmissing.db` wird nicht als Django-Datenbank verwendet.

## Tests und Qualität

Finaler Stand: 113/113 Django-Tests, Ruff, Django Check, Migration-Drift, Restore/Reconciliation, echte MariaDB-Concurrency und ausführbare Release-/Rollback-Tests PASS. `check --deploy` meldet nur W005/W021 als Operatorentscheidungen. Production Ready: YES.

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\ruff.exe check apps config manage.py
.\.venv\Scripts\ruff.exe format --check apps config manage.py
```

## Legacy-Migration

Immer zuerst Dry-Run:

```powershell
.\.venv\Scripts\python.exe manage.py migrate_legacy_brickmissing --source .\data\brickmissing.db --dry-run
```

Danach nur gegen die gewünschte V8-Zieldatenbank ohne `--dry-run`. Die Quelle
wird read-only geöffnet, validiert und niemals verändert oder gelöscht.

## Production

- Environment-Referenz: `.env.example`
- Debian 13: `docs/DEPLOYMENT_DEBIAN13.md`
- Nginx: `deploy/nginx/brickmissing.conf`
- systemd: `deploy/systemd/brickmissing.service`
- Gunicorn: `deploy/gunicorn.conf.py` (nur `127.0.0.1:8000`)

Production startet nicht ohne Secret, Hosts und vollständige MariaDB-Variablen.
SMTP einschließlich testmail.app wird ausschließlich per `EMAIL_*` konfiguriert.
Das Deployment darf erst nach erfolgreichem `scripts/rehearse_mariadb.py` auf
einem unterstützten MariaDB-Server freigegeben werden.

## Backups

```bash
.venv/bin/python manage.py backup_database --destination /var/backups/brickmissing
```

Das Passwort erscheint nicht in der Kommandozeile. Restore-Schritte und das
Maintenance-Verfahren stehen in der Deployment-Anleitung. Bestehende Ordner
`data/`, `backups/`, `cache/` und insbesondere `.master.key` werden nie gelöscht.

## Dokumentation

- `docs/LEGACY_FEATURE_INVENTORY.md`
- `docs/V8_MIGRATION_PLAN.md`
- `docs/V8_MIGRATION_REPORT.md`
- `docs/SECURITY_REVIEW_V8.md`
- `docs/DEPLOYMENT_DEBIAN13.md`
