from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
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


def with_authoritative_missing_quantity(queryset):
    """Annotate Part rows with the missing quantity used by inventory UI.

    A Part linked to a set is an optional workflow mirror.  Its quantity fields
    can lag behind the actual set or minifigure inventory, so an exact
    set/ElementID/color match delegates to those authoritative rows.  Parts
    without such a match (including manually entered loose parts) retain their
    own established quantity semantics.

    Missing amounts are capped per inventory allocation before they are added.
    Consequently, an over-owned allocation can never cancel a shortage in a
    different set or minifigure.
    """
    from apps.organizer.models import MinifigurePart

    normal_items = SetInventoryItem.objects.filter(
        lego_set_id=OuterRef("lego_set_id"),
        lego_set__owner_id=OuterRef("owner_id"),
        lego_set__deleted_at__isnull=True,
        element_id=OuterRef("element_id"),
        color_name=OuterRef("color"),
        is_spare=False,
    )
    minifigure_parts = MinifigurePart.objects.filter(
        minifigure__lego_set_id=OuterRef("lego_set_id"),
        minifigure__owner_id=OuterRef("owner_id"),
        minifigure__lego_set__deleted_at__isnull=True,
        element_id=OuterRef("element_id"),
        color_name=OuterRef("color"),
        is_spare=False,
    )
    queryset = queryset.annotate(
        _has_normal_inventory=Exists(normal_items),
        _has_minifigure_inventory=Exists(minifigure_parts),
        _normal_inventory_missing=Coalesce(
            Subquery(
                _missing_total(normal_items, "lego_set_id", "required_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _minifigure_inventory_missing=Coalesce(
            Subquery(
                _missing_total(
                    minifigure_parts, "minifigure__lego_set_id", "quantity"
                ),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
    )
    return queryset.annotate(
        authoritative_missing_quantity=Case(
            When(
                Q(_has_normal_inventory=True) | Q(_has_minifigure_inventory=True),
                then=(
                    F("_normal_inventory_missing")
                    + F("_minifigure_inventory_missing")
                ),
            ),
            When(quantity__gt=F("owned_quantity"), then=F("quantity") - F("owned_quantity")),
            default=Value(0),
            output_field=IntegerField(),
        )
    )


def authoritative_lego_export_parts(user, *, colors=()):
    """Return the user-scoped Part gateway for read-only LEGO export rows."""
    queryset = Part.objects.filter(
        owner=user,
        status=Part.Status.MISSING,
        deleted_at__isnull=True,
    ).exclude(element_id="")
    queryset = queryset.filter(
        Q(lego_set__isnull=True)
        | Q(lego_set__owner=user, lego_set__deleted_at__isnull=True)
    )
    if colors:
        queryset = queryset.filter(color__in=colors)
    return with_authoritative_missing_quantity(queryset).filter(
        authoritative_missing_quantity__gt=0
    )


def authoritative_lego_export_rows(user, *, colors=()):
    """Build deterministic LEGO rows without counting a mirror more than once."""
    parts = authoritative_lego_export_parts(user, colors=colors).values(
        "pk",
        "lego_set_id",
        "element_id",
        "color",
        "authoritative_missing_quantity",
        "_has_normal_inventory",
        "_has_minifigure_inventory",
    )
    totals = {}
    seen_allocations = set()
    for part in parts:
        has_inventory = (
            part["_has_normal_inventory"] or part["_has_minifigure_inventory"]
        )
        allocation_key = (
            "inventory",
            part["lego_set_id"],
            part["element_id"],
            part["color"].casefold(),
        ) if has_inventory else ("part", part["pk"])
        if allocation_key in seen_allocations:
            continue
        seen_allocations.add(allocation_key)
        element_id = part["element_id"]
        totals[element_id] = (
            totals.get(element_id, 0) + part["authoritative_missing_quantity"]
        )
    return [
        {"element_id": element_id, "export_quantity": quantity}
        for element_id, quantity in sorted(totals.items())
    ]


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
