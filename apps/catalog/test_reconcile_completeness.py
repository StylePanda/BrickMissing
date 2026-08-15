from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import LegoSet, SetInventoryItem


class ReconcileSetCompletenessCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "reconcile", "reconcile@example.test", "Strong-password-123"
        )
        self.lego_set = LegoSet.objects.create(
            owner=self.user, set_number="21368", name="Dry-run", completeness="vollständig"
        )
        SetInventoryItem.objects.create(
            lego_set=self.lego_set, part_number="3001", name="Stein",
            required_quantity=2, owned_quantity=0,
        )

    def test_default_is_read_only_and_reports_safe_identifier(self):
        output = StringIO()
        call_command("reconcile_set_completeness", stdout=output)
        self.lego_set.refresh_from_db()
        self.assertEqual(self.lego_set.completeness, "vollständig")
        self.assertIn("DRY-RUN: 1 Abweichungen", output.getvalue())
        self.assertIn("Set 21368", output.getvalue())

    def test_apply_is_explicit_and_uses_central_computation(self):
        call_command("reconcile_set_completeness", "--apply", stdout=StringIO())
        self.lego_set.refresh_from_db()
        self.assertEqual(self.lego_set.completeness, "unvollständig")
