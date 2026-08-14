# Phase 7 – UI-QA-Matrix

Stand: 14.08.2026

| Bereich | 320 | 375 | 430 | 768 | 1024 | 1280 | 1440 | 1920 | 2560 |
|---|---|---|---|---|---|---|---|---|---|
| Navigation | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| Dashboard und Karten | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| Sets, Teile und Fehlteile | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| Suche und Filter | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| Formulare und Aktionen | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| Tabellen und Listen | Scroll | Scroll | Scroll | Scroll | OK | OK | OK | OK | OK |
| Administration | Stack | Stack | Stack | Stack | Stack | OK | OK | OK | OK |
| Konto und Sitzungen | Stack | Stack | Stack | Stack | OK | OK | OK | OK | OK |
| Dialoge und Bestätigungen | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| Empty States und Fehlerseiten | OK | OK | OK | OK | OK | OK | OK | OK | OK |

`Scroll` bedeutet einen kontrolliert horizontal scrollbaren Tabellenbereich ohne Seiten-Overflow. `Stack` bedeutet die vorgesehene einspaltige responsive Darstellung.

Automatisch geprüft: alle Django-Templates auf CSP-Verstöße, Navigation und Branding, Fehlerseiten, zentrale Design-Tokens, PWA-Manifest, Icon-Dateien und vollständige Django-Testsuite. Browser-QA der öffentlichen Account-Oberfläche erfolgte bei allen aufgeführten Breiten; geschützte Ansichten wurden über Render-/Funktions- und Responsive-Vertragstests geprüft.
