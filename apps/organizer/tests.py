from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import LegoSet
from apps.inventory.models import InventoryItem

from .models import (
    Collection,
    LabelTemplate,
    Loan,
    MinifigurePart,
    Moc,
    MocPart,
    MocVersion,
    PersonalNote,
    SetMinifigure,
    WishlistItem,
)


class OrganizerOwnershipTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.first = users.objects.create_user(
            "org1", "org1@example.test", "A-very-long-password-123", email_verified=True
        )
        self.second = users.objects.create_user(
            "org2", "org2@example.test", "A-very-long-password-123", email_verified=True
        )
        self.foreign = Collection.objects.create(owner=self.second, name="Foreign")

    def test_foreign_collection_is_not_visible_or_mutable(self):
        self.client.force_login(self.first)
        self.assertNotContains(
            self.client.get(reverse("organizer:list", args=["collections"])), "Foreign"
        )
        self.assertEqual(
            self.client.get(
                reverse("organizer:edit", args=["collections", self.foreign.pk])
            ).status_code,
            404,
        )

    def test_moc_version_crud_activate_and_ownership(self):
        moc = Moc.objects.create(owner=self.first, name="Build")
        MocPart.objects.create(moc=moc, part_number="3001", name="Brick", required_quantity=2)
        self.client.force_login(self.first)
        response = self.client.post(
            reverse("organizer:moc_version_create", args=[moc.pk]),
            {"version": "1.0", "name": "Initial", "description": "First", "notes": "Keep"},
        )
        self.assertRedirects(response, reverse("organizer:detail", args=["mocs", moc.pk]))
        version = MocVersion.objects.get(moc=moc)
        self.assertEqual(version.parts_snapshot[0]["part_number"], "3001")
        moc.parts.all().delete()
        MocPart.objects.create(moc=moc, part_number="9999", name="Changed")
        self.client.post(reverse("organizer:moc_version_activate", args=[moc.pk, version.pk]))
        self.assertEqual(list(moc.parts.values_list("part_number", flat=True)), ["3001"])
        response = self.client.get(reverse("organizer:moc_version_edit", args=[moc.pk, version.pk]))
        self.assertEqual(response.status_code, 200)
        foreign_moc = Moc.objects.create(owner=self.second, name="Foreign MOC")
        foreign_version = MocVersion.objects.create(moc=foreign_moc, version="1", parts_snapshot=[])
        self.assertEqual(
            self.client.post(
                reverse(
                    "organizer:moc_version_activate",
                    args=[foreign_moc.pk, foreign_version.pk],
                )
            ).status_code,
            404,
        )
        self.client.post(reverse("organizer:moc_version_delete", args=[moc.pk, version.pk]))
        self.assertFalse(MocVersion.objects.filter(pk=version.pk).exists())

    def test_label_preview_print_layout_qr_and_ownership(self):
        label = LabelTemplate.objects.create(
            owner=self.first,
            name="Shelf",
            width_mm=50,
            height_mm=30,
            configuration={"qr_code": True, "text": "Bin A"},
        )
        item = InventoryItem.objects.create(
            owner=self.first,
            part_number="3001",
            element_id="300101",
            name="Brick",
            color="Red",
            quantity=4,
        )
        self.client.force_login(self.first)
        response = self.client.get(reverse("organizer:label_preview", args=[label.pk]))
        self.assertContains(response, "50")
        self.assertContains(response, "Brick")
        self.assertContains(response, "Bin A")
        qr = self.client.get(reverse("organizer:label_qr", args=[label.pk, item.pk]))
        self.assertEqual(qr["Content-Type"], "image/svg+xml")
        foreign = LabelTemplate.objects.create(owner=self.second, name="Foreign label")
        self.assertEqual(
            self.client.get(reverse("organizer:label_preview", args=[foreign.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("organizer:delete", args=["collections", self.foreign.pk])
            ).status_code,
            404,
        )

    def test_label_capacity_start_orientation_margins_and_modes(self):
        label = LabelTemplate.objects.create(
            owner=self.first,
            name="HERMA",
            width_mm=50,
            height_mm=30,
            orientation="landscape",
            configuration={"rows": 2, "columns": 2, "margin_top": 5, "margin_left": 7},
        )
        for number in range(5):
            InventoryItem.objects.create(
                owner=self.first, part_number=f"30{number}", name=f"Item {number}", quantity=1
            )
        lego_set = LegoSet.objects.create(owner=self.first, set_number="100-1", name="Mode Set")
        SetMinifigure.objects.create(
            owner=self.first, lego_set=lego_set, figure_number="fig-1", name="Mode Figure"
        )
        self.client.force_login(self.first)
        response = self.client.get(
            reverse("organizer:label_preview", args=[label.pk]), {"start": 3}
        )
        self.assertEqual(len(response.context["leading_slots"]), 2)
        self.assertEqual(len(response.context["items"]), 2)
        css = self.client.get(reverse("organizer:label_print_css", args=[label.pk]))
        self.assertContains(css, "A4 landscape")
        self.assertContains(css, "margin:5.00mm")
        last = self.client.get(reverse("organizer:label_preview", args=[label.pk]), {"start": 999})
        self.assertEqual(last.context["start"], 4)
        self.assertEqual(len(last.context["items"]), 1)
        self.assertContains(
            self.client.get(reverse("organizer:label_preview", args=[label.pk]), {"mode": "set"}),
            "Mode Set",
        )
        self.assertContains(
            self.client.get(
                reverse("organizer:label_preview", args=[label.pk]), {"mode": "minifigure"}
            ),
            "Mode Figure",
        )

    def test_label_configuration_and_start_are_normalized_without_server_error(self):
        label = LabelTemplate.objects.create(
            owner=self.first,
            name="Robust",
            width_mm=50,
            height_mm=30,
            configuration=[],
        )
        self.client.force_login(self.first)
        url = reverse("organizer:label_preview", args=[label.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.context["rows"], response.context["columns"]), (4, 2))

        label.configuration = {"rows": "abc"}
        label.save(update_fields=["configuration"])
        self.assertEqual(self.client.get(url).context["rows"], 4)
        for value, expected in (("abc", 1), ("-100", 1), ("999999", 8)):
            with self.subTest(start=value):
                page = self.client.get(url, {"start": value})
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context["start"], expected)

    def test_absurd_configuration_and_dimensions_are_bounded_for_print(self):
        label = LabelTemplate.objects.create(
            owner=self.first,
            name="Bounded",
            width_mm=9999,
            height_mm=9999,
            configuration={
                "rows": -500,
                "columns": 999999,
                "margin_top": -20,
                "margin_right": 999999,
                "margin_bottom": "invalid",
                "margin_left": 999999,
                "qr_code": "false",
                "text": ["safe"],
            },
        )
        self.client.force_login(self.first)
        preview = self.client.get(reverse("organizer:label_preview", args=[label.pk]))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context["rows"], 1)
        self.assertGreaterEqual(preview.context["columns"], 1)
        self.assertLessEqual(preview.context["columns"], 10)
        self.assertFalse(preview.context["label_configuration"].qr_code)
        self.assertEqual(preview.context["label_configuration"].text, "['safe']")
        css = self.client.get(reverse("organizer:label_print_css", args=[label.pk]))
        self.assertEqual(css.status_code, 200)
        css_text = css.content.decode()
        self.assertNotIn("9999.00mm", css_text)
        self.assertNotIn("nan", css_text.casefold())

    @override_settings(PUBLIC_URL="https://brickmissing.example")
    def test_inventory_qr_uses_existing_owner_protected_absolute_url(self):
        label = LabelTemplate.objects.create(owner=self.first, name="QR")
        item = InventoryItem.objects.create(
            owner=self.first, part_number="3001", name="Brick", quantity=1
        )
        foreign_item = InventoryItem.objects.create(
            owner=self.second, part_number="secret", name="Secret", quantity=1
        )
        self.client.force_login(self.first)
        with patch("apps.organizer.views.qr_svg", return_value=b"<svg/>") as mocked_qr:
            response = self.client.get(
                reverse("organizer:label_qr", args=[label.pk, item.pk])
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mocked_qr.call_args.args[0],
            f"https://brickmissing.example{reverse('inventory:edit', args=[item.pk])}",
        )
        self.assertEqual(mocked_qr.call_args.kwargs["border"], 4)
        self.assertEqual(
            self.client.get(
                reverse("organizer:label_qr", args=[label.pk, foreign_item.pk])
            ).status_code,
            404,
        )

    def test_read_only_label_resource_routes_reject_post_and_qr_has_quiet_zone(self):
        label = LabelTemplate.objects.create(owner=self.first, name="Methods")
        item = InventoryItem.objects.create(
            owner=self.first, part_number="3001", name="Brick", quantity=1
        )
        lego_set = LegoSet.objects.create(owner=self.first, set_number="405", name="QR Set")
        self.client.force_login(self.first)
        urls = (
            reverse("organizer:label_preview", args=[label.pk]),
            reverse("organizer:label_print_css", args=[label.pk]),
            reverse("organizer:label_qr", args=[label.pk, item.pk]),
            reverse("organizer:label_set_qr", args=[lego_set.pk]),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)
        with patch("apps.organizer.views.qr_svg", return_value=b"<svg/>") as mocked_qr:
            self.client.get(reverse("organizer:label_set_qr", args=[lego_set.pk]))
        self.assertEqual(mocked_qr.call_args.kwargs["border"], 4)

    @patch("apps.accounts.totp.qrcode.make")
    def test_qr_helper_default_remains_totp_compatible_and_border_is_configurable(self, make):
        from apps.accounts.totp import qr_svg

        qr_svg("otpauth://example")
        self.assertEqual(make.call_args.kwargs["border"], 2)
        qr_svg("https://brickmissing.example", border=4)
        self.assertEqual(make.call_args.kwargs["border"], 4)

    def test_owned_domain_get_edit_delete_and_relation_idor_matrix(self):
        foreign_set = LegoSet.objects.create(
            owner=self.second, set_number="foreign-1", name="Foreign Set"
        )
        records = {
            "collections": Collection.objects.create(owner=self.second, name="Foreign Collection"),
            "mocs": Moc.objects.create(owner=self.second, name="Foreign MOC matrix"),
            "wishlist": WishlistItem.objects.create(
                owner=self.second, reference="x", name="Foreign Wish"
            ),
            "loans": Loan.objects.create(
                owner=self.second,
                entity_type="set",
                entity_id="x",
                borrower="Foreign",
                loaned_at=timezone.now(),
            ),
            "notes": PersonalNote.objects.create(
                owner=self.second, title="Foreign Note", content="secret"
            ),
            "labels": LabelTemplate.objects.create(owner=self.second, name="Foreign Label matrix"),
            "minifigures": SetMinifigure.objects.create(
                owner=self.second,
                lego_set=foreign_set,
                figure_number="foreign-fig",
                name="Foreign Figure",
            ),
        }
        self.client.force_login(self.first)
        for area, record in records.items():
            self.assertEqual(
                self.client.get(reverse("organizer:edit", args=[area, record.pk])).status_code,
                404,
            )
            self.assertEqual(
                self.client.post(reverse("organizer:delete", args=[area, record.pk])).status_code,
                404,
            )
        own_collection = Collection.objects.create(owner=self.first, name="Own")
        response = self.client.post(
            reverse("organizer:create", args=["mocs"]),
            {
                "name": "Injected",
                "collection": records["collections"].pk,
                "location": "",
                "status": "Planung",
                "version": "1.0",
                "progress": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Moc.objects.filter(owner=self.first, name="Injected").exists())
        self.assertTrue(Collection.objects.filter(pk=own_collection.pk).exists())


class OrganizerListRenderingTests(TestCase):
    areas = ("collections", "mocs", "wishlist", "loans", "notes", "labels", "minifigures")

    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create_user(
            "lists", "lists@example.test", "A-very-long-password-123", email_verified=True
        )
        self.client.force_login(self.user)

    def test_every_empty_organizer_list_renders(self):
        for area in self.areas:
            with self.subTest(area=area):
                response = self.client.get(reverse("organizer:list", args=[area]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Noch keine Einträge vorhanden.")

    def test_every_create_form_uses_shared_german_form_system(self):
        LegoSet.objects.create(owner=self.user, set_number="FORM-1", name="Formularset")
        for area in self.areas:
            with self.subTest(area=area):
                response = self.client.get(reverse("organizer:create", args=[area]))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "organizer/form.html")
                self.assertContains(response, "Organisation")
                self.assertContains(response, "Speichern")
                self.assertContains(response, "Abbrechen")
                self.assertNotContains(response, " object (")

    def test_organizer_navigation_marks_current_area_and_number_fields_are_compact(self):
        response = self.client.get(reverse("organizer:list", args=["collections"]))
        self.assertContains(response, 'aria-current="page">Sammlungen</a>')
        form = self.client.get(reverse("organizer:create", args=["labels"]))
        self.assertContains(form, 'class="compact-number"')
        self.assertContains(form, "Querformat")
        self.assertContains(form, "Hochformat")

    def test_every_populated_organizer_list_uses_its_explicit_display_fields(self):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="10300", name="Zeitmaschine")
        expected = {
            "collections": "V7 Hauptsammlung",
            "mocs": "V7 Bahnhof",
            "wishlist": "V7 Wunschset",
            "loans": "Max Mustermann",
            "notes": "V7 Notiz",
            "labels": "V7 Teileetikett",
            "minifigures": "V7 Minifigur",
        }
        Collection.objects.create(owner=self.user, legacy_id=5, name=expected["collections"])
        Moc.objects.create(owner=self.user, legacy_id=6, name=expected["mocs"])
        WishlistItem.objects.create(
            owner=self.user,
            legacy_id=7,
            reference="10300-1",
            name=expected["wishlist"],
        )
        Loan.objects.create(
            owner=self.user,
            legacy_id=8,
            entity_type="set",
            entity_id="10300-1",
            borrower=expected["loans"],
            loaned_at=timezone.now(),
        )
        PersonalNote.objects.create(
            owner=self.user, legacy_id=9, title=expected["notes"], content="Migriert"
        )
        LabelTemplate.objects.create(owner=self.user, legacy_id=10, name=expected["labels"])
        SetMinifigure.objects.create(
            owner=self.user,
            lego_set=lego_set,
            legacy_id=11,
            figure_number="fig-1",
            name=expected["minifigures"],
        )

        for area, label in expected.items():
            with self.subTest(area=area):
                response = self.client.get(reverse("organizer:list", args=[area]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, label)
                self.assertNotContains(response, "Collection object")

    def test_default_label_template_is_listed_first_and_marked(self):
        LabelTemplate.objects.create(owner=self.user, name="A normal")
        preferred = LabelTemplate.objects.create(
            owner=self.user, name="Z preferred", is_default=True
        )
        response = self.client.get(reverse("organizer:list", args=["labels"]))
        self.assertEqual(response.context["rows"][0]["record"], preferred)
        self.assertContains(response, "Standard")

    def test_organizer_lists_are_paginated_without_silent_limit(self):
        Collection.objects.bulk_create(
            [Collection(owner=self.user, name=f"Collection {index:03d}") for index in range(501)]
        )

        first = self.client.get(reverse("organizer:list", args=["collections"]))
        self.assertEqual(first.context["page_obj"].paginator.count, 501)
        self.assertEqual(len(first.context["page_obj"].object_list), 50)
        self.assertContains(first, 'class="pagination"')

        last = self.client.get(reverse("organizer:list", args=["collections"]), {"page": 11})
        self.assertEqual(len(last.context["page_obj"].object_list), 1)
        self.assertContains(last, "Collection 000")

    def test_organizer_area_navigation_is_compact_on_mobile(self):
        response = self.client.get(reverse("organizer:list", args=["collections"]))
        self.assertContains(response, 'class="filters organizer-area-nav"')
        self.assertContains(response, 'aria-current="page">Sammlungen</a>')


class MinifigureInventoryInteractionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("figure-owner", "figure@example.test", "A-very-long-password-123")
        self.other = get_user_model().objects.create_user("figure-other", "other-figure@example.test", "A-very-long-password-123")
        lego_set = LegoSet.objects.create(owner=self.user, set_number="75010", name="B-wing")
        self.figure = SetMinifigure.objects.create(owner=self.user, lego_set=lego_set, figure_number="fig-1", name="Pilot")
        self.part = MinifigurePart.objects.create(minifigure=self.figure, part_number="head", name="Kopf", quantity=2)
        self.client.force_login(self.user)

    def test_quantity_and_all_none_actions(self):
        quantity_url = reverse("organizer:minifigure_part_quantity", args=[self.figure.pk, self.part.pk])
        self.assertRedirects(self.client.post(quantity_url, {"owned_quantity": 1}), reverse("organizer:detail", args=["minifigures", self.figure.pk]))
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 1)
        self.client.post(reverse("organizer:minifigure_inventory_action", args=[self.figure.pk, "complete"]))
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 2)
        self.client.post(reverse("organizer:minifigure_inventory_action", args=[self.figure.pk, "missing"]))
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 0)

    def test_foreign_user_cannot_change_minifigure_part(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse("organizer:minifigure_part_quantity", args=[self.figure.pk, self.part.pk]), {"owned_quantity": 2})
        self.assertEqual(response.status_code, 404)

    def test_inline_quantity_returns_complete_json_without_redirect(self):
        response = self.client.post(
            reverse("organizer:minifigure_part_quantity", args=[self.figure.pk, self.part.pk]),
            {"owned_quantity": 2},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["part"]["id"], self.part.pk)
        self.assertEqual(payload["part"]["minifigure_id"], self.figure.pk)
        self.assertEqual(payload["part"]["required"], 2)
        self.assertEqual(payload["part"]["owned"], 2)
        self.assertEqual(payload["part"]["missing"], 0)
        self.assertEqual(payload["part"]["status"], "complete")
        self.assertEqual(payload["figure"]["id"], self.figure.pk)
        self.assertEqual(payload["figure"]["owned"], 2)
        self.assertEqual(payload["figure"]["required"], 2)
        self.assertEqual(payload["figure"]["missing"], 0)
        self.assertEqual(payload["figure"]["status"], "complete")
        self.assertEqual(payload["set"]["key"], "complete")

    def test_inline_manual_quantity_transitions_are_persistent_and_idempotent(self):
        url = reverse("organizer:minifigure_part_quantity", args=[self.figure.pk, self.part.pk])
        headers = {"HTTP_ACCEPT": "application/json", "HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

        partial = self.client.post(url, {"owned_quantity": 1}, **headers).json()
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 1)
        self.assertEqual((partial["part"]["owned"], partial["part"]["missing"], partial["part"]["status"]), (1, 1, "partial"))
        self.assertEqual((partial["figure"]["owned"], partial["figure"]["required"], partial["figure"]["status"]), (1, 2, "partial"))

        missing = self.client.post(url, {"owned_quantity": 0}, **headers).json()
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 0)
        self.assertEqual((missing["part"]["owned"], missing["part"]["missing"], missing["part"]["status"]), (0, 2, "missing"))
        self.assertEqual(missing["figure"]["status"], "missing")

        repeated = self.client.post(url, {"owned_quantity": 0}, **headers).json()
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 0)
        self.assertEqual(repeated["figure"], missing["figure"])

    def test_x_button_payload_makes_complete_figure_incomplete_and_persists(self):
        self.part.owned_quantity = self.part.quantity
        self.part.save(update_fields=["owned_quantity"])
        response = self.client.post(
            reverse("organizer:minifigure_part_quantity", args=[self.figure.pk, self.part.pk]),
            {"owned_quantity": 0},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 0)
        payload = response.json()
        self.assertEqual(payload["part"]["status"], "missing")
        self.assertEqual(payload["figure"]["status"], "missing")

    def test_part_from_another_figure_cannot_be_changed_through_owned_figure(self):
        other_figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=self.figure.lego_set, figure_number="fig-2", name="Mechaniker"
        )
        other_part = MinifigurePart.objects.create(
            minifigure=other_figure, part_number="legs", name="Beine", quantity=1
        )
        response = self.client.post(
            reverse("organizer:minifigure_part_quantity", args=[self.figure.pk, other_part.pk]),
            {"owned_quantity": 1},
        )
        self.assertEqual(response.status_code, 404)
        other_part.refresh_from_db()
        self.assertEqual(other_part.owned_quantity, 0)


class MinifigurePageTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create(username="mini-page", email="mini-page@example.test")
        other = users.objects.create(username="mini-other", email="mini-other@example.test")
        self.lego_set = LegoSet.objects.create(
            owner=self.user, set_number="3180", name="Tank Truck"
        )
        self.figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=self.lego_set, figure_number="fig-000265",
            name="Mann mit blauer Jacke", image_url="https://example.test/figure.png",
        )
        self.part = MinifigurePart.objects.create(
            minifigure=self.figure, part_number="86035", element_id="4567909",
            name="Kappe", color_name="Blue", quantity=2, owned_quantity=1,
        )
        foreign_set = LegoSet.objects.create(owner=other, set_number="SECRET", name="Fremd")
        SetMinifigure.objects.create(
            owner=other, lego_set=foreign_set, figure_number="foreign", name="Geheimfigur"
        )
        self.client.force_login(self.user)

    def test_page_group_search_filter_parts_status_and_user_scope(self):
        url = reverse("organizer:minifigure_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        for text in ("Set 3180", "Tank Truck", "fig-000265", "Einzelteile anzeigen", "Teilweise"):
            self.assertContains(response, text)
        self.assertNotContains(response, "Geheimfigur")
        self.assertContains(self.client.get(url, {"q": "Jacke"}), "fig-000265")
        self.assertNotContains(self.client.get(url, {"q": "unauffindbar"}), "fig-000265")
        self.assertContains(self.client.get(url, {"set": self.lego_set.pk}), "Tank Truck")

    def test_every_sort_option_renders_and_direct_update_is_scoped(self):
        url = reverse("organizer:minifigure_list")
        for sort in ("set_number", "-set_number", "name", "-name", "figure_number",
                     "-figure_number", "completeness", "-missing", "missing",
                     "-required", "-owned"):
            with self.subTest(sort=sort):
                self.assertEqual(self.client.get(url, {"sort": sort}).status_code, 200)
        response = self.client.post(
            reverse("organizer:minifigure_part_quantity", args=[self.figure.pk, self.part.pk]),
            {"owned_quantity": 2, "return": "list"},
        )
        self.assertRedirects(response, url)
        self.part.refresh_from_db()
        self.assertEqual(self.part.owned_quantity, 2)

    def _create_paged_figures(self, count=35, lego_set=None):
        lego_set = lego_set or self.lego_set
        figures = []
        for index in range(count):
            figure = SetMinifigure.objects.create(
                owner=self.user,
                lego_set=lego_set,
                figure_number=f"paged-{index:03d}",
                name=f"Paged Figure {index:03d}",
            )
            MinifigurePart.objects.create(
                minifigure=figure,
                part_number=f"part-{index:03d}",
                name=f"Part Paged {index:03d}",
                quantity=1,
            )
            figures.append(figure)
        return figures

    def test_pagination_renders_only_current_page_figures_and_parts(self):
        figures = self._create_paged_figures()
        url = reverse("organizer:minifigure_list")
        first = self.client.get(url, {"q": "Paged", "sort": "figure_number"})
        second = self.client.get(
            url, {"q": "Paged", "sort": "figure_number", "page": 2}
        )
        first_records = [record for group in first.context["groups"] for record in group["figures"]]
        second_records = [record for group in second.context["groups"] for record in group["figures"]]
        self.assertEqual([len(first_records), len(second_records)], [30, 5])
        rendered = [record["figure"].pk for record in first_records + second_records]
        self.assertEqual(len(rendered), len(set(rendered)))
        self.assertEqual(set(rendered), {figure.pk for figure in figures})
        self.assertContains(first, "Part Paged 029")
        self.assertNotContains(first, "Part Paged 030")
        self.assertContains(second, "Part Paged 030")
        self.assertContains(first, "Seite 1 von 2")
        for fragment in ("q=Paged", "sort=figure_number", "page=2"):
            self.assertContains(first, fragment)

    def test_pagination_applies_set_filter_and_sort_before_grouping(self):
        other_set = LegoSet.objects.create(
            owner=self.user, set_number="9990", name="Paged other set"
        )
        self._create_paged_figures(31, lego_set=other_set)
        url = reverse("organizer:minifigure_list")
        response = self.client.get(
            url,
            {"set": other_set.pk, "sort": "-figure_number", "page": 2},
        )
        records = [record for group in response.context["groups"] for record in group["figures"]]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["figure"].lego_set_id, other_set.pk)
        self.assertEqual(response.context["page_obj"].paginator.count, 31)
        self.assertContains(response, f"set={other_set.pk}")
        self.assertContains(response, "sort=-figure_number")
        self.assertEqual(
            self.client.get(url, {"set": other_set.pk}).context["page_obj"].number, 1
        )

    def test_pagination_empty_single_page_and_progress_accessible_name(self):
        url = reverse("organizer:minifigure_list")
        empty = self.client.get(url, {"q": "does-not-exist"})
        self.assertEqual(empty.context["page_obj"].paginator.count, 0)
        self.assertContains(empty, "Keine Minifiguren gefunden")
        self.assertNotContains(empty, 'class="pagination"')
        single = self.client.get(url, {"q": self.figure.figure_number})
        self.assertEqual(single.context["page_obj"].paginator.count, 1)
        self.assertNotContains(single, 'class="pagination"')
        self.assertContains(
            single,
            f'aria-label="Vollständigkeit von {self.figure.name}: 50 Prozent"',
        )
        self.assertNotContains(single, 'class="panel section-heading"')


class LabelStudioTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create(username="labels-page", email="labels-page@example.test")
        other = users.objects.create(username="labels-other", email="labels-other@example.test")
        self.lego_set = LegoSet.objects.create(
            owner=self.user, set_number="7345-1", name="Transport Chopper", theme="Creator",
            year=2012, total_parts=383, image_url="https://example.test/set.png",
        )
        SetMinifigure.objects.create(
            owner=self.user, lego_set=self.lego_set, figure_number="fig-a", name="Pilot", quantity=2
        )
        foreign = LegoSet.objects.create(owner=other, set_number="9999", name="Geheimes Set")
        self.foreign_pk = foreign.pk
        self.client.force_login(self.user)

    def test_login_ownership_search_layout_and_start_positions(self):
        url = reverse("organizer:label_studio")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HERMA 5077")
        self.assertContains(response, "Transport Chopper")
        self.assertNotContains(response, "Geheimes Set")
        self.assertEqual(len(response.context["slots"]), 8)
        for start in range(1, 9):
            with self.subTest(start=start):
                page = self.client.get(url, {"selection": 1, "item": self.lego_set.pk, "start": start})
                self.assertEqual(page.context["slots"][: start - 1], [None] * (start - 1))
        self.assertEqual(list(self.client.get(url, {"q": "kein Treffer"}).context["sets"]), [])

    def test_label_types_minifigure_count_images_and_qr_targets(self):
        url = reverse("organizer:label_studio")
        common = {"selection": 1, "item": self.lego_set.pk}
        for label_type in ("full", "collected", "per_minifigure", "colors"):
            with self.subTest(label_type=label_type):
                self.assertEqual(self.client.get(url, {**common, "type": label_type}).status_code, 200)
        page = self.client.get(url, {**common, "type": "per_minifigure"})
        self.assertEqual(sum(slot is not None for slot in page.context["slots"]), 2)
        self.assertContains(self.client.get(url, common), "label-set-image")
        self.assertNotContains(self.client.get(url, {**common, "images": 0}), "label-set-image")
        for target in ("set", "inventory", "missing", "edit", "bricklink", "rebrickable"):
            qr = self.client.get(
                reverse("organizer:label_set_qr", args=[self.lego_set.pk]), {"target": target}
            )
            self.assertEqual(qr.status_code, 200)
            self.assertEqual(qr["Content-Type"], "image/svg+xml")
        self.assertEqual(
            self.client.get(reverse("organizer:label_set_qr", args=[self.foreign_pk])).status_code,
            404,
        )

    def test_minifigure_label_has_identity_image_status_and_owner_protected_qr(self):
        figure = self.lego_set.minifigures_inventory.get()
        page = self.client.get(
            reverse("organizer:label_studio"),
            {"selection": 1, "type": "minifigure", "item": self.lego_set.pk},
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, figure.figure_number)
        self.assertContains(page, figure.name)
        self.assertContains(page, self.lego_set.set_number)
        self.assertContains(page, "label-minifigure")
        self.assertContains(page, reverse("organizer:label_minifigure_qr", args=[figure.pk]))
        qr = self.client.get(reverse("organizer:label_minifigure_qr", args=[figure.pk]))
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr["Content-Type"], "image/svg+xml")

    def test_missing_part_label_has_quantities_color_set_and_qr(self):
        self.lego_set.inventory_items.create(
            part_number="3001", element_id="300101", name="Brick", color_name="Rot",
            required_quantity=5, owned_quantity=2, image_url="https://example.test/brick.png",
        )
        page = self.client.get(
            reverse("organizer:label_studio"),
            {"selection": 1, "type": "missing_parts", "item": self.lego_set.pk},
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "3001")
        self.assertContains(page, "Rot")
        self.assertContains(page, "Soll 5")
        self.assertContains(page, "Vorhanden 2")
        self.assertContains(page, "Fehlend 3")
        self.assertContains(page, "label-missing-part")
        self.assertContains(page, reverse("organizer:label_set_qr", args=[self.lego_set.pk]))
        self.assertContains(page, "label-item-image")

    def test_four_templates_have_independent_layouts_and_partial_response(self):
        url = reverse("organizer:label_studio")
        common = {"selection": 1, "item": self.lego_set.pk}
        collected = self.client.get(url, {**common, "type": "collected"})
        self.assertContains(collected, "number-grid")
        self.assertEqual(collected.context["slots"][0]["numbers"], ["7345-1"])
        small = self.client.get(url, {**common, "type": "per_minifigure", "start": 189})
        self.assertContains(small, "25,4 × 10 mm")
        self.assertEqual(small.context["capacity"], 189)
        checked = self.client.get(
            url, {"selection": 1, "type": "colors", "checked_text": "GEPRÜFT", "checked_count": 3}
        )
        self.assertEqual(sum(slot is not None for slot in checked.context["slots"]), 3)
        self.assertContains(checked, "GEPRÜFT")
        partial = self.client.post(
            url, {**common, "type": "full"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertTemplateUsed(partial, "organizer/labels/preview.html")
        self.assertNotContains(partial, "<html")

    def test_collected_numbers_have_deterministic_internal_cut_grid(self):
        second = LegoSet.objects.create(
            owner=self.user, set_number="8000-1", name="Second collected set"
        )
        third = LegoSet.objects.create(
            owner=self.user, set_number="9000-1", name="Third collected set"
        )
        response = self.client.get(
            reverse("organizer:label_studio"),
            {
                "selection": 1,
                "type": "collected",
                "item": [self.lego_set.pk, second.pk, third.pk],
            },
        )
        self.assertContains(response, "7345-1")
        self.assertContains(response, "8000-1")
        self.assertContains(response, "9000-1")
        self.assertContains(response, "has-right-cut", count=2)
        self.assertContains(response, "has-bottom-cut", count=0)
        self.assertContains(response, 'class="number-grid-item is-last"', count=1)

        css = (Path(settings.BASE_DIR) / "static" / "css" / "labels.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".number-grid-item.has-right-cut::after", css)
        self.assertIn(".number-grid-item.has-bottom-cut::before", css)
        self.assertNotIn(":nth-child(4n)", css)
        cut_line_rule = css.split(".number-grid-item.has-right-cut::after", 1)[1].split("}", 1)[0]
        self.assertIn("border-right:.35mm dashed", cut_line_rule)
        self.assertNotIn("border-left", cut_line_rule)

    def test_control_bag_uses_centered_vector_checkmark_in_ajax_preview(self):
        response = self.client.post(
            reverse("organizer:label_studio"),
            {
                "selection": 1,
                "type": "colors",
                "checked_text": "GEPRÜFT",
                "checked_count": 1,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="print-label label-checked"')
        self.assertContains(response, 'class="checkmark" aria-hidden="true"')
        self.assertContains(response, 'viewBox="0 0 24 24"')
        self.assertContains(response, 'class="checkmark-circle"')
        self.assertContains(response, 'class="checkmark-tick"')
        self.assertContains(response, "INHALT KONTROLLIERT")

        css = (Path(settings.BASE_DIR) / "static" / "css" / "labels.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            ".label-checked .checkmark svg{display:block;width:100%;height:100%}",
            css,
        )
        self.assertIn("stroke-linecap:round;stroke-linejoin:round", css)

    def test_get_post_preview_full_refresh_and_csrf_protection(self):
        url = reverse("organizer:label_studio")
        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'method="post"')
        self.assertContains(get_response, "csrfmiddlewaretoken")

        preview = self.client.post(
            url,
            {"selection": 1, "type": "full", "item": self.lego_set.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(preview.status_code, 200)
        self.assertTemplateUsed(preview, "organizer/labels/preview.html")
        self.assertNotContains(preview, "<html")

        full = self.client.post(
            url,
            {"selection": 1, "type": "collected", "item": self.lego_set.pk},
        )
        self.assertEqual(full.status_code, 200)
        self.assertTemplateUsed(full, "organizer/label_studio.html")
        self.assertContains(full, "data-label-studio")
        self.assertEqual(full.context["label_type"], "collected")

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        denied = csrf_client.post(
            url,
            {"selection": 1, "type": "full", "item": self.lego_set.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(denied.status_code, 403)
        csrf_client.get(url)
        token = csrf_client.cookies["csrftoken"].value
        allowed = csrf_client.post(
            url,
            {
                "csrfmiddlewaretoken": token,
                "selection": 1,
                "type": "full",
                "item": self.lego_set.pk,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(allowed.status_code, 200)

    def test_ajax_search_updates_visible_sets_and_preserves_hidden_selection(self):
        second = LegoSet.objects.create(
            owner=self.user, set_number="8000-1", name="Second searchable set"
        )
        url = reverse("organizer:label_studio")
        filtered = self.client.post(
            url,
            {
                "selection": 1,
                "type": "full",
                "q": "Second",
                "item": self.lego_set.pk,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertTemplateUsed(filtered, "organizer/labels/studio_update.html")
        self.assertTemplateUsed(filtered, "organizer/labels/preview.html")
        self.assertContains(filtered, "data-label-selection-state")
        self.assertContains(filtered, "data-label-preview")
        self.assertEqual(list(filtered.context["sets"]), [second])
        self.assertEqual(filtered.context["hidden_selected_ids"], [str(self.lego_set.pk)])
        self.assertContains(filtered, "data-label-preserved-item")

        combined = self.client.post(
            url,
            {
                "selection": 1,
                "type": "full",
                "q": "",
                "item": [self.lego_set.pk, second.pk],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(
            set(combined.context["selected_ids"]),
            {str(self.lego_set.pk), str(second.pk)},
        )
        self.assertEqual(set(combined.context["sets"]), {self.lego_set, second})
        self.assertContains(combined, 'class="print-label label-full"', count=2)

    def test_label_studio_uses_number_neutral_subtitle_and_partial_contract(self):
        response = self.client.get(reverse("organizer:label_studio"))
        self.assertContains(response, "Eigenständige, maßgenaue Vorlagen")
        self.assertNotContains(response, "Vier eigenständige")
        source = (Path(settings.BASE_DIR) / "static" / "js" / "labels.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('querySelector("[data-label-selection-state]")', source)
        self.assertIn('querySelector("[data-label-preview]")', source)
        history_builder = source.split("function buildHistoryUrl", 1)[1].split(
            "async function refresh", 1
        )[0]
        self.assertNotIn('"item"', history_builder)

    def test_large_post_selection_images_type_switch_invalid_ids_and_owner_scope(self):
        additional_sets = [
            LegoSet(
                owner=self.user,
                set_number=f"LARGE-{number:03d}",
                name=f"Large collection {number}",
                image_url=f"https://example.test/large-{number}.png",
            )
            for number in range(110)
        ]
        LegoSet.objects.bulk_create(additional_sets)
        selected_sets = [self.lego_set, *additional_sets]
        selected_ids = [str(lego_set.pk) for lego_set in selected_sets]
        legacy_query = urlencode(
            [("selection", "1"), ("type", "full")]
            + [("item", value) for value in selected_ids]
        )
        self.assertGreater(len(legacy_query), 4094)

        url = reverse("organizer:label_studio")
        submitted_ids = [*selected_ids, str(self.foreign_pk), "not-a-uuid", "999"]
        common = {"selection": 1, "type": "full", "item": submitted_ids}
        without_images = self.client.post(
            url,
            {**common, "images": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(without_images.status_code, 200)
        self.assertEqual(
            sum(slot is not None for slot in without_images.context["slots"]),
            len(selected_sets),
        )
        self.assertEqual(len(without_images.context["selected_ids"]), len(selected_sets))
        self.assertNotContains(without_images, 'class="label-set-image"')
        self.assertNotContains(without_images, "Geheimes Set")

        with_images = self.client.post(
            url,
            {**common, "images": ["0", "1"]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(with_images.status_code, 200)
        self.assertContains(
            with_images,
            'class="label-set-image"',
            count=len(selected_sets),
        )

        switched = self.client.post(
            url,
            {**common, "type": "collected", "images": "1", "q": "Transport"},
        )
        self.assertEqual(switched.status_code, 200)
        self.assertTemplateUsed(switched, "organizer/label_studio.html")
        self.assertContains(switched, "data-label-studio")
        self.assertEqual(switched.context["label_type"], "collected")
        self.assertEqual(len(switched.context["selected_ids"]), len(selected_sets))
        self.assertContains(
            switched,
            "data-label-preserved-item",
            count=len(selected_sets) - 1,
        )

    def test_javascript_posts_formdata_and_never_puts_selection_in_history(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "labels.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('method: "POST"', source)
        self.assertIn("body: formData", source)
        self.assertNotIn("URLSearchParams(new FormData(form))", source)
        history_builder = source.split("function buildHistoryUrl", 1)[1].split(
            "async function refresh", 1
        )[0]
        self.assertNotIn('"item"', history_builder)
        for invariant in ("AbortController", "sequence", "180", "aria-busy"):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, source)

    def test_empty_and_multiple_set_preview_are_valid(self):
        second = LegoSet.objects.create(
            owner=self.user, set_number="7957-1", name="Sith Nightspeeder"
        )
        url = reverse("organizer:label_studio")
        empty = self.client.get(
            url,
            {"selection": 1, "type": "full"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(sum(slot is not None for slot in empty.context["slots"]), 0)
        self.assertEqual(empty.context["label_pages"], [])
        self.assertContains(empty, "Keine Sets ausgewählt.")
        self.assertNotContains(empty, 'class="label-sheet label-sheet-herma"')
        multiple = self.client.get(
            url,
            {
                "selection": 1,
                "type": "full",
                "item": [self.lego_set.pk, second.pk],
                "start": 3,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(multiple.status_code, 200)
        self.assertEqual(multiple.context["slots"][:2], [None, None])
        self.assertEqual(sum(slot is not None for slot in multiple.context["slots"]), 2)

    def test_herma_labels_are_grouped_into_explicit_physical_sheets(self):
        sets = [self.lego_set]
        for number in range(8):
            sets.append(
                LegoSet.objects.create(
                    owner=self.user, set_number=f"PAGE-{number}", name=f"Page {number}"
                )
            )
        response = self.client.get(
            reverse("organizer:label_studio"),
            {"selection": 1, "type": "full", "item": [item.pk for item in sets]},
        )
        self.assertEqual(len(response.context["label_pages"]), 2)
        self.assertEqual([len(page) for page in response.context["label_pages"]], [8, 8])
        self.assertEqual(sum(slot is not None for slot in response.context["slots"]), 9)
        self.assertContains(response, 'class="label-sheet label-sheet-herma"', count=2)

    def test_herma_pagination_capacity_is_exact(self):
        for count, expected_pages in ((8, 1), (9, 2), (16, 2), (17, 3)):
            sets = [self.lego_set]
            for number in range(count - 1):
                sets.append(
                    LegoSet.objects.create(
                        owner=self.user,
                        set_number=f"CAP-{count}-{number}",
                        name=f"Capacity {count}-{number}",
                    )
                )
            response = self.client.get(
                reverse("organizer:label_studio"),
                {"selection": 1, "type": "full", "item": [item.pk for item in sets]},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context["label_pages"]), expected_pages)
            self.assertTrue(all(len(page) == 8 for page in response.context["label_pages"]))

    def test_collected_numbers_use_one_herma_sheet_and_complete_cut_grid(self):
        sets = [self.lego_set]
        for number in range(7):
            sets.append(
                LegoSet.objects.create(
                    owner=self.user, set_number=f"COLLECTED-{number}", name="Collected"
                )
            )
        response = self.client.get(
            reverse("organizer:label_studio"),
            {"selection": 1, "type": "collected", "item": [item.pk for item in sets]},
        )
        self.assertEqual(len(response.context["label_pages"]), 1)
        self.assertEqual(sum(slot is not None for slot in response.context["slots"]), 1)
        cells = response.context["slots"][0]["number_cells"]
        self.assertEqual(len(cells), 8)
        self.assertEqual(sum(cell["has_right_cut"] for cell in cells), 6)
        self.assertEqual(sum(cell["has_bottom_cut"] for cell in cells), 4)

    def test_eight_collected_label_slots_fit_one_herma_sheet(self):
        sets = [self.lego_set]
        for number in range(159):
            sets.append(
                LegoSet.objects.create(
                    owner=self.user, set_number=f"COLLECTED-SHEET-{number}", name="Collected"
                )
            )
        response = self.client.get(
            reverse("organizer:label_studio"),
            {"selection": 1, "type": "collected", "item": [item.pk for item in sets]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["label_pages"]), 1)
        self.assertEqual(sum(slot is not None for slot in response.context["slots"]), 8)

    def test_collected_cut_grid_handles_partial_rows_without_outer_lines(self):
        expected = {1: (0, 0), 2: (1, 0), 4: (3, 0), 5: (3, 1), 8: (6, 4), 20: (15, 16)}
        for count, (right_cuts, bottom_cuts) in expected.items():
            sets = [self.lego_set]
            for number in range(count - 1):
                sets.append(
                    LegoSet.objects.create(
                        owner=self.user,
                        set_number=f"CUT-{count}-{number}",
                        name="Cut grid",
                    )
                )
            response = self.client.get(
                reverse("organizer:label_studio"),
                {"selection": 1, "type": "collected", "item": [item.pk for item in sets]},
            )
            cells = response.context["slots"][0]["number_cells"]
            self.assertEqual(sum(cell["has_right_cut"] for cell in cells), right_cuts)
            self.assertEqual(sum(cell["has_bottom_cut"] for cell in cells), bottom_cuts)

    def test_print_css_neutralizes_screen_scroll_and_sheet_fragmentation(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "labels.css").read_text(
            encoding="utf-8"
        )
        print_css = css.split("@media print", 1)[1]
        for fragment in (
            "overflow:visible",
            "max-height:none",
            "height:auto",
            "scrollbar-gutter:auto",
            "gap:0",
            "break-inside:avoid",
            "page-break-inside:avoid",
            "break-after:auto",
            "page-break-after:auto",
        ):
            self.assertIn(fragment, print_css)
        self.assertIn("width:198.2mm;height:270.8mm", css)
        self.assertIn("width:177.8mm;height:270mm", css)
        self.assertIn("@page herma{size:A4 portrait;margin:13.1mm 5.9mm}", css)

    def test_start_position_is_preserved_across_multiple_sheets(self):
        second = LegoSet.objects.create(
            owner=self.user, set_number="PAGE-SECOND", name="Second"
        )
        response = self.client.get(
            reverse("organizer:label_studio"),
            {
                "selection": 1,
                "type": "full",
                "item": [self.lego_set.pk, second.pk],
                "start": 8,
            },
        )
        pages = response.context["label_pages"]
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0][:7], [None] * 7)
        self.assertIsNotNone(pages[0][7])
        self.assertIsNotNone(pages[1][0])

    def test_more_than_189_small_labels_create_multiple_sheets(self):
        self.lego_set.minifigures_inventory.update(quantity=190)
        response = self.client.get(
            reverse("organizer:label_studio"),
            {
                "selection": 1,
                "type": "per_minifigure",
                "item": self.lego_set.pk,
            },
        )
        self.assertEqual(len(response.context["label_pages"]), 2)
        self.assertEqual([len(page) for page in response.context["label_pages"]], [189, 189])
        self.assertEqual(sum(slot is not None for slot in response.context["slots"]), 190)
        self.assertContains(response, 'class="label-sheet label-sheet-small"', count=2)

    @override_settings(PUBLIC_URL="https://brickmissing.example")
    def test_configured_public_origin_is_used_without_localhost(self):
        response = self.client.get(reverse("organizer:label_studio"))
        self.assertContains(response, "https://brickmissing.example")
        self.assertNotContains(response, "127.0.0.1")

    @override_settings(PUBLIC_URL="https://brickmissing.example")
    def test_all_six_set_qr_targets_keep_their_resolved_destinations(self):
        set_detail = reverse("catalog:set_detail", args=[self.lego_set.pk])
        expected = {
            "set": f"https://brickmissing.example{set_detail}",
            "inventory": f"https://brickmissing.example{set_detail}#set-inventory",
            "missing": (
                f"https://brickmissing.example{reverse('catalog:missing_parts')}"
                f"?set={self.lego_set.pk}"
            ),
            "edit": (
                "https://brickmissing.example"
                f"{reverse('catalog:set_edit', args=[self.lego_set.pk])}"
            ),
            "bricklink": (
                "https://www.bricklink.com/v2/catalog/catalogitem.page?S=7345-1"
            ),
            "rebrickable": "https://rebrickable.com/sets/7345-1/",
        }
        url = reverse("organizer:label_set_qr", args=[self.lego_set.pk])
        for target, destination in expected.items():
            with self.subTest(target=target):
                with patch("apps.organizer.views.qr_svg", return_value=b"<svg/>") as mocked_qr:
                    response = self.client.get(url, {"target": target})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(mocked_qr.call_args.args[0], destination)
                self.assertEqual(mocked_qr.call_args.kwargs["border"], 4)
