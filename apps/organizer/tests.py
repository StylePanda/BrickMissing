from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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
        partial = self.client.get(
            url, {**common, "type": "full"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertTemplateUsed(partial, "organizer/labels/preview.html")
        self.assertNotContains(partial, "<html")

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

    @override_settings(PUBLIC_URL="https://brickmissing.example")
    def test_configured_public_origin_is_used_without_localhost(self):
        response = self.client.get(reverse("organizer:label_studio"))
        self.assertContains(response, "https://brickmissing.example")
        self.assertNotContains(response, "127.0.0.1")
