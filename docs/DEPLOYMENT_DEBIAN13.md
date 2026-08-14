# BrickMissing 8.0 auf Debian 13

> Final audit 2026-08-12: every manifest path, size and SHA-256 is verified before/after copy; `current` switches atomically. Executable tests cover success, pre-activation failure and smoke rollback. The complete MariaDB 11.8.6 rehearsal, 106-test suite, locking verification and cleanup pass. Never use production as rehearsal.

## Voraussetzungen

Verwende MariaDB **10.5 oder neuer**. Vor dem ersten Deployment muss `scripts/rehearse_mariadb.py` gegen eine lokale, isolierte Rehearsal-Datenbank erfolgreich sein. MariaDB 10.4 ist für Django 5.2 nicht unterstützt.

## V7-MariaDB-Quelle migrieren

Die optionale Source-Verbindung wird ausschließlich extern konfiguriert:

```text
LEGACY_DB_HOST=127.0.0.1
LEGACY_DB_PORT=3306
LEGACY_DB_NAME=brickmissing_v7_source
LEGACY_DB_USER=<read-only-user>
LEGACY_DB_PASSWORD=<external-secret>
```

Wenn `LEGACY_DB_NAME` gesetzt ist, stellt Production den Django-Alias `legacy_v7`
bereit. Der DB-User erhält serverseitig ausschließlich `SELECT`. Zusätzlich setzt
der Client die Session read-only und der Importer akzeptiert ausschließlich SELECT.
Source und Target müssen unterschiedliche Datenbanken sein.

Dry-run (vollständiges Mapping, alle Target-Schreibvorgänge werden zurückgerollt):

```bash
/var/www/brickmissing/current/.venv/bin/python manage.py migrate_legacy_brickmissing --source-db-alias legacy_v7 --dry-run
```

Echter atomarer Import:

```bash
/var/www/brickmissing/current/.venv/bin/python manage.py migrate_legacy_brickmissing --source-db-alias legacy_v7
```

Reconciliation:

```bash
/var/www/brickmissing/current/.venv/bin/python manage.py validate_legacy_migration --source-db-alias legacy_v7 --output /var/www/brickmissing/shared/var/reports/legacy_reconciliation.json
```

Vor dem echten Import einen vollständigen Dump der V8-Zieldatenbank erstellen. Ein
Importfehler rollt die Target-Transaktion zurück. Für operatorseitiges Rollback nach
erfolgreichem Import den Target-Dump zurückspielen; niemals die V7-Quelle verändern.
Der SQLite-Aufruf mit `--source /pfad/datei.sqlite3` bleibt unterstützt.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential nginx mariadb-server mariadb-client certbot python3-certbot-nginx ufw
sudo adduser --system --group --home /var/www/brickmissing brickmissing
sudo install -d -o brickmissing -g brickmissing -m 0750 /var/www/brickmissing/releases /var/www/brickmissing/shared/var /var/backups/brickmissing
sudo install -d -o root -g brickmissing -m 0750 /etc/brickmissing
```

Die feste Struktur lautet:

```text
/var/www/brickmissing/
  releases/       unveränderliche Release-Verzeichnisse
  shared/var/     Uploads, Static, Backups und Maintenance-State
  current -> releases/8.0.0-<timestamp>
