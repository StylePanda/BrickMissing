# Statusworkflow

`Part.status` speichert einen von sechs Werten:

| Wert | UI | Fachliche Bedeutung |
| --- | --- | --- |
| `missing` | Fehlt | Offener Such-/Beschaffungsfall. |
| `found` | Gefunden | Besitzbezogener Fundstatus. |
| `ordered` | Bestellt | Beschaffung begonnen, kein Bestandszugang. |
| `shipped` | Versendet | Versand gemeldet, kein Bestandszugang. |
| `received` | Erhalten | Besitzbezogener Eingang. |
| `installed` | Eingebaut | Besitzbezogener Einbau. |

`effective_workflow_status` verändert den gespeicherten Wert nicht. Bei `authoritative_missing_quantity > 0` maskiert er `found`, `received` und `installed` als `missing`. `ordered` und `shipped` bleiben sichtbar. Statusänderungen über die Fehlteile-Views und `PartForm` werden gegen die Mengen geprüft; ein neuer Besitzstatus ist bei offener Fehlmenge unzulässig. Mengenänderungen über die Services können einen inkonsistenten Besitzstatus auf `missing` synchronisieren.

Der **Mengenstatus** ist davon getrennt. `stock_state` liefert **Nicht vorhanden**, **Teilweise vorhanden** oder **Vollständig vorhanden**. `group_quantity_status` liefert bei offener Gruppe **Fehlt** oder **Teilweise**; ohne Fehlmenge **Erhalten**. `missing_group_status` zeigt einen einheitlichen wirksamen Workflowstatus der Gruppenzuordnungen, sofern er nicht `missing` ist; bei gemischten oder fehlenden Statuswerten zeigt es den Mengenstatus. Derselbe Gruppenstatus steuert Badge und Statusfilter der Fehlteileansicht. Figurenteile besitzen keinen eigenen `Part.status` und werden dort rein mengenbasiert angezeigt.

Ein alter persistierter Wert `received`/`installed` darf damit eine offene maßgebliche Fehlmenge weder in der Karte noch im Filter als erledigt darstellen. Die lesende Diagnose `analyze_part_status` meldet solche Fälle zur manuellen Prüfung und korrigiert Statuswerte nicht pauschal. `reconcile_part_status` kann nur dafür vorgesehene sichere Korrekturen am redundanten Marker ausführen.
