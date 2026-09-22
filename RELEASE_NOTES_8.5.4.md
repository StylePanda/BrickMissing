# BrickMissing 8.5.4

BrickMissing 8.5.4 härtet die Mengenkonsistenz zwischen Fehlteile-Seite und CSV-Export ab.

Der untersuchte Fall `30237a`/Set `7744` ist eine unterschiedliche Aggregationsebene: Die sichtbare Karte ist nach Teile-Identität und Farbe gruppiert und zeigt für Set 7744 `7 benötigt`, `6 vorhanden`, `1 fehlend`. Die bestehende zweispaltige CSV aggregiert dagegen global nach dem ausgegebenen `elementId`-Wert. Bei blanker autoritativer Element-ID wird gemäß bestehender Matching-Semantik die Design-/Part-Identität `30237a` verwendet; weitere offene Zuordnungen desselben Export-Identifiers ergeben im reproduzierten Fall zusätzlich `2 + 1`, also CSV-Gesamtmenge `4`.

Der Hotfix führt die farbisolierte Voraggregation beider Pfade zusammen, verhindert doppelte Zählung historischer Part-Mirrors und gleicht den Ausschluss gelöschter Sets an. CSV-Header, Spalten, Reihenfolge, Encoding und Format bleiben unverändert.

Keine Datenbankmigration, keine neue Dependency und keine automatische Datenreconciliation.

Die manuelle Produktionsvalidierung bleibt ausstehend.
