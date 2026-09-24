# Teile und Bestand

## Drei Arten von Mengen

**Benötigte Menge** ist das Soll, **Vorhandene Menge** das Ist. Die offene Fehlmenge wird je Position als `max(benötigt − vorhanden, 0)` berechnet. **Nicht zugeordnete Fundmenge** eines einzelnen Teile-Eintrags ist ein zusätzliches Merkmal und ersetzt keine Zuordnung zu einem Setinventar.

Es gibt getrennte Bereiche:

| Bereich | Inhalt |
| --- | --- |
| **Set-Inventar** im Setdetail | Normale Setteile und Ersatzteile mit Soll-/Ist-Mengen. |
| **Minifigurenbestandteile** | Bestand je Bestandteil einer Figur. |
| **Teile** | Manuelle Einzelteile und gegebenenfalls Workflow-Einträge zu Setpositionen. |
| **Inventar** | Eigenes Lager mit Lagerorten, Reservierungen und Bewegungen; die Menge ist nicht automatisch die Set-Soll-/Ist-Menge. |

Wenn ein **Teil** genau zu einer Set- oder Minifigurenposition passt, zeigt die Anwendung deren Mengen als maßgeblich an. Bei mehreren passenden Positionen werden die Mengen für die Anzeige addiert. Eine Bestandsänderung über diesen einzelnen Teile-Eintrag ist dann nicht eindeutig und wird abgewiesen; ändere die konkrete Inventarposition. Lose Teile ohne passende Position verwenden ihre eigenen Mengen.

In **Teile** kannst du nach Nummer, Name oder Farbe suchen und nach gespeichertem Workflowstatus filtern. Sortierungen sind Name, Element-ID, Farbe, Menge, letzte Änderung sowie **Größe/Form – aufsteigend/absteigend**. Die Größe/Form-Sortierung wertet erkennbare Maße im Teilenamen aus. Teile ohne lesbare Größe stehen in beiden Richtungen hinten; Form und Name lösen Gleichstände auf. Die Sortierung ändert keine Daten.

**Inventar** und **Lagerorte** verwalten gesonderte Lagerbestände. Reservierte Mengen verringern den verfügbaren Lagerbestand. Sie sind kein automatischer Abgleich mit den Soll-/Ist-Positionen eines LEGO-Sets.
