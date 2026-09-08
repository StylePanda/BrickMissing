from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.integrations.rebrickable_sync import synchronize_set
from apps.organizer.models import MinifigurePart, SetMinifigure

from .models import LegoSet, Part, SetInventoryItem
from .owned_quantity_reconciliation import (
    AMBIGUOUS,
    PROVEN_ALLOCATION_USER_EDIT,
    PROVEN_PART_USER_EDIT,
    apply_reconciliation,
    classify_owned_quantity_consistency,
)
from .services import (
    authoritative_lego_export_rows,
    owned_quantity_consistency_rows,
    set_authoritative_owned_quantity,
)


class OwnedQuantityReconciliationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "reconcile", "reconcile@example.test", "A-long-password-123"
        )

    def allocation(
        self,
        suffix,
        *,
        element_id="4117070",
        inventory_element_id="4117070",
        part_number="3062b",
        color="Tan",
        part_owned=36,
        inventory_owned=3,
        required=42,
        owner=None,
    ):
        owner = owner or self.user
        lego_set = LegoSet.objects.create(
            owner=owner, set_number=f"set-{suffix}", name=f"Set {suffix}"
        )
        item = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number=part_number,
            element_id=inventory_element_id,
            name="Part",
            color_id=1,
            color_name=color,
            required_quantity=required,
            owned_quantity=inventory_owned,
        )
        part = Part.objects.create(
            owner=owner,
            lego_set=lego_set,
            element_id=element_id,
            design_id=part_number,
            part_number=part_number,
            name="Part mirror",
            color=color,
            quantity=required,
            owned_quantity=part_owned,
        )
        return lego_set, item, part

    def event(self, action, instance, owned, *, owner=None):
        owner = owner or self.user
        return AuditEvent.objects.create(
            actor=owner,
            target_user=owner,
            action=action,
            entity_type=(
                "part" if isinstance(instance, Part) else "set_inventory_item"
            ),
            entity_id=str(instance.pk),
            details={"owned_quantity": owned},
        )

    def test_confirmed_part_edit_is_proven_applied_and_idempotent(self):
        lego_set, item, part = self.allocation("4117070")
        self.event("missing_part.quantity_changed", part, 36)

        plans = classify_owned_quantity_consistency(self.user)
        self.assertEqual(plans[0].classification, PROVEN_PART_USER_EDIT)
        self.assertEqual(plans[0].proposed_final_owned, 36)

        output = StringIO()
        call_command(
            "reconcile_owned_quantity_consistency",
            "--user-id",
            str(self.user.pk),
            "--apply",
            stdout=output,
        )
        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, part.owned_quantity), (36, 36))
        self.assertIn("divergences: 0", output.getvalue())
        self.assertEqual(owned_quantity_consistency_rows(self.user), [])

        synchronize_set(
            lego_set,
            "key",
            set_fetcher=lambda _number, _key: (
                {"name": "Set 4117070", "num_parts": 42},
                [
                    {
                        "part": {"part_num": "3062b", "name": "Part"},
                        "color": {"id": 1, "name": "Tan"},
                        "element_id": "4117070",
                        "quantity": 42,
                    }
                ],
            ),
            minifigure_fetcher=lambda _number, _key: [],
        )
        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, part.owned_quantity), (36, 36))

        second = StringIO()
        call_command(
            "reconcile_owned_quantity_consistency",
            "--user-id",
            str(self.user.pk),
            "--apply",
            stdout=second,
        )
        self.assertIn("applied_writes: 0", second.getvalue())

    def test_blank_element_allocation_edit_is_proven(self):
        _set, item, part = self.allocation(
            "blank", inventory_element_id="", part_owned=0, inventory_owned=25,
            required=26, element_id="3711b", part_number="3711b", color="Black"
        )
        self.event("set_inventory.quantity_changed", item, 25)
        with self.assertNumQueries(4):
            plans = classify_owned_quantity_consistency(self.user)
        self.assertEqual(plans[0].classification, PROVEN_ALLOCATION_USER_EDIT)
        apply_reconciliation(plans, user=self.user)
        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 25)
        self.assertEqual(
            authoritative_lego_export_rows(self.user),
            [{"element_id": "3711b", "export_quantity": 1}],
        )

    def test_latest_explicit_allocation_action_beats_older_part_action(self):
        _set, item, part = self.allocation("allocation", part_owned=7, inventory_owned=30)
        self.event("missing_part.quantity_changed", part, 7)
        self.event("set_inventory.quantity_changed", item, 30)
        plan = classify_owned_quantity_consistency(self.user)[0]
        self.assertEqual(plan.classification, PROVEN_ALLOCATION_USER_EDIT)

    def test_no_event_and_mismatching_latest_event_are_ambiguous(self):
        _set, item, part = self.allocation("none")
        plan = classify_owned_quantity_consistency(self.user)[0]
        self.assertEqual(plan.classification, AMBIGUOUS)
        self.event("missing_part.quantity_changed", part, 12)
        plan = classify_owned_quantity_consistency(self.user)[0]
        self.assertEqual(plan.classification, AMBIGUOUS)

        output = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "reconcile_owned_quantity_consistency",
                "--user-id",
                str(self.user.pk),
                "--apply",
                stdout=output,
            )
        item.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, part.owned_quantity), (3, 36))
        self.assertIn("unresolved_ambiguities: 1", output.getvalue())

    def test_part_total_cannot_be_distributed_over_multiple_allocations(self):
        lego_set, _item, part = self.allocation("multi", part_owned=10, inventory_owned=2)
        SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="alternate",
            element_id="4117070",
            name="Second allocation",
            color_id=2,
            color_name="Tan",
            required_quantity=8,
            owned_quantity=1,
        )
        self.event("missing_part.quantity_changed", part, 10)
        plan = classify_owned_quantity_consistency(self.user)[0]
        self.assertEqual(plan.classification, AMBIGUOUS)
        self.assertIn("distributed", plan.reason)

    def test_allocation_edit_synchronizes_multiple_allocation_aggregate(self):
        lego_set, first, part = self.allocation(
            "aggregate", part_owned=1, inventory_owned=2, required=10
        )
        second = SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number="alternate",
            element_id="4117070",
            name="Second allocation",
            color_id=2,
            color_name="Tan",
            required_quantity=8,
            owned_quantity=3,
        )
        self.event("set_inventory.quantity_changed", first, 2)
        plan = classify_owned_quantity_consistency(self.user)[0]
        self.assertEqual(plan.classification, PROVEN_ALLOCATION_USER_EDIT)
        apply_reconciliation([plan], user=self.user)
        part.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((part.quantity, part.owned_quantity), (18, 5))
        self.assertEqual(second.owned_quantity, 3)

        set_authoritative_owned_quantity("set", second, 6, self.user)
        part.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((part.quantity, part.owned_quantity), (18, 8))
        self.assertEqual(second.owned_quantity, 6)

    def test_normal_plus_minifigure_is_not_collapsed_and_allocation_wins(self):
        lego_set, item, part = self.allocation(
            "normal-mini", part_owned=1, inventory_owned=2, required=10
        )
        figure = SetMinifigure.objects.create(
            owner=self.user,
            lego_set=lego_set,
            figure_number="fig-1",
            name="Figure",
        )
        component = MinifigurePart.objects.create(
            minifigure=figure,
            part_number="3062b",
            element_id="4117070",
            name="Component",
            color_name="Tan",
            quantity=4,
            owned_quantity=3,
        )
        AuditEvent.objects.create(
            actor=self.user,
            target_user=self.user,
            action="minifigure_part.quantity_changed",
            entity_type="minifigure_part",
            entity_id=str(component.pk),
            details={"owned_quantity": 3},
        )
        plan = classify_owned_quantity_consistency(self.user)[0]
        self.assertEqual(plan.classification, PROVEN_ALLOCATION_USER_EDIT)
        apply_reconciliation([plan], user=self.user)
        item.refresh_from_db()
        component.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((item.owned_quantity, component.owned_quantity), (2, 3))
        self.assertEqual((part.quantity, part.owned_quantity), (14, 5))

    def test_audit_isolation_and_zero_values_are_not_unknown(self):
        _set, item, part = self.allocation("zero", part_owned=0, inventory_owned=3)
        SetInventoryItem.objects.create(
            lego_set=part.lego_set,
            part_number="3062b",
            element_id="",
            name="Spare",
            color_id=2,
            color_name="Tan",
            required_quantity=1,
            owned_quantity=1,
            is_spare=True,
        )
        Part.objects.create(
            owner=self.user,
            element_id="manual",
            name="Manual",
            quantity=2,
            owned_quantity=0,
        )
        foreign = get_user_model().objects.create_user(
            "foreign-reconcile", "foreign-reconcile@example.test", "A-long-password-123"
        )
        self.allocation("foreign", owner=foreign)
        rows = owned_quantity_consistency_rows(self.user)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["part_owned"], 0)
        self.assertEqual(rows[0]["allocation_count"], 1)

        output = StringIO()
        call_command("audit_owned_quantity_consistency", "--user-id", str(self.user.pk), stdout=output)
        self.assertIn("\t0\t", output.getvalue())
        self.assertNotIn(str(foreign.pk), output.getvalue())
        item.refresh_from_db()

    def test_changed_state_aborts_before_any_write(self):
        _set, item, part = self.allocation("race")
        self.event("missing_part.quantity_changed", part, 36)
        plans = classify_owned_quantity_consistency(self.user)
        Part.objects.filter(pk=part.pk).update(owned_quantity=35)
        with self.assertRaises(CommandError):
            apply_reconciliation(plans, user=self.user)
        item.refresh_from_db()
        self.assertEqual(item.owned_quantity, 3)

    def test_local_two_example_command_simulation_reaches_zero(self):
        _set_a, item_a, part_a = self.allocation("sim-4117070")
        self.event("missing_part.quantity_changed", part_a, 36)
        self.allocation(
            "sim-3711b",
            element_id="3711b",
            inventory_element_id="",
            part_number="3711b",
            color="Black",
            required=26,
            part_owned=0,
            inventory_owned=25,
        )
        item_b = SetInventoryItem.objects.get(lego_set__set_number="set-sim-3711b")
        self.event("set_inventory.quantity_changed", item_b, 25)

        audit_before = StringIO()
        call_command(
            "audit_owned_quantity_consistency",
            "--user-id",
            str(self.user.pk),
            stdout=audit_before,
        )
        self.assertIn("divergences: 2", audit_before.getvalue())

        dry_run = StringIO()
        call_command(
            "reconcile_owned_quantity_consistency",
            "--user-id",
            str(self.user.pk),
            stdout=dry_run,
        )
        self.assertIn("mode: DRY-RUN", dry_run.getvalue())
        self.assertIn("proposed_writes: 2", dry_run.getvalue())

        applied = StringIO()
        call_command(
            "reconcile_owned_quantity_consistency",
            "--user-id",
            str(self.user.pk),
            "--apply",
            stdout=applied,
        )
        audit_after = StringIO()
        call_command(
            "audit_owned_quantity_consistency",
            "--user-id",
            str(self.user.pk),
            stdout=audit_after,
        )
        self.assertIn("divergences: 0", audit_after.getvalue())
        self.assertEqual(
            authoritative_lego_export_rows(self.user),
            [
                {"element_id": "3711b", "export_quantity": 1},
                {"element_id": "4117070", "export_quantity": 6},
            ],
        )
        item_a.refresh_from_db()
        self.assertEqual(item_a.owned_quantity, 36)
