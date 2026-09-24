# Fehlteile und Status

Die Seite **Fehlteile** zeigt offene Mengen. Mehrere gleiche Teile werden für die Ansicht nach Identität und Farbe gruppiert; gleiche Positionen aus mehreren Sets können gemeinsam erscheinen. Minifigurenbestandteile erscheinen aus ihrem eigenen Bestand. Offene Setinventarpositionen benötigen für die normale gruppierte Teilansicht einen passenden **Teil**-Eintrag; **Alle fehlenden zur Fehlliste** im Setdetail erstellt solche Einträge. Minifigurenbestandteile werden direkt angezeigt.

## Mengenstatus und Workflow

| Anzeige | Bedeutung |
| --- | --- |
| **Fehlt** | Von der benötigten Menge ist nichts vorhanden. |
| **Teilweise** | Ein Teil der benötigten Menge ist vorhanden. |
| **Erhalten** | In einer Mengenanzeige ist keine Fehlmenge offen. |

Ein **Teil** hat zusätzlich einen gespeicherten Bearbeitungsstatus: **Fehlt**, **Gefunden**, **Bestellt**, **Versendet**, **Erhalten**, **Eingebaut**. **Bestellt** und **Versendet** beschreiben die Beschaffung; sie erhöhen den Bestand nicht. **Gefunden**, **Erhalten** und **Eingebaut** setzen für eine neue Statusänderung voraus, dass keine Fehlmenge offen ist. Ein alter gespeicherter Besitzstatus bei offener Fehlmenge wird in der Fehlteileansicht als **Fehlt** wirksam. Der sichtbare Gruppenstatus und der Statusfilter folgen derselben Ableitung. Gemischte Gruppen verwenden den Mengenstatus, damit der Status einer einzigen Position nicht die ganze Gruppe bestimmt. Minifigurenbestandteile verwenden nur ihren Mengenstatus.

Du kannst nach Text, Farbe, Set, Teilart, benötigter Häufigkeit, Mindestfehlmenge, **Status** und **Bestand** filtern. Der Bestandsfilter meint **Nicht vorhanden** oder **Teilweise vorhanden**; die Seite enthält nur offene Fehlmengen. Sortierungen umfassen Name, Teilenummer, Farbe, Mengen, Setnummer und **Größe/Form**. Über einzelne Teilkarten oder die Sammelaktion lässt sich der Workflowstatus ändern; die benötigte und vorhandene Menge pflegst du separat. Ein Gruppenstatus ist keine Bestellung und keine automatische Bestandsbuchung.

Der **Papierkorb** enthält gelöschte Sets und manuelle Teile. Gelöschte oder zu gelöschten Sets gehörende Teile werden nicht als aktuelle Fehlteile behandelt.
