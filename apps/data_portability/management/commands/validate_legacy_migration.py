from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.data_portability.legacy_source import LegacySourceError, open_legacy_source
from apps.data_portability.models import LegacyArchiveRecord

# target field -> legacy column. Relationships are compared through related.legacy_id.
MAPPINGS = {
    "users": ("accounts.User", {"username": "name", "email": "email", "email_verified": "email_verified_at", "is_staff": "role", "is_active": "disabled"}),
    "sets": ("catalog.LegoSet", {"owner": "user_id", "set_number": "set_number", "name": "name", "theme": "theme", "subtheme": "subtheme", "year": "year", "total_parts": "total_parts", "minifigures": "minifigures", "description": "description", "condition": "condition", "completeness": "completeness", "build_status": "build_status", "favorite": "favorite", "image_url": "image_url", "purchase_date": "purchase_date", "purchase_price": "purchase_price", "current_value": "current_value", "has_box": "has_box", "has_instructions": "has_instructions", "has_stickers": "has_stickers", "notes": "notes", "deleted_at": "deleted_at"}),
    "set_copies": ("catalog.SetCopy", {"lego_set": "set_id", "inventory_number": "inventory_number", "serial_number": "serial_number", "condition": "condition", "completeness": "completeness", "build_status": "build_status", "purchase_date": "purchase_date", "purchase_price": "purchase_price", "notes": "notes", "image_url": "image_url", "deleted_at": "deleted_at"}),
    "parts": ("catalog.Part", {"owner": "user_id", "lego_set": "set_id", "element_id": "element_id", "design_id": "design_id", "part_number": "id", "name": "name", "color": "color", "quantity": "quantity", "owned_quantity": "owned_quantity", "unassigned_found_quantity": "unassigned_found_quantity", "is_present": "is_present", "status": "status", "priority": "priority", "unit_price": "unit_price", "supplier": "supplier", "notes": "notes", "image_url": "image_url", "deleted_at": "deleted_at"}),
    "set_inventory": ("catalog.SetInventoryItem", {"lego_set": "set_id", "part_number": "part_num", "element_id": "element_id", "name": "name", "color_id": "color_id", "color_name": "color_name", "required_quantity": "required_quantity", "owned_quantity": "owned_quantity", "is_spare": "is_spare", "image_url": "image_url"}),
    "history": ("catalog.PartHistory", {"part": "part_id", "status": "status", "note": "note", "created_at": "created_at"}),
    "collections": ("organizer.Collection", {"owner": "owner_id", "name": "name", "description": "description", "is_shared": "is_shared"}),
    "warehouse_locations": ("inventory.WarehouseLocation", {"owner": "user_id", "parent": "parent_id", "name": "name", "location_type": "location_type", "capacity": "capacity", "photo_url": "photo_url", "notes": "notes", "short_code": "short_code", "description": "description", "room": "room", "color": "color", "active": "active", "locked": "locked", "archived_at": "archived_at"}),
    "inventory_items": ("inventory.InventoryItem", {"owner": "user_id", "location": "location_id", "part_number": "part_number", "design_id": "design_id", "element_id": "element_id", "name": "name", "color": "color", "category": "category", "subcategory": "subcategory", "quantity": "quantity", "reserved_quantity": "reserved_quantity", "condition": "condition", "image_url": "image_url", "source": "source", "purchase_price": "purchase_price", "unit_price": "unit_price", "notes": "notes", "archived_at": "archived_at"}),
    "inventory_movements": ("inventory.InventoryMovement", {"item": "inventory_item_id", "actor": "user_id", "movement_type": "movement_type", "old_quantity": "old_quantity", "new_quantity": "new_quantity", "difference": "difference", "old_reserved": "old_reserved", "new_reserved": "new_reserved", "source": "source", "destination": "destination", "note": "note"}),
    "set_minifigures": ("organizer.SetMinifigure", {"owner": "user_id", "lego_set": "set_id", "figure_number": "fig_number", "name": "name", "quantity": "quantity", "owned_quantity": "owned_quantity", "image_url": "image_url", "notes": "notes"}),
    "minifigure_parts": ("organizer.MinifigurePart", {"minifigure": "minifigure_id", "part_number": "part_num", "element_id": "element_id", "name": "name", "color_id": "color_id", "color_name": "color_name", "quantity": "quantity", "owned_quantity": "owned_quantity", "is_spare": "is_spare", "image_url": "image_url"}),
    "personal_notes": ("organizer.PersonalNote", {"owner": "user_id", "title": "title", "content": "content"}),
    "orders": ("orders.Order", {"owner": "user_id", "supplier": "supplier", "order_number": "order_number", "status": "status", "order_date": "order_date", "expected_delivery": "expected_delivery", "delivery_date": "delivery_date", "goods_total": "goods_total", "shipping_cost": "shipping_cost", "total": "total", "currency": "currency", "payment_status": "payment_status", "shipping_status": "shipping_status", "tracking_number": "tracking_number", "tracking_url": "tracking_url", "notes": "notes", "deleted_at": "deleted_at"}),
    "order_items": ("orders.OrderItem", {"order": "order_id", "inventory_item": "inventory_item_id", "target_set": "target_set_id", "target_location": "target_location_id", "part_number": "part_number", "name": "name", "color": "color", "quantity": "quantity", "received_quantity": "received_quantity", "damaged_quantity": "damaged_quantity", "wrong_quantity": "wrong_quantity", "unit_price": "unit_price", "notes": "notes"}),
    "mocs": ("organizer.Moc", {"owner": "user_id", "collection": "collection_id", "location": "location_id", "name": "name", "project_code": "project_code", "description": "description", "status": "status", "version": "version", "progress": "progress", "instruction_url": "instruction_url", "image_url": "image_url", "notes": "notes", "deleted_at": "deleted_at"}),
    "moc_parts": ("organizer.MocPart", {"moc": "moc_id", "inventory_item": "inventory_item_id", "part_number": "part_number", "name": "name", "color": "color", "required_quantity": "required_quantity", "allocated_quantity": "allocated_quantity", "notes": "notes"}),
    "moc_versions": ("organizer.MocVersion", {"moc": "moc_id", "version": "version", "description": "description", "parts_snapshot": "parts_snapshot"}),
    "wishlist": ("organizer.WishlistItem", {"owner": "user_id", "collection": "collection_id", "entity_type": "entity_type", "reference": "reference", "name": "name", "priority": "priority", "target_price": "target_price", "notes": "notes"}),
    "loans": ("organizer.Loan", {"owner": "user_id", "entity_type": "entity_type", "entity_id": "entity_id", "borrower": "borrower", "loaned_at": "loaned_at", "due_at": "due_at", "returned_at": "returned_at", "notes": "notes"}),
    "price_history": ("integrations.PriceObservation", {"entity_type": "entity_type", "entity_id": "entity_id", "price": "price", "shipping": "shipping", "currency": "currency", "source": "source", "supplier": "supplier", "is_estimate": "is_estimate", "note": "note", "recorded_at": "recorded_at"}),
    "value_snapshots": ("integrations.ValueSnapshot", {"owner": "user_id", "collection_value": "collection_value", "missing_cost": "missing_cost", "warehouse_quantity": "warehouse_quantity", "captured_at": "captured_at"}),
    "notifications": ("core.Notification", {"owner": "user_id", "kind": "kind", "title": "title", "message": "message", "entity_type": "entity_type", "entity_id": "entity_id", "read_at": "read_at"}),
    "label_templates": ("organizer.LabelTemplate", {"owner": "user_id", "name": "name", "width_mm": "width_mm", "height_mm": "height_mm", "orientation": "orientation", "configuration": "configuration", "is_default": "is_default"}),
    "saved_views": ("core.SavedView", {"owner": "user_id", "area": "area", "name": "name", "path": "configuration", "configuration": "configuration", "is_default": "is_default"}),
    "recent_items": ("core.RecentItem", {"owner": "user_id", "entity_type": "entity_type", "entity_id": "entity_id", "label": "label", "path": "entity_id"}),
    "data_quality_issues": ("core.DataQualityIssue", {"owner": "user_id", "issue_key": "issue_key", "entity_type": "entity_type", "entity_id": "entity_id", "severity": "severity", "message": "message"}),
}

