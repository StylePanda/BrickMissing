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

        self.assertContains(response, 'href="/sets/"')
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

    def test_set_form_has_scoped_theme_combobox_and_accepts_new_theme(self):
        LegoSet.objects.create(owner=self.user, set_number="1", name="One", theme="  Space  ", subtheme="Classic")
        LegoSet.objects.create(owner=self.user, set_number="2", name="Two", theme="space", subtheme="classic")
        other = get_user_model().objects.create_user("theme-other", "theme-other@example.test", "Strong-password-123")
        LegoSet.objects.create(owner=other, set_number="3", name="Other", theme="Secret Theme")
        response = self.client.get(reverse("catalog:set_create"))
        self.assertContains(response, 'list="theme-suggestions"')
        self.assertContains(response, 'value="Space"')
        self.assertNotContains(response, "Secret Theme")
        response = self.client.post(reverse("catalog:set_create"), {"set_number": "4", "name": "New", "theme": "Brand New Theme", "condition": "neu", "completeness": "vollständig", "build_status": "gebaut", "purchase_price": "0", "current_value": "0"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(LegoSet.objects.filter(owner=self.user, theme="Brand New Theme").exists())

    def test_set_form_has_lookup_hook_and_part_form_uses_shared_structure(self):
        set_page = self.client.get(reverse("catalog:set_create"))
        self.assertContains(set_page, "data-set-lookup-url")
        self.assertContains(set_page, 'id="set-lookup-status"')
        part_page = self.client.get(reverse("catalog:part_create"))
        self.assertTemplateUsed(part_page, "catalog/part_form.html")
        self.assertContains(part_page, 'class="sectioned-form"')
        self.assertContains(part_page, "Teilinformationen")

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
        self.assertEqual(list(response.context["page_obj"].object_list)[0]["part_number"], "3001")

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

    def test_missing_parts_groups_element_and_color_with_set_allocations(self):
        first = LegoSet.objects.create(owner=self.user, set_number="100", name="Erstes Set")
        second = LegoSet.objects.create(owner=self.user, set_number="200", name="Zweites Set")
        Part.objects.create(owner=self.user, lego_set=first, element_id="6550135", name="Brick 1 x 4", color="White", quantity=4, owned_quantity=0)
        Part.objects.create(owner=self.user, lego_set=second, element_id="6550135", name="Brick 1 x 4", color="White", quantity=4, owned_quantity=2)
        response = self.client.get(reverse("catalog:missing_parts"))
        groups = response.context["page_obj"].object_list
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["required"], groups[0]["owned"], groups[0]["missing"]), (8, 2, 6))
        self.assertContains(response, "Erstes Set")
        self.assertContains(response, "Zweites Set")
        self.assertContains(response, "Teilweise gefunden")

    def test_missing_part_image_lightbox_and_placeholder_are_safe(self):
        Part.objects.create(owner=self.user, element_id="with-image", name="Mit Bild", quantity=1, image_url="https://cdn.rebrickable.com/part.jpg")
        Part.objects.create(owner=self.user, element_id="without-image", name="Ohne Bild", quantity=1)
        response = self.client.get(reverse("catalog:missing_parts"))
        self.assertContains(response, "data-lightbox-image")
        self.assertContains(response, 'id="image-lightbox"')
        self.assertContains(response, "Kein Bild")
        self.assertContains(response, 'aria-label="Bild von Mit Bild vergrößern"')

    def test_permanent_delete_is_post_only_and_owner_scoped(self):
        from django.utils import timezone
        own = Part.objects.create(owner=self.user, element_id="trash-own", name="Eigen", deleted_at=timezone.now())
        other_user = get_user_model().objects.create_user("trash-other", "trash-other@example.test", "Strong-password-123")
        foreign = Part.objects.create(owner=other_user, element_id="trash-foreign", name="Fremd", deleted_at=timezone.now())
        own_url = reverse("catalog:permanent_delete", args=["part", own.pk])
        self.assertEqual(self.client.get(own_url).status_code, 405)
        self.assertEqual(self.client.post(reverse("catalog:permanent_delete", args=["part", foreign.pk])).status_code, 404)
        self.assertTrue(Part.objects.filter(pk=foreign.pk).exists())
        self.assertRedirects(self.client.post(own_url), reverse("catalog:trash"))
        self.assertFalse(Part.objects.filter(pk=own.pk).exists())
