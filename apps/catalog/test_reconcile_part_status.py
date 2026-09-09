from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import TestCase

from apps.catalog.models import LegoSet, Part, SetInventoryItem


class ReconcilePartStatusCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "part-reconcile", "part-reconcile@example.test", "Strong-password-123"
        )

    def create_part(self, suffix, **values):
        defaults = {
            "owner": self.user, "element_id": f"element-{suffix}", "name": f"Teil {suffix}",
            "quantity": 2, "owned_quantity": 0, "unassigned_found_quantity": 0,
            "status": Part.Status.MISSING, "is_present": False,
        }
        defaults.update(values)
        return Part.objects.create(**defaults)

    def test_dry_run_classifies_without_changes(self):
        found_zero = self.create_part("a", status=Part.Status.FOUND)
        found_partial = self.create_part("b", status=Part.Status.FOUND, owned_quantity=1)
        missing_full = self.create_part("c", status=Part.Status.MISSING, owned_quantity=2)
        output = StringIO()
        call_command("reconcile_part_status", stdout=output)
        for part in (found_zero, found_partial, missing_full):
            part.refresh_from_db()
        self.assertEqual((found_zero.owned_quantity, found_partial.owned_quantity), (0, 1))
        self.assertEqual(missing_full.status, Part.Status.MISSING)
        self.assertIn("A) Gefunden + Bestand 0: 1", output.getvalue())
        self.assertIn("B) Gefunden + Teilbestand: 1", output.getvalue())
        self.assertIn("C) Fehlt + vollständig vorhanden: 1", output.getvalue())
        self.assertIn("AMBIGUOUS / MANUAL REVIEW", output.getvalue())

    def test_dry_run_reports_historical_received_status_with_shortage(self):
        stale = self.create_part(
            "received-shortage",
            status=Part.Status.RECEIVED,
            quantity=1,
            owned_quantity=0,
        )

        output = StringIO()
        call_command("reconcile_part_status", stdout=output)
        stale.refresh_from_db()

        self.assertEqual((stale.status, stale.owned_quantity), (Part.Status.RECEIVED, 0))
        self.assertIn("F) Erhalten/Eingebaut + offene Fehlmenge: 1", output.getvalue())
        self.assertIn("DRY-RUN", output.getvalue())

    def test_dry_run_uses_authoritative_allocation_for_stale_mirror(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="audit-authority", name="Authority"
        )
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="2436",
            element_id="4282737",
            name="Bracket",
            color_name="White",
            required_quantity=1,
            owned_quantity=0,
        )
        stale = self.create_part(
            "authority",
            lego_set=lego_set,
            element_id="4282737",
            part_number="2436",
            color="White",
            status=Part.Status.RECEIVED,
            quantity=1,
            owned_quantity=1,
        )

        output = StringIO()
        call_command("reconcile_part_status", stdout=output)
        stale.refresh_from_db()

        self.assertEqual((stale.status, stale.owned_quantity), (Part.Status.RECEIVED, 1))
        self.assertIn("F) Erhalten/Eingebaut + offene Fehlmenge: 1", output.getvalue())
        self.assertIn("benötigt=1 | owned=0", output.getvalue())

    def test_apply_only_updates_safe_redundant_marker(self):
        ambiguous = self.create_part("ambiguous", status=Part.Status.FOUND)
        safe = self.create_part(
            "safe", status=Part.Status.ORDERED, owned_quantity=1, is_present=False
        )
        consistent = self.create_part(
            "consistent", status=Part.Status.INSTALLED, owned_quantity=2, is_present=True
        )
        call_command("reconcile_part_status", "--apply", stdout=StringIO())
        for part in (ambiguous, safe, consistent):
            part.refresh_from_db()
        self.assertEqual((ambiguous.status, ambiguous.owned_quantity), (Part.Status.FOUND, 0))
        self.assertTrue(safe.is_present)
        self.assertEqual((safe.status, safe.owned_quantity), (Part.Status.ORDERED, 1))
        self.assertTrue(consistent.is_present)

    def test_unassigned_found_quantity_drives_safe_present_marker(self):
        part = self.create_part(
            "unassigned", unassigned_found_quantity=3, owned_quantity=0, is_present=False
        )
        call_command("reconcile_part_status", "--apply", stdout=StringIO())
        part.refresh_from_db()
        self.assertTrue(part.is_present)
        self.assertEqual(part.unassigned_found_quantity, 3)

    def test_apply_rolls_back_all_safe_updates_on_error(self):
        first = self.create_part("rollback-1", owned_quantity=1, is_present=False)
        second = self.create_part("rollback-2", owned_quantity=1, is_present=False)
        original_update = QuerySet.update
        calls = 0

        def fail_second(queryset, **values):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("controlled rollback")
            return original_update(queryset, **values)

        with mock.patch.object(QuerySet, "update", autospec=True, side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                call_command("reconcile_part_status", "--apply", stdout=StringIO())
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_present)
        self.assertFalse(second.is_present)