RELATION_FIELDS = {"owner", "actor", "lego_set", "part", "parent", "location", "item", "minifigure", "order", "inventory_item", "target_set", "target_location", "collection", "moc"}
NONNEGATIVE = {"quantity", "owned_quantity", "required_quantity", "allocated_quantity", "reserved_quantity", "old_quantity", "new_quantity", "old_reserved", "new_reserved", "capacity", "total_parts", "minifigures", "progress", "warehouse_quantity", "received_quantity", "damaged_quantity", "wrong_quantity", "unassigned_found_quantity"}
GENERATED_TIMESTAMP_FIELDS = {
    ("history", "created_at"), ("loans", "loaned_at"),
    ("price_history", "recorded_at"), ("value_snapshots", "captured_at"),
}


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _datetime(value):
    if value is None or value == "":
        return None
    parsed = parse_datetime(str(value))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed.astimezone(UTC).isoformat() if parsed else None


def _expected(field, model_field, value, row):
    if field in RELATION_FIELDS:
        return int(value) if value is not None else None
    if field == "email":
        normalized = f"legacy-{row['id']}@invalid.local" if value is None or value == "" else value
        return str(normalized).strip().casefold()
    if field == "username":
        normalized = f"legacy-{row['id']}" if value is None or value == "" else value
        return str(normalized).strip()
    if field == "part_number" and model_field.model._meta.label == "catalog.Part":
        return ""
    if field == "path" and "configuration" in row.keys():
        try:
            configuration = json.loads(value if value is not None and value != "" else "{}")
        except (TypeError, ValueError):
            configuration = {}
        return str(configuration.get("path", "/"))[:255]
    if field == "path":
        return "/"
    if field == "email_verified":
        return bool(value)
    if field == "is_staff":
        return value == "admin"
    if field == "is_active":
        return not bool(value if value is not None else row["deleted_at"])
    if field == "parts_snapshot" or field == "configuration":
        try:
            fallback = "[]" if field == "parts_snapshot" else "{}"
            parsed = json.loads(fallback if value is None or value == "" else value)
        except (TypeError, ValueError):
            parsed = [] if field == "parts_snapshot" else {}
        if field == "configuration" and "path" in parsed:
            parsed = {key: item for key, item in parsed.items() if key != "path"}
        return parsed
    if isinstance(model_field, models.BooleanField):
        return bool(value)
    if isinstance(model_field, models.DecimalField):
        try:
            normalized = 0 if value is None or value == "" else value
            return str(max(Decimal(str(normalized)), Decimal("0")).quantize(Decimal(1).scaleb(-model_field.decimal_places)))
        except InvalidOperation:
            return str(Decimal("0").quantize(Decimal(1).scaleb(-model_field.decimal_places)))
    if isinstance(model_field, models.DateTimeField):
        return _datetime(value)
    if isinstance(model_field, models.DateField):
        parsed = parse_date("" if value is None else str(value))
        return parsed.isoformat() if parsed else None
    if isinstance(model_field, (models.IntegerField, models.BigIntegerField)):
        number = int(0 if value is None or value == "" else value)
        return max(number, 0) if field in NONNEGATIVE else number
    if field == "entity_id":
        return "" if value is None else str(value)
    if value in {None, ""} and model_field.has_default():
        default = model_field.get_default()
        return default if default is not None else ""
    return "" if value is None else value


