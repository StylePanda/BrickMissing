# Import und Export

Unter **Import & Export** stehen drei verschiedene Datenwege bereit:

| Aktion | Zweck und Grenzen |
| --- | --- |
| **Alle Sets und Teile als JSON** | Exportiert kontoeigene Set- und Teilefelder sowie Minifiguren mit Bestandteilen im Format `brickmissing-8`. Dies ist kein vollständiger personenbezogener Datenexport und enthält zum Beispiel nicht alle Setinventar-, Organisations- und Lagerdaten. |
| **LEGO-Fehlteile als CSV exportieren** | UTF-8-CSV mit `elementId,quantity`; exportiert offene, als **Fehlt** gespeicherte Teil-Einträge mit Element-ID und zusätzlich lose Minifigurenbestandteile mit Element-ID. Optional nach verfügbaren Farben einschränkbar. Gleiche Element-IDs werden über Farben summiert. |
| **Meine Daten exportieren** im Profil | Separater personenbezogener Export nach Bestätigungswort und gegebenenfalls Passwort. |

Für die LEGO-CSV wird pro Inventarposition zuerst die offene Menge ermittelt; ein Überschuss an anderer Stelle gleicht sie nicht aus. Ein fehlender Element-ID-Wert ist nicht exportierbar. Die CSV ist ein einfaches Übergabeformat, keine automatische Bestellung bei LEGO oder BrickLink.

## Import

**JSON importieren** akzeptiert `brickmissing-8` oder `brickmissing` mit Sets, Teilen und optional Minifiguren. **CSV / BrickLink importieren** akzeptiert unterstützte UTF-8-Spalten für Teile. Für beide gilt höchstens 5 MiB. Zuerst erscheint eine **Importvorschau** mit Validierungsfehlern und Duplikaten, dann bestätigst du den Import. Die Strategien **SKIP**, **UPDATE**, **MERGE** und **ERROR** steuern den Umgang mit Duplikaten; bei Teilen addiert MERGE Mengen, bei Sets werden nicht leere Felder übernommen. Die Übernahme läuft in einer Datenbanktransaktion und nur für dein Konto. Sie stellt nicht jeden Datenbereich aus dem JSON-Export wieder her. Der Export enthält auch Papierkorb-Einträge; der Import wertet deren `deleted_at`-Markierung nicht aus. Ein Wiederimport kann solche Sets oder Teile daher als aktive Einträge anlegen.

**LEGO-Datei mit nicht verfügbaren Teilen analysieren** nimmt CSV oder JSON mit genau `elementId`, `quantity`, `error` entgegen (höchstens 2 MiB). Die Funktion vergleicht Element-IDs mit deinen Teilen und zeigt Treffer, ohne den Bestand zu ändern.