```

## MariaDB und Environment

Erstelle eine dedizierte UTF-8-Datenbank und einen minimal berechtigten Benutzer. Port 3306 bleibt an Loopback gebunden. Kopiere `.env.example` nach `/etc/brickmissing/brickmissing.env`, setze zufällige unabhängige Secrets und `chmod 0640`; Secrets liegen nie im Release.

```bash
sudo cp .env.example /etc/brickmissing/brickmissing.env
sudo chown root:brickmissing /etc/brickmissing/brickmissing.env
sudo chmod 0640 /etc/brickmissing/brickmissing.env
sudoedit /etc/brickmissing/brickmissing.env
```

`SECURE_HSTS_INCLUDE_SUBDOMAINS` und `SECURE_HSTS_PRELOAD` erst nach Prüfung aller Subdomains aktivieren.

## Rehearsal

Das Script prüft zuerst die Serverversion, verweigert MariaDB unter 10.5, erstellt ausschließlich `brickmissing_v8_migration_rehearsal`, führt Migration, Legacy-Import, Wert-/Beziehungs-Reconciliation, Checks und Tests aus und entfernt die Testdatenbank im `finally`. Eine bereits existierende gleichnamige Datenbank wird nicht verwendet oder gelöscht.

```bash
python3 scripts/rehearse_mariadb.py --config /sicherer/pfad/mariadb-rehearsal.json --source /sicherer/pfad/brickmissing.db
```

Der Report liegt standardmäßig unter `var/reports/` und wird nicht veröffentlicht.

## systemd und Nginx

```bash
sudo cp deploy/systemd/brickmissing.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable brickmissing
sudo sed 's/BRICKMISSING_DOMAIN/example.com/g' deploy/nginx/brickmissing.conf | sudo tee /etc/nginx/sites-available/brickmissing >/dev/null
sudo ln -s /etc/nginx/sites-available/brickmissing /etc/nginx/sites-enabled/brickmissing
sudo nginx -t
sudo systemctl reload nginx
```

systemd führt ausschließlich `/var/www/brickmissing/current` aus. Gunicorn bindet an `127.0.0.1:8000`; nur Nginx veröffentlicht 80/443.

## Release bauen und atomar deployen

```bash
python3 scripts/build_release.py --output-root /tmp/brickmissing-release
sudo -u brickmissing ./scripts/deploy.sh /tmp/brickmissing-release/brickmissing-8.0.0
```

Das Script validiert das Artefakt, kopiert es in ein neues Release-Verzeichnis, verbindet `var` mit `shared/var`, installiert Abhängigkeiten und führt Check, Migration-Drift, Migrationsplan, Migration, Collectstatic und Deploy-Check **vor** Aktivierung aus. Erst dann wird `current` atomar gewechselt und der Dienst neu gestartet. Bei einem Fehler vor Aktivierung bleibt `current` unverändert. Bei fehlgeschlagenem Smoke-Test wird das vorherige Release atomar wieder aktiviert, der Dienst erneut gestartet und nochmals geprüft. Aktuelles und vorheriges funktionierendes Release müssen aufbewahrt werden; weitere alte Releases dürfen erst nach manueller Prüfung entfernt werden.

## HTTPS und Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo certbot --nginx -d example.com
sudo certbot renew --dry-run
```

Niemals 8000 oder 3306 öffentlich öffnen.

## Application Backup Restore

Das `.bm8`-Restore ist ein **Business-state snapshot with append-only security audit history**. Es stellt alle BrickMissing-Fachdaten und privaten Dateien auf den Snapshot-Zustand zurück. Security-Audit, Backup-Katalog, Sessions, Django-Admin- und Content-Type-Metadaten werden nicht zurückgedreht. Der Restore erzeugt danach ein neues Audit-Event. Das Verfahren prüft Hash, Verschlüsselung, Archivpfade, Symlinks, ausführbare Dateien, Größen und freien Speicher und verwendet staging plus Dateisystem-/DB-Rollback.

Restore erfolgt ausschließlich über die staffgeschützte Anwendung unter `/system/backups/` und verlangt das aktuelle Administratorpasswort.

## Full MariaDB Disaster Recovery

Ein SQL-Dump ist ein separates Infrastrukturverfahren, kein `.bm8`-Application-Restore. Es wird nur bei gestopptem Dienst, nach Prüfung von Ziel, Hash, Eigentümer und aktuellem Sicherheitsbackup durch den Serveroperator eingespielt. Das konkrete Dump-/Restore-Kommando hängt vom externen Backup-System ab und ist bewusst nicht mit dem Application-Restore vermischt.
