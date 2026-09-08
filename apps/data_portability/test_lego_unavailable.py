import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.data_portability.lego_unavailable import (
    MAX_UPLOAD_SIZE,
    analyze_lego_unavailable,
    parse_lego_unavailable_upload,
)
from apps.inventory.models import InventoryItem, WarehouseLocation


class LegoUnavailablePageTests(TestCase):
    password = "A-very-long-password-123"  # noqa: S105 - ephemeral test credential
    error_text = "Die Elementnummer ist derzeit bei Pick a Brick nicht verfügbar"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "lego-analysis",
            "lego-analysis@example.test",
            self.password,
            email_verified=True,
        )
        self.client.force_login(self.user)
        self.url = reverse("data_portability:lego_unavailable")
        self.lego_set = LegoSet.objects.create(
            owner=self.user,
            set_number="10307-1",
            name="Eiffelturm",
        )
        self.part = Part.objects.create(
            owner=self.user,
            lego_set=self.lego_set,
            element_id="30237a",
            design_id="30237",
            part_number="30237",
            name="Brick Special",
            color="Black",
            quantity=10,
            owned_quantity=2,
            status=Part.Status.MISSING,
            image_url="https://example.test/30237a.png",
        )

    def fixture_upload(self, name):
        path = Path(__file__).with_name("test_fixtures") / name
        content_type = "text/csv" if path.suffix == ".csv" else "application/json"
        return SimpleUploadedFile(name, path.read_bytes(), content_type=content_type)

    def csv_upload(self, body, name="unavailable.csv"):
        return SimpleUploadedFile(name, body.encode(), content_type="text/csv")

    def json_upload(self, payload, name="unavailable.json"):
        content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return SimpleUploadedFile(name, content, content_type="application/json")

    def post(self, upload):
        return self.client.post(self.url, {"file": upload})

    def test_authentication_is_required_for_page_and_analysis(self):
        self.client.logout()

        get_response = self.client.get(self.url)
        post_response = self.post(self.fixture_upload("lego_unavailable.csv"))

        self.assertEqual(get_response.status_code, 302)
        self.assertEqual(post_response.status_code, 302)

    def test_get_renders_dedicated_upload_page_and_import_area_link(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Nicht verfügbare LEGO-Teile")
        self.assertContains(response, 'accept=".csv,.json,text/csv,application/json"')
        self.assertContains(response, "Die Datei wird nicht gespeichert")
        self.assertContains(
            self.client.get(reverse("data_portability:import_page")),
            self.url,
        )

    def test_valid_csv_upload_matches_and_keeps_unmatched_row(self):
        response = self.post(self.fixture_upload("lego_unavailable.csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"], {
            "entries": 2,
            "matched": 1,
            "unmatched": 1,
            "quantity": 15,
        })
        self.assertContains(response, "Brick Special")
        self.assertContains(response, "10307-1")
        self.assertContains(response, "Aktuell fehlend")
        self.assertContains(response, ">8<")
        self.assertContains(response, "9999999")
        self.assertContains(response, "Nicht zugeordnet", count=4)

    def test_valid_json_upload(self):
        response = self.post(self.fixture_upload("lego_unavailable.json"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["quantity"], 15)
        self.assertTrue(response.context["results"][0]["matched"])
        self.assertFalse(response.context["results"][1]["matched"])

    def test_csv_and_json_fixtures_produce_same_logical_analysis(self):
        csv_response = self.post(self.fixture_upload("lego_unavailable.csv"))
        json_response = self.post(self.fixture_upload("lego_unavailable.json"))

        def logical(response):
            return [
                (
                    row["element_id"],
                    row["quantity"],
                    row["error"],
                    [str(part.pk) for part in row["matches"]],
                )
                for row in response.context["results"]
            ]

        self.assertEqual(logical(csv_response), logical(json_response))
        self.assertEqual(csv_response.context["summary"], json_response.context["summary"])

    def test_several_uploaded_ids_remain_in_source_order(self):
        payload = [
            {"elementId": "third", "quantity": 3, "error": "three"},
            {"elementId": "30237a", "quantity": 1, "error": "one"},
            {"elementId": "second", "quantity": 2, "error": "two"},
        ]

        response = self.post(self.json_upload(payload))

        self.assertEqual(
            [row["element_id"] for row in response.context["results"]],
            ["third", "30237a", "second"],
        )

    def test_one_element_id_displays_every_matching_part(self):
        second_set = LegoSet.objects.create(
            owner=self.user,
            set_number="10497-1",
            name="Galaxy Explorer",
        )
        Part.objects.create(
            owner=self.user,
            lego_set=second_set,
            element_id="30237a",
            name="Second matching row",
            color="White",
        )

        response = self.post(self.fixture_upload("lego_unavailable.json"))

        matches = response.context["results"][0]["matches"]
        self.assertEqual(len(matches), 2)
        self.assertContains(response, "2 BrickMissing-Zuordnungen")
        self.assertContains(response, "Brick Special")
        self.assertContains(response, "Second matching row")

    def test_uploaded_quantity_is_informational_and_part_state_is_unchanged(self):
        before = (
            self.part.quantity,
            self.part.owned_quantity,
            self.part.status,
            self.part.element_id,
            self.part.color,
        )

        response = self.post(self.fixture_upload("lego_unavailable.csv"))
        self.part.refresh_from_db()

        self.assertContains(response, "LEGO-Menge")
        self.assertContains(response, ">13<")
        self.assertEqual(
            (
                self.part.quantity,
                self.part.owned_quantity,
                self.part.status,
                self.part.element_id,
                self.part.color,
            ),
            before,
        )

    def test_set_and_inventory_state_are_not_modified(self):
        inventory_item = SetInventoryItem.objects.create(
            lego_set=self.lego_set,
            part_number="30237",
            element_id="30237a",
            name="Inventory reference",
            required_quantity=10,
            owned_quantity=2,
        )
        location = WarehouseLocation.objects.create(owner=self.user, name="Shelf")
        stock = InventoryItem.objects.create(
            owner=self.user,
            location=location,
            part_number="30237",
            element_id="30237a",
            name="Stock",
            quantity=7,
        )
        before_set = (self.lego_set.name, self.lego_set.completeness, self.lego_set.updated_at)
        before_inventory = (
            inventory_item.required_quantity,
            inventory_item.owned_quantity,
            inventory_item.updated_at,
            stock.quantity,
            stock.updated_at,
        )

        self.post(self.fixture_upload("lego_unavailable.csv"))
        self.lego_set.refresh_from_db()
        inventory_item.refresh_from_db()
        stock.refresh_from_db()

        self.assertEqual(
            (self.lego_set.name, self.lego_set.completeness, self.lego_set.updated_at),
            before_set,
        )
        self.assertEqual(
            (
                inventory_item.required_quantity,
                inventory_item.owned_quantity,
                inventory_item.updated_at,
                stock.quantity,
                stock.updated_at,
            ),
            before_inventory,
        )

    def test_another_users_exact_element_id_is_never_displayed(self):
        other = get_user_model().objects.create_user(
            "lego-analysis-other",
            "lego-analysis-other@example.test",
            self.password,
            email_verified=True,
        )
        Part.objects.create(
            owner=other,
            element_id="foreign-only",
            name="Private foreign part",
            quantity=4,
        )
        payload = [{"elementId": "foreign-only", "quantity": 4, "error": self.error_text}]

        response = self.post(self.json_upload(payload))

        self.assertEqual(response.context["summary"]["unmatched"], 1)
        self.assertNotContains(response, "Private foreign part")

    def test_matching_is_exact_and_does_not_use_design_id_or_case_folding(self):
        payload = [
            {"elementId": "30237", "quantity": 1, "error": self.error_text},
            {"elementId": "30237A", "quantity": 1, "error": self.error_text},
        ]

        response = self.post(self.json_upload(payload))

        self.assertEqual(response.context["summary"]["matched"], 0)

    def test_duplicate_element_ids_are_preserved_without_losing_quantities(self):
        payload = [
            {"elementId": "30237a", "quantity": 2, "error": self.error_text},
            {"elementId": "30237a", "quantity": 5, "error": "Second message"},
        ]

        response = self.post(self.json_upload(payload))

        self.assertEqual(len(response.context["results"]), 2)
        self.assertEqual(response.context["summary"]["quantity"], 7)
        self.assertEqual(
            [row["quantity"] for row in response.context["results"]],
            [2, 5],
        )
        self.assertContains(response, "Second message")

    def test_long_error_is_escaped_and_wrapped_as_plain_text(self):
        error = "<script>alert('x')</script> " + ("nicht verfügbar " * 100)
        payload = [{"elementId": "30237a", "quantity": 1, "error": error}]

        response = self.post(self.json_upload(payload))

        self.assertContains(response, "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert('x')</script>")

    def test_missing_element_id_is_rejected_for_csv_and_json(self):
        uploads = (
            self.csv_upload(f"elementId,quantity,error\n,1,{self.error_text}\n"),
            self.json_upload([{"elementId": "", "quantity": 1, "error": self.error_text}]),
        )
        for upload in uploads:
            with self.subTest(name=upload.name):
                response = self.post(upload)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "elementId fehlt", status_code=400)

    def test_invalid_quantity_is_rejected_for_csv_and_json(self):
        uploads = (
            self.csv_upload(f"elementId,quantity,error\n30237a,nope,{self.error_text}\n"),
            self.json_upload(
                [{"elementId": "30237a", "quantity": 1.5, "error": self.error_text}]
            ),
        )
        for upload in uploads:
            with self.subTest(name=upload.name):
                response = self.post(upload)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "quantity ist keine ganze Zahl", status_code=400)

    def test_malformed_and_missing_column_csv_are_rejected(self):
        uploads = (
            self.csv_upload('elementId,quantity,error\n"unterminated,1,error\n'),
            self.csv_upload("elementId,quantity\n30237a,1\n"),
        )
        for upload in uploads:
            with self.subTest(name=upload.name, body=upload.size):
                response = self.post(upload)
                self.assertEqual(response.status_code, 400)

    def test_malformed_non_list_and_nested_json_are_rejected(self):
        uploads = (
            self.json_upload(b"{"),
            self.json_upload({"elementId": "30237a", "quantity": 1, "error": "x"}),
            self.json_upload(
                [{"elementId": ["30237a"], "quantity": 1, "error": "x"}]
            ),
        )
        for upload in uploads:
            with self.subTest(name=upload.name, size=upload.size):
                response = self.post(upload)
                self.assertEqual(response.status_code, 400)

    def test_unsupported_empty_and_oversized_uploads_are_rejected(self):
        uploads = (
            SimpleUploadedFile("result.txt", b"plain", content_type="text/plain"),
            SimpleUploadedFile("empty.csv", b"", content_type="text/csv"),
            SimpleUploadedFile(
                "large.json",
                b"[" + (b" " * MAX_UPLOAD_SIZE) + b"]",
                content_type="application/json",
            ),
        )
        expected = ("Nur CSV", "Datei ist leer", "größer als 2 MiB")
        for upload, message in zip(uploads, expected, strict=True):
            with self.subTest(name=upload.name):
                response = self.post(upload)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, message, status_code=400)

    def test_business_database_state_is_identical_after_analysis(self):
        models_and_values = (
            (LegoSet, ("pk", "name", "completeness", "updated_at")),
            (
                Part,
                (
                    "pk",
                    "element_id",
                    "quantity",
                    "owned_quantity",
                    "status",
                    "color",
                    "updated_at",
                ),
            ),
            (SetInventoryItem, ("pk", "required_quantity", "owned_quantity", "updated_at")),
            (WarehouseLocation, ("pk", "name", "updated_at")),
            (InventoryItem, ("pk", "quantity", "reserved_quantity", "updated_at")),
        )
        before = {
            model._meta.label: list(model.objects.order_by("pk").values_list(*fields))
            for model, fields in models_and_values
        }

        response = self.post(self.fixture_upload("lego_unavailable.json"))

        self.assertEqual(response.status_code, 200)
        after = {
            model._meta.label: list(model.objects.order_by("pk").values_list(*fields))
            for model, fields in models_and_values
        }
        self.assertEqual(after, before)

    def test_part_query_count_is_constant_for_many_uploaded_rows(self):
        rows = [
            {"elementId": f"unknown-{index}", "quantity": 1, "error": self.error_text}
            for index in range(200)
        ]
        rows.append(
            {"elementId": self.part.element_id, "quantity": 1, "error": self.error_text}
        )
        parsed_rows = parse_lego_unavailable_upload(self.json_upload(rows))
        with self.assertNumQueries(1):
            analysis = analyze_lego_unavailable(parsed_rows, self.user)

        self.assertEqual(analysis["summary"]["entries"], 201)
