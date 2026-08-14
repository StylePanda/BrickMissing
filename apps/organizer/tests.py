from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import LegoSet
from apps.inventory.models import InventoryItem

from .models import (
    Collection,
    LabelTemplate,
    Loan,
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
