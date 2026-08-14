from __future__ import annotations

import io
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet, Part, PartHistory, SetCopy, SetInventoryItem
from apps.core.models import DataQualityIssue, Notification, RecentItem, SavedView
from apps.data_portability.legacy_source import LegacySourceError, open_legacy_source
from apps.data_portability.models import LegacyArchiveRecord, LegacyImportRecord
from apps.integrations.models import PriceObservation, ValueSnapshot
from apps.inventory.models import InventoryItem, InventoryMovement, WarehouseLocation
from apps.orders.models import Order, OrderItem
from apps.organizer.models import (
    Collection,
    CollectionMember,
    LabelTemplate,
    Loan,
    MinifigurePart,
    Moc,
    MocPart,
    MocVersion,
    PersonalNote,
    SetMinifigure,
    WishlistItem,
    WorkshopDocument,
)

TABLES = {"users", "sets", "parts", "set_inventory", "history"}
SECURITY_RUNTIME_TABLES = {
    "account_tokens",
    "sessions",
    "trusted_devices",
    "background_jobs",
    "schema_migrations",
    "system_health",
}


def aware_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def money(value):
    try:
        return max(Decimal(str(value or 0)), Decimal("0"))
    except InvalidOperation:
        return Decimal("0")


def legacy_password(encoded):
    """Return Django-compatible V7 PBKDF2 encoding or None for forced reset."""
    if not encoded or not isinstance(encoded, str):
        return None
    fields = encoded.split("$")
    if len(fields) != 4 or fields[0] != "pbkdf2_sha256":
        return None
    try:
        if int(fields[1]) <= 0:
            return None
    except ValueError:
        return None
    return f"brickmissing_{encoded}"


