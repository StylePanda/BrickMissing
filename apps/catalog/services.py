from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    Exists,
    F,
    IntegerField,
    Max,
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

from .colors import normalized_color_name
from .models import LegoSet, Part, PartHistory, SetInventoryItem
from .part_status import synchronize_presence_marker, synchronize_workflow_status


def dashboard_collection_data(user):
    """Return owner-scoped dashboard facts from authoritative allocations.

    SetInventoryItem and MinifigurePart are the quantity source of truth.  The
    deliberately small number of bulk queries also supplies the top shortages,
    so rendering cards never triggers per-object database work.
    """
    from apps.organizer.models import MinifigurePart, SetMinifigure

    sets = LegoSet.objects.filter(owner=user, deleted_at__isnull=True)
    theme_rows = list(
        sets.exclude(theme="")
        .values("theme")
        .annotate(set_count=Count("pk"))
        .order_by("-set_count", "theme")[:7]
    )
    normal_items = SetInventoryItem.objects.filter(
        lego_set__owner=user,
        lego_set__deleted_at__isnull=True,
        is_spare=False,
        required_quantity__gt=0,
    )
    minifigure_items = MinifigurePart.objects.filter(
        minifigure__owner=user,
        minifigure__lego_set__owner=user,
        minifigure__lego_set__deleted_at__isnull=True,
        is_spare=False,
        quantity__gt=0,
    )

    def allocation_summary(queryset, required_field):
        return queryset.aggregate(
            required=Coalesce(Sum(required_field), Value(0)),
            owned=Coalesce(
                Sum(
                    Case(
                        When(
                            owned_quantity__lt=F(required_field),
                            then=F("owned_quantity"),
                        ),
                        default=F(required_field),
                        output_field=IntegerField(),
                    )
                ),
                Value(0),
            ),
            missing=Coalesce(
                Sum(
                    Case(
                        When(
                            owned_quantity__lt=F(required_field),
                            then=F(required_field) - F("owned_quantity"),
                        ),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                Value(0),
            ),
            missing_positions=Count(
                "pk", filter=Q(owned_quantity__lt=F(required_field))
            ),
        )

    def shortage_groups(queryset, required_field):
        return list(
            queryset.filter(owned_quantity__lt=F(required_field))
            .annotate(
                dashboard_identifier=Case(
                    When(element_id="", then=F("part_number")),
                    default=F("element_id"),
                    output_field=CharField(),
                )
            )
            .values("dashboard_identifier", "color_name")
            .annotate(
                name=Max("name"),
                image_url=Max("image_url"),
                missing=Sum(F(required_field) - F("owned_quantity")),
            )
        )

    normal_summary = allocation_summary(normal_items, "required_quantity")
    minifigure_summary = allocation_summary(minifigure_items, "quantity")
    normal_rows = shortage_groups(normal_items, "required_quantity")
    minifigure_rows = shortage_groups(minifigure_items, "quantity")

    totals = {"required": 0, "owned": 0, "missing": 0, "missing_positions": 0}
    shortages = {}

    def add_rows(rows):
        for row in rows:
            missing = row["missing"]
            identifier = row["dashboard_identifier"].strip()
            key = (identifier.casefold(), row["color_name"].strip().casefold())
            group = shortages.setdefault(
                key,
                {
                    "identifier": identifier,
                    "name": row["name"],
                    "color": row["color_name"],
                    "image_url": row["image_url"],
                    "missing": 0,
                },
            )
            group["missing"] += missing
            if not group["image_url"] and row["image_url"]:
                group["image_url"] = row["image_url"]

    for summary in (normal_summary, minifigure_summary):
        for key in totals:
            totals[key] += summary[key]
    add_rows(normal_rows)
    add_rows(minifigure_rows)

    required = totals["required"]
    owned_percent = round(totals["owned"] * 100 / required, 1) if required else 0.0
    missing_percent = round(totals["missing"] * 100 / required, 1) if required else 0.0
    top_missing_parts = sorted(
        shortages.values(),
        key=lambda item: (-item["missing"], item["name"].casefold(), item["identifier"]),
    )[:5]
    recent_sets = list(sets.order_by("-created_at", "-pk")[:6])
    set_count = sets.count()
    return {
        "set_count": set_count,
        "part_count": Part.objects.filter(
            owner=user, deleted_at__isnull=True
        ).count(),
        "lego_parts_total": required,
        "lego_parts_owned": totals["owned"],
        "lego_parts_missing": totals["missing"],
        "missing_position_count": totals["missing_positions"],
        "minifigure_count": SetMinifigure.objects.filter(
            owner=user, lego_set__deleted_at__isnull=True
        ).count(),
        "owned_percent": owned_percent,
        "missing_percent": missing_percent,
        "owned_percent_svg": f"{owned_percent:.1f}",
        "owned_percent_display": f"{owned_percent:.1f}".replace(".", ","),
        "missing_percent_display": f"{missing_percent:.1f}".replace(".", ","),
        "recent_sets": recent_sets,
        "top_missing_parts": top_missing_parts,
        "top_themes": theme_rows,
    }


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


def _authoritative_set_allocation_querysets():
    """Return the two allocation sources shared by set completeness/filtering."""
    from apps.organizer.models import MinifigurePart

    normal_items = SetInventoryItem.objects.filter(
        lego_set_id=OuterRef("pk"),
        lego_set__owner_id=OuterRef("owner_id"),
        lego_set__deleted_at__isnull=True,
        is_spare=False,
        required_quantity__gt=0,
    )
    minifigure_parts = MinifigurePart.objects.filter(
        minifigure__lego_set_id=OuterRef("pk"),
        minifigure__owner_id=OuterRef("owner_id"),
        minifigure__lego_set__deleted_at__isnull=True,
        is_spare=False,
        quantity__gt=0,
    )
    return normal_items, minifigure_parts


def with_set_completeness(queryset):
    """Annotate LegoSet rows using BrickMissing's authoritative completeness rule.

    Only required, non-spare regular inventory and constituent minifigure parts
    belonging to the same owner participate. Empty inventories remain unknown.
    """
    normal_items, minifigure_parts = _authoritative_set_allocation_querysets()
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


def filter_sets_by_missing_colors(queryset, colors):
    """Keep sets with any authoritative shortage in any selected exact color."""
    colors = tuple(dict.fromkeys(color for color in colors if color))
    if not colors:
        return queryset
    normal_items, minifigure_parts = _authoritative_set_allocation_querysets()
    return queryset.annotate(
        _has_selected_normal_shortage=Exists(
            normal_items.filter(
                color_name__in=colors,
                owned_quantity__lt=F("required_quantity"),
            )
        ),
        _has_selected_minifigure_shortage=Exists(
            minifigure_parts.filter(
                color_name__in=colors,
                owned_quantity__lt=F("quantity"),
            )
        ),
    ).filter(
        Q(_has_selected_normal_shortage=True)
        | Q(_has_selected_minifigure_shortage=True)
    )


def missing_color_values(user):
    """Return exact color values occurring in the user's current shortages."""
    from apps.organizer.models import MinifigurePart

    normal = SetInventoryItem.objects.filter(
        lego_set__owner=user,
        lego_set__deleted_at__isnull=True,
        is_spare=False,
        required_quantity__gt=F("owned_quantity"),
    ).exclude(color_name="").values_list("color_name", flat=True)
    minifigure = MinifigurePart.objects.filter(
        minifigure__owner=user,
        minifigure__lego_set__deleted_at__isnull=True,
        is_spare=False,
        quantity__gt=F("owned_quantity"),
    ).exclude(color_name="").values_list("color_name", flat=True)
    return sorted(
        {
            color
            for color in set(normal).union(minifigure)
            if normalized_color_name(color)
        },
        key=str.casefold,
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
    set/ElementID/color match delegates to those authoritative rows.  When an
    inventory row legitimately has no ElementID, its exact part number may
    instead match the Part's design identity.  Parts without either match
    (including manually entered loose parts) retain their own established
    quantity semantics.

    Exact ElementID matches take precedence within each inventory source.  A
    blank-ElementID fallback is therefore never added to an exact allocation.
    Matching rows are aggregated rather than arbitrarily selected, consistent
    with set completeness treating every inventory position as an allocation.

    Missing amounts are capped per inventory allocation before they are added.
    Consequently, an over-owned allocation can never cancel a shortage in a
    different set or minifigure.
    """
    from apps.organizer.models import MinifigurePart

    # Rebrickable's part_num is a design/part identity.  Legacy imports and the
    # missing-part workflow can retain that exact value in any of Part's three
    # identifier fields, so each exact relationship is accepted independently.
    # No case folding, substring comparison, or ElementID/design conversion is
    # performed.
    part_identity = (
        Q(part_number=OuterRef("design_id"))
        | Q(part_number=OuterRef("part_number"))
        | Q(part_number=OuterRef("element_id"))
    )
    normal_base = SetInventoryItem.objects.filter(
        lego_set_id=OuterRef("lego_set_id"),
        lego_set__owner_id=OuterRef("owner_id"),
        lego_set__deleted_at__isnull=True,
        color_name=OuterRef("color"),
        is_spare=False,
    )
    normal_exact = normal_base.exclude(element_id="").filter(
        element_id=OuterRef("element_id")
    )
    normal_fallback = normal_base.filter(part_identity, element_id="")
    minifigure_base = MinifigurePart.objects.filter(
        minifigure__lego_set_id=OuterRef("lego_set_id"),
        minifigure__owner_id=OuterRef("owner_id"),
        minifigure__lego_set__deleted_at__isnull=True,
        color_name=OuterRef("color"),
        is_spare=False,
    )
    minifigure_exact = minifigure_base.exclude(element_id="").filter(
        element_id=OuterRef("element_id")
    )
    minifigure_fallback = minifigure_base.filter(part_identity, element_id="")
    queryset = queryset.annotate(
        _has_exact_normal_inventory=Exists(normal_exact),
        _has_fallback_normal_inventory=Exists(normal_fallback),
        _has_exact_minifigure_inventory=Exists(minifigure_exact),
        _has_fallback_minifigure_inventory=Exists(minifigure_fallback),
        _exact_normal_inventory_missing=Coalesce(
            Subquery(
                _missing_total(normal_exact, "lego_set_id", "required_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _fallback_normal_inventory_missing=Coalesce(
            Subquery(
                _missing_total(normal_fallback, "lego_set_id", "required_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _exact_minifigure_inventory_missing=Coalesce(
            Subquery(
                _missing_total(minifigure_exact, "minifigure__lego_set_id", "quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _fallback_minifigure_inventory_missing=Coalesce(
            Subquery(
                _missing_total(minifigure_fallback, "minifigure__lego_set_id", "quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _exact_normal_inventory_required=Coalesce(
            Subquery(
                _quantity_total(normal_exact, "lego_set_id", "required_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _fallback_normal_inventory_required=Coalesce(
            Subquery(
                _quantity_total(normal_fallback, "lego_set_id", "required_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _exact_normal_inventory_owned=Coalesce(
            Subquery(
                _quantity_total(normal_exact, "lego_set_id", "owned_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _fallback_normal_inventory_owned=Coalesce(
            Subquery(
                _quantity_total(normal_fallback, "lego_set_id", "owned_quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _exact_minifigure_inventory_required=Coalesce(
            Subquery(
                _quantity_total(minifigure_exact, "minifigure__lego_set_id", "quantity"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _fallback_minifigure_inventory_required=Coalesce(
            Subquery(
                _quantity_total(
                    minifigure_fallback, "minifigure__lego_set_id", "quantity"
                ),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _exact_minifigure_inventory_owned=Coalesce(
            Subquery(
                _quantity_total(
                    minifigure_exact, "minifigure__lego_set_id", "owned_quantity"
                ),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        _fallback_minifigure_inventory_owned=Coalesce(
            Subquery(
                _quantity_total(
                    minifigure_fallback, "minifigure__lego_set_id", "owned_quantity"
                ),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
    ).annotate(
        _has_normal_inventory=Case(
            When(_has_exact_normal_inventory=True, then=Value(True)),
            default=F("_has_fallback_normal_inventory"),
            output_field=BooleanField(),
        ),
        _has_minifigure_inventory=Case(
            When(_has_exact_minifigure_inventory=True, then=Value(True)),
            default=F("_has_fallback_minifigure_inventory"),
            output_field=BooleanField(),
        ),
        _normal_inventory_missing=Case(
            When(
                _has_exact_normal_inventory=True,
                then=F("_exact_normal_inventory_missing"),
            ),
            default=F("_fallback_normal_inventory_missing"),
            output_field=IntegerField(),
        ),
        _minifigure_inventory_missing=Case(
            When(
                _has_exact_minifigure_inventory=True,
                then=F("_exact_minifigure_inventory_missing"),
            ),
            default=F("_fallback_minifigure_inventory_missing"),
            output_field=IntegerField(),
        ),
        _normal_inventory_required=Case(
            When(
                _has_exact_normal_inventory=True,
                then=F("_exact_normal_inventory_required"),
            ),
            default=F("_fallback_normal_inventory_required"),
            output_field=IntegerField(),
        ),
        _normal_inventory_owned=Case(
            When(
                _has_exact_normal_inventory=True,
                then=F("_exact_normal_inventory_owned"),
            ),
            default=F("_fallback_normal_inventory_owned"),
            output_field=IntegerField(),
        ),
        _minifigure_inventory_required=Case(
            When(
                _has_exact_minifigure_inventory=True,
                then=F("_exact_minifigure_inventory_required"),
            ),
            default=F("_fallback_minifigure_inventory_required"),
            output_field=IntegerField(),
        ),
        _minifigure_inventory_owned=Case(
            When(
                _has_exact_minifigure_inventory=True,
                then=F("_exact_minifigure_inventory_owned"),
            ),
            default=F("_fallback_minifigure_inventory_owned"),
            output_field=IntegerField(),
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
        ),
        authoritative_required_quantity=Case(
            When(
                Q(_has_normal_inventory=True) | Q(_has_minifigure_inventory=True),
                then=(
                    F("_normal_inventory_required")
                    + F("_minifigure_inventory_required")
                ),
            ),
            default=F("quantity"),
            output_field=IntegerField(),
        ),
        authoritative_owned_quantity=Case(
            When(
                Q(_has_normal_inventory=True) | Q(_has_minifigure_inventory=True),
                then=F("_normal_inventory_owned") + F("_minifigure_inventory_owned"),
            ),
            default=F("owned_quantity"),
            output_field=IntegerField(),
        ),
    )


class AmbiguousAuthoritativeAllocation(ValidationError):
    """Raised before writes when one Part maps to multiple allocations."""


def _part_identity_values(part):
    return {value for value in (part.design_id, part.part_number, part.element_id) if value}


def _matching_authoritative_allocations(part, *, lock=False):
    """Return exact-precedence normal/minifigure allocations for one Part."""
    from apps.organizer.models import MinifigurePart

    if not part.lego_set_id or part.lego_set.deleted_at is not None:
        return []
    if part.lego_set.owner_id != part.owner_id:
        return []

    normal = SetInventoryItem.objects.filter(
        lego_set_id=part.lego_set_id,
        lego_set__owner_id=part.owner_id,
        lego_set__deleted_at__isnull=True,
        color_name=part.color,
        is_spare=False,
    )
    minifigure = MinifigurePart.objects.filter(
        minifigure__lego_set_id=part.lego_set_id,
        minifigure__owner_id=part.owner_id,
        minifigure__lego_set__deleted_at__isnull=True,
        color_name=part.color,
        is_spare=False,
    )
    if lock:
        normal = normal.select_for_update()
        minifigure = minifigure.select_for_update()
    exact_normal = list(normal.exclude(element_id="").filter(element_id=part.element_id))
    exact_minifigure = list(
        minifigure.exclude(element_id="").filter(element_id=part.element_id)
    )
    identities = _part_identity_values(part)
    fallback_normal = (
        []
        if exact_normal or not identities
        else list(normal.filter(element_id="", part_number__in=identities))
    )
    fallback_minifigure = (
        []
        if exact_minifigure or not identities
        else list(minifigure.filter(element_id="", part_number__in=identities))
    )
    return [
        *(("set", item) for item in exact_normal or fallback_normal),
        *(("minifigure", item) for item in exact_minifigure or fallback_minifigure),
    ]


def _allocation_values(kind, allocation):
    if kind == "set":
        return allocation.required_quantity, allocation.owned_quantity
    return allocation.quantity, allocation.owned_quantity


def _save_allocation_owned(kind, allocation, quantity):
    allocation.owned_quantity = quantity
    allocation.full_clean()
    fields = ["owned_quantity"]
    if kind == "set":
        fields.append("updated_at")
    allocation.save(update_fields=fields)


def _matching_from_collections(part, normal_items, minifigure_parts):
    identities = _part_identity_values(part)
    exact_normal = [
        item
        for item in normal_items
        if item.element_id and item.element_id == part.element_id
    ]
    exact_minifigure = [
        item
        for item in minifigure_parts
        if item.element_id and item.element_id == part.element_id
    ]
    fallback_normal = [
        item
        for item in normal_items
        if not item.element_id and item.part_number in identities
    ]
    fallback_minifigure = [
        item
        for item in minifigure_parts
        if not item.element_id and item.part_number in identities
    ]
    return [
        *(("set", item) for item in exact_normal or fallback_normal),
        *(("minifigure", item) for item in exact_minifigure or fallback_minifigure),
    ]


def owned_quantity_consistency_rows(
    user=None, *, part_id=None, set_number=None, include_consistent=False
):
    """Return existing Part/allocation divergences without modifying data."""
    from apps.organizer.models import MinifigurePart

    parts = Part.objects.filter(
        lego_set__isnull=False,
        lego_set__deleted_at__isnull=True,
        lego_set__owner_id=F("owner_id"),
        deleted_at__isnull=True,
    ).select_related("lego_set")
    if user is not None:
        parts = parts.filter(owner=user)
    if part_id is not None:
        parts = parts.filter(pk=part_id)
    if set_number is not None:
        parts = parts.filter(lego_set__set_number=set_number)
    parts = list(parts.order_by("owner_id", "lego_set_id", "pk"))
    set_ids = {part.lego_set_id for part in parts}
    normal_by_set = {}
    for item in SetInventoryItem.objects.filter(
        lego_set_id__in=set_ids,
        lego_set__deleted_at__isnull=True,
        is_spare=False,
    ).select_related("lego_set"):
        normal_by_set.setdefault(item.lego_set_id, []).append(item)
    minifigure_by_set = {}
    for item in MinifigurePart.objects.filter(
        minifigure__lego_set_id__in=set_ids,
        minifigure__lego_set__deleted_at__isnull=True,
        minifigure__owner_id=F("minifigure__lego_set__owner_id"),
        is_spare=False,
    ).select_related("minifigure", "minifigure__lego_set"):
        minifigure_by_set.setdefault(item.minifigure.lego_set_id, []).append(item)

    rows = []
    for part in parts:
        normal = [
            item
            for item in normal_by_set.get(part.lego_set_id, ())
            if item.color_name == part.color
        ]
        minifigure = [
            item
            for item in minifigure_by_set.get(part.lego_set_id, ())
            if item.color_name == part.color
        ]
        matches = _matching_from_collections(part, normal, minifigure)
        if not matches:
            continue
        required = sum(_allocation_values(kind, item)[0] for kind, item in matches)
        owned = sum(_allocation_values(kind, item)[1] for kind, item in matches)
        if part.owned_quantity == owned and not include_consistent:
            continue
        timestamps = [
            item.updated_at
            for kind, item in matches
            if kind == "set" and item.updated_at is not None
        ]
        rows.append(
            {
                "part_id": str(part.pk),
                "owner_id": str(part.owner_id),
                "set_id": str(part.lego_set_id),
                "set_number": part.lego_set.set_number,
                "element_id": part.element_id,
                "design_or_part_number": part.design_id or part.part_number,
                "color": part.color,
                "part_required": part.quantity,
                "part_owned": part.owned_quantity,
                "authoritative_required": required,
                "authoritative_owned": owned,
                "difference": part.owned_quantity - owned,
                "part_updated_at": part.updated_at,
                "authoritative_updated_at": max(timestamps) if timestamps else None,
                "allocation_count": len(matches),
                "allocation_types": ",".join(kind for kind, _item in matches),
                "allocations": tuple(
                    {
                        "kind": kind,
                        "id": str(item.pk),
                        "required": _allocation_values(kind, item)[0],
                        "owned": _allocation_values(kind, item)[1],
                        "updated_at": item.updated_at if kind == "set" else None,
                    }
                    for kind, item in matches
                ),
            }
        )
    return rows


@transaction.atomic
def set_part_owned_quantity(part, quantity, actor):
    """Atomically write a Part edit through its authoritative allocation."""
    locked = (
        Part.objects.select_for_update()
        .select_related("lego_set")
        .get(pk=part.pk, owner=actor, deleted_at__isnull=True)
    )
    matches = _matching_authoritative_allocations(locked, lock=True)
    if len(matches) > 1:
        raise AmbiguousAuthoritativeAllocation(
            "Die Bestandsmenge kann nicht eindeutig einer Inventarposition zugeordnet werden."
        )
    maximum = locked.quantity
    if matches:
        kind, allocation = matches[0]
        maximum, _owned = _allocation_values(kind, allocation)
    if not isinstance(quantity, int) or not 0 <= quantity <= maximum:
        raise ValidationError("Der vorhandene Bestand ist ungültig.")
    if matches:
        _save_allocation_owned(kind, allocation, quantity)
        locked.quantity = maximum
    locked.owned_quantity = quantity
    synchronize_presence_marker(locked)
    synchronize_workflow_status(locked, maximum, quantity)
    locked.full_clean()
    locked.save(
        update_fields=["quantity", "owned_quantity", "is_present", "status", "updated_at"]
    )
    return locked


def _allocation_owner_and_set(kind, allocation):
    if kind == "set":
        return allocation.lego_set.owner_id, allocation.lego_set
    return allocation.minifigure.owner_id, allocation.minifigure.lego_set


def _candidate_part_mirrors(kind, allocation, *, lock=False):
    owner_id, lego_set = _allocation_owner_and_set(kind, allocation)
    queryset = Part.objects.filter(
        owner_id=owner_id,
        lego_set=lego_set,
        lego_set__deleted_at__isnull=True,
        deleted_at__isnull=True,
        color=allocation.color_name,
    ).select_related("lego_set")
    if allocation.element_id:
        queryset = queryset.filter(element_id=allocation.element_id)
    else:
        queryset = queryset.filter(
            Q(design_id=allocation.part_number)
            | Q(part_number=allocation.part_number)
            | Q(element_id=allocation.part_number)
        )
    return queryset.select_for_update() if lock else queryset


@transaction.atomic
def set_authoritative_owned_quantity(kind, allocation, quantity, actor):
    """Update a known inventory row and all unambiguous Part mirrors atomically."""
    from apps.organizer.models import MinifigurePart

    model = SetInventoryItem if kind == "set" else MinifigurePart
    lookup = {"pk": allocation.pk}
    if kind == "set":
        lookup.update(lego_set__owner=actor, lego_set__deleted_at__isnull=True)
        related = ("lego_set",)
    else:
        lookup.update(
            minifigure__owner=actor,
            minifigure__lego_set__deleted_at__isnull=True,
        )
        related = ("minifigure", "minifigure__lego_set")
    locked = model.objects.select_for_update().select_related(*related).get(**lookup)
    maximum, _owned = _allocation_values(kind, locked)
    if not isinstance(quantity, int) or not 0 <= quantity <= maximum:
        raise ValidationError("Der vorhandene Bestand ist ungültig.")

    mirrors = []
    for part in _candidate_part_mirrors(kind, locked, lock=True):
        matches = _matching_authoritative_allocations(part, lock=True)
        target_matches = [
            candidate
            for candidate_kind, candidate in matches
            if candidate_kind == kind and candidate.pk == locked.pk
        ]
        if target_matches:
            required = sum(
                _allocation_values(match_kind, item)[0]
                for match_kind, item in matches
            )
            owned = sum(
                quantity
                if match_kind == kind and item.pk == locked.pk
                else _allocation_values(match_kind, item)[1]
                for match_kind, item in matches
            )
            missing = sum(
                max(
                    _allocation_values(match_kind, item)[0]
                    - (
                        quantity
                        if match_kind == kind and item.pk == locked.pk
                        else _allocation_values(match_kind, item)[1]
                    ),
                    0,
                )
                for match_kind, item in matches
            )
            mirrors.append((part, required, owned, missing))

    _save_allocation_owned(kind, locked, quantity)
    for part, required, owned, missing in mirrors:
        part.quantity = max(required, owned)
        part.owned_quantity = owned
        synchronize_presence_marker(part)
        synchronize_workflow_status(part, required, owned, missing)
        part.full_clean()
        part.save(
            update_fields=[
                "quantity", "owned_quantity", "is_present", "status", "updated_at"
            ]
        )
    return locked


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
    locked = set_part_owned_quantity(locked, locked.owned_quantity, actor)
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
