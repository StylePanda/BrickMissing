from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import AuditEvent

from .models import InventoryItem, InventoryMovement


def _validate_quantities(quantity, reserved):
    if quantity < 0 or reserved < 0 or reserved > quantity:
        raise ValidationError("Bestand und Reservierung sind ungültig.")


@transaction.atomic
def adjust_inventory(
    item,
    actor,
    quantity,
    reserved,
    movement_type,
    note="",
    request_id=None,
    *,
    metadata=None,
    source="",
    destination="",
):
    """Set absolute stock values while holding the database row lock."""
    _validate_quantities(quantity, reserved)
    locked = InventoryItem.objects.select_for_update().get(pk=item.pk)
    if actor is None or locked.owner_id != actor.pk:
        raise PermissionDenied
    old_quantity = locked.quantity
    old_reserved = locked.reserved_quantity
    for field, value in (metadata or {}).items():
        if field in {"quantity", "reserved_quantity", "owner", "legacy_id"}:
            raise ValidationError("Ungültiges Bestandsfeld.")
        setattr(locked, field, value)
    locked.quantity = quantity
    locked.reserved_quantity = reserved
    locked.full_clean()
    locked.save(
        update_fields=[
            "quantity", "reserved_quantity", "updated_at", *(metadata or {}).keys()
        ]
    )
    movement = InventoryMovement.objects.create(
        item=locked,
        movement_type=movement_type,
        old_quantity=old_quantity,
        new_quantity=quantity,
        difference=quantity - old_quantity,
        old_reserved=old_reserved,
        new_reserved=reserved,
        actor=actor,
        note=note,
        source=source,
        destination=destination,
    )
    AuditEvent.objects.create(
        actor=actor,
        target_user=actor,
        action="inventory.adjusted",
        entity_type="inventory_item",
        entity_id=str(locked.pk),
        details={"movement": movement.pk},
        request_id=request_id,
    )
    return locked


@transaction.atomic
def change_inventory(item, actor, quantity_delta=0, reserved_delta=0, **kwargs):
    """Apply deltas to the latest locked values, preventing lost increments."""
    locked = InventoryItem.objects.select_for_update().get(pk=item.pk)
    return adjust_inventory(
        locked,
        actor,
        locked.quantity + quantity_delta,
        locked.reserved_quantity + reserved_delta,
        **kwargs,
    )


@transaction.atomic
def create_inventory(
    actor, quantity, reserved, movement_type="create", request_id=None, **fields
):
    _validate_quantities(quantity, reserved)
    item = InventoryItem(owner=actor, quantity=0, reserved_quantity=0, **fields)
    item.full_clean()
    item.save()
    return adjust_inventory(
        item, actor, quantity, reserved, movement_type, request_id=request_id
    )
