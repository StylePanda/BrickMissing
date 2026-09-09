# BrickMissing 8.1.2

## Fehlerbehebungen

- Der Filter **Fehlende Farben** in der Set-Liste löst ausgewählte Farben zuverlässig auf die tatsächlich gespeicherten Farbwerte auf.
- Der Filter verwendet weiterhin ausschließlich die autoritativen Set- und Minifiguren-Allokationen; mehrere Farben bleiben ODER-verknüpft.
- Der sichtbare Gruppenstatus stimmt jetzt mit benötigter, vorhandener und fehlender Menge überein.
- **Erhalten** wird nicht mehr angezeigt, solange in der dargestellten Gruppe eine benötigte Menge fehlt.
- Status- und Mengenänderungen können keine neue widersprüchliche Besitzstatus-/Fehlmengen-Kombination erzeugen.

## Technisch

- Keine Datenbankmigration.
- Keine Änderung an Benutzer-, Set- oder Spare-Isolation.
- Die bestehende Owned-Quantity-Reconciliation und die zentralen Farbgruppen bleiben die fachlichen Quellen.
- Der dependency-freie Release-Build aus BrickMissing 8.1.1 bleibt erhalten.
