# Maßgebliche Mengenlogik

## Quellen und Formeln

`SetInventoryItem.required_quantity` und `.owned_quantity` sind die Soll-/Ist-Werte einer normalen Setposition. `MinifigurePart.quantity` und `.owned_quantity` erfüllen dieselbe Rolle für Figurenbestandteile. Beide haben eine `missing_quantity`-Eigenschaft mit `max(required − owned, 0)`. `Part.quantity`, `.owned_quantity` und `.missing_quantity` gelten direkt nur, wenn keine passende maßgebliche Position gefunden wird.

`with_authoritative_missing_quantity(queryset)` annotiert `Part` mit `authoritative_required_quantity`, `authoritative_owned_quantity` und `authoritative_missing_quantity`. Die Zuordnung verlangt dasselbe aktive Set, denselben Besitzer und exakt dieselbe Farbe; Ersatzteile sind ausgeschlossen. Nicht leere Element-IDs haben je Quellart Vorrang. Falls dort kein Treffer besteht, dürfen Positionen ohne Element-ID über ihre exakte `part_number` mit `Part.design_id`, `.part_number` oder `.element_id` übereinstimmen. Normalinventar und Figurenbestandteile werden jeweils berücksichtigt.

Bei mehreren passenden Positionen werden Soll und Ist addiert. Die Fehlmenge wird **zuerst pro Position auf mindestens null begrenzt und dann addiert**: `Σ max(required_i − owned_i, 0)`. Daher ist sie nicht zwingend `max(authoritative_required_quantity − authoritative_owned_quantity, 0)`, falls historische Überbestände vorkommen. Gibt es keine Zuordnung, lauten die drei Werte `Part.quantity`, `Part.owned_quantity` und `max(quantity − owned_quantity, 0)`.

## Schreiben

`set_authoritative_owned_quantity(kind, allocation, quantity, actor)` schreibt eine bekannte Set- oder Figurenposition unter Transaktion und aktualisiert eindeutige `Part`-Spiegel samt Vorhanden-Marker und konsistentem Workflowstatus. Die Eingabe muss zwischen 0 und dem Soll der Position liegen. `set_part_owned_quantity(part, quantity, actor)` sucht die maßgebliche Position. Bei genau einem Treffer schreibt es dorthin und zum Spiegel; bei mehreren Treffern bricht es wegen Mehrdeutigkeit ab. Ohne Treffer schreibt es auf `Part`.

`Part.is_present` ist ein redundanter Marker aus `owned_quantity + unassigned_found_quantity > 0`; er ist nicht die Quelle der Fehlmenge. Rebrickable-Sync ändert Soll-/Referenzdaten und lässt Bestände im Normalfall bestehen. Die spezielle Erst-Synchronisation eines als neu gekauft markierten Sets setzt anschließend die importierten Positionen auf vorhanden.

## Aggregation und CSV

Setvollständigkeit addiert erforderliche normale `SetInventoryItem`- und `MinifigurePart`-Positionen desselben Besitzers; Ersatzteile und Positionen mit Soll 0 zählen nicht. Ohne erforderliche Positionen ist das Ergebnis `unknown`. Die Fehlteileansicht gruppiert annotierte `Part`-Einträge nach Teilidentität und Farbe. Spiegel desselben Setinventars werden innerhalb einer Gruppe nicht mehrfach gezählt. Figurenteile erscheinen zusätzlich aus ihren eigenen Positionen; überlappende `Part`-Spiegel werden in der Ansicht entfernt.

Der LEGO-CSV-Export benutzt `authoritative_lego_export_parts` und `authoritative_lego_export_rows`. Er nimmt aktive `Part`-Einträge mit gespeichertem Status `missing`, Element-ID und offener maßgeblicher Fehlmenge sowie lose Figurenteile mit Element-ID. Die UI-Gruppierung bleibt farbgetrennt, die CSV summiert danach nach `elementId`. Die CSV ist deshalb nicht die vollständige Setinventarliste. Das separate Lager (`InventoryItem`) ist keine Quelle dieser authoritative Setmengen.

Für vorhandene Abweichungen zwischen `Part` und Positionen gibt es lesende Audits und explizite Reconciliation-Kommandos. Eine Dokumentationsversion führt keine solche Korrektur aus.
