# Erste Schritte

## Was BrickMissing verwaltet

Die Startseite zeigt Kennzahlen deiner Sammlung und Verknüpfungen zu **Sets**, **Teile**, **Fehlteile**, **Minifiguren**, **Import & Export** und **Papierkorb**. Daten werden einem Benutzerkonto zugeordnet. Ein Set kann ein Soll-/Ist-Inventar, Minifiguren und mehrere physische Exemplare besitzen.

## Konto einrichten

1. Über **Registrieren** ein Konto mit Benutzername, E-Mail und Passwort anlegen.
2. Den Link in der Bestätigungsmail öffnen und danach **Anmelden**.
3. Unter **Konto / Profil** bei Bedarf einen Rebrickable API-Key speichern und mit **Verbindung testen** prüfen.

Ohne Rebrickable-Key kannst du Sets und Teile manuell anlegen. Automatische Setinformationen, Setinventare, die Wunschlistenvalidierung sowie die Suche nach losen Minifiguren benötigen den Key. Die lokale Entwicklung verwendet standardmäßig eine Konsolen-E-Mail-Ausgabe; der Betreiber muss für echte Zustellung eine E-Mail-Konfiguration eingerichtet haben.

## Erste Sammlung

Unter **Sets** → **Set hinzufügen** Setnummer und Stammdaten eingeben. Im Setdetail kannst du **Soll-/Ist-Teile** manuell hinzufügen oder mit Rebrickable synchronisieren. Pflege anschließend **Vorhandene Menge** je Inventarposition; daraus ergibt sich die Fehlmenge. **Fehlteile** zeigt offene Positionen und ihren Bearbeitungsstatus. [Sets im Detail](sets.md) · [Mengen verstehen](parts.md).

Die Oberfläche ist für Desktop und kleinere Bildschirme ausgelegt. Die Anzeige passt sich an; eine installierbare Web-App und ein Service Worker sind vorhanden, aber für die normalen Arbeitsabläufe ist eine Verbindung zur Anwendung erforderlich.
