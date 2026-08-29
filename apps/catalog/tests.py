from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.totp import encrypt_secret
from apps.core.models import SavedView
from apps.organizer.models import MinifigurePart, SetMinifigure

from .colors import color_category
from .models import LegoSet, Part, SetInventoryItem
from .services import set_completeness
from .views import parse_batch_set_numbers


class CompletenessAndColorTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="derived", email="derived@example.test")
        self.lego_set = LegoSet.objects.create(owner=self.user, set_number="1", name="Set")

    def test_set_completeness_is_derived_from_normal_and_minifigure_parts(self):
        empty = set_completeness(self.lego_set)
        self.assertEqual((empty["key"], empty["label"]), ("unknown", "Unbekannt"))
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

    def test_batch_set_number_parser_normalizes_and_deduplicates(self):
        numbers, invalid, duplicates = parse_batch_set_numbers("10300, 10300-1; 75367\nnot-a-set 42171")
        self.assertEqual(numbers, ["10300-1", "75367-1", "42171-1"])
        self.assertEqual(invalid, ["not-a-set"])
        self.assertEqual(duplicates, 1)


class MissingPartKindTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="kinds", email="kinds@example.test")
        self.lego_set = LegoSet.objects.create(owner=self.user, set_number="9449", name="Podracer")
        Part.objects.create(
            owner=self.user, lego_set=self.lego_set, element_id="normal", name="Normaler Stein",
            quantity=1, owned_quantity=0,
        )
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=self.lego_set, figure_number="fig-sebulba", name="Sebulba"
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="head", element_id="mini", name="Sebulba-Kopf",
            quantity=1, owned_quantity=0,
        )
        self.client.force_login(self.user)

    def test_all_normal_minifigure_and_exclusion_filters(self):
        url = reverse("catalog:missing_parts")
        all_parts = self.client.get(url, {"kind": "all"})
        self.assertContains(all_parts, "Normaler Stein")
        self.assertContains(all_parts, "Sebulba-Kopf")
        self.assertContains(all_parts, "9449 – Podracer · Minifigur Sebulba")
        only_mini = self.client.get(url, {"kind": "minifigure"})
        self.assertContains(only_mini, "Sebulba-Kopf")
        self.assertNotContains(only_mini, "Normaler Stein")
        normal = self.client.get(url, {"kind": "normal"})
        self.assertContains(normal, "Normaler Stein")
        self.assertNotContains(normal, "Sebulba-Kopf")
        excluded = self.client.get(url, {"kind": "exclude_minifigure"})
        self.assertContains(excluded, "Normaler Stein")
        self.assertNotContains(excluded, "Sebulba-Kopf")


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

    def test_built_incomplete_status_is_selectable_and_persisted(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="status-1", name="Status")
        response = self.client.get(reverse("catalog:set_edit", args=[lego_set.pk]))
        self.assertContains(response, "Aufgebaut, unvollständig")
        response = self.client.post(
            reverse("catalog:set_edit", args=[lego_set.pk]),
            {"set_number": lego_set.set_number, "name": lego_set.name, "condition": "gebraucht",
             "build_status": "aufgebaut unvollständig", "purchase_price": "0", "current_value": "0"},
        )
        self.assertRedirects(response, reverse("catalog:set_detail", args=[lego_set.pk]))
        lego_set.refresh_from_db()
        self.assertEqual(lego_set.build_status, "aufgebaut unvollständig")
        self.assertContains(self.client.get(reverse("catalog:set_detail", args=[lego_set.pk])), "aufgebaut unvollständig")

    def test_newly_purchased_set_button_uses_existing_add_workflow_and_preset(self):
        response = self.client.get(reverse("catalog:set_list"))
        self.assertContains(response, "Neu gekauftes Set hinzufügen")
        preset = self.client.get(reverse("catalog:set_create"), {"preset": "neu"})
        self.assertContains(preset, 'option value="neu" selected')

    def test_set_inventory_bulk_creates_owned_missing_parts(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="100-1", name="Test")
        SetInventoryItem.objects.create(lego_set=lego_set, part_number="3001", element_id="300101", name="Brick", required_quantity=4, owned_quantity=1)
        response = self.client.post(reverse("catalog:set_inventory_action", args=[lego_set.pk, "create-missing"]))
        self.assertRedirects(response, reverse("catalog:set_detail", args=[lego_set.pk]))
        part = Part.objects.get(owner=self.user, lego_set=lego_set)
        self.assertEqual(part.quantity, 3)

    def test_set_inventory_bulk_keeps_workflow_state_and_counts_minifigure_parts(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="100-2", name="Test")
        SetInventoryItem.objects.create(
            lego_set=lego_set, part_number="3002", element_id="300202", name="Brick",
            required_quantity=5, owned_quantity=3,
        )
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-2", name="Figure"
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="head", name="Head", quantity=2, owned_quantity=1
        )
        response = self.client.post(reverse("catalog:set_inventory_action", args=[lego_set.pk, "create-missing"]))
        self.assertRedirects(response, reverse("catalog:set_detail", args=[lego_set.pk]))
        part = Part.objects.get(owner=self.user, lego_set=lego_set)
        self.assertEqual(part.quantity, 2)
        part.status = Part.Status.ORDERED
        part.save(update_fields=["status"])
        self.client.post(reverse("catalog:set_inventory_action", args=[lego_set.pk, "create-missing"]))
        part.refresh_from_db()
        self.assertEqual(part.status, Part.Status.ORDERED)
        self.assertEqual(Part.objects.filter(owner=self.user, lego_set=lego_set).count(), 1)
        self.assertContains(self.client.get(reverse("catalog:missing_parts")), "Head")

    def test_set_inventory_action_is_post_only_and_owner_scoped(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="100-3", name="Test")
        self.assertEqual(self.client.get(reverse("catalog:set_inventory_action", args=[lego_set.pk, "create-missing"])).status_code, 405)
        other = get_user_model().objects.create_user("other-action", "other-action@example.test", "Strong-password-123")
        foreign = LegoSet.objects.create(owner=other, set_number="100-4", name="Foreign")
        self.assertEqual(self.client.post(reverse("catalog:set_inventory_action", args=[foreign.pk, "create-missing"])).status_code, 404)

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
        self.assertEqual((own.owned_quantity, own.status), (0, Part.Status.FOUND))
        self.assertEqual((foreign.owned_quantity, foreign.status), (0, Part.Status.MISSING))

    def test_missing_parts_bulk_toolbar_is_compact_and_disabled_without_selection(self):
        response = self.client.get(reverse("catalog:missing_parts"))
        self.assertContains(response, "Status ändern")
        self.assertContains(response, 'data-selection-count>0</strong> ausgewählt')
        self.assertContains(response, '<button type="submit" disabled>Anwenden</button>')
        self.assertNotContains(response, "Workflowstatus setzen")

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
        self.assertContains(
            response,
            'data-lightbox-image="/integrationen/bild/?url=https%3A%2F%2Fexample.test%2Fpart.png"',
            count=1,
        )
        self.assertEqual({part.lego_set for part in groups[0]["allocations"]}, set(sets))

    def test_grouping_separates_colors_and_derives_all_group_statuses(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="1", name="Statusset")
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="same", name="Black", color="Black", quantity=2, owned_quantity=0)
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="same", name="Red", color="Red", quantity=2, owned_quantity=1)
        Part.objects.create(owner=self.user, lego_set=lego_set, element_id="full", name="Full", color="Red", quantity=3, owned_quantity=2, status=Part.Status.FOUND)
        response = self.client.get(reverse("catalog:missing_parts"))
        groups = response.context["page_obj"].object_list
        self.assertEqual(len(groups), 3)
        self.assertEqual({group["status"] for group in groups}, {Part.Status.MISSING, Part.Status.FOUND})
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
        self.assertEqual((red_first.owned_quantity, red_second.owned_quantity), (1, 0))
        self.assertEqual((red_first.status, red_second.status), (Part.Status.FOUND, Part.Status.FOUND))

    def test_single_allocation_quantity_change_updates_group_aggregation(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="300", name="Mengen")
        part = Part.objects.create(owner=self.user, lego_set=lego_set, element_id="aggregate", name="Aggregate", color="White", quantity=4, owned_quantity=0)
        self.client.post(reverse("catalog:missing_part_quantity", args=[part.pk]), {"owned_quantity": 3})
        group = self.client.get(reverse("catalog:missing_parts")).context["page_obj"].object_list[0]
        self.assertEqual((group["required"], group["owned"], group["missing"], group["status"]), (4, 3, 1, Part.Status.MISSING))
        self.assertEqual(group["stock"], "partial")

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

    def test_direct_quantity_does_not_change_workflow_status(self):
        part = Part.objects.create(owner=self.user, element_id="direct", name="Direkt", quantity=5)
        url = reverse("catalog:missing_part_quantity", args=[part.pk])
        self.assertRedirects(self.client.post(url, {"owned_quantity": 2}), reverse("catalog:missing_parts"))
        part.refresh_from_db()
        self.assertEqual((part.owned_quantity, part.status, part.missing_quantity), (2, Part.Status.MISSING, 3))
        self.assertEqual(self.client.post(url, {"owned_quantity": 6}).status_code, 400)
        self.client.post(url, {"owned_quantity": 5})
        part.refresh_from_db()
        self.assertEqual((part.owned_quantity, part.status), (5, Part.Status.MISSING))

    def test_direct_status_does_not_change_quantity(self):
        part = Part.objects.create(owner=self.user, element_id="status", name="Status", quantity=3, owned_quantity=1)
        url = reverse("catalog:missing_part_status", args=[part.pk])
        self.client.post(url, {"status": Part.Status.FOUND})
        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 1)
        self.client.post(url, {"status": Part.Status.MISSING})
        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 1)

    def test_part_form_keeps_workflow_status_and_stock_independent(self):
        from apps.catalog.forms import PartForm

        form = PartForm(
            {
                "element_id": "consistent", "design_id": "", "part_number": "",
                "name": "Konsistent", "color": "", "quantity": 3,
                "owned_quantity": 0, "unassigned_found_quantity": 0,
                "is_present": "", "status": Part.Status.FOUND, "priority": "normal",
                "unit_price": 0, "supplier": "", "notes": "", "image_url": "",
            },
            owner=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        saved.owner = self.user
        saved.save()
        saved.refresh_from_db()
        self.assertEqual((saved.status, saved.owned_quantity), (Part.Status.FOUND, 0))

    def test_each_workflow_status_filter_is_exact(self):
        url = reverse("catalog:missing_parts")
        records = {}
        for status, label in Part.Status.choices:
            records[status] = Part.objects.create(
                owner=self.user, element_id=f"filter-{status}", name=f"Teil {label}",
                quantity=2, owned_quantity=1, status=status,
            )
        for status, _label in Part.Status.choices:
            with self.subTest(status=status):
                groups = self.client.get(url, {"status": status}).context["page_obj"].object_list
                allocations = [part for group in groups for part in group["allocations"]]
                self.assertEqual(allocations, [records[status]])

    def test_stock_filter_is_independent_from_workflow_status(self):
        url = reverse("catalog:missing_parts")
        complete = Part.objects.create(
            owner=self.user, element_id="stock-complete", name="Komplett",
            quantity=2, owned_quantity=2, status=Part.Status.INSTALLED,
        )
        partial = Part.objects.create(
            owner=self.user, element_id="stock-partial", name="Teilweise",
            quantity=2, owned_quantity=1, status=Part.Status.FOUND,
        )
        missing = Part.objects.create(
            owner=self.user, element_id="stock-none", name="Nicht vorhanden",
            quantity=2, owned_quantity=0, status=Part.Status.ORDERED,
        )
        for value, expected in (
            ("partial", partial), ("none", missing)
        ):
            with self.subTest(stock=value):
                groups = self.client.get(url, {"stock": value}).context["page_obj"].object_list
                allocations = [part for group in groups for part in group["allocations"]]
                self.assertEqual(allocations, [expected])
        self.assertFalse(
            self.client.get(url, {"stock": "complete"}).context["page_obj"].object_list
        )
        self.assertFalse(any(
            complete in group["allocations"]
            for group in self.client.get(url).context["page_obj"].object_list
        ))

    def test_group_workflow_status_is_mixed_not_derived_from_stock(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="mix", name="Gemischt")
        Part.objects.create(
            owner=self.user, lego_set=lego_set, element_id="mix", name="Mix",
            color="Black", quantity=2, owned_quantity=1, status=Part.Status.FOUND,
        )
        Part.objects.create(
            owner=self.user, lego_set=lego_set, element_id="mix", name="Mix",
            color="Black", quantity=2, owned_quantity=1, status=Part.Status.INSTALLED,
        )
        group = self.client.get(reverse("catalog:missing_parts")).context["page_obj"].object_list[0]
        self.assertEqual((group["status"], group["status_label"]), ("mixed", "Gemischt"))
        self.assertEqual((group["stock"], group["stock_label"]), ("partial", "Teilweise vorhanden"))

    def test_missing_page_hides_complete_deleted_and_foreign_records(self):
        visible = Part.objects.create(
            owner=self.user, element_id="open", name="Offen", quantity=2, owned_quantity=1
        )
        Part.objects.create(
            owner=self.user, element_id="complete", name="Erledigt", quantity=1,
            owned_quantity=1, status=Part.Status.INSTALLED,
        )
        from django.utils import timezone
        Part.objects.create(
            owner=self.user, element_id="deleted", name="Gelöscht", quantity=1,
            deleted_at=timezone.now(),
        )
        other = get_user_model().objects.create_user(
            "integrity-other", "integrity-other@example.test", "Strong-password-123"
        )
        Part.objects.create(owner=other, element_id="foreign-open", name="Fremd", quantity=1)
        groups = self.client.get(reverse("catalog:missing_parts")).context["page_obj"].object_list
        allocations = [part for group in groups for part in group["allocations"]]
        self.assertEqual(allocations, [visible])

    def test_minifigure_parts_are_open_deduplicated_and_filterable(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="fig-1", name="Figurenset")
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-a", name="Figur"
        )
        canonical = MinifigurePart.objects.create(
            minifigure=figure, part_number="973", element_id="97301", name="Torso",
            color_id=1, color_name="White", quantity=2, owned_quantity=0,
            image_url="https://cdn.rebrickable.com/torso.png",
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="973", element_id="97301", name="Torso alt",
            color_id=1, color_name="White", quantity=1, owned_quantity=0,
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="3626", name="Kopf", color_name="Yellow",
            quantity=1, owned_quantity=1,
        )
        response = self.client.get(reverse("catalog:missing_parts"), {"kind": "minifigure"})
        groups = response.context["page_obj"].object_list
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["allocations"], [canonical])
        self.assertEqual((groups[0]["first_set"], groups[0]["color"], groups[0]["missing"]), ("fig-1", "White", 2))
        self.assertContains(response, "Figurenset")
        self.assertContains(response, "Figur")
        self.assertContains(response, "https%3A%2F%2Fcdn.rebrickable.com%2Ftorso.png")
        self.assertFalse(
            self.client.get(reverse("catalog:missing_parts"), {"kind": "exclude_minifigure"}).context["page_obj"].object_list
        )

    def test_parallel_normal_representation_of_minifigure_part_is_not_shown_twice(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="fig-2", name="Doppelt")
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-b", name="Pilot"
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="973", element_id="97301", name="Torso",
            color_id=1, color_name="Red", quantity=1,
        )
        Part.objects.create(
            owner=self.user, lego_set=lego_set, part_number="973", element_id="97301",
            name="Torso", color="Red", quantity=1,
        )
        groups = self.client.get(reverse("catalog:missing_parts")).context["page_obj"].object_list
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0]["is_minifigure"])

    def test_integrity_audit_is_read_only_and_reports_duplicates(self):
        from io import StringIO

        from django.core.management import call_command

        lego_set = LegoSet.objects.create(owner=self.user, set_number="audit", name="Audit")
        figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=lego_set, figure_number="fig-audit", name="Auditfigur"
        )
        for _ in range(2):
            MinifigurePart.objects.create(
                minifigure=figure, part_number="head", color_name="Yellow", name="Kopf"
            )
        before = MinifigurePart.objects.count()
        output = StringIO()
        call_command("audit_missing_parts_integrity", stdout=output)
        self.assertIn("duplicate_minifigure_parts: 1", output.getvalue())
        self.assertIn("audit_mode: read-only", output.getvalue())
        self.assertEqual(MinifigurePart.objects.count(), before)

    def test_ajax_status_response_comes_from_reloaded_database_state(self):
        part = Part.objects.create(
            owner=self.user, element_id="ajax", name="Ajax", quantity=1,
            owned_quantity=1, status=Part.Status.FOUND,
        )
        response = self.client.post(
            reverse("catalog:missing_part_status", args=[part.pk]),
            {"status": Part.Status.INSTALLED},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        part.refresh_from_db()
        self.assertEqual(part.status, Part.Status.INSTALLED)
        self.assertEqual(part.owned_quantity, 1)
        self.assertEqual(response.json()["part"]["status"], part.status)
        filtered = self.client.get(reverse("catalog:missing_parts"), {"status": "found"})
        self.assertFalse(any(part in group["allocations"] for group in filtered.context["page_obj"]))

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


class BatchSetImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("batch", "batch@example.test", "A-long-safe-password-123")
        self.client.force_login(self.user)

    def test_batch_page_and_preview_are_owner_protected_post_endpoints(self):
        page = self.client.get(reverse("catalog:set_batch_import"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "batch-default-date")
        response = self.client.post(reverse("catalog:set_batch_preview"), {"set_numbers": "10300 10300"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["duplicates"], 1)

    @patch("apps.integrations.services.rebrickable_set_preview", return_value={"name": "Preview Set", "set_number": "10300-1"})
    def test_preview_one_uses_metadata_only(self, preview):
        self.user.rebrickable_api_key_encrypted = encrypt_secret("preview-key")  # noqa: S106
        self.user.save(update_fields=["rebrickable_api_key_encrypted"])
        response = self.client.post(reverse("catalog:set_batch_preview_one"), {"set_number": "10300"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["set"]["status"], "ready")
        preview.assert_called_once()

    def test_batch_import_one_is_post_only_and_idempotent(self):
        self.assertEqual(self.client.get(reverse("catalog:set_batch_import_one"), {"set_number": "10300"}).status_code, 405)
        LegoSet.objects.create(owner=self.user, set_number="10300-1", name="Existing")
        response = self.client.post(reverse("catalog:set_batch_import_one"), {"set_number": "10300"})
        self.assertEqual(response.json()["status"], "existing")

    @patch("apps.integrations.rebrickable_sync.synchronize_set")
    @patch("apps.integrations.services.rebrickable_minifigures")
    @patch("apps.integrations.services.rebrickable_set")
    def test_batch_import_saves_purchase_metadata_and_built_status(self, _set_api, _fig_api, sync):
        from apps.integrations.rebrickable_sync import SyncResult

        self.user.rebrickable_api_key_encrypted = encrypt_secret("batch-key")  # noqa: S106
        self.user.save(update_fields=["rebrickable_api_key_encrypted"])
        sync.return_value = SyncResult(0, 0, 0)
        response = self.client.post(reverse("catalog:set_batch_import_one"), {
            "set_number": "10300", "purchase_date": "2026-08-29", "purchase_price": "169,99",
            "condition": "neu", "notes": "Müller",
        })
        self.assertEqual(response.status_code, 200)
        lego_set = LegoSet.objects.get(owner=self.user, set_number="10300-1")
        self.assertEqual((lego_set.purchase_date.isoformat(), lego_set.purchase_price, lego_set.build_status), ("2026-08-29", Decimal("169.99"), "gebaut"))

    def test_batch_import_rejects_invalid_metadata_without_creating_set(self):
        response = self.client.post(reverse("catalog:set_batch_import_one"), {"set_number": "10301", "purchase_date": "not-a-date"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LegoSet.objects.filter(owner=self.user, set_number="10301-1").exists())


class MissingSavedViewsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user("views", "views@example.test", "A-long-safe-password-123")
        self.other = user_model.objects.create_user("otherviews", "otherviews@example.test", "A-long-safe-password-123")
        self.client.force_login(self.user)

    def test_saved_view_is_visible_and_load_restores_get_filters(self):
        item = SavedView.objects.create(owner=self.user, area="missing_parts", name="Bestellt Schwarz", path="/fehlteile/", configuration={"query": "q=Brick&status=ordered&color=Black&sort=-missing"})
        response = self.client.get(reverse("catalog:missing_parts"))
        self.assertContains(response, "Gespeicherte Ansichten")
        self.assertContains(response, "Bestellt Schwarz")
        loaded = self.client.get(reverse("saved_view_load", args=[item.pk]))
        self.assertEqual(loaded.status_code, 302)
        self.assertIn("q=Brick&status=ordered&color=Black&sort=-missing", loaded["Location"])
        filtered = self.client.get(loaded["Location"])
        self.assertEqual(filtered.context["status"], "ordered")
        self.assertEqual(filtered.context["selected_colors"], ["Black"])
        self.assertEqual(filtered.context["sort"], "-missing")

    def test_saved_view_owner_isolation_and_delete_are_safe(self):
        foreign = SavedView.objects.create(owner=self.other, area="missing_parts", name="Fremd", path="/fehlteile/", configuration={"query": "status=ordered"})
        self.assertNotContains(self.client.get(reverse("catalog:missing_parts")), "Fremd")
        self.assertEqual(self.client.get(reverse("saved_view_load", args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("saved_view_delete", args=[foreign.pk])).status_code, 404)
        own = SavedView.objects.create(owner=self.user, area="missing_parts", name="Eigen", path="/fehlteile/", configuration={})
        self.assertEqual(self.client.get(reverse("saved_view_delete", args=[own.pk])).status_code, 405)
        deleted = self.client.post(reverse("saved_view_delete", args=[own.pk]), {"next": "/fehlteile/"})
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse(SavedView.objects.filter(pk=own.pk).exists())
