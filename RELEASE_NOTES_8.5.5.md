# BrickMissing 8.5.5

Die Größe/Form-Sortierung wurde vollständig auf eine globale Schätzung der physischen Ausdehnung umgestellt. Beide Richtungen auf /teile/ und /fehlteile/ verwenden denselben zentralen Python-Helper.

- Längste Ausdehnung, Footprint und erkennbare Höhe bestimmen gemeinsam die Größenbewertung; Form dient nur noch bei gleichem Score als Tie-Breaker.
- Der Parser erkennt 2D- und 3D-Maße, Bruchmaße und Technic-Längen (L). Lokal belegte Reifen- und Radmaße in Millimetern werden in Stud-Einheiten umgerechnet.
- Große Wings, Panels, Fahrzeug-Bases und Spezialteile werden global nach ihrer Ausdehnung eingeordnet.
- Unbekannte Größen stehen auf- und absteigend am Ende; Identität und Farbe sind nur stabile Tie-Breaker.
- Keine Änderung an Mengen, Gruppierung, Status oder Daten. Sortierung bleibt read-only; keine Migration, neue Dependency oder Netzwerkanfrage.
