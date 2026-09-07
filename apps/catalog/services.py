from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    F,
    IntegerField,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.audit.models import AuditEvent

from .models import LegoSet, Part, PartHistory, SetInventoryItem
from .part_status import synchronize_presence_marker


def _quantity_total(queryset, group_field, quantity_field):
    return (
        queryset.values(group_field)
        .annotate(total=Sum(quantity_field))
        .values("total")[:1]
    )


def _missing_total(queryset, group_field, required_field):
    return (
        queryset.values(group_field)
        .annotate(
            total=Sum(
                Case(
                    When(
                        **{
                            "owned_quantity__lt": F(required_field),
                            "then": F(required_field) - F("owned_quantity"),
                        }
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
        )
        .values("total")[:1]
    )


def with_set_completeness(queryset):
    """Annotate LegoSet rows using BrickMissing's authoritative completeness rule.

    Only required, non-spare regular inventory and constituent minifigure parts
    belonging to the same owner participate. Empty inventories remain unknown.
    """
    from apps.organizer.models import MinifigurePart

    normal_items = SetInventoryItem.objects.filter(
        lego_set_id=OuterRef("pk"),
        is_spare=False,
        required_quantity__gt=0,
    )
    minifigure_parts = MinifigurePart.objects.filter(
        minifigure__lego_set_id=OuterRef("pk"),
        minifigure__owner_id=OuterRef("owner_id"),
        is_spare=False,
        quantity__gt=0,
    )
    queryset = queryset.annotate(
        _normal_required=Coalesce(
            Subquery(
                _quantity_total(normal_items, "lego_set_id", "required_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _normal_missing=Coalesce(
            Subquery(
                _missing_total(normal_items, "lego_set_id", "required_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _minifigure_required=Coalesce(
            Subquery(
                _quantity_total(minifigure_parts, "minifigure__lego_set_id", "quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _minifigure_missing=Coalesce(
            Subquery(
                _missing_total(minifigure_parts, "minifigure__lego_set_id", "quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
    ).annotate(
        completeness_required=F("_normal_required") + F("_minifigure_required"),
        completeness_missing=F("_normal_missing") + F("_minifigure_missing"),
    )
    return queryset.annotate(
        completeness_key=Case(
            When(completeness_required__lte=0, then=Value("unknown")),
            When(completeness_missing__gt=0, then=Value("incomplete")),
            default=Value("complete"),
            output_field=CharField(),
        )
    )


def set_completeness(lego_set):
    result = (
        with_set_completeness(
            LegoSet.objects.filter(pk=lego_set.pk, owner_id=lego_set.owner_id)
        )
        .values("completeness_key", "completeness_required", "completeness_missing")
        .get()
    )
    required = result["completeness_required"]
    missing = result["completeness_missing"]
    key = result["completeness_key"]
    labels = {
        "complete": "Vollständig",
        "incomplete": "Unvollständig",
        "unknown": "Unbekannt",
    }
    return {
        "key": key,
        "label": labels[key],
        "required": required,
        "owned": required - missing,
        "missing": missing,
    }


def stored_completeness_value(result):
    values = {
        "complete": "vollständig",
        "incomplete": "unvollständig",
        "unknown": "unbekannt",
    }
    return values[result["key"]]


@transaction.atomic
def update_part(part: Part, values: dict, actor, request_id=None) -> Part:
    locked = Part.objects.select_for_update().get(pk=part.pk, owner=actor)
    old_status = locked.status
    for field, value in values.items():
        setattr(locked, field, value)
    synchronize_presence_marker(locked)
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
