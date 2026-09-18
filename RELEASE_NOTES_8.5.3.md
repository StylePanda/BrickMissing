# BrickMissing 8.5.3

## Status-Speichern Hotfix

- Technischen JSON-Parserfehler beim Speichern eines Fehlteile-Status behoben.
- Erwartbare Validierungsfehler des Status-Endpunkts werden im AJAX-Workflow als JSON zurückgegeben.
- Die vorhandene fachliche Fehlermeldung erscheint verständlich im UI.
- Der Ladezustand von „Status speichern“ endet auch bei Fehlern zuverlässig.
- Abgelehnte Statusänderungen lassen Statusanzeige, Auswahl und Mengen unverändert.

Die fachliche Statusvalidierung und die Mengenlogik bleiben unverändert. Keine Migration oder neue Dependency.
