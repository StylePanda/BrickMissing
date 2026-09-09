# BrickMissing-Versionierung

Die aktuelle Produktversion steht ausschließlich in `brickmissing_version.py`. Das neutrale Top-Level-Modul hat keine Runtime-Abhängigkeiten und kann deshalb auch von Release-Skripten mit einem nackten System-Python gelesen werden. Vor jedem produktiven Update muss bewusst geprüft werden, ob diese Versionsnummer geändert werden muss. Ein produktives Update darf nicht versehentlich mit derselben Versionsnummer ausgeliefert werden.

BrickMissing verwendet `MAJOR.MINOR.PATCH`, zum Beispiel `8.1.3`:

- `MAJOR`: nur für große, grundlegende Versionssprünge erhöhen (`8.x.x` → `9.0.0`). `MINOR` und `PATCH` werden auf `0` zurückgesetzt.
- `MINOR`: für mittelgroße Funktionsupdates oder relevante neue Features erhöhen (`8.0.5` → `8.1.0`). `PATCH` wird auf `0` zurückgesetzt.
- `PATCH`: für Hotfixes, Bugfixes und kleine Korrekturen erhöhen (`8.1.0` → `8.1.1`).

Release-Skripte, Backend, Healthcheck, UI, Export-Metadaten und externe User-Agents lesen die zentrale Version. Historische Changelog-Einträge und Migrationen werden nicht rückwirkend geändert.
