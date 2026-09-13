import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import LegoSet, Part


class MissingPartStatusJsonTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(
            "status-json-owner", "status-json-owner@example.test", "Local-test-password-123"
        )
        self.other = users.objects.create_user(
            "status-json-other", "status-json-other@example.test", "Local-test-password-456"
        )
        lego_set = LegoSet.objects.create(
            owner=self.owner, set_number="status-json", name="Status JSON"
        )
        self.part = Part.objects.create(
            owner=self.owner, lego_set=lego_set, element_id="status-json-part",
            name="Status JSON part", quantity=2, owned_quantity=0,
            status=Part.Status.MISSING,
        )
        self.url = reverse("catalog:missing_part_status", args=[self.part.pk])
        self.client.force_login(self.owner)

    def post_ajax(self, url, status):
        return self.client.post(
            url, {"status": status}, HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_possession_with_shortage_returns_fachlich_correct_json_error(self):
        response = self.post_ajax(self.url, Part.Status.RECEIVED)
        self.part.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        self.assertEqual(response.json(), {
            "ok": False,
            "message": "Ein Besitzstatus ist erst ohne offene Fehlmenge zulässig.",
        })
        self.assertEqual(
            (self.part.status, self.part.quantity, self.part.owned_quantity,
             self.part.missing_quantity),
            (Part.Status.MISSING, 2, 0, 2),
        )

    def test_invalid_status_returns_json_without_changing_part(self):
        response = self.post_ajax(self.url, "not-a-status")
        self.part.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        self.assertEqual(response.json(), {"ok": False, "message": "Der Status ist ungültig."})
        self.assertEqual((self.part.status, self.part.owned_quantity), (Part.Status.MISSING, 0))

    def test_valid_status_change_preserves_quantity_and_returns_json_success(self):
        response = self.post_ajax(self.url, Part.Status.ORDERED)
        self.part.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(response.json()["part"]["status"], Part.Status.ORDERED)
        self.assertEqual(response.json()["part"]["status_label"], "Bestellt")
        self.assertEqual((self.part.status, self.part.quantity, self.part.owned_quantity),
                         (Part.Status.ORDERED, 2, 0))

    def test_foreign_and_missing_parts_return_scoped_json_404(self):
        foreign = Part.objects.create(
            owner=self.other, element_id="status-json-foreign", name="Foreign",
            quantity=2, owned_quantity=0, status=Part.Status.MISSING,
        )
        for identifier in (foreign.pk, uuid.uuid4()):
            with self.subTest(identifier=identifier):
                response = self.post_ajax(
                    reverse("catalog:missing_part_status", args=[identifier]),
                    Part.Status.FOUND,
                )
                self.assertEqual(response.status_code, 404)
                self.assertTrue(response["Content-Type"].startswith("application/json"))
                self.assertEqual(response.json(), {
                    "ok": False, "message": "Fehlteil nicht gefunden.",
                })
        foreign.refresh_from_db()
        self.assertEqual((foreign.status, foreign.owned_quantity), (Part.Status.MISSING, 0))

    def test_non_ajax_validation_response_keeps_existing_plaintext_contract(self):
        response = self.client.post(self.url, {"status": Part.Status.RECEIVED})

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response["Content-Type"].startswith("text/html"))
        self.assertIn("Ein Besitzstatus", response.content.decode())
