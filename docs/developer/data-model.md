# Datenmodell

## Katalog

`LegoSet` gehört über `owner` einem `accounts.User` und hat eine UUID. `set_number` ist zusammen mit `owner` für aktive Sets eindeutig: `active_set_number` wird beim Speichern aus der Setnummer gesetzt und beim Soft Delete geleert. `deleted_at` markiert ein Set im Papierkorb. Metadaten wie Name, Jahr, Wert und angezeigter Aufbaustatus liegen auf dem Set; die berechnete Vollständigkeit kommt aus Positionen.

`SetCopy` verweist auf ein `LegoSet`, besitzt einen eigenen `owner` sowie Inventarnummer, Zustand und Kaufdaten. Es repräsentiert ein physisches Exemplar, vervielfacht aber keine `SetInventoryItem`-Mengen. `SetInventoryItem` ist die normale Setposition mit `required_quantity`, `owned_quantity`, Farbe, Element-ID, Teilenummer und `is_spare`. Pro Set, Teilenummer, Farb-ID und Ersatzteilkennzeichen besteht eine Eindeutigkeitsregel.

`Part` ist ein nutzerbezogener, optional einem Set zugeordneter Einzelteil-/Workflow-Eintrag mit `quantity`, `owned_quantity`, `unassigned_found_quantity` und gespeichertem `status`. Er kann ein Spiegel einer Inventarposition sein. `PartHistory` protokolliert Statusänderungen. `Part` und `LegoSet` besitzen `deleted_at`; ihre üblichen Listen filtern gelöschte Einträge aus. Setexemplare haben ebenfalls ein Löschfeld, aber die hier sichtbare Exemplarbearbeitung führt keine eigene Papierkorbaktion aus.

## Figuren und weitere Bereiche

`SetMinifigure` gehört einem Benutzer und hat optional eine `lego_set`-Beziehung. `NULL` bedeutet eine lose/standalone Figur. Eine Setfigur ist über Besitzer, Set und Figurennummer eindeutig; lose Figuren können mehrfach als einzelne Objekte vorkommen. `MinifigurePart` verweist auf die Figur und speichert `quantity`, `owned_quantity`, Teil-/Element- und Farbangaben sowie `is_spare`. Ihre Fehlmenge wird je Position berechnet.

`Collection` und `CollectionMember` bilden Sammlungen und Rollen ab. `Moc`, `MocPart`, `MocVersion`, `WishlistItem`, `Loan`, `PersonalNote` und `LabelTemplate` decken Organisation ab. `WarehouseLocation`, `InventoryItem`, `InventoryMovement` modellieren das separate Lager; `Order` und `OrderItem` Bestellungen. `SavedView`, `RecentItem`, `DataQualityIssue`, `ImportBatch`, `PrivateDocument`, `BackupArtifact` und `AuditEvent` tragen Ansichten, Prüfungen und Betrieb.

## Ownership

Die meisten Stammmodelle besitzen einen direkten `owner`; abhängige Positionen werden über Set, Figur, Bestellung oder Lageritem eingegrenzt. Views filtern auf den angemeldeten Benutzer und prüfen Elternobjekte. Services validieren bei Schreiboperationen die Eigentümerschaft erneut. Ein fremder Primärschlüssel darf keine Zuordnung erzeugen. Die globale Backupfunktion ist hiervon getrennt und nur für Personal mit `backups.manage_backup` zugänglich. Soft Delete betrifft nur die entsprechend implementierten Modelle; ein endgültiges Löschen aus dem Papierkorb führt das normale kaskadierende Django-Löschen aus.
