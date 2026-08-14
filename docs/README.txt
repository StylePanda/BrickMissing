BRICKMISSING PRO 6.1
====================

Neue lokale Funktionen:
- automatische Setdaten über Rebrickable
- Setinventar mit Filter, Sortierung und Fehlteile-Transfer
- Lagerbestand
- Bestellungsverwaltung
- Papierkorb und Wiederherstellung
- Mehrfachauswahl und Sammelstatus
- direkte Statusänderung per Klick
- Setsuche und Setfilter
- Bildzoom
- Kaufpreis und aktueller Sammlungswert
- Drag-and-Drop JSON-Import
- Tastenkürzel: Strg+N, Strg+S, Entf
- SQLite, automatische Backups, Dark/Light, Benutzer

Start: START_WEBSITE.bat
Rebrickable-Funktionen benötigen einen API-Key in Einstellungen.
Live-Preisvergleiche und Cloud-Synchronisation sind nicht ohne externe Anbieter-Konten möglich und daher nicht als scheinbar funktionierende Platzhalter eingebaut.


ANMELDUNG UND ERSTER START
--------------------------
- Beim Start erscheint zuerst die neue Anmeldeseite.
- Unter "Registrieren" kann ein normales Benutzerkonto erstellt werden.
- Normale Benutzer benötigen bei der Registrierung eine eindeutige
  E-Mail-Adresse. Administratoren benötigen keine E-Mail-Adresse.
- Bei der Anmeldung genügt ein gemeinsames Feld: normale Benutzer können
  Benutzername oder E-Mail-Adresse verwenden; Administratoren melden sich
  einfach mit ihrem Benutzernamen an.
- Es gibt keinen getrennten Admin-Login. Die Rolle wird nach erfolgreicher
  Anmeldung automatisch erkannt.
- Falls noch kein Administrator existiert, wird das erste über
  "Registrieren" angelegte Konto ohne E-Mail-Abfrage zum Administrator.
- Der bisherige Benutzer "Simon" kann bei der ersten Registrierung mit diesem
  Namen übernommen und mit einem Passwort abgesichert werden.
- Unter "Admin" wird einmalig das erste Administratorkonto eingerichtet.
  Danach dient derselbe Bereich zur Admin-Anmeldung.
- Passwörter werden nicht im Klartext gespeichert. In SQLite liegt nur ein
  PBKDF2-SHA256-Hash mit individuellem Salt und 310.000 Iterationen.
- Ein Passwort muss mindestens 8 Zeichen lang sein.
- Vom Administrator erstellte Konten erhalten ein temporäres Startpasswort.
  Nach der ersten Anmeldung wird der Benutzer automatisch zur Änderung dieses
  Passworts aufgefordert; andere Änderungen sind bis dahin gesperrt.
- Bestehende Konten ohne E-Mail-Adresse können beim nächsten erfolgreichen
  Login einmalig eine noch nicht verwendete Adresse hinterlegen.
- Darstellung und Rebrickable API-Key werden für jedes Benutzerprofil separat
  gespeichert. Beim Profilwechsel werden dessen Einstellungen geladen.
- Nur ein angemeldeter Administrator darf das Programm vollständig beenden.
  Für normale Benutzer ist die Schaltfläche ausgeblendet und der Serverzugriff
  auf die Beenden-Funktion gesperrt.
- Jeder Account benötigt einen eigenen Rebrickable API-Key. Schlüssel anderer
  Benutzer können auch von Administratoren weder gelesen noch verwendet oder
  überschrieben werden. Gespeicherte Schlüssel werden nie an den Browser
  zurückgesendet.
- Unter Einstellungen kann jeder Benutzer den eigenen API-Key entfernen und
  das eigene Passwort nach Prüfung des bisherigen Passworts ändern.
- Die Benutzerverwaltung befindet sich ausschließlich auf der separaten
  Admin-Seite. Normale Benutzer sehen weder die Seite noch einen Profilwähler.
- Administratoren können dort Benutzer anlegen, Sammlungen öffnen und Konten
  löschen. Das gerade angemeldete Administratorkonto ist gegen Löschen geschützt.


MEHRBENUTZER- UND SICHERHEITSERWEITERUNG
---------------------------------------
- Der Webserver bindet fest an 127.0.0.1 und ist ausschließlich auf demselben
  PC über http://127.0.0.1 beziehungsweise http://localhost erreichbar.
- Geräte im Heimnetz, VPN-Teilnehmer und externe Systeme können keine
  Verbindung zum BrickMissing-Webserver herstellen.
- Es werden keine lokalen HTTPS-Zertifikate und keine
  Windows-Firewallfreigaben benötigt oder erstellt.
- Sitzungs-Cookies verwenden HttpOnly und SameSite=Strict.
- Objektorientierte Services in app_core.py verwalten Konfiguration,
  Datenbankverbindungen, Passwörter, Sitzungen, Login-Sperren, Audit und Backups.
- Sitzungen werden serverseitig in SQLite gespeichert, laufen automatisch ab
  und verwenden CSRF-Sicherheitstoken.
- Nach fünf falschen Loginversuchen wird das Konto vorübergehend gesperrt.
- Administratoren können Benutzer deaktivieren, wieder aktivieren,
  wiederherstellen und temporäre Passwörter vergeben.