def _actual(field, model_field, obj):
    value = getattr(obj, field)
    if field in RELATION_FIELDS:
        return getattr(value, "legacy_id", None) if value else None
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal(1).scaleb(-model_field.decimal_places)))
    if isinstance(value, datetime):
        return _datetime(value.isoformat())
    if isinstance(value, date):
        return value.isoformat()
    return value


class Command(BaseCommand):
    help = "Reconciles normalized legacy values and relationships against Django rows."

    def add_arguments(self, parser):
        sources = parser.add_mutually_exclusive_group(required=True)
        sources.add_argument("--source", type=Path)
        sources.add_argument("--source-db-alias")
        parser.add_argument("--output", type=Path)

    def handle(self, *args, **options):
        try:
            legacy = open_legacy_source(
                path=options.get("source"), alias=options.get("source_db_alias")
            )
            legacy.validate()
        except (LegacySourceError, OSError) as exc:
            raise CommandError(f"Legacy source could not be read: {exc}") from exc
        before = legacy.fingerprint()
        results, mismatches = [], []
        try:
            tables = legacy.table_names()
            for table, (label, field_map) in MAPPINGS.items():
                if table not in tables:
                    continue
                model = apps.get_model(label)
                rows = list(legacy.execute(f"SELECT * FROM `{table}` ORDER BY id"))  # noqa: S608
                if table == "history":
                    valid_part_ids = {row[0] for row in legacy.execute("SELECT id FROM parts")}
                    rows = [row for row in rows if row["part_id"] in valid_part_ids]
                if table == "data_quality_issues":
                    rows = [row for row in rows if row["status"] == "open"]
                checked = 0
                relationship_checks = 0
                table_mismatches = 0
                source_keys = {int(row["id"]) for row in rows}
                target_keys = set(
                    model.objects.filter(legacy_id__isnull=False).values_list(
                        "legacy_id", flat=True
                    )
                )
                for extra in sorted(target_keys - source_keys):
                    mismatches.append({"table": table, "legacy_id": extra, "field": "legacy_id", "reason": "unexplained extra target row"})
                    table_mismatches += 1
                for row in rows:
                    obj = model.objects.filter(legacy_id=row["id"]).first()
                    if not obj:
                        mismatches.append({"table": table, "legacy_id": row["id"], "field": "legacy_id", "reason": "missing target row"})
                        table_mismatches += 1
                        continue
                    for target_field, source_field in field_map.items():
                        if source_field not in row.keys():
                            mismatches.append({"table": table, "legacy_id": row["id"], "field": target_field, "reason": f"legacy column {source_field} missing"})
                            table_mismatches += 1
                            continue
                        model_field = model._meta.get_field(target_field)
                        expected = _expected(target_field, model_field, row[source_field], row)
                        actual = _actual(target_field, model_field, obj)
                        # Missing source timestamps have one explicit invariant: importer-generated,
                        # timezone-aware and non-null. It is never copied from the target as expected.
                        if (
                            (table, target_field) in GENERATED_TIMESTAMP_FIELDS
                            and (row[source_field] is None or row[source_field] == "")
                        ):
                            expected = "generated-aware-datetime"
                            actual = "generated-aware-datetime" if actual else "missing-generated-timestamp"
                        checked += 1
                        relationship_checks += int(target_field in RELATION_FIELDS)
                        if expected != actual:
                            reason = "normalized values differ"
                            if isinstance(model_field, models.DateTimeField):
                                reason += f" ({expected} != {actual})"
                            mismatches.append({"table": table, "legacy_id": row["id"], "field": target_field, "expected_hash": _hash(expected), "actual_hash": _hash(actual), "reason": reason})
                            table_mismatches += 1
                    if table == "set_copies":
                        source_owner = legacy.execute(
                            "SELECT user_id FROM sets WHERE id = ?", (row["set_id"],)
                        )
                        expected_owner = source_owner[0][0] if source_owner else None
                        actual_owner = getattr(obj.owner, "legacy_id", None)
                        relationship_checks += 1
                        if expected_owner != actual_owner:
                            mismatches.append({"table": table, "legacy_id": row["id"], "field": "owner", "expected_hash": _hash(expected_owner), "actual_hash": _hash(actual_owner), "reason": "normalized values differ"})
                            table_mismatches += 1
                    if table == "price_history":
                        source_model = {
                            "set": "catalog.LegoSet",
                            "inventory": "inventory.InventoryItem",
                            "inventory_item": "inventory.InventoryItem",
                            "part": "inventory.InventoryItem",
                            "moc": "organizer.Moc",
                        }.get(row["entity_type"])
                        target = apps.get_model(source_model).objects.filter(legacy_id=row["entity_id"]).first() if source_model else None
                        expected_owner = getattr(getattr(target, "owner", None), "legacy_id", None)
                        actual_owner = getattr(obj.owner, "legacy_id", None) if obj.owner else None
                        relationship_checks += 1
                        if expected_owner != actual_owner:
                            mismatches.append({"table": table, "legacy_id": row["id"], "field": "owner", "expected_hash": _hash(expected_owner), "actual_hash": _hash(actual_owner), "reason": "normalized values differ"})
                            table_mismatches += 1
                results.append({"table": table, "rows_checked": len(rows), "value_fields_checked": checked, "relationships_checked": relationship_checks, "mismatches": table_mismatches, "result": "PASS" if not table_mismatches else "FAIL"})

            if "collection_members" in tables:
                Member = apps.get_model("organizer.CollectionMember")
                source_rows = list(legacy.execute("SELECT * FROM collection_members"))
                expected = {
                    (int(row["collection_id"]), int(row["user_id"])): row["role"] if row["role"] is not None and row["role"] != "" else "viewer"
                    for row in source_rows
                }
                actual = {
                    (item.collection.legacy_id, item.user.legacy_id): item.role
                    for item in Member.objects.select_related("collection", "user").filter(
                        collection__legacy_id__isnull=False, user__legacy_id__isnull=False
                    )
                }
                count = 0
                for key in sorted(set(expected) | set(actual)):
                    if expected.get(key) != actual.get(key):
                        mismatches.append({"table": "collection_members", "legacy_id": f"{key[0]}:{key[1]}", "field": "role", "expected_hash": _hash(expected.get(key)), "actual_hash": _hash(actual.get(key)), "reason": "membership missing, extra, or changed"})
                        count += 1
                results.append({"table": "collection_members", "rows_checked": len(source_rows), "value_fields_checked": len(source_rows), "relationships_checked": len(source_rows) * 2, "mismatches": count, "result": "PASS" if not count else "FAIL"})

            if "workshop_documents" in tables:
                Workshop = apps.get_model("organizer.WorkshopDocument")
                source_rows = list(legacy.execute("SELECT * FROM workshop_documents"))
                count = 0
                for row in source_rows:
                    try:
                        expected_payload = json.loads(row["payload"] if row["payload"] is not None and row["payload"] != "" else "{}")
                    except (TypeError, ValueError):
                        expected_payload = {"legacy_raw": row["payload"]}
                    item = Workshop.objects.filter(owner__legacy_id=row["user_id"]).first()
                    if not item or item.payload != expected_payload:
                        mismatches.append({"table": "workshop_documents", "legacy_id": row["user_id"], "field": "payload", "expected_hash": _hash(expected_payload), "actual_hash": _hash(item.payload if item else None), "reason": "document missing or changed"})
                        count += 1
                results.append({"table": "workshop_documents", "rows_checked": len(source_rows), "value_fields_checked": len(source_rows), "relationships_checked": len(source_rows), "mismatches": count, "result": "PASS" if not count else "FAIL"})

            if "audit_log" in tables:
                Event = apps.get_model("audit.AuditEvent")
                source_rows = list(legacy.execute("SELECT * FROM audit_log ORDER BY id"))
                valid_user_ids = {row[0] for row in legacy.execute("SELECT id FROM users")}
                count = 0
                for row in source_rows:
                    item = Event.objects.filter(details__legacy_id=row["id"]).first()
                    try:
                        expected_details = json.loads(
                            row["details"]
                            if row["details"] is not None and row["details"] != ""
                            else "{}"
                        )
                    except (TypeError, ValueError):
                        expected_details = {"legacy_details": row["details"] or ""}
                    expected_details = {**expected_details, "legacy_id": row["id"]}
                    expected_actor = (
                        int(row["actor_id"]) if row["actor_id"] in valid_user_ids else None
                    )
                    expected_target = (
                        int(row["target_user_id"])
                        if row["target_user_id"] in valid_user_ids
                        else None
                    )
                    expected_remote = row["remote_address"] or None
                    expected_created = _datetime(row["created_at"])
                    actual_actor = getattr(item.actor, "legacy_id", None) if item and item.actor else None
                    actual_target = getattr(item.target_user, "legacy_id", None) if item and item.target_user else None
                    actual_created = _datetime(item.created_at) if item else None
                    differences = []
                    if not item:
                        differences.append("missing")
                    else:
                        if item.action != f"legacy.{row['action']}":
                            differences.append("action")
                        if item.details != expected_details:
                            differences.append("details")
                        if actual_actor != expected_actor:
                            differences.append("actor")
                        if actual_target != expected_target:
                            differences.append("target")
                        if row["actor_id"] is not None and row["actor_id"] not in valid_user_ids and item.actor_identifier != f"legacy-user:{row['actor_id']}":
                            differences.append("actor_identifier")
                        if row["target_user_id"] is not None and row["target_user_id"] not in valid_user_ids and item.target_identifier != f"legacy-user:{row['target_user_id']}":
                            differences.append("target_identifier")
                        if item.remote_address != expected_remote:
                            differences.append("remote_address")
                        if expected_created is not None and actual_created != expected_created:
                            differences.append("created_at")
                        if expected_created is None and actual_created is None:
                            differences.append("created_at")
                    if differences:
                        mismatches.append({"table": "audit_log", "legacy_id": row["id"], "field": "event", "reason": f"audit mismatch: {','.join(differences)}"})
                        count += 1
                results.append({"table": "audit_log", "rows_checked": len(source_rows), "value_fields_checked": len(source_rows) * 3, "relationships_checked": len(source_rows) * 2, "mismatches": count, "result": "PASS" if not count else "FAIL"})

            if "history" in tables:
                valid_part_ids = {row[0] for row in legacy.execute("SELECT id FROM parts")}
                orphans = [dict(row) for row in legacy.execute("SELECT * FROM history ORDER BY id") if row["part_id"] not in valid_part_ids]
                archived = {
                    record.source_pk: record.payload
                    for record in LegacyArchiveRecord.objects.filter(
                        source_fingerprint=before,
                        source_table="history",
                        classification="orphaned_relation_preserved",
                    )
                }
                for row in orphans:
                    if archived.get(str(row["id"])) != row:
                        mismatches.append({"table": "history_orphans", "legacy_id": row["id"], "field": "payload", "reason": "lossless archive mismatch"})
                expected_orphan_keys = {str(row["id"]) for row in orphans}
                for extra in sorted(set(archived) - expected_orphan_keys):
                    mismatches.append({"table": "history_orphans", "legacy_id": extra, "field": "payload", "reason": "unexplained extra orphan archive"})
                results.append({"table": "history_orphans", "rows_checked": len(orphans), "value_fields_checked": sum(len(row) for row in orphans), "relationships_checked": 0, "mismatches": sum(1 for item in mismatches if item["table"] == "history_orphans"), "result": "PASS" if not any(item["table"] == "history_orphans" for item in mismatches) else "FAIL"})
            after = legacy.fingerprint()
        finally:
            legacy.close()
        report = {"version": 2, "source_sha256": before, "source_unchanged": before == after, "mismatch_count": len(mismatches), "status": "PASS" if before == after and not mismatches else "FAIL", "tables": results, "mismatches": mismatches}
        rendered = json.dumps(report, indent=2, sort_keys=True)
        if options["output"]:
            output = options["output"].resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8", newline="\n")
        self.stdout.write(rendered)
        if report["status"] != "PASS":
            sample = "; ".join(
                f"{item['table']}:{item['legacy_id']}:{item['field']}:{item['reason']}"
                for item in mismatches[:10]
            )
            raise CommandError(
                f"Legacy reconciliation failed with {len(mismatches)} mismatch(es): {sample}"
            )
