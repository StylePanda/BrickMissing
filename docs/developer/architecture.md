# Architektur und Datenfluss

`manage.py` startet das Django-Projekt in `config/`. `config/settings/base.py` enthält gemeinsame Einstellungen, `config/settings/development.py` nutzt eine lokale SQLite-Datenbank, `config/settings/production.py` verlangt MariaDB und explizite Sicherheitsvariablen. `config/urls.py` bindet die App-Routen ein; `templates/` enthält serverseitig gerenderte Seiten, `static/js/` ergänzt Interaktion, Filter, Mengenaktualisierung, Batch-Sync und Druckvorschau. `frontend/`, `brickmissing/` und `server.py` enthalten zusätzlich einen älteren Runtimepfad; die V8-Webanwendung wird über Django/WSGI ausgeliefert.

| App | Verantwortung |
| --- | --- |
| `accounts`, `legal` | Konten, Anmeldung, 2FA, Profil, Datenschutz- und Rechtstexte. |
| `catalog` | Sets, Exemplare, Setinventar, Teile, Fehlteile, Mengen- und Statusableitung. |
| `organizer` | Minifiguren, MOCs, Sammlungen, Wunschliste, Ausleihen, Notizen, Labels. |
| `inventory`, `orders` | Eigenes Lager mit Bewegungen und Bestellungen/Wareneingang. |
| `integrations` | Rebrickable, Anleitungen, Preisdienste und Bildabruf. |
| `data_portability` | JSON-/CSV-Import, Exporte, persönliche Datenkopie und LEGO-Fehlerdateianalyse. |
| `backups`, `media_library` | Verschlüsselte Anwendungsbackups und private Dokumente. |
| `core`, `audit` | Startseite, Suche, gespeicherte Ansichten, Datenqualität, Middleware und Audit-Ereignisse. |

Typischer Datenfluss: Eine authentifizierte View filtert nach `request.user`, validiert ein Formular oder eine Aktion, ruft einen Service auf, schreibt transaktional und protokolliert ein `AuditEvent`. Setinventar und Minifigurenbestandteile liefern maßgebliche Mengen; `catalog.services.with_authoritative_missing_quantity` versieht Teile-Einträge für Anzeigen und CSV mit abgeleiteten Mengen. `catalog.part_status` berechnet Workflow- und Gruppenanzeigen. Rebrickable-Antworten werden in `integrations.rebrickable_sync` auf Referenzpositionen abgebildet; vorhandene Nutzerbestände bleiben bei regulärem Sync erhalten.

Middleware ergänzt Request-IDs, Sicherheitsheader, Wartungs- und Sitzungsprüfung. Die UI verwendet Django-Templates; JavaScript unterstützt Inline-Bestand, responsive Navigation, Etikettenvorschau und Rebrickable-Sammelaktionen. Jede mutierende Funktion muss serverseitig validiert werden, unabhängig vom JavaScript.
