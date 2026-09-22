# BrickMissing 8.5.6 – Release Notes

- Einzelne Rebrickable-Minifiguren lassen sich nach Name oder `fig-...`-Kennung suchen, ansehen und ohne Set hinzufügen.
- Bestandteile werden in die vorhandenen `MinifigurePart`-Zuordnungen importiert und zunächst gemäß dem Besitz einer vollständigen Figur als vorhanden markiert. Einzelne Mengen bleiben anschließend bearbeitbar.
- Lose Figuren erscheinen in der Minifiguren- und Fehlteileansicht, bleiben pro Besitzer getrennt und können einzeln gelöscht werden. Fehlende exportfähige Bestandteile fließen in die Fehlteile-CSV ein.
- Der vollständige JSON-Export und -Import übertragen lose Figuren und ihre Bestandsmengen. Mehrere gleiche lose Figuren bleiben getrennte Besitzinstanzen.
- Einzeln katalogisierte Varianten wie `71049-1` bis `71049-3` verwenden weiterhin den normalen Set-Workflow. Es wird kein Complete-Set automatisch angelegt.
- Rebrickable bleibt die einzige externe Datenquelle für diese Funktion; es gibt keine BrickLink-Abhängigkeit und keine Fake-Sets.
- Die neue optionale Set-Beziehung erfordert eine Migration. Die bestehende autoritative Mengenarchitektur bleibt erhalten.
