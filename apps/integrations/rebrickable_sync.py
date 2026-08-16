import time
from dataclasses import dataclass

from django.db import transaction

from apps.catalog.models import LegoSet, SetInventoryItem
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


def _fetch_with_retry(fetcher, set_number, api_key):
    for attempt in range(2):
        try:
            return fetcher(set_number, api_key)
        except RebrickableError as exc:
            if attempt or exc.code not in {"rate_limit", "unavailable"}:
                raise
            time.sleep(0.25)


@transaction.atomic
def synchronize_set(
    lego_set, api_key, *, set_fetcher=rebrickable_set,
    minifigure_fetcher=rebrickable_minifigures,
):
    """Refresh Rebrickable reference data while preserving all user-owned state."""
    lego_set = LegoSet.objects.select_for_update().get(pk=lego_set.pk)
    metadata, parts = _fetch_with_retry(set_fetcher, lego_set.set_number, api_key)
    lego_set.name = metadata.get("name") or lego_set.name
    lego_set.year = metadata.get("year") or lego_set.year
    lego_set.total_parts = _nonnegative(metadata.get("num_parts"))
    lego_set.image_url = metadata.get("set_img_url") or lego_set.image_url
    lego_set.save(update_fields=["name", "year", "total_parts", "image_url", "updated_at"])

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
        _upsert_reference(
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
        part_count += 1

    try:
        figures = _fetch_with_retry(minifigure_fetcher, lego_set.set_number, api_key)
        minifigures_available = True
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
    return SyncResult(part_count, figure_count, component_count, minifigures_available)
