# BrickMissing nur auf diesem PC

BrickMissing ist bewusst ausschließlich über die lokale Loopback-Adresse
erreichbar. Andere PCs, Geräte im Heimnetz, VPN-Teilnehmer und Systeme aus dem
Internet können keine Verbindung zum Webserver herstellen.

## Start

1. `START_WEBSITE.bat` auf diesem PC ausführen.
2. Django läuft lokal auf `http://127.0.0.1:8000`.
3. Alternativ kann auf demselben PC `http://localhost:8000` verwendet werden.

Falls der Standardport belegt ist, wählt die Anwendung den nächsten freien Port
und zeigt die vollständige lokale Adresse im Serverfenster an.

## Netzwerksicherheit

- Der Server bindet fest an `127.0.0.1`.
- Umgebungsvariablen können diese Bindung nicht auf eine Netzwerkadresse ändern.
- Es ist keine eingehende Windows-Firewallfreigabe erforderlich.
- Im Router darf keine Portweiterleitung eingerichtet werden.
- Lokale HTTPS-Zertifikate werden nicht erstellt oder verwendet.

Die Anwendung stellt weiterhin ausgehende HTTPS-Verbindungen zu ausdrücklich
konfigurierten Diensten wie Rebrickable oder Resend her. Diese ausgehenden
Verbindungen machen den lokalen Webserver nicht von anderen Geräten erreichbar.

## Sicherheitsdatei

`data/.master.key` verschlüsselt API-Schlüssel und Backups. Diese Datei muss
zusammen mit den verschlüsselten Backups sicher aufbewahrt werden. Sie darf
niemals veröffentlicht oder an andere Personen weitergegeben werden.

## Datenbank

SQLite und MariaDB/MySQL können weiterhin verwendet werden. Eine konfigurierte
MariaDB kann technisch auf einem anderen Datenbankserver liegen; der
BrickMissing-Webserver selbst bleibt trotzdem ausschließlich über localhost
erreichbar.
