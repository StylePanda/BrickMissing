# Häufige Fragen und Sonderfälle

## Warum ist mein Set „Unbekannt“ oder im Filter „Unvollständige Sets“?

Ohne erforderliche normale Inventarpositionen oder Minifigurenbestandteile ist Vollständigkeit nicht beweisbar. Der Übersichtsfilter zählt solche Sets zur nicht vollständigen Gruppe. Ersatzteile zählen für die Berechnung nicht.

## Warum steht „Erhalten“ nicht auf der Fehlteilekarte?

Eine offene maßgebliche Fehlmenge hat Vorrang vor einem älteren gespeicherten Besitzstatus. Prüfe die **Vorhandene Menge** der konkreten Set- oder Minifigurenposition. [Statusregeln](missing-parts.md).

## Warum lässt sich die Menge eines Teils nicht ändern?

Ein einzelner Teile-Eintrag kann mehreren passenden Inventarpositionen entsprechen. Dann wäre eine Zuordnung der Eingabe mehrdeutig; ändere die Position im Set- oder Figureninventar. Werte oberhalb der benötigten Menge werden ebenfalls abgewiesen.

## Warum fehlen Setteile im CSV-Export?

Für die LEGO-CSV sind eine Element-ID, eine offene Menge und bei normalen Teilen ein als **Fehlt** gespeicherter Teile-Eintrag erforderlich. Lose Minifigurenbestandteile werden aus ihrem eigenen Bestand aufgenommen. Die CSV enthält nur `elementId` und `quantity`.

## Warum liefert Rebrickable nichts?

Prüfe unter **Konto / Profil** den API-Key mit **Verbindung testen** und die Setnummer samt Variante. Rebrickable kann einen Schlüssel ablehnen, einen Datensatz nicht kennen, vorübergehend nicht erreichbar sein oder Anfragen begrenzen.

## Sichert der JSON-Export alles?

Nein. Er enthält den implementierten Set-/Teile-/Minifiguren-Ausschnitt. Für personenbezogene Daten nutze **Meine Daten exportieren**; für eine administrative Anwendungssicherung ist **Backups** zuständig.
