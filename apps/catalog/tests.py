from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import LegoSet, Part, SetInventoryItem


class OwnershipTests(TestCase):
    def setUp(self):
        user = get_user_model()
        self.alice = user.objects.create_user(
            "alice", "alice@example.test", "A-very-long-password-123"
        )
        self.bob = user.objects.create_user("bob", "bob@example.test", "Another-long-password-456")
        self.bob_set = LegoSet.objects.create(owner=self.bob, set_number="75300", name="Bob Set")
        self.bob_part = Part.objects.create(
            owner=self.bob, lego_set=self.bob_set, element_id="3001", name="Brick"
        )

    def test_foreign_set_is_not_visible_or_mutable(self):
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(reverse("catalog:set_detail", args=[self.bob_set.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("catalog:set_delete", args=[self.bob_set.pk])).status_code, 404
        )
        self.bob_set.refresh_from_db()
        self.assertIsNone(self.bob_set.deleted_at)

    def test_foreign_part_is_not_visible_or_mutable(self):
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(reverse("catalog:part_edit", args=[self.bob_part.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("catalog:part_delete", args=[self.bob_part.pk])).status_code,
            404,
        )

    def test_lists_are_user_scoped(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("catalog:set_list"))
        self.assertNotContains(response, "Bob Set")


class CatalogFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "owner", "owner@example.test", "Strong-and-long-password-789"
        )
        self.client.force_login(self.user)

    def test_form_cancel_link_is_csp_safe_with_dashboard_fallback(self):
        response = self.client.get(reverse("catalog:set_create"))

        self.assertContains(response, 'href="/" data-history-back')
        self.assertNotContains(response, "java" + "script:")

    def test_set_create_soft_delete_and_restore(self):
        response = self.client.post(
            reverse("catalog:set_create"),
            {
                "set_number": "10300",
                "name": "Back to the Future",
                "theme": "Icons",
                "total_parts": 1872,
                "condition": "neu",
                "completeness": "vollständig",
                "build_status": "gebaut",
                "purchase_price": "0",
                "current_value": "0",
            },
        )
        item = LegoSet.objects.get(owner=self.user)
        self.assertRedirects(response, reverse("catalog:set_detail", args=[item.pk]))
        self.client.post(reverse("catalog:set_delete", args=[item.pk]))
        item.refresh_from_db()
        self.assertIsNotNone(item.deleted_at)
        self.client.post(reverse("catalog:restore", args=["set", item.pk]))
        item.refresh_from_db()
        self.assertIsNone(item.deleted_at)

    def test_set_inventory_bulk_creates_owned_missing_parts(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="100-1", name="Test")
        SetInventoryItem.objects.create(lego_set=lego_set, part_number="3001", element_id="300101", name="Brick", required_quantity=4, owned_quantity=1)
        response = self.client.post(reverse("catalog:set_inventory_action", args=[lego_set.pk, "create-missing"]))
        self.assertRedirects(response, reverse("catalog:set_detail", args=[lego_set.pk]))
        part = Part.objects.get(owner=self.user, lego_set=lego_set)
        self.assertEqual(part.quantity, 3)

    def test_missing_parts_search_filter_sort_combination_and_ownership(self):
        lego_set = LegoSet.objects.create(
            owner=self.user, set_number="100-1", name="My Castle"
        )
        Part.objects.create(
            owner=self.user, lego_set=lego_set, part_number="3001",
            element_id="300101", name="Red Brick", color="Red", quantity=5,
            owned_quantity=1, status=Part.Status.ORDERED,
        )
        other = get_user_model().objects.create_user(
            "missing-other", "missing-other@example.test", "Strong-password-123"
        )
        Part.objects.create(
            owner=other, part_number="3001", element_id="foreign", name="Foreign",
            color="Red", quantity=10, owned_quantity=0,
        )
        response = self.client.get(
            reverse("catalog:missing_parts"),
            {"q": "Castle", "color": "Red", "status": "ordered", "minimum": "4", "sort": "-quantity"},
        )
        self.assertContains(response, "Red Brick")
        self.assertNotContains(response, "Foreign")
        self.assertEqual(list(response.context["page_obj"].object_list)[0].part_number, "3001")

    def test_missing_parts_paginates_and_preserves_query(self):
        Part.objects.bulk_create(
            [
                Part(
                    owner=self.user, element_id=f"e{index}", name=f"Needle {index}",
                    quantity=2, owned_quantity=0,
                )
                for index in range(55)
            ]
        )
        response = self.client.get(
            reverse("catalog:missing_parts"), {"q": "Needle", "page": 2}
        )
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertContains(response, "q=Needle")

    def test_missing_parts_bulk_updates_only_owned_selected_rows(self):
        own = Part.objects.create(
            owner=self.user, element_id="bulk-own", name="Own", quantity=3,
            owned_quantity=0, status=Part.Status.MISSING,
        )
        other = get_user_model().objects.create_user(
            "bulk-other", "bulk-other@example.test", "Strong-password-123"
        )
        foreign = Part.objects.create(
            owner=other, element_id="bulk-foreign", name="Foreign", quantity=3,
            owned_quantity=0, status=Part.Status.MISSING,
        )
        response = self.client.post(
            reverse("catalog:missing_parts_bulk"),
            {"item": [own.pk, foreign.pk], "action": "found"},
        )
        self.assertRedirects(response, reverse("catalog:missing_parts"))
        own.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual((own.owned_quantity, own.status), (3, Part.Status.FOUND))
        self.assertEqual((foreign.owned_quantity, foreign.status), (0, Part.Status.MISSING))
