from .models import RecentItem


def record_recent(user, entity_type, entity_id, label, path):
    item = RecentItem.objects.filter(
        owner=user, entity_type=entity_type, entity_id=str(entity_id)
    ).first()
    if item:
        item.label = str(label)[:255]
        item.path = path[:255]
        item.save(update_fields=["label", "path", "viewed_at"])
    else:
        RecentItem.objects.create(
            owner=user, entity_type=entity_type, entity_id=str(entity_id),
            label=str(label)[:255], path=path[:255],
        )
    stale = RecentItem.objects.filter(owner=user).order_by("-viewed_at").values_list(
        "pk", flat=True
    )[50:]
    RecentItem.objects.filter(pk__in=list(stale)).delete()
