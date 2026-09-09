from dataclasses import dataclass

from apps.catalog.models import Part

WORKFLOW_STATUS_LABELS = dict(Part.Status.choices)
POSSESSION_WORKFLOW_STATUSES = {
    Part.Status.FOUND,
    Part.Status.RECEIVED,
    Part.Status.INSTALLED,
}


def workflow_status_label(status):
    return WORKFLOW_STATUS_LABELS.get(status, status or "–")


def stock_state(quantity, owned_quantity):
    if owned_quantity <= 0:
        return "none", "Nicht vorhanden"
    if owned_quantity >= quantity:
        return "complete", "Vollständig vorhanden"
    return "partial", "Teilweise vorhanden"


def group_quantity_status(required_quantity, owned_quantity, missing_quantity=None):
    """Return the visible group status derived from authoritative quantities."""
    missing = (
        max(required_quantity - owned_quantity, 0)
        if missing_quantity is None
        else missing_quantity
    )
    if missing <= 0:
        return "complete", "Erhalten"
    if required_quantity > 0 and required_quantity - missing <= 0:
        return "missing", "Fehlt"
    return "partial", "Teilweise"


def effective_workflow_status(
    status, required_quantity, owned_quantity, missing_quantity=None
):
    """Mask a stale possession status while an authoritative shortage exists."""
    missing = (
        max(required_quantity - owned_quantity, 0)
        if missing_quantity is None
        else missing_quantity
    )
    if missing > 0 and status in POSSESSION_WORKFLOW_STATUSES:
        return Part.Status.MISSING
    return status


def synchronize_workflow_status(
    part, required_quantity=None, owned_quantity=None, missing_quantity=None
):
    required = part.quantity if required_quantity is None else required_quantity
    owned = part.owned_quantity if owned_quantity is None else owned_quantity
    part.status = effective_workflow_status(
        part.status, required, owned, missing_quantity
    )
    return part


def workflow_status_is_consistent(
    status, required_quantity, owned_quantity, missing_quantity=None
):
    return (
        effective_workflow_status(
            status, required_quantity, owned_quantity, missing_quantity
        )
        == status
    )


def expected_is_present(part):
    return part.owned_quantity + part.unassigned_found_quantity > 0


def synchronize_presence_marker(part):
    part.is_present = expected_is_present(part)
    return part


@dataclass(frozen=True)
class PartStatusFinding:
    category: str
    title: str
    expected_status: str
    proposed_change: str
    safe_apply: bool = False
    field: str = ""
    value: object = None


def analyze_part_status(
    part, required_quantity=None, owned_quantity=None, missing_quantity=None
):
    required = part.quantity if required_quantity is None else required_quantity
    owned = part.owned_quantity if owned_quantity is None else owned_quantity
    missing = max(required - owned, 0) if missing_quantity is None else missing_quantity
    effective_owned = max(required - missing, 0)
    findings = []
    if part.status == Part.Status.FOUND and effective_owned == 0:
        findings.append(PartStatusFinding(
            "A", "Gefunden bei Bestand 0", "MANUAL REVIEW",
            "Workflowstatus oder Menge fachlich prüfen; keine automatische Änderung.",
        ))
    elif part.status == Part.Status.FOUND and missing > 0:
        findings.append(PartStatusFinding(
            "B", "Gefunden bei Teilbestand", "MANUAL REVIEW",
            "Workflowstatus und Teilbestand fachlich prüfen; keine automatische Änderung.",
        ))
    if (
        part.status in {Part.Status.RECEIVED, Part.Status.INSTALLED}
        and missing > 0
    ):
        findings.append(PartStatusFinding(
            "F", "Besitzstatus bei offener Fehlmenge", "MANUAL REVIEW",
            "Persistierten Workflowstatus fachlich prüfen; die Anzeige wird aus Mengen abgeleitet.",
        ))
    if part.status == Part.Status.MISSING and missing <= 0:
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
