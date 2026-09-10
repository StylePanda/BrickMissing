# BrickMissing 8.2.0

## Neue Funktionen

- Neue Sortierung **Größe/Form** für Teile und Fehlteile.
- Aufsteigende und absteigende Größensortierung innerhalb stabiler Formfamilien.
- Ähnliche Teile werden anhand vorhandener standardisierter Teilenamen, zuverlässig erkennbarer Dimensionen und stabiler Teile-IDs sinnvoll gruppiert.
- Besonders praktisch beim Abarbeiten physisch nach Farben sortierter LEGO-Teile.

## Fehlerbehebungen

- Der Filter **Fehlende Farben** in der Set-Liste ist über dieselbe Feldstruktur und korrekt auf das jeweilige `details` begrenzte Abstände sauber ausgerichtet – geschlossen und geöffnet.

## Technisch

- Die bestehende autoritative Mengen- und Gruppenstatuslogik bleibt unverändert.
- Die neue Sortierung führt keine Datenmutation oder externe API-Abfrage aus.
- Keine neue Dependency und keine Datenbankmigration.
