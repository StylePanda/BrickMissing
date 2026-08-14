from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent

from .models import Part, PartHistory


def set_completeness(lego_set):
    inventory = list(lego_set.inventory_items.filter(is_spare=False))
    minifigure_parts = [
        part
        for figure in lego_set.minifigures_inventory.all()
        for part in figure.parts.all()
        if not part.is_spare
    ]
    positions = inventory + minifigure_parts
    if not positions:
        return {"key": "unknown", "label": "Unbekannt", "required": 0, "owned": 0, "missing": 0}
    required = sum(item.required_quantity if hasattr(item, "required_quantity") else item.quantity for item in positions)
    owned = sum(min(item.owned_quantity, item.required_quantity if hasattr(item, "required_quantity") else item.quantity) for item in positions)
    missing = max(required - owned, 0)
    return {"key": "incomplete" if missing else "complete", "label": "Unvollständig" if missing else "Vollständig", "required": required, "owned": owned, "missing": missing}


@transaction.atomic
def update_part(part: Part, values: dict, actor, request_id=None) -> Part:
    locked = Part.objects.select_for_update().get(pk=part.pk, owner=actor)
    old_status = locked.status
    for field, value in values.items():
        setattr(locked, field, value)
    locked.full_clean()
    locked.save()
    if locked.status != old_status:
        PartHistory.objects.create(part=locked, status=locked.status, note="Status geändert")
    AuditEvent.objects.create(
        actor=actor,
        target_user=actor,
        action="part.updated",
        entity_type="part",
        entity_id=str(locked.pk),
        request_id=request_id,
    )
    return locked


@transaction.atomic
def soft_delete(instance, actor, request_id=None):
    locked = instance.__class__.objects.select_for_update().get(pk=instance.pk, owner=actor)
    locked.deleted_at = timezone.now()
    locked.save(update_fields=["deleted_at", "updated_at"])
    AuditEvent.objects.create(
        actor=actor,
        target_user=actor,
        action=f"{instance._meta.model_name}.trashed",
        entity_type=instance._meta.model_name,
        entity_id=str(instance.pk),
        request_id=request_id,
    )
