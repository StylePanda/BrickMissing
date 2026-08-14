from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizer.models import MinifigurePart, SetMinifigure

from .colors import color_category
from .models import LegoSet, Part, SetInventoryItem
from .services import set_completeness


class CompletenessAndColorTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="derived", email="derived@example.test")
        self.lego_set = LegoSet.objects.create(owner=self.user, set_number="1", name="Set")

    def test_set_completeness_is_derived_from_normal_and_minifigure_parts(self):
        self.assertEqual(set_completeness(self.lego_set)["key"], "unknown")
        item = SetInventoryItem.objects.create(
            lego_set=self.lego_set, part_number="3001", name="Stein",
            required_quantity=2, owned_quantity=2,
        )
        self.assertEqual(set_completeness(self.lego_set)["key"], "complete")
        item.owned_quantity = 1
        item.save(update_fields=["owned_quantity"])
        self.assertEqual(set_completeness(self.lego_set)["key"], "incomplete")
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=self.lego_set, figure_number="fig-1", name="Figur"
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="head", name="Kopf", quantity=1, owned_quantity=0
        )
        self.assertEqual(set_completeness(self.lego_set)["missing"], 2)

    def test_spares_do_not_make_a_set_incomplete(self):
        SetInventoryItem.objects.create(
            lego_set=self.lego_set, part_number="spare", name="Ersatz",
            required_quantity=1, owned_quantity=0, is_spare=True,
        )
        self.assertEqual(set_completeness(self.lego_set)["key"], "unknown")

    def test_central_color_categories(self):
        cases = {
            "Lime": "GREEN", "Light Nougat": "BROWN", "Trans-Clear": "TRANS",
            "Trans-Dark Blue": "TRANS", "Flat Silver": "METALLIC / PEARL / FLAT",
            "Pearl Gold": "METALLIC / PEARL / FLAT", "Dark Bluish Gray": "GRAY",
            "Black": "BLACK",
        }
        for color, expected in cases.items():
            with self.subTest(color=color):
                self.assertEqual(color_category(color), expected)


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

    def test_foreign_inventory_quantities_cannot_be_changed(self):
        item = SetInventoryItem.objects.create(lego_set=self.bob_set, part_number="3001", name="Stein", required_quantity=4)
        self.client.force_login(self.alice)
        response = self.client.post(reverse("catalog:set_inventory_quantity", args=[self.bob_set.pk, item.pk]), {"owned_quantity": 4})
        self.assertEqual(response.status_code, 404)
        item.refresh_from_db()
        self.assertEqual(item.owned_quantity, 0)

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
        self.assertContains(response, 'data-combobox')
        self.assertContains(response, 'role="listbox"')
        self.assertNotContains(response, "<datalist")
        self.assertContains(response, 'data-combobox-option="Space"')
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
            {"q": "Castle", "color": "Red", "status": "partial", "minimum": "4", "sort": "-quantity"},
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
        self.assertContains(response, "Teilweise vorhanden")

    def test_grouped_missing_part_renders_one_main_row_and_all_allocations(self):
        sets = [
            LegoSet.objects.create(owner=self.user, set_number=number, name=name)
            for number, name in (("9448", "Samurai X Mech"), ("70000", "Razcal's Glider"), ("9447", "Lasha's Bite Cycle"), ("70002", "Lennox' Lion Attack"))
        ]
        quantities = (3, 2, 3, 2)
        for lego_set, quantity in zip(sets, quantities, strict=True):
            Part.objects.create(owner=self.user, lego_set=lego_set, element_id=" 6000606 ", part_number="6000606", name="Bracket 1 x 2 - 1 x 2 Inverted", color="Dark Bluish Gray", quantity=quantity, owned_quantity=0, image_url="https://example.test/part.png")

        response = self.client.get(reverse("catalog:missing_parts"))
        groups = response.context["page_obj"].object_list
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["required"], groups[0]["owned"], groups[0]["missing"]), (10, 0, 10))
        self.assertEqual(groups[0]["status"], Part.Status.MISSING)
        self.assertEqual(len(groups[0]["allocations"]), 4)
        self.assertContains(response, 'class="missing-group-row"', count=1)
        self.assertContains(response, 'data-lightbox-image="https://example.test/part.png"', count=1)
        self.assertEqual({part.lego_set for part in groups[0]["allocations"]}, set(sets))

    def test_grouping_separates_colors_and_derives_all_group_statuses(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="1", name="Statusset")
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="same", name="Black", color="Black", quantity=2, owned_quantity=0)
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="same", name="Red", color="Red", quantity=2, owned_quantity=1)
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="full", name="Full", color="Red", quantity=2, owned_quantity=2, status=Part.Status.FOUND)
        response = self.client.get(reverse("catalog:missing_parts"))
        groups = response.context["page_obj"].object_list
        self.assertEqual(len(groups), 2)
        self.assertEqual({group["status"] for group in groups}, {Part.Status.MISSING, "partial"})
        found = self.client.get(reverse("catalog:missing_parts"), {"status": "found"})
        self.assertEqual(found.context["page_obj"].object_list[0]["status_label"], "Gefunden")

    def test_group_filters_sort_and_bulk_apply_to_visible_allocations(self):
        first = LegoSet.objects.create(owner=self.user, set_number="100", name="Erstes Set")
        second = LegoSet.objects.create(owner=self.user, set_number="200", name="Zweites Set")
        red_first = Part.objects.create(owner=self.user, lego_set=first, element_id="shared", name="Shared", color="Red", quantity=4, owned_quantity=1)
        red_second = Part.objects.create(owner=self.user, lego_set=second, element_id="shared", name="Shared", color="Red", quantity=2, owned_quantity=0)
        Part.objects.create(owner=self.user, lego_set=second, element_id="other", name="Other", color="Blue", quantity=9, owned_quantity=0)
        response = self.client.get(reverse("catalog:missing_parts"), {"set": first.pk, "color": "Red", "sort": "-missing"})
        groups = response.context["page_obj"].object_list
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["allocations"], [red_first])
        self.assertEqual(groups[0]["allocations"][0].lego_set, first)
        bulk = self.client.post(reverse("catalog:missing_parts_bulk"), {"item": f"{red_first.pk},{red_second.pk}", "action": "found"})
        self.assertEqual(bulk.status_code, 302)
        red_first.refresh_from_db()
        red_second.refresh_from_db()
        self.assertEqual((red_first.owned_quantity, red_second.owned_quantity), (4, 2))

    def test_single_allocation_quantity_change_updates_group_aggregation(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="300", name="Mengen")
        part = Part.objects.create(owner=self.user, lego_set=lego_set, element_id="aggregate", name="Aggregate", color="White", quantity=4, owned_quantity=0)
        self.client.post(reverse("catalog:missing_part_quantity", args=[part.pk]), {"owned_quantity": 3})
        group = self.client.get(reverse("catalog:missing_parts")).context["page_obj"].object_list[0]
        self.assertEqual((group["required"], group["owned"], group["missing"], group["status"]), (4, 3, 1, "partial"))

    def test_color_multiselect_has_compact_shared_checkbox_layout(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="400", name="Farben")
        SetInventoryItem.objects.create(lego_set=lego_set, element_id="x", name="No color", color_name="[No Color/Any Color]")
        Part.objects.create(owner=self.user, element_id="y", name="Blue", color="Blue", quantity=1)
        set_page = self.client.get(reverse("catalog:set_detail", args=[lego_set.pk]))
        missing_page = self.client.get(reverse("catalog:missing_parts"))
        for response in (set_page, missing_page):
            self.assertContains(response, 'data-color-filter')
            self.assertContains(response, 'class="color-filter-popover"')
        self.assertContains(set_page, "Keine Farbangabe")

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

    def test_direct_missing_quantity_derives_status_and_rejects_invalid_values(self):
        part = Part.objects.create(owner=self.user, element_id="direct", name="Direkt", quantity=5)
        url = reverse("catalog:missing_part_quantity", args=[part.pk])
        self.assertRedirects(self.client.post(url, {"owned_quantity": 2}), reverse("catalog:missing_parts"))
        part.refresh_from_db()
        self.assertEqual((part.owned_quantity, part.status, part.missing_quantity), (2, Part.Status.MISSING, 3))
        self.assertEqual(self.client.post(url, {"owned_quantity": 6}).status_code, 400)
        self.client.post(url, {"owned_quantity": 5})
        part.refresh_from_db()
        self.assertEqual((part.owned_quantity, part.status), (5, Part.Status.FOUND))

    def test_direct_status_keeps_quantity_consistent(self):
        part = Part.objects.create(owner=self.user, element_id="status", name="Status", quantity=3, owned_quantity=1)
        url = reverse("catalog:missing_part_status", args=[part.pk])
        self.client.post(url, {"status": Part.Status.FOUND})
        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 3)
        self.client.post(url, {"status": Part.Status.MISSING})
        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 0)

    def test_set_detail_inventory_workbench_and_direct_quantity(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="75010", name="B-wing")
        item = SetInventoryItem.objects.create(lego_set=lego_set, part_number="3001", name="Stein", required_quantity=4, owned_quantity=1, is_spare=True)
        response = self.client.get(reverse("catalog:set_detail", args=[lego_set.pk]), {"art": "spare"})
        self.assertContains(response, "Set-Inventar")
        self.assertContains(response, "Ersatzteil")
        self.assertContains(response, "3")
        update = reverse("catalog:set_inventory_quantity", args=[lego_set.pk, item.pk])
        self.assertRedirects(self.client.post(update, {"owned_quantity": 3}), reverse("catalog:set_detail", args=[lego_set.pk]))
        item.refresh_from_db()
        self.assertEqual(item.owned_quantity, 3)

    def test_set_inventory_supports_multicolor_stock_filters_and_all_sorts(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="75010", name="B-wing")
        SetInventoryItem.objects.create(lego_set=lego_set, part_number="2", name="Ziegel", color_name="Red", required_quantity=4, owned_quantity=2)
        SetInventoryItem.objects.create(lego_set=lego_set, part_number="1", name="Platte", color_name="Black", required_quantity=1, owned_quantity=1)
        response = self.client.get(reverse("catalog:set_detail", args=[lego_set.pk]), {"color": ["Red", "Black"], "stock": "partial", "sort": "-missing"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ziegel")
        self.assertNotContains(response, ">Platte</a>")
        self.assertEqual(response.context["selected_colors"], ["Red", "Black"])
        for ordering in ("name", "-name", "part_number", "-part_number", "color", "required", "-required", "owned", "-owned", "missing", "-missing"):
            with self.subTest(ordering=ordering):
                self.assertEqual(self.client.get(reverse("catalog:set_detail", args=[lego_set.pk]), {"sort": ordering}).status_code, 200)

    def test_missing_workbench_combines_v7_parity_filters(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="123", name="Filterset")
        target = Part.objects.create(owner=self.user, lego_set=lego_set, part_number="3001", element_id="E1", name="Ziel", color="Red", quantity=3, owned_quantity=0)
        Part.objects.create(owner=self.user, part_number="3002", element_id="E2", name="Andere", color="Blue", quantity=1, owned_quantity=0)
        response = self.client.get(reverse("catalog:missing_parts"), {"color": ["Red", "Blue"], "set": str(lego_set.pk), "kind": "assigned", "rarity": "multiple", "sort": "-missing"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, target.name)
        self.assertNotContains(response, "Andere")
        for label in ("Suche", "Status", "Farbe", "Set", "Teileart", "Seltenheit", "Sortierung"):
            self.assertContains(response, label)
        self.assertContains(response, 'class="table-wrap missing-worktable"')
