import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts.totp import encrypt_secret
from apps.catalog.models import LegoSet
from apps.integrations.rebrickable_sync import create_standalone_minifigure, synchronize_set
from apps.integrations.services import RebrickableError, normalize_rebrickable_set_number
from apps.organizer.models import SetMinifigure

FIGURE = {"set_num": "fig-123", "name": "Bride", "set_img_url": "https://example.test/bride.png"}
COMPONENTS = [
    {"part": {"part_num": "head", "name": "Head"}, "color": {"id": 1, "name": "White"},
     "quantity": 1, "element_id": "1001", "is_spare": False},
    {"part": {"part_num": "veil", "name": "Veil"}, "color": {"id": 2, "name": "White"},
     "quantity": 2, "element_id": "1002", "is_spare": False},
]


class StandaloneMinifigureTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("loose", "loose@example.test", "Password123456!", email_verified=True)
        self.other = users.objects.create_user("otherloose", "otherloose@example.test", "Password123456!", email_verified=True)
        self.client.force_login(self.owner)

    def test_import_multiple_and_set_instance_are_independent(self):
        lego_set = LegoSet.objects.create(owner=self.owner, set_number="100-1", name="Test")
        set_figure = SetMinifigure.objects.create(owner=self.owner, lego_set=lego_set, figure_number="fig-123", name="Bride")
        first = create_standalone_minifigure(self.owner, FIGURE, COMPONENTS)
        second = create_standalone_minifigure(self.owner, FIGURE, COMPONENTS)
        self.assertEqual(LegoSet.objects.count(), 1)
        self.assertEqual(SetMinifigure.objects.filter(owner=self.owner).count(), 3)
        self.assertEqual((first.lego_set_id, second.lego_set_id), (None, None))
        self.assertEqual(first.owned_quantity, 1)
        self.assertEqual(list(first.parts.values_list("quantity", "owned_quantity")), [(1, 1), (2, 2)])
        self.client.post(reverse("organizer:delete", args=["minifigures", first.pk]))
        self.assertFalse(SetMinifigure.objects.filter(pk=first.pk).exists())
        self.assertTrue(SetMinifigure.objects.filter(pk__in=[second.pk, set_figure.pk]).count() == 2)
        self.assertEqual(LegoSet.objects.count(), 1)

    def test_part_quantity_endpoint_updates_only_standalone_allocation(self):
        figure = create_standalone_minifigure(self.owner, FIGURE, COMPONENTS)
        other_figure = create_standalone_minifigure(self.other, FIGURE, COMPONENTS)
        part = figure.parts.get(part_number="veil")
        response = self.client.post(
            reverse("organizer:minifigure_part_quantity", args=[figure.pk, part.pk]),
            {"owned_quantity": "1"},
        )
        self.assertEqual(response.status_code, 302)
        part.refresh_from_db()
        self.assertEqual(part.owned_quantity, 1)
        self.assertEqual(other_figure.parts.get(part_number="veil").owned_quantity, 2)
        self.assertContains(self.client.get(reverse("catalog:missing_parts")), "Veil")

    def test_failed_import_rolls_back(self):
        with self.assertRaises(RebrickableError):
            create_standalone_minifigure(self.owner, FIGURE, [{"part": {}, "color": {}, "quantity": 1}])
        self.assertFalse(SetMinifigure.objects.exists())

    def test_search_preview_import_and_missing_csv_owner_isolation(self):
        self.owner.rebrickable_api_key_encrypted = encrypt_secret("test-key")
        self.owner.save(update_fields=["rebrickable_api_key_encrypted"])
        add = reverse("organizer:minifigure_add")
        with patch("apps.organizer.views.rebrickable_minifigure_search", return_value=[FIGURE]), patch(
            "apps.organizer.views.rebrickable_minifigure", return_value=(FIGURE, COMPONENTS)
        ):
            self.assertContains(self.client.get(add, {"q": "Bride"}), "Bride")
            self.assertContains(self.client.get(add, {"figure": "fig-123"}), "Bride")
            response = self.client.post(add, {"figure_number": "fig-123"})
        self.assertRedirects(response, reverse("organizer:minifigure_list"))
        figure = SetMinifigure.objects.get(owner=self.owner)
        self.assertContains(self.client.get(reverse("organizer:minifigure_list")), "Ohne Set")
        veil = figure.parts.get(part_number="veil")
        veil.owned_quantity = 0
        veil.save(update_fields=["owned_quantity"])
        self.assertContains(self.client.get(reverse("catalog:missing_parts")), "Veil")
        csv = self.client.get(reverse("data_portability:export_csv")).content.decode("utf-8-sig")
        self.assertIn("1002,2", csv)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse("organizer:minifigure_list")), "Bride")
        self.assertNotContains(self.client.get(reverse("catalog:missing_parts")), "Veil")
        self.assertNotIn("1002", self.client.get(reverse("data_portability:export_csv")).content.decode("utf-8-sig"))
        self.assertEqual(self.client.post(reverse("organizer:delete", args=["minifigures", figure.pk])).status_code, 404)

    def test_json_roundtrip_preserves_two_loose_instances_and_parts(self):
        first = create_standalone_minifigure(self.owner, FIGURE, COMPONENTS)
        second = create_standalone_minifigure(self.owner, FIGURE, COMPONENTS)
        first.parts.filter(part_number="veil").update(owned_quantity=0)
        exported = self.client.get(reverse("data_portability:export_json")).content
        payload = json.loads(exported)
        self.assertEqual(len(payload["minifigures"]), 2)
        SetMinifigure.objects.all().delete()
        upload = SimpleUploadedFile("export.json", exported, content_type="application/json")
        preview = self.client.post(reverse("data_portability:import_json"), {"file": upload})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context["report"]["minifigures"], 2)
        confirm = self.client.post(reverse("data_portability:import_confirm", args=[preview.context["batch"].pk]), {"strategy": "error"})
        self.assertEqual(confirm.status_code, 200)
        figures = list(SetMinifigure.objects.order_by("legacy_id"))
        self.assertEqual(len(figures), 2)
        self.assertTrue(all(figure.lego_set_id is None for figure in figures))
        self.assertEqual([list(f.parts.values_list("part_number", "quantity", "owned_quantity")) for f in figures], [
            [("head", 1, 1), ("veil", 2, 0)], [("head", 1, 1), ("veil", 2, 2)],
        ])
        self.assertEqual({f.legacy_id for f in figures}, {first.pk, second.pk})

    def test_variant_sync_imports_only_selected_sets(self):
        numbers = [f"71049-{index}" for index in (1, 2, 3)]
        fetched = []

        def set_fetcher(number, _key):
            fetched.append(number)
            return {"name": number, "num_parts": 1}, [
                {"part": {"part_num": "car", "name": "Car"},
                 "color": {"id": 1, "name": "Red"}, "quantity": 1},
            ]

        for number in numbers:
            lego_set = LegoSet.objects.create(owner=self.owner, set_number=number, name=number)
            synchronize_set(
                lego_set, "test-key", set_fetcher=set_fetcher,
                minifigure_fetcher=lambda _number, _key: [],
            )
        self.assertEqual(fetched, numbers)
        self.assertEqual(LegoSet.objects.count(), 3)
        self.assertFalse(LegoSet.objects.filter(set_number="71049-13").exists())

    def test_variant_identifiers_remain_distinct(self):
        numbers = [normalize_rebrickable_set_number(f"71049-{i}") for i in (1, 2, 3)]
        for number in numbers:
            LegoSet.objects.create(owner=self.owner, set_number=number, name=number)
        self.assertEqual(set(LegoSet.objects.values_list("set_number", flat=True)), set(numbers))
        self.assertFalse(LegoSet.objects.filter(set_number="71049-13").exists())
