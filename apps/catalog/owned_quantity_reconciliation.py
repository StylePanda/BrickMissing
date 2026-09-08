from dataclasses import dataclass, replace

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.organizer.models import MinifigurePart

from .models import Part, SetInventoryItem
from .part_status import synchronize_presence_marker
from .services import owned_quantity_consistency_rows

PROVEN_PART_USER_EDIT = "PROVEN_PART_USER_EDIT"
PROVEN_ALLOCATION_USER_EDIT = "PROVEN_ALLOCATION_USER_EDIT"
DERIVED_STALE_MIRROR = "DERIVED_STALE_MIRROR"
EXACTLY_EQUAL_AFTER_NORMALIZATION = "EXACTLY_EQUAL_AFTER_NORMALIZATION"
AMBIGUOUS = "AMBIGUOUS"
USER_APPROVED_AUTHORITY_RESOLUTION = "USER_APPROVED_AUTHORITY_RESOLUTION"
USER_APPROVED_REASON = (
    "Explicit user-approved historical policy: retain authoritative allocation "
    "ownership and synchronize Part mirror."
)

PART_ACTION = "missing_part.quantity_changed"
ALLOCATION_ACTIONS = {
    "set": "set_inventory.quantity_changed",
    "minifigure": "minifigure_part.quantity_changed",
}


@dataclass(frozen=True)
class ReconciliationPlan:
    row: dict
    classification: str
    proposed_winner: str
    proposed_final_owned: int | None
    reason: str
    event_id: int | None = None

    @property
    def would_write(self):
        return self.classification not in {
            AMBIGUOUS,
            EXACTLY_EQUAL_AFTER_NORMALIZATION,
        }

    @property
    def state_token(self):
        allocations = tuple(
            (item["kind"], item["id"], item["required"], item["owned"])
            for item in self.row["allocations"]
        )
        return (
            self.row["part_id"],
            self.row["part_required"],
            self.row["part_owned"],
            allocations,
            self.classification,
            self.event_id,
        )


def _event_owned(event):
    value = (event.details or {}).get("owned_quantity")
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_owned_quantity_consistency(
    user=None,
    *,
    part_id=None,
    set_number=None,
    include_consistent=False,
    resolve_ambiguous_from_authority=False,
):
    rows = owned_quantity_consistency_rows(
        user,
        part_id=part_id,
        set_number=set_number,
        include_consistent=include_consistent,
    )
    part_ids = {row["part_id"] for row in rows}
    allocation_keys = {
        (item["kind"], item["id"])
        for row in rows
        for item in row["allocations"]
    }
    entity_ids = part_ids | {item_id for _kind, item_id in allocation_keys}
    actions = {PART_ACTION, *ALLOCATION_ACTIONS.values()}
    events = AuditEvent.objects.filter(
        action__in=actions,
        entity_id__in=entity_ids,
    ).order_by("-created_at", "-pk")
    if user is not None:
        events = events.filter(target_user=user)

    latest = {}
    for event in events:
        if event.action == PART_ACTION:
            key = ("part", event.entity_id)
        elif event.action == ALLOCATION_ACTIONS["set"]:
            key = ("set", event.entity_id)
        else:
            key = ("minifigure", event.entity_id)
        latest.setdefault(key, event)

    plans = []
    for row in rows:
        if row["part_owned"] == row["authoritative_owned"]:
            plans.append(
                ReconciliationPlan(
                    row,
                    EXACTLY_EQUAL_AFTER_NORMALIZATION,
                    "equal",
                    row["part_owned"],
                    "Part mirror already equals the grouped authoritative allocation.",
                )
            )
            continue

        relevant = []
        part_event = latest.get(("part", row["part_id"]))
        if part_event is not None:
            relevant.append((part_event, "part", row["part_owned"]))
        for allocation in row["allocations"]:
            event = latest.get((allocation["kind"], allocation["id"]))
            if event is not None:
                relevant.append((event, "allocation", allocation["owned"]))

        if not relevant:
            plans.append(
                ReconciliationPlan(
                    row,
                    AMBIGUOUS,
                    "none",
                    None,
                    "No retained allocation-specific user quantity event proves either value.",
                )
            )
            continue

        event, side, current_value = max(
            relevant, key=lambda item: (item[0].created_at, item[0].pk)
        )
        recorded_value = _event_owned(event)
        if recorded_value != current_value:
            plans.append(
                ReconciliationPlan(
                    row,
                    AMBIGUOUS,
                    "none",
                    None,
                    "The latest retained quantity event does not equal current state; a later unrecorded write is possible.",
                    event.pk,
                )
            )
        elif side == "part" and row["allocation_count"] != 1:
            plans.append(
                ReconciliationPlan(
                    row,
                    AMBIGUOUS,
                    "none",
                    None,
                    "A Part-side total cannot be distributed safely across multiple allocations.",
                    event.pk,
                )
            )
        elif side == "part":
            allocation = row["allocations"][0]
            if recorded_value > allocation["required"]:
                plans.append(
                    ReconciliationPlan(
                        row,
                        AMBIGUOUS,
                        "none",
                        None,
                        "The proven Part value exceeds the allocation requirement.",
                        event.pk,
                    )
                )
            else:
                plans.append(
                    ReconciliationPlan(
                        row,
                        PROVEN_PART_USER_EDIT,
                        "part",
                        recorded_value,
                        "Latest retained allocation-specific user action is the historical Fehlteile quantity edit and its value still matches Part.",
                        event.pk,
                    )
                )
        else:
            plans.append(
                ReconciliationPlan(
                    row,
                    PROVEN_ALLOCATION_USER_EDIT,
                    "authoritative allocation",
                    row["authoritative_owned"],
                    "Latest retained allocation-specific user action edited authoritative set/minifigure inventory and still matches that allocation.",
                    event.pk,
                )
            )
    if resolve_ambiguous_from_authority:
        plans = [
            replace(
                plan,
                classification=USER_APPROVED_AUTHORITY_RESOLUTION,
                proposed_winner="authoritative allocation",
                proposed_final_owned=plan.row["authoritative_owned"],
                reason=USER_APPROVED_REASON,
            )
            if plan.classification == AMBIGUOUS
            else plan
            for plan in plans
        ]
    return plans


