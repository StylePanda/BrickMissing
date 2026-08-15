from dataclasses import dataclass

from apps.catalog.models import Part

WORKFLOW_STATUS_LABELS = dict(Part.Status.choices)
MIXED_STATUS = "mixed"
MIXED_STATUS_LABEL = "Gemischt"


def workflow_status_label(status):
    return WORKFLOW_STATUS_LABELS.get(status, status or "–")


def stock_state(quantity, owned_quantity):
    if owned_quantity <= 0:
        return "none", "Nicht vorhanden"
    if owned_quantity >= quantity:
        return "complete", "Vollständig vorhanden"
    return "partial", "Teilweise vorhanden"


def expected_is_present(part):
    return part.owned_quantity + part.unassigned_found_quantity > 0


def synchronize_presence_marker(part):
    part.is_present = expected_is_present(part)
    return part


def group_workflow_status(statuses):
    values = set(statuses)
    if len(values) == 1:
        status = values.pop()
        return status, workflow_status_label(status)
    if values:
        return MIXED_STATUS, MIXED_STATUS_LABEL
    return "none", "Kein Workflowstatus"


@dataclass(frozen=True)
class PartStatusFinding:
    category: str
    title: str
    expected_status: str
    proposed_change: str
    safe_apply: bool = False
    field: str = ""
    value: object = None


def analyze_part_status(part):
    findings = []
    if part.status == Part.Status.FOUND and part.owned_quantity == 0:
        findings.append(PartStatusFinding(
            "A", "Gefunden bei Bestand 0", "MANUAL REVIEW",
            "Workflowstatus oder Menge fachlich prüfen; keine automatische Änderung.",
        ))
    elif part.status == Part.Status.FOUND and part.owned_quantity < part.quantity:
        findings.append(PartStatusFinding(
            "B", "Gefunden bei Teilbestand", "MANUAL REVIEW",
            "Workflowstatus und Teilbestand fachlich prüfen; keine automatische Änderung.",
        ))
    if part.status == Part.Status.MISSING and part.owned_quantity >= part.quantity:
        findings.append(PartStatusFinding(
            "C", "Fehlt bei vollständigem Bestand", "MANUAL REVIEW",
            "Workflowstatus fachlich prüfen; keine automatische Änderung.",
        ))
    if part.status not in Part.Status.values:
        findings.append(PartStatusFinding(
            "D", "Unbekannter Workflowstatus", "MANUAL REVIEW",
            "Statuswert fachlich einem gültigen Workflowstatus zuordnen.",
        ))
    expected_present = expected_is_present(part)
    if part.is_present != expected_present:
        findings.append(PartStatusFinding(
            "E", "Redundanter Vorhanden-Marker widerspricht Mengen",
            part.status,
            f"is_present auf {expected_present} setzen; Status und Mengen bleiben unverändert.",
            safe_apply=True, field="is_present", value=expected_present,
        ))
    return findings
