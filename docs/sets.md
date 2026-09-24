# Sets und Exemplare

## Set hinzufügen

Unter **Sets** stehen **Set hinzufügen**, **Neu gekauftes Set hinzufügen** und **Mehrere neue Sets hinzufügen** bereit. Die Setnummer wird für Rebrickable bei Bedarf um die Variante `-1` ergänzt; eine bereits angegebene Endung bleibt erhalten. Verschiedene Varianten wie `123-1` und `123-2` sind eigenständige Sets. Eine aktive Setnummer kann pro Konto nur einmal gespeichert werden.

Mit hinterlegtem Rebrickable-Key lädt das Setformular Metadaten zur Nummer. Die Aktion **Rebrickable synchronisieren** im Setdetail lädt Setstammdaten, normale Teile, Minifiguren und deren Bestandteile. Die Mehrfachanlage prüft Nummern in einer Vorschau, importiert neue Sets einzeln und markiert ihre importierten Positionen als vorhanden. Eine reguläre Synchronisation aktualisiert Referenzmengen und lässt vorhandene Bestände grundsätzlich bestehen. Bei **Neu gekauftes Set hinzufügen** werden beim ersten anschließenden Einzel-Sync alle importierten Positionen als vorhanden markiert. Das gilt nicht für den Sammel-Sync bestehender Sets.

## Verwalten

Das Setdetail bietet Stammdaten, **Set-Inventar**, Minifiguren und **Setexemplare**. **Setexemplar hinzufügen** erfasst ein weiteres physisches Exemplar mit eigener Inventarnummer, Zustand, Kaufdaten und Notizen. Die Setinventar-Mengen sind im Datenmodell dem Set zugeordnet; sie werden nicht automatisch pro Exemplar vervielfacht. Wer mehrere Exemplare verwaltet, muss diese Unterscheidung bei der Bestandsführung beachten.

Im Inventar kannst du nach Teilnummer, Element-ID, Name und Farbe suchen, nach **Normale Teile** oder **Ersatzteile**, Farbe und **Bestandsstatus** filtern und nach Name, Teilenummer, Farbe oder Mengen sortieren. **Bestand gesammelt bearbeiten** setzt alle Positionen auf **Alle vorhanden** oder **Alle fehlend**. **Alle fehlenden zur Fehlliste** legt für fehlende normale Positionen passende Teil-Einträge an; fehlende Minifigurenbestandteile werden bereits aus ihrem Bestand in der Fehlliste angezeigt. [Mengen und Bestände](parts.md).

Die Setliste filtert nach Suche, **Themenwelt**, **Vollständigkeit** und **Fehlende Farben**. **Unvollständige Sets** enthält auch Sets ohne auswertbares Inventar, denn diese gelten als **Unbekannt**. Sortierung: neueste, Setnummer, Name, Jahr oder Wert. Die berechnete Vollständigkeit verwendet erforderliche normale Setteile und Minifigurenbestandteile, keine Ersatzteile. Sie ist unabhängig von einem manuell gespeicherten Vollständigkeitsfeld.

**Löschen** verschiebt ein Set in den **Papierkorb**. Dort ist Wiederherstellen oder endgültiges Löschen möglich. Ein Set mit gleicher Nummer lässt sich nach dem Verschieben neu anlegen; eine Wiederherstellung kann dann mit der Eindeutigkeitsregel kollidieren.