class Command(BaseCommand):
    help = "Imports BrickMissing 7 from read-only SQLite or MariaDB into Django."

    def add_arguments(self, parser):
        sources = parser.add_mutually_exclusive_group(required=True)
        sources.add_argument("--source", type=Path)
        sources.add_argument("--source-db-alias")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        try:
            alias = options.get("source_db_alias")
            if alias:
                target = connections["default"].settings_dict
                source_settings = connections[alias].settings_dict if alias in connections else {}
                def identity(cfg):
                    host = str(cfg.get("HOST") or "localhost").casefold()
                    host = "loopback" if host in {"localhost", "127.0.0.1", "::1"} else host
                    return (
                        host,
                        str(cfg.get("PORT") or "3306"),
                        str(cfg.get("NAME") or "").casefold(),
                    )
                if source_settings and identity(source_settings) == identity(target):
                    raise CommandError("Legacy source and target database must be different")
            legacy = open_legacy_source(path=options.get("source"), alias=alias)
            legacy.validate()
            existing = legacy.table_names()
            missing = TABLES - existing
            if missing:
                raise CommandError(
                    f"Erforderliche Legacy-Tabellen fehlen: {', '.join(sorted(missing))}"
                )
            fingerprint = legacy.fingerprint()
            with transaction.atomic(using="default"):
                summary = self._import(legacy, fingerprint)
                if dry_run:
                    reconciliation_options = {"stdout": io.StringIO()}
                    if alias:
                        reconciliation_options["source_db_alias"] = alias
                    else:
                        reconciliation_options["source"] = options["source"]
                    call_command("validate_legacy_migration", **reconciliation_options)
                    summary["Reconciliation"] = "PASS"
                    transaction.set_rollback(True, using="default")
        except (LegacySourceError, OSError) as exc:
            raise CommandError(f"Legacy-Datenbank konnte nicht gelesen werden: {exc}") from exc
        finally:
            if "legacy" in locals():
                legacy.close()
        prefix = "DRY-RUN – " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(prefix + "Legacy-Migration validiert/abgeschlossen"))
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")

    def _record(self, fingerprint, table, source_pk, instance):
        LegacyImportRecord.objects.update_or_create(
            source_fingerprint=fingerprint,
            source_table=table,
            source_pk=str(source_pk),
            defaults={"target_model": instance._meta.label_lower, "target_pk": str(instance.pk)},
        )

    def _import(self, legacy, fingerprint):
        counts = {
            "Users": 0,
            "Sets": 0,
            "Set copies": 0,
            "Parts": 0,
            "Set inventory": 0,
            "History": 0,
            "Collections": 0,
            "Collection members": 0,
            "Inventory items": 0,
            "Inventory movements": 0,
            "Locations": 0,
            "Minifigures": 0,
            "Minifigure parts": 0,
            "Notes": 0,
            "Orders": 0,
            "Order items": 0,
            "MOCs": 0,
            "MOC parts": 0,
            "MOC versions": 0,
            "Wishlist": 0,
            "Loans": 0,
            "Price observations": 0,
            "Value snapshots": 0,
            "Notifications": 0,
            "Workshop documents": 0,
            "Audit events": 0,
            "Label templates": 0,
            "Saved views": 0,
            "Recent items": 0,
            "Data quality issues": 0,
            "Archived auxiliary rows": 0,
            "Skipped security/runtime rows": 0,
        }
        users = {}
        for row in legacy.execute("SELECT * FROM users ORDER BY id"):
            username = (row["name"] or f"legacy-{row['id']}").strip()
            email = (row["email"] or f"legacy-{row['id']}@invalid.local").strip().casefold()
            user = User.objects.filter(legacy_id=row["id"]).first()
            manually_verified = bool(user and user.email_verified)
            if user and not user.has_placeholder_email and email.endswith("@invalid.local"):
                email = user.email
            defaults = {
                "username": username,
                "email": email,
                "email_verified": manually_verified or bool(row["email_verified_at"]),
                "is_active": bool(user and user.deactivated_at is None or not user) and not bool(row["disabled"] or row["deleted_at"]),
                "is_staff": row["role"] == "admin",
                "is_superuser": False,
            }
            if user:
                for field, value in defaults.items():
                    setattr(user, field, value)
                user.save()
            else:
                user = User.objects.create(legacy_id=row["id"], **defaults)
            encoded = legacy_password(row["password_hash"])
            if encoded:
                user.password = encoded
            else:
                user.set_unusable_password()
            user.save(update_fields=["password"])
            users[row["id"]] = user
            self._record(fingerprint, "users", row["id"], user)
            counts["Users"] += 1

        sets = {}
        for row in legacy.execute("SELECT * FROM sets ORDER BY id"):
            owner = users.get(row["user_id"])
            if not owner:
                raise CommandError(
                    f"Set {row['id']} verweist auf unbekannten User {row['user_id']}"
                )
            item, _ = LegoSet.objects.update_or_create(
                owner=owner,
                legacy_id=row["id"],
                defaults={
                    "set_number": row["set_number"],
                    "name": row["name"],
                    "theme": row["theme"] or "",
                    "subtheme": row["subtheme"] or "",
                    "year": row["year"],
                    "total_parts": max(row["total_parts"] or 0, 0),
                    "minifigures": max(row["minifigures"] or 0, 0),
                    "description": row["description"] or "",
                    "condition": row["condition"] or "gebraucht",
                    "completeness": row["completeness"] or "unbekannt",
                    "build_status": row["build_status"] or "zerlegt vollständig",
                    "favorite": bool(row["favorite"]),
                    "image_url": row["image_url"] or "",
                    "purchase_date": parse_date(row["purchase_date"] or ""),
                    "purchase_price": money(row["purchase_price"]),
                    "current_value": money(row["current_value"]),
                    "has_box": bool(row["has_box"]),
                    "has_instructions": bool(row["has_instructions"]),
                    "has_stickers": bool(row["has_stickers"]),
                    "notes": row["notes"] or "",
                    "deleted_at": aware_datetime(row["deleted_at"]),
                },
            )
            sets[row["id"]] = item
            self._record(fingerprint, "sets", row["id"], item)
            counts["Sets"] += 1

        if self._has_table(legacy, "set_copies"):
            for row in legacy.execute("SELECT * FROM set_copies ORDER BY id"):
                lego_set = sets.get(row["set_id"])
                if lego_set:
                    SetCopy.objects.update_or_create(
                        owner=lego_set.owner,
                        legacy_id=row["id"],
                        defaults={
                            "lego_set": lego_set,
                            "inventory_number": row["inventory_number"] or "",
                            "serial_number": row["serial_number"] or "",
                            "condition": row["condition"] or "gebraucht",
                            "completeness": row["completeness"] or "unbekannt",
                            "build_status": row["build_status"] or "zerlegt vollständig",
                            "purchase_date": parse_date(row["purchase_date"] or ""),
                            "purchase_price": money(row["purchase_price"]),
                            "notes": row["notes"] or "",
                            "image_url": row["image_url"] or "",
                            "deleted_at": aware_datetime(row["deleted_at"]),
                        },
                    )
                    counts["Set copies"] += 1

        parts = {}
        for row in legacy.execute("SELECT * FROM parts ORDER BY id"):
            owner = users.get(row["user_id"])
            if not owner:
                raise CommandError(
                    f"Teil {row['id']} verweist auf unbekannten User {row['user_id']}"
                )
            quantity = max(row["quantity"] or 0, 0)
            owned = min(max(row["owned_quantity"] or 0, 0), quantity)
            status = row["status"] if row["status"] in Part.Status.values else Part.Status.MISSING
            item, _ = Part.objects.update_or_create(
                owner=owner,
                legacy_id=row["id"],
                defaults={
                    "lego_set": sets.get(row["set_id"]),
                    "element_id": row["element_id"] or f"legacy-{row['id']}",
                    "design_id": row["design_id"] or "",
                    "name": row["name"] or "Unbenannt",
                    "color": row["color"] or "",
                    "quantity": quantity,
                    "owned_quantity": owned,
                    "unassigned_found_quantity": max(row["unassigned_found_quantity"] or 0, 0),
                    "is_present": bool(row["is_present"]),
                    "status": status,
                    "priority": row["priority"] or "normal",
                    "unit_price": money(row["unit_price"]),
                    "supplier": row["supplier"] or "",
                    "notes": row["notes"] or "",
                    "image_url": row["image_url"] or "",
                    "deleted_at": aware_datetime(row["deleted_at"]),
                },
            )
            parts[row["id"]] = item
            self._record(fingerprint, "parts", row["id"], item)
            counts["Parts"] += 1

        for row in legacy.execute("SELECT * FROM set_inventory ORDER BY id"):
            lego_set = sets.get(row["set_id"])
            if not lego_set:
                raise CommandError(
                    f"Set-Inventar {row['id']} verweist auf unbekanntes Set {row['set_id']}"
                )
            SetInventoryItem.objects.update_or_create(
                lego_set=lego_set,
                legacy_id=row["id"],
                defaults={
                    "part_number": row["part_num"],
                    "element_id": row["element_id"] or "",
                    "name": row["name"] or "Unbenannt",
                    "color_id": row["color_id"],
                    "color_name": row["color_name"] or "",
                    "required_quantity": max(row["required_quantity"] or 0, 0),
                    "owned_quantity": max(row["owned_quantity"] or 0, 0),
                    "is_spare": bool(row["is_spare"]),
                    "image_url": row["image_url"] or "",
                },
            )
            counts["Set inventory"] += 1

        for row in legacy.execute("SELECT * FROM history ORDER BY id"):
            part = parts.get(row["part_id"])
            if part:
                history_item, _ = PartHistory.objects.update_or_create(
                    legacy_id=row["id"],
                    defaults={
                        "part": part, "status": row["status"], "note": row["note"] or "",
                        "created_at": aware_datetime(row["created_at"]) or timezone.now(),
                    },
                )
                created = aware_datetime(row["created_at"])
                if created:
                    PartHistory.objects.filter(pk=history_item.pk).update(created_at=created)
                counts["History"] += 1
            else:
                LegacyArchiveRecord.objects.update_or_create(
                    source_fingerprint=fingerprint, source_table="history",
                    source_pk=str(row["id"]),
                    defaults={
                        "payload": {key: row[key] for key in row.keys()},
                        "classification": "orphaned_relation_preserved",
                    },
                )
                counts["Archived auxiliary rows"] += 1

        collections = {}
        if self._has_table(legacy, "collections"):
            for row in legacy.execute("SELECT * FROM collections ORDER BY id"):
                owner = users.get(row["owner_id"])
                if owner:
                    obj, _ = Collection.objects.update_or_create(
                        owner=owner,
                        legacy_id=row["id"],
                        defaults={
                            "name": row["name"],
                            "description": row["description"] or "",
                            "is_shared": bool(row["is_shared"]),
                        },
                    )
                    collections[row["id"]] = obj
                    counts["Collections"] += 1
        if self._has_table(legacy, "collection_members"):
            for row in legacy.execute("SELECT * FROM collection_members"):
                collection, user = collections.get(row["collection_id"]), users.get(row["user_id"])
                if collection and user:
                    CollectionMember.objects.update_or_create(
                        collection=collection, user=user, defaults={"role": row["role"] or "viewer"}
                    )
                    counts["Collection members"] += 1

        locations = {}
        if self._has_table(legacy, "warehouse_locations"):
            location_rows = list(legacy.execute("SELECT * FROM warehouse_locations ORDER BY id"))
            for row in location_rows:
                owner = users.get(row["user_id"])
                if owner:
                    obj, _ = WarehouseLocation.objects.update_or_create(
                        owner=owner,
                        legacy_id=row["id"],
                        defaults={
                            "name": row["name"],
                            "location_type": row["location_type"] or "Box",
                            "capacity": max(row["capacity"] or 0, 0),
                            "photo_url": row["photo_url"] or "",
                            "notes": row["notes"] or "",
                            "short_code": row["short_code"] or "",
                            "description": row["description"] or "",
                            "room": row["room"] or "",
                            "color": row["color"] or "",
                            "active": bool(row["active"]),
                            "locked": bool(row["locked"]),
                            "archived_at": aware_datetime(row["archived_at"]),
                        },
                    )
                    locations[row["id"]] = obj
                    counts["Locations"] += 1
            for row in location_rows:
                if row["parent_id"] and row["id"] in locations and row["parent_id"] in locations:
                    locations[row["id"]].parent = locations[row["parent_id"]]
                    locations[row["id"]].save(update_fields=["parent"])

        inventory = {}
        if self._has_table(legacy, "inventory_items"):
            for row in legacy.execute("SELECT * FROM inventory_items ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    obj, _ = InventoryItem.objects.update_or_create(
                        owner=owner,
                        legacy_id=row["id"],
                        defaults={
                            "part_number": row["part_number"],
                            "design_id": row["design_id"] or "",
                            "element_id": row["element_id"] or "",
                            "name": row["name"],
                            "color": row["color"] or "",
                            "category": row["category"] or "",
                            "subcategory": row["subcategory"] or "",
                            "quantity": max(row["quantity"] or 0, 0),
                            "reserved_quantity": max(row["reserved_quantity"] or 0, 0),
                            "condition": row["condition"] or "gebraucht",
                            "location": locations.get(row["location_id"]),
                            "image_url": row["image_url"] or "",
                            "source": row["source"] or "",
                            "purchase_price": money(row["purchase_price"]),
                            "unit_price": money(row["unit_price"]),
                            "notes": row["notes"] or "",
                            "archived_at": aware_datetime(row["archived_at"]),
                        },
                    )
                    inventory[row["id"]] = obj
                    counts["Inventory items"] += 1
        if self._has_table(legacy, "inventory_movements"):
            for row in legacy.execute("SELECT * FROM inventory_movements ORDER BY id"):
                item = inventory.get(row["inventory_item_id"])
                if item:
                    InventoryMovement.objects.update_or_create(
                        item=item,
                        legacy_id=row["id"],
                        defaults={
                            "movement_type": row["movement_type"],
                            "old_quantity": max(row["old_quantity"], 0),
                            "new_quantity": max(row["new_quantity"], 0),
                            "difference": row["difference"],
                            "old_reserved": max(row["old_reserved"] or 0, 0),
                            "new_reserved": max(row["new_reserved"] or 0, 0),
                            "source": row["source"] or "",
                            "destination": row["destination"] or "",
                            "actor": users.get(row["user_id"]),
                            "note": row["note"] or "",
                        },
                    )
                    counts["Inventory movements"] += 1

        figures = {}
        if self._has_table(legacy, "set_minifigures"):
            for row in legacy.execute("SELECT * FROM set_minifigures ORDER BY id"):
                owner, lego_set = users.get(row["user_id"]), sets.get(row["set_id"])
                if owner and lego_set:
                    obj, _ = SetMinifigure.objects.update_or_create(
                        owner=owner,
                        legacy_id=row["id"],
                        defaults={
                            "lego_set": lego_set,
                            "figure_number": row["fig_number"],
                            "name": row["name"],
                            "quantity": max(row["quantity"], 1),
                            "owned_quantity": max(row["owned_quantity"] or 0, 0),
                            "image_url": row["image_url"] or "",
                            "notes": row["notes"] or "",
                        },
                    )
                    figures[row["id"]] = obj
                    counts["Minifigures"] += 1
        if self._has_table(legacy, "minifigure_parts"):
            for row in legacy.execute("SELECT * FROM minifigure_parts ORDER BY id"):
                figure = figures.get(row["minifigure_id"])
                if figure:
                    MinifigurePart.objects.update_or_create(
                        minifigure=figure,
                        legacy_id=row["id"],
                        defaults={
                            "part_number": row["part_num"],
                            "element_id": row["element_id"] or "",
                            "name": row["name"],
                            "color_id": row["color_id"],
                            "color_name": row["color_name"] or "",
                            "quantity": max(row["quantity"], 1),
                            "owned_quantity": max(row["owned_quantity"] or 0, 0),
                            "is_spare": bool(row["is_spare"]),
                            "image_url": row["image_url"] or "",
                        },
                    )
                    counts["Minifigure parts"] += 1
        if self._has_table(legacy, "personal_notes"):
            for row in legacy.execute("SELECT * FROM personal_notes ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    PersonalNote.objects.update_or_create(
                        owner=owner,
                        legacy_id=row["id"],
                        defaults={"title": row["title"], "content": row["content"]},
                    )
                    counts["Notes"] += 1

        orders = {}
        if self._has_table(legacy, "orders"):
            for row in legacy.execute("SELECT * FROM orders ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    obj, _ = Order.objects.update_or_create(
                        owner=owner,
                        legacy_id=row["id"],
                        defaults={
                            "supplier": row["supplier"], "order_number": row["order_number"] or "",
                            "status": row["status"] or "ordered", "order_date": parse_date(row["order_date"] or ""),
                            "expected_delivery": parse_date(row["expected_delivery"] or ""),
                            "delivery_date": parse_date(row["delivery_date"] or ""),
                            "goods_total": money(row["goods_total"]), "shipping_cost": money(row["shipping_cost"]),
                            "total": money(row["total"]), "currency": row["currency"] or "EUR",
                            "payment_status": row["payment_status"] or "", "shipping_status": row["shipping_status"] or "",
                            "tracking_number": row["tracking_number"] or "", "tracking_url": row["tracking_url"] or "",
                            "notes": row["notes"] or "", "deleted_at": aware_datetime(row["deleted_at"]),
                        },
                    )
                    orders[row["id"]] = obj
                    counts["Orders"] += 1
        if self._has_table(legacy, "order_items"):
            for row in legacy.execute("SELECT * FROM order_items ORDER BY id"):
                order = orders.get(row["order_id"])
                if order:
                    quantity = max(row["quantity"] or 1, 1)
                    OrderItem.objects.update_or_create(
                        order=order, legacy_id=row["id"],
                        defaults={
                            "inventory_item": inventory.get(row["inventory_item_id"]), "part_number": row["part_number"],
                            "name": row["name"] or "", "color": row["color"] or "", "quantity": quantity,
                            "received_quantity": min(max(row["received_quantity"] or 0, 0), quantity),
                            "damaged_quantity": min(max(row["damaged_quantity"] or 0, 0), quantity),
                            "wrong_quantity": max(row["wrong_quantity"] or 0, 0), "unit_price": money(row["unit_price"]),
                            "target_set": sets.get(row["target_set_id"]), "target_location": locations.get(row["target_location_id"]),
                            "notes": row["notes"] or "",
                        },
                    )
                    counts["Order items"] += 1

        mocs = {}
        if self._has_table(legacy, "mocs"):
            for row in legacy.execute("SELECT * FROM mocs ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    obj, _ = Moc.objects.update_or_create(
                        owner=owner, legacy_id=row["id"],
                        defaults={"collection": collections.get(row["collection_id"]), "location": locations.get(row["location_id"]),
                                  "name": row["name"], "project_code": row["project_code"] or "", "description": row["description"] or "",
                                  "status": row["status"] or "Planung", "version": row["version"] or "1.0", "progress": min(max(row["progress"] or 0, 0), 100),
                                  "instruction_url": row["instruction_url"] or "", "image_url": row["image_url"] or "", "notes": row["notes"] or "",
                                  "deleted_at": aware_datetime(row["deleted_at"])},
                    )
                    mocs[row["id"]] = obj
                    counts["MOCs"] += 1
        if self._has_table(legacy, "moc_parts"):
            for row in legacy.execute("SELECT * FROM moc_parts ORDER BY id"):
                moc = mocs.get(row["moc_id"])
                if moc:
                    MocPart.objects.update_or_create(moc=moc, legacy_id=row["id"], defaults={"inventory_item": inventory.get(row["inventory_item_id"]), "part_number": row["part_number"], "name": row["name"] or "", "color": row["color"] or "", "required_quantity": max(row["required_quantity"] or 0, 0), "allocated_quantity": max(row["allocated_quantity"] or 0, 0), "notes": row["notes"] or ""})
                    counts["MOC parts"] += 1
        if self._has_table(legacy, "moc_versions"):
            for row in legacy.execute("SELECT * FROM moc_versions ORDER BY id"):
                moc = mocs.get(row["moc_id"])
                if moc:
                    try:
                        snapshot = json.loads(row["parts_snapshot"] or "[]")
                    except (TypeError, ValueError):
                        snapshot = []
                    MocVersion.objects.update_or_create(moc=moc, legacy_id=row["id"], defaults={"version": row["version"], "description": row["description"] or "", "parts_snapshot": snapshot})
                    counts["MOC versions"] += 1

        if self._has_table(legacy, "wishlist"):
            for row in legacy.execute("SELECT * FROM wishlist ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    WishlistItem.objects.update_or_create(owner=owner, legacy_id=row["id"], defaults={"collection": collections.get(row["collection_id"]), "entity_type": row["entity_type"] or "set", "reference": row["reference"], "name": row["name"], "priority": row["priority"] or "normal", "target_price": money(row["target_price"]), "notes": row["notes"] or ""})
                    counts["Wishlist"] += 1
        if self._has_table(legacy, "loans"):
            for row in legacy.execute("SELECT * FROM loans ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    Loan.objects.update_or_create(owner=owner, legacy_id=row["id"], defaults={"entity_type": row["entity_type"], "entity_id": str(row["entity_id"]), "borrower": row["borrower"], "loaned_at": aware_datetime(row["loaned_at"]) or timezone.now(), "due_at": aware_datetime(row["due_at"]), "returned_at": aware_datetime(row["returned_at"]), "notes": row["notes"] or ""})
                    counts["Loans"] += 1
        if self._has_table(legacy, "price_history"):
            for row in legacy.execute("SELECT * FROM price_history ORDER BY id"):
                entity_type = row["entity_type"]
                entity_id = row["entity_id"]
                target = sets.get(entity_id) if entity_type == "set" else inventory.get(entity_id) if entity_type in {"inventory", "inventory_item", "part"} else mocs.get(entity_id) if entity_type == "moc" else None
                owner = getattr(target, "owner", None)
                PriceObservation.objects.update_or_create(
                    legacy_id=row["id"],
                    defaults={"owner": owner, "entity_type": entity_type, "entity_id": str(entity_id), "price": money(row["price"]), "shipping": money(row["shipping"]), "currency": row["currency"] or "EUR", "source": row["source"] or "", "supplier": row["supplier"] or "", "is_estimate": bool(row["is_estimate"]), "note": row["note"] or "", "recorded_at": aware_datetime(row["recorded_at"]) or timezone.now()},
                )
                counts["Price observations"] += 1
        if self._has_table(legacy, "value_snapshots"):
            for row in legacy.execute("SELECT * FROM value_snapshots ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    ValueSnapshot.objects.update_or_create(owner=owner, legacy_id=row["id"], defaults={"collection_value": money(row["collection_value"]), "missing_cost": money(row["missing_cost"]), "warehouse_quantity": max(row["warehouse_quantity"] or 0, 0), "captured_at": aware_datetime(row["captured_at"]) or timezone.now()})
                    counts["Value snapshots"] += 1
        if self._has_table(legacy, "notifications"):
            for row in legacy.execute("SELECT * FROM notifications ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    Notification.objects.update_or_create(owner=owner, legacy_id=row["id"], defaults={"kind": row["kind"], "title": row["title"], "message": row["message"], "entity_type": row["entity_type"] or "", "entity_id": str(row["entity_id"] or ""), "read_at": aware_datetime(row["read_at"])})
                    counts["Notifications"] += 1
        if self._has_table(legacy, "workshop_documents"):
            for row in legacy.execute("SELECT * FROM workshop_documents"):
                owner = users.get(row["user_id"])
                if owner:
                    try:
                        payload = json.loads(row["payload"] or "{}")
                    except (TypeError, ValueError):
                        payload = {"legacy_raw": row["payload"]}
                    WorkshopDocument.objects.update_or_create(owner=owner, defaults={"payload": payload})
                    counts["Workshop documents"] += 1
        if self._has_table(legacy, "audit_log"):
            for row in legacy.execute("SELECT * FROM audit_log ORDER BY id"):
                try:
                    details = json.loads(row["details"] or "{}")
                except (TypeError, ValueError):
                    details = {"legacy_details": row["details"] or ""}
                event, _ = AuditEvent.objects.get_or_create(
                    action=f"legacy.{row['action']}",
                    details={**details, "legacy_id": row["id"]},
                    defaults={
                        "actor": users.get(row["actor_id"]),
                        "target_user": users.get(row["target_user_id"]),
                        "actor_identifier": (
                            f"legacy-user:{row['actor_id']}"
                            if row["actor_id"] is not None and row["actor_id"] not in users
                            else ""
                        ),
                        "target_identifier": (
                            f"legacy-user:{row['target_user_id']}"
                            if row["target_user_id"] is not None
                            and row["target_user_id"] not in users
                            else ""
                        ),
                        "target_type": (
                            "accounts.User" if row["target_user_id"] is not None else ""
                        ),
                        "remote_address": row["remote_address"] or None,
                    },
                )
                created = aware_datetime(row["created_at"])
                if created:
                    AuditEvent.objects.filter(pk=event.pk).update(created_at=created)
                counts["Audit events"] += 1
        if self._has_table(legacy, "label_templates"):
            for row in legacy.execute("SELECT * FROM label_templates ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    try:
                        configuration = json.loads(row["configuration"] or "{}")
                    except (TypeError, ValueError):
                        configuration = {}
                    LabelTemplate.objects.update_or_create(owner=owner, legacy_id=row["id"], defaults={"name": row["name"], "width_mm": money(row["width_mm"]), "height_mm": money(row["height_mm"]), "orientation": row["orientation"] or "landscape", "configuration": configuration, "is_default": bool(row["is_default"])})
                    counts["Label templates"] += 1
        if self._has_table(legacy, "saved_views"):
            for row in legacy.execute("SELECT * FROM saved_views ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    try:
                        configuration = json.loads(row["configuration"] or "{}")
                    except (TypeError, ValueError):
                        configuration = {}
                    SavedView.objects.update_or_create(
                        owner=owner, legacy_id=row["id"],
                        defaults={
                            "area": row["area"], "name": row["name"],
                            "path": str(configuration.pop("path", "/"))[:255],
                            "configuration": configuration,
                            "is_default": bool(row["is_default"]),
                        },
                    )
                    counts["Saved views"] += 1
        if self._has_table(legacy, "recent_items"):
            for row in legacy.execute("SELECT * FROM recent_items ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner:
                    RecentItem.objects.update_or_create(
                        owner=owner, legacy_id=row["id"],
                        defaults={
                            "entity_type": row["entity_type"],
                            "entity_id": str(row["entity_id"] or ""),
                            "label": row["label"] or "", "path": "/",
                        },
                    )
                    counts["Recent items"] += 1
        if self._has_table(legacy, "data_quality_issues"):
            for row in legacy.execute("SELECT * FROM data_quality_issues ORDER BY id"):
                owner = users.get(row["user_id"])
                if owner and row["status"] == "open":
                    DataQualityIssue.objects.update_or_create(
                        owner=owner, legacy_id=row["id"],
                        defaults={
                            "issue_key": row["issue_key"],
                            "entity_type": row["entity_type"],
                            "entity_id": str(row["entity_id"] or ""),
                            "severity": row["severity"] or "warning",
                            "message": row["message"],
                        },
                    )
                    counts["Data quality issues"] += 1

        mapped = TABLES | {
            "set_copies",
            "collections",
            "collection_members",
            "warehouse_locations",
            "inventory_items",
            "inventory_movements",
            "set_minifigures",
            "minifigure_parts",
            "personal_notes",
            "orders",
            "order_items",
            "mocs",
            "moc_parts",
            "moc_versions",
            "wishlist",
            "loans",
            "price_history",
            "value_snapshots",
            "notifications",
            "workshop_documents",
            "audit_log",
            "label_templates",
            "saved_views",
            "recent_items",
            "data_quality_issues",
        }
        for table in self._table_names(legacy) - mapped:
            # Names come exclusively from backend introspection and are identifier-quoted.
            rows = list(legacy.execute(f"SELECT * FROM `{table}`"))  # noqa: S608
            if table in SECURITY_RUNTIME_TABLES:
                counts["Skipped security/runtime rows"] += len(rows)
                counts[f"Skipped {table}"] = len(rows)
                continue
            for position, row in enumerate(rows):
                payload = {key: row[key] for key in row.keys()}
                source_pk = payload.get("id", payload.get("key", position))
                owner = users.get(payload.get("user_id") or payload.get("owner_id"))
                LegacyArchiveRecord.objects.update_or_create(
                    source_fingerprint=fingerprint,
                    source_table=table,
                    source_pk=str(source_pk),
                    defaults={
                        "owner": owner,
                        "payload": payload,
                        "classification": "preserved_pending_typed_model",
                    },
                )
                counts["Archived auxiliary rows"] += 1
            counts[f"Archived {table}"] = len(rows)

        AuditEvent.objects.create(
            action="legacy.import", details={"source_sha256": fingerprint, "summary": counts}
        )
        return counts

    @staticmethod
    def _table_names(connection):
        return connection.table_names()

    @classmethod
    def _has_table(cls, connection, name):
        return name in cls._table_names(connection)