@transaction.atomic
def apply_reconciliation(
    plans,
    *,
    user=None,
    part_id=None,
    set_number=None,
    resolve_ambiguous_from_authority=False,
):
    candidate_ids = [plan.row["part_id"] for plan in plans if plan.would_write]
    if not candidate_ids:
        return 0

    parts = {
        str(part.pk): part
        for part in Part.objects.select_for_update()
        .select_related("lego_set")
        .filter(pk__in=candidate_ids)
    }
    set_ids = {
        allocation["id"]
        for plan in plans
        for allocation in plan.row["allocations"]
        if allocation["kind"] == "set"
    }
    mini_ids = {
        allocation["id"]
        for plan in plans
        for allocation in plan.row["allocations"]
        if allocation["kind"] == "minifigure"
    }
    set_items = {
        str(item.pk): item
        for item in SetInventoryItem.objects.select_for_update().filter(pk__in=set_ids)
    }
    mini_items = {
        str(item.pk): item
        for item in MinifigurePart.objects.select_for_update().filter(pk__in=mini_ids)
    }
    list(
        AuditEvent.objects.select_for_update().filter(
            action__in={PART_ACTION, *ALLOCATION_ACTIONS.values()},
            entity_id__in=set(candidate_ids) | set_ids | mini_ids,
        )
    )

    locked_plans = classify_owned_quantity_consistency(
        user,
        part_id=part_id,
        set_number=set_number,
        include_consistent=True,
        resolve_ambiguous_from_authority=resolve_ambiguous_from_authority,
    )
    original = {plan.row["part_id"]: plan.state_token for plan in plans}
    current = {plan.row["part_id"]: plan.state_token for plan in locked_plans}
    if any(current.get(identifier) != token for identifier, token in original.items()):
        raise CommandError("State or provenance changed after dry-run classification; no writes applied.")

    now = timezone.now()
    changed_parts = []
    changed_sets = []
    changed_minis = []
    logs = []
    for plan in locked_plans:
        if not plan.would_write:
            continue
        part = parts[plan.row["part_id"]]
        if plan.classification == PROVEN_PART_USER_EDIT:
            allocation = plan.row["allocations"][0]
            target = (
                set_items[allocation["id"]]
                if allocation["kind"] == "set"
                else mini_items[allocation["id"]]
            )
            target.owned_quantity = plan.proposed_final_owned
            if allocation["kind"] == "set":
                target.updated_at = now
                changed_sets.append(target)
            else:
                changed_minis.append(target)
        else:
            part.owned_quantity = plan.row["authoritative_owned"]

        final_owned = plan.proposed_final_owned
        final_required = plan.row["authoritative_required"]
        part.quantity = max(final_required, final_owned)
        part.owned_quantity = final_owned
        synchronize_presence_marker(part)
        part.updated_at = now
        part.full_clean()
        changed_parts.append(part)
        logs.append(
            AuditEvent(
                actor_id=part.owner_id,
                target_user_id=part.owner_id,
                action="ownership.reconciled",
                entity_type="part",
                entity_id=str(part.pk),
                details={
                    "classification": plan.classification,
                    "resolution_source": (
                        "user_approved_authoritative_policy"
                        if plan.classification == USER_APPROVED_AUTHORITY_RESOLUTION
                        else "retained_explicit_quantity_event"
                    ),
                    "part_owned_before": plan.row["part_owned"],
                    "authoritative_owned_before": plan.row["authoritative_owned"],
                    "final_owned": final_owned,
                    "provenance_event_id": plan.event_id,
                },
            )
        )

    if changed_sets:
        SetInventoryItem.objects.bulk_update(changed_sets, ["owned_quantity", "updated_at"])
    if changed_minis:
        MinifigurePart.objects.bulk_update(changed_minis, ["owned_quantity"])
    if changed_parts:
        Part.objects.bulk_update(
            changed_parts,
            ["quantity", "owned_quantity", "is_present", "updated_at"],
        )
    if logs:
        AuditEvent.objects.bulk_create(logs)
    return len(changed_parts)
