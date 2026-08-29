from dataclasses import dataclass

from django.db import models, transaction

from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.organizer.models import MinifigurePart, SetMinifigure

from .services import RebrickableError, rebrickable_minifigures, rebrickable_set


@dataclass(frozen=True)
class SyncResult:
    parts: int
    minifigures: int
    minifigure_parts: int
    minifigures_available: bool = True


def _nonnegative(value, default=0):
    try:
        return max(int(value or default), 0)
    except (TypeError, ValueError):
        return default


def _upsert_reference(model, lookup, defaults):
    """Update one canonical row without failing on historical duplicate rows."""
    instance = model.objects.filter(**lookup).order_by("pk").first()
    if instance is None:
        return model.objects.create(**lookup, **defaults)
    changed = []
    for field, value in defaults.items():
        if getattr(instance, field) != value:
            setattr(instance, field, value)
            changed.append(field)
    if changed:
        instance.save(update_fields=changed)
    return instance


def initialize_newly_purchased_inventory(lego_set):
    """Mark only this newly purchased set's synchronized requirements as owned."""
    SetInventoryItem.objects.filter(lego_set=lego_set).update(
        owned_quantity=models.F("required_quantity")
    )
    SetMinifigure.objects.filter(lego_set=lego_set, owner=lego_set.owner).update(
        owned_quantity=models.F("quantity")
    )
    MinifigurePart.objects.filter(
        minifigure__lego_set=lego_set, minifigure__owner=lego_set.owner
    ).update(owned_quantity=models.F("quantity"))


def _reconcile_missing_part_requirement(lego_set, inventory_item):
    """Keep the optional missing-parts mirror aligned without changing user state."""
    identity = (inventory_item.element_id or inventory_item.part_number).strip()
    if not identity:
        return
    part = (
        Part.objects.filter(
            owner=lego_set.owner,
            lego_set=lego_set,
            deleted_at__isnull=True,
        )
        .filter(models.Q(element_id=identity) | models.Q(part_number=inventory_item.part_number))
        .filter(color=inventory_item.color_name)
        .order_by("pk")
        .first()
    )
    if not part:
        return
    new_owned = min(part.owned_quantity, inventory_item.required_quantity)
    if part.quantity == inventory_item.required_quantity and part.owned_quantity == new_owned:
        return
    part.quantity = inventory_item.required_quantity
    part.owned_quantity = new_owned
    part.save(update_fields=["quantity", "owned_quantity", "updated_at"])


@transaction.atomic
def synchronize_set(
    lego_set, api_key, *, set_fetcher=rebrickable_set,
    minifigure_fetcher=rebrickable_minifigures,
):
    """Refresh Rebrickable reference data while preserving all user-owned state."""
    lego_set = LegoSet.objects.select_for_update().get(pk=lego_set.pk)
    metadata, parts = set_fetcher(lego_set.set_number, api_key)
    lego_set.name = metadata.get("name") or lego_set.name
    lego_set.year = metadata.get("year") or lego_set.year
    lego_set.total_parts = _nonnegative(metadata.get("num_parts"))
    lego_set.image_url = metadata.get("set_img_url") or lego_set.image_url
    lego_set.save(update_fields=["name", "year", "total_parts", "image_url", "updated_at"])

    existing_inventory = set(
        SetInventoryItem.objects.filter(lego_set=lego_set).values_list(
            "part_number", "color_id", "is_spare"
        )
    )
    seen_inventory = set()
    part_count = 0
    for row in parts:
        part = row.get("part") or {}
        color = row.get("color") or {}
        part_number = str(part.get("part_num") or "")[:100]
        key = (part_number, color.get("id"), bool(row.get("is_spare")))
        if not part_number or key in seen_inventory:
            continue
        seen_inventory.add(key)
        item = _upsert_reference(
            SetInventoryItem,
            {
                "lego_set": lego_set,
                "part_number": part_number,
                "color_id": color.get("id"),
                "is_spare": key[2],
            },
            {
                "element_id": str(row.get("element_id") or "")[:100],
                "name": str(part.get("name") or part_number)[:255],
                "color_name": str(color.get("name") or "")[:150],
                "required_quantity": _nonnegative(row.get("quantity")),
                "image_url": str(part.get("part_img_url") or "")[:1000],
            },
        )
        _reconcile_missing_part_requirement(lego_set, item)
        part_count += 1
    for old in SetInventoryItem.objects.filter(lego_set=lego_set):
        key = (old.part_number, old.color_id, old.is_spare)
        if key not in seen_inventory and key in existing_inventory and old.required_quantity:
            old.required_quantity = 0
            old.save(update_fields=["required_quantity", "updated_at"])
            mirror = (
                Part.objects.filter(owner=lego_set.owner, lego_set=lego_set, deleted_at__isnull=True)
                .filter(models.Q(element_id=old.element_id) | models.Q(part_number=old.part_number))
                .filter(color=old.color_name)
                .order_by("pk")
                .first()
            )
            if mirror:
                mirror.quantity = mirror.owned_quantity
                mirror.save(update_fields=["quantity", "updated_at"])

    try:
        figures = minifigure_fetcher(lego_set.set_number, api_key)
        minifigures_available = True
    except RebrickableError as exc:
        if exc.code == "rate_limit":
            raise
        figures = []
        minifigures_available = False
    except ValueError:
        figures = []
        minifigures_available = False

    figure_count = component_count = 0
    seen_figures = set()
    for figure, components in figures:
        number = str(figure.get("set_num") or "")[:100]
        if not number or number in seen_figures:
            continue
        seen_figures.add(number)
        minifigure = _upsert_reference(
            SetMinifigure,
            {"owner": lego_set.owner, "lego_set": lego_set, "figure_number": number},
            {
                "name": str(figure.get("name") or number)[:191],
                "quantity": max(_nonnegative(figure.get("quantity"), 1), 1),
                "image_url": str(figure.get("set_img_url") or "")[:1000],
            },
        )
        figure_count += 1
        existing_components = set(
            MinifigurePart.objects.filter(minifigure=minifigure).values_list(
                "part_number", "color_id", "is_spare"
            )
        )
        seen_components = set()
        for row in components:
            part = row.get("part") or {}
            color = row.get("color") or {}
            part_number = str(part.get("part_num") or "")[:100]
            key = (part_number, color.get("id"), bool(row.get("is_spare")))
            if not part_number or key in seen_components:
                continue
            seen_components.add(key)
            _upsert_reference(
                MinifigurePart,
                {
                    "minifigure": minifigure,
                    "part_number": part_number,
                    "color_id": color.get("id"),
                    "is_spare": key[2],
                },
                {
                    "element_id": str(row.get("element_id") or "")[:100],
                    "name": str(part.get("name") or part_number)[:191],
                    "color_name": str(color.get("name") or "")[:100],
                    "quantity": max(_nonnegative(row.get("quantity"), 1), 1),
                    "image_url": str(part.get("part_img_url") or "")[:1000],
                },
            )
            component_count += 1
        for old in MinifigurePart.objects.filter(minifigure=minifigure):
            key = (old.part_number, old.color_id, old.is_spare)
            if key not in seen_components and key in existing_components and old.quantity:
                old.quantity = 0
                old.save(update_fields=["quantity", "updated_at"])
    if minifigures_available:
        for old in SetMinifigure.objects.filter(lego_set=lego_set, owner=lego_set.owner):
            if old.figure_number not in seen_figures and old.quantity:
                old.quantity = 0
                old.save(update_fields=["quantity", "updated_at"])
    return SyncResult(part_count, figure_count, component_count, minifigures_available)