- Temporäre Passwörter müssen nach der Anmeldung geändert werden.
- Benutzerlöschung ist zunächst wiederherstellbar; Sammlungsdaten bleiben bis
  zur Wiederherstellung erhalten.
- Das Admin-Protokoll dokumentiert sicherheitsrelevante Aktionen ohne
  Passwörter oder API-Keys.
- API-Keys werden mit Fernet verschlüsselt gespeichert.
- Neue Datenbankbackups werden verschlüsselt als .db.enc abgelegt.
- data/.master.key ist für Entschlüsselung und Wiederherstellung zwingend
  erforderlich und muss separat gesichert werden.
- Der eigene Rebrickable API-Key kann vor Verwendung getestet werden.

Details zum Netzwerkbetrieb stehen in MEHRBENUTZER_SETUP.md.


E-MAIL-BESTÄTIGUNG
------------------
- Im Admin-Panel kann zwischen SMTP, der Resend-HTTPS-API und deaktiviertem
  E-Mail-Versand gewählt werden.
- Bei Resend werden nur Absenderadresse und API-Schlüssel benötigt. Die
  Absenderdomain muss zuvor beim Anbieter bestätigt werden. Optional kann im
  Admin-Panel ein sichtbarer Absendername festgelegt werden.
- Ist der E-Mail-Versand deaktiviert, blendet das Admin-Panel sämtliche
  Konfigurations- und Testfelder aus.
- Der Resend-API-Schlüssel wird verschlüsselt gespeichert und niemals an den
  Browser zurückgesendet. Die Integration benötigt keine zusätzliche
  Python-Bibliothek.
- Im Admin-Panel kann ein SMTP-Server mit Host, Port, Absender, Benutzer,
  Passwort und STARTTLS/SSL konfiguriert werden.
- "Automatisch erkennen" füllt anhand der Absenderadresse die verifizierten
  SMTP-Voreinstellungen für Gmail, Outlook/Hotmail, WEB.DE und Yahoo aus.
  Das SMTP- oder App-Passwort muss aus Sicherheitsgründen manuell eingegeben
  werden. Eigene und unbekannte Domains werden nicht geraten.
- Das SMTP-Passwort beziehungsweise der Resend-API-Schlüssel wird
  verschlüsselt in data/smtp.json gespeichert und niemals an den Browser
  zurückgesendet.
- Mit "Testmail senden" kann die Konfiguration vor der Verwendung geprüft
  werden.
- Normale Benutzer erhalten nach Selbstregistrierung oder Anlage durch einen
  Administrator automatisch eine E-Mail zur Bestätigung der Kontoerstellung.
- Die Nachricht enthält niemals ein Passwort.
- Falls SMTP nicht konfiguriert, deaktiviert oder vorübergehend nicht erreichbar
  ist, bleibt das Konto bestehen und der Fehler wird im Admin-Protokoll erfasst.


MARIADB-VERWALTUNG
------------------
- Die Auswahl zwischen SQLite und MariaDB/MySQL ist ausschließlich auf der
  Admin-Seite sichtbar. Normale Benutzer sehen keine Angaben zur Speicherart.
- Auf der Admin-Seite können Host, Port, Datenbank, Benutzer, Passwort und
  TLS-Nutzung einer MariaDB/MySQL-Datenbank konfiguriert werden.
- Das Datenbankpasswort wird verschlüsselt in data/mariadb.json gespeichert und
  niemals an den Browser zurückgesendet.
- Verbindung, Serverversion, Tabellen, Engines, Zeilenschätzungen und
  Speichergrößen können im Admin-Panel geprüft werden.
- Beim Speichern einer gültigen MariaDB-Konfiguration werden alle benötigten
  Tabellen automatisch aus dem Anwendungsschema erzeugt und sämtliche
  vorhandenen SQLite-Daten übertragen.
- Nach erfolgreichem Verbindungstest und der einmaligen Migration ist MariaDB
  die primäre Datenbank. Alle Lese- und Schreibzugriffe erfolgen direkt dort.
- Die Aktivierung wird erst gespeichert, nachdem Schema und SQLite-Bestand
  erfolgreich nach MariaDB übertragen wurden.
- SQLite bleibt als lokaler Fallback und als Zwischenformat für verschlüsselte
  Sicherungen erhalten. Vor einem Backup wird es aus MariaDB aktualisiert.
- Fehlt data/.master.key bei bereits verschlüsselten Daten, bricht der Start
  sicher ab. Es wird niemals still ein unpassender neuer Schlüssel erzeugt.


VERSION 6.1
-----------
- Der Haken im Tabellenkopf der Fehlteile markiert jetzt alle aktuell sichtbaren Teile.
- Filter und Suche werden berücksichtigt: Es werden nur die sichtbaren Zeilen ausgewählt.
- Teilweise Auswahl wird im Tabellenkopf als Zwischenzustand dargestellt.
- Im Papierkorb werden Bilder von Sets und Fehlteilen angezeigt.
- Der Papierkorb zeigt Zähler für gelöschte Sets und Teile.
- Neuer Button „Papierkorb leeren“.
- Vor dem endgültigen Löschen erscheint eine deutliche Sicherheitsabfrage.
- Endgültiges Leeren entfernt nur Papierkorb-Inhalte des aktuell ausgewählten Benutzers.
