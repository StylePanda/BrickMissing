# BrickMissing 8.6.0

BrickMissing ist eine Django-Anwendung zur Verwaltung einer LEGO-Sammlung. Sets, Exemplare, Soll-/Ist-Teile, Minifiguren und Fehlteile gehören zu persönlichen Benutzerkonten. Für automatische Set- und Figurendaten kann ein eigener Rebrickable API-Key hinterlegt werden.

## Funktionen

- Sets und Varianten, mehrere physische Exemplare, Setinventar und berechnete Vollständigkeit
- Teile- und Fehlteileverwaltung mit Mengen, Workflowstatus, Filtern und Größe/Form-Sortierung
- Set- und lose Minifiguren mit Bestandteilen; Rebrickable-Synchronisation
- Wunschliste, Sammlungen, MOCs, Lagerorte, Inventar, Bestellungen und Etiketten/QR-Codes
- JSON-/CSV-Import und -Export, persönliche Datenkopie, Konto-/Datenschutzfunktionen und administrative Backups

## Lokal entwickeln

Python 3.12 bis 3.14; die Entwicklung nutzt `var/development.sqlite3`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\development.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\ruff.exe check .
```

## Dokumentation

- In der laufenden BrickMissing-Anwendung unter `/docs/` mit Benutzeranleitung und Entwicklerbereich
- [Markdown-Quellen](docs/index.md) und [Entwickler-Quellen](docs/developer/index.md); diese Dateien werden direkt für die Webansicht gerendert

Der produktive Django-Pfad verwendet Nginx, Gunicorn und MariaDB. Release-Artefakte werden mit `scripts/build_release.py` gebaut und mit `scripts/verify_release.py` geprüft. Historische Migrations- und Auditnotizen liegen ebenfalls unter `docs/`; die aktuelle Funktionsbeschreibung beginnt bei `docs/index.md`.
