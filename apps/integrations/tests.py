import io
import json
import threading
import urllib.error
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.totp import decrypt_secret, encrypt_secret
from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.organizer.models import MinifigurePart, SetMinifigure

from .services import (
    RebrickableError,
    _external_json,
    _rebrickable_json,
    _RebrickableRateLimiter,
    brickeconomy_set,
    bricklink_price,
    brickset_set,
    lego_pick_a_brick_url,
    normalize_rebrickable_set_number,
    rebrickable_minifigures,
    rebrickable_set,
    rebrickable_set_metadata,
    validated_image_url,
)


class IntegrationSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", "owner@example.test", "A-long-safe-password-123", email_verified=True)
        self.user.rebrickable_api_key_encrypted = encrypt_secret("owner-test-key")  # noqa: S106
        self.user.save(update_fields=["rebrickable_api_key_encrypted"])
        self.other = User.objects.create_user("other", "other@example.test", "A-long-safe-password-123", email_verified=True)
        self.foreign_set = LegoSet.objects.create(owner=self.other, set_number="123-1", name="Foreign")
        self.client.force_login(self.user)

    def test_rebrickable_sync_enforces_ownership_before_network(self):
        with patch("apps.integrations.views.rebrickable_set") as remote:
            response = self.client.post(reverse("integrations:sync_rebrickable", args=[self.foreign_set.pk]))
        self.assertEqual(response.status_code, 404)
        remote.assert_not_called()

    def test_image_proxy_rejects_local_and_unapproved_hosts(self):
        self.assertEqual(self.client.get(reverse("integrations:image_proxy"), {"url": "http://127.0.0.1/secret"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("integrations:image_proxy"), {"url": "https://example.invalid/x.png"}).status_code, 400)

    def test_templates_route_external_images_through_proxy(self):
        external = "https://cdn.rebrickable.com/media/sets/100.jpg"
        LegoSet.objects.create(owner=self.user, set_number="100", name="Proxy", image_url=external)
        response = self.client.get(reverse("catalog:set_list"))
        self.assertContains(response, reverse("integrations:image_proxy"))
        self.assertNotContains(response, f'src="{external}"')

    @patch("apps.integrations.services.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))])
    def test_allowed_hostname_resolving_private_is_rejected(self, _lookup):
        with self.assertRaises(ValueError):
            validated_image_url("https://cdn.rebrickable.com/image.png")

    def test_ssrf_address_scheme_and_redirect_matrix(self):
        private_addresses = (
            "127.0.0.1", "::1", "10.0.0.1", "172.16.0.1", "192.168.1.1",
            "169.254.169.254", "100.100.100.200",
        )
        for address in private_addresses:
            family = 10 if ":" in address else 2
            with patch(
                "apps.integrations.services.socket.getaddrinfo",
                return_value=[(family, 1, 6, "", (address, 443))],
            ), self.assertRaises(ValueError):
                validated_image_url("https://cdn.rebrickable.com/image.png")
        for url in (
            "http://cdn.rebrickable.com/a.png", "file:///etc/passwd",
            "ftp://cdn.rebrickable.com/a.png", "https://user:pass@cdn.rebrickable.com/a.png",
            "not-a-url", "https://127.0.0.1/a.png",
        ):
            with self.assertRaises(ValueError):
                validated_image_url(url)
        redirect = urllib.error.HTTPError(
            "https://cdn.rebrickable.com/a.png", 302, "redirect", {"Location": "http://127.0.0.1/"}, io.BytesIO()
        )
        with patch("apps.integrations.services.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]), patch(
            "apps.integrations.services.urllib.request.build_opener"
        ) as opener:
            opener.return_value.open.side_effect = redirect
            response = self.client.get(
                reverse("integrations:image_proxy"),
                {"url": "https://cdn.rebrickable.com/a.png"},
            )
            self.assertEqual(response.status_code, 400)

    @patch(
        "apps.integrations.services.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_image_proxy_rejects_wrong_mime_and_timeout(self, opener, _lookup):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers.get_content_type.return_value = "text/html"
        opener.return_value.open.return_value = response
        self.assertEqual(
            self.client.get(
                reverse("integrations:image_proxy"),
                {"url": "https://cdn.rebrickable.com/a.png"},
            ).status_code,
            400,
        )
        opener.return_value.open.side_effect = urllib.error.URLError("timeout")
        self.assertEqual(
            self.client.get(
                reverse("integrations:image_proxy"),
                {"url": "https://cdn.rebrickable.com/a.png"},
            ).status_code,
            400,
        )

    @patch("apps.integrations.views.rebrickable_minifigures")
    @patch("apps.integrations.views.rebrickable_set")
    def test_sync_imports_minifigures_parts_and_handles_duplicates(self, set_api, fig_api):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="100-1", name="Set")
        set_api.return_value = ({"name": "Set", "num_parts": 1}, [])
        figure = {"set_num": "fig-1", "name": "Figure", "quantity": 1}
        component = {
            "part": {"part_num": "973", "name": "Torso"},
            "color": {"id": 1, "name": "White"}, "quantity": 1,
        }
        fig_api.return_value = [(figure, [component, component])]
        response = self.client.post(
            reverse("integrations:sync_rebrickable", args=[lego_set.pk])
        )
        self.assertRedirects(response, reverse("catalog:set_detail", args=[lego_set.pk]))
        self.assertEqual(SetMinifigure.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(MinifigurePart.objects.count(), 1)

    @patch("apps.integrations.views.rebrickable_minifigures")
    @patch("apps.integrations.views.rebrickable_set")
    def test_repeated_sync_is_idempotent_and_preserves_user_stock(self, set_api, fig_api):
        lego_set = LegoSet.objects.create(
            owner=self.user,
            set_number="200-1",
            name="Alt",
            build_status="in Bau",
            notes="Persönliche Set-Notiz",
        )
        set_api.return_value = (
            {"name": "Neu", "num_parts": 2},
            [{
                "part": {"part_num": "3001", "name": "Brick"},
                "color": {"id": 1, "name": "White"}, "quantity": 2,
            }],
        )
        figure = {"set_num": "fig-2", "name": "Pilot", "quantity": 1}
        component = {
            "part": {"part_num": "973", "name": "Torso"},
            "color": {"id": 5, "name": "Red"}, "quantity": 1,
        }
        fig_api.return_value = [(figure, [component])]
        url = reverse("integrations:sync_rebrickable", args=[lego_set.pk])
        self.client.post(url)
        inventory = SetInventoryItem.objects.get(lego_set=lego_set)
        inventory.owned_quantity = 1
        inventory.save(update_fields=["owned_quantity"])
        mini_part = MinifigurePart.objects.get()
        mini_part.owned_quantity = 1
        mini_part.save(update_fields=["owned_quantity"])
        minifigure = SetMinifigure.objects.get()
        minifigure.owned_quantity = 1
        minifigure.notes = "Persönliche Figuren-Notiz"
        minifigure.save(update_fields=["owned_quantity", "notes"])
        for _ in range(2):
            self.client.post(url)
        self.assertEqual(SetInventoryItem.objects.filter(lego_set=lego_set).count(), 1)
        self.assertEqual(SetMinifigure.objects.filter(lego_set=lego_set).count(), 1)
        self.assertEqual(MinifigurePart.objects.filter(minifigure__lego_set=lego_set).count(), 1)
        inventory.refresh_from_db()
        mini_part.refresh_from_db()
        minifigure.refresh_from_db()
        lego_set.refresh_from_db()
        self.assertEqual((inventory.owned_quantity, mini_part.owned_quantity), (1, 1))
        self.assertEqual((minifigure.owned_quantity, minifigure.notes), (1, "Persönliche Figuren-Notiz"))
        self.assertEqual((lego_set.build_status, lego_set.notes), ("in Bau", "Persönliche Set-Notiz"))

    @patch("apps.integrations.views.rebrickable_minifigures", return_value=[])
    @patch("apps.integrations.views.rebrickable_set")
    def test_bulk_sync_endpoints_are_processed_sequentially(self, set_api, _fig_api):
        first = LegoSet.objects.create(owner=self.user, set_number="301-1", name="First")
        second = LegoSet.objects.create(owner=self.user, set_number="302-1", name="Second")
        order = []

        def set_payload(set_number, _api_key):
            order.append(set_number)
            return {"name": set_number, "num_parts": 0}, []

        set_api.side_effect = set_payload
        for lego_set in (first, second):
            response = self.client.post(
                reverse("integrations:sync_rebrickable", args=[lego_set.pk]),
                {"bulk": "1"},
                HTTP_ACCEPT="application/json",
            )
            self.assertEqual((response.status_code, response.json()["ok"]), (200, True))
        self.assertEqual(order, ["301-1", "302-1"])

    @patch(
        "apps.integrations.views.rebrickable_minifigures",
        side_effect=RebrickableError("rate limited", "rate_limit", status_code=429),
    )
    @patch("apps.integrations.views.rebrickable_set")
    def test_exhausted_minifigure_rate_limit_fails_bulk_item(self, set_api, _fig_api):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="303-1", name="Set")
        set_api.return_value = ({"name": "Set", "num_parts": 0}, [])
        response = self.client.post(
            reverse("integrations:sync_rebrickable", args=[lego_set.pk]),
            {"bulk": "1"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_sets_page_bulk_manifest_is_owned_active_valid_and_deterministic(self):
        from django.utils import timezone

        first = LegoSet.objects.create(owner=self.user, set_number="100-1", name="First")
        second = LegoSet.objects.create(owner=self.user, set_number="200", name="Second")
        LegoSet.objects.create(owner=self.user, set_number="invalid set", name="Invalid")
        LegoSet.objects.create(
            owner=self.user, set_number="300", name="Deleted", deleted_at=timezone.now()
        )
        response = self.client.get(reverse("catalog:set_list"))
        self.assertEqual(response.context["sync_sets"], [first, second])
        self.assertContains(response, "Alle Sets synchronisieren")
        self.assertContains(response, reverse("integrations:sync_rebrickable", args=[first.pk]))
        self.assertNotContains(response, str(self.foreign_set.pk))

    @patch("apps.integrations.views.rebrickable_instructions")
    def test_instruction_links_are_owned_and_rendered(self, remote):
        lego_set = LegoSet.objects.create(owner=self.user, set_number="100-1", name="Set")
        remote.return_value = [
            {"name": "Manual", "url": "https://example.test/manual", "source": "LEGO"}
        ]
        response = self.client.get(reverse("integrations:instructions", args=[lego_set.pk]))
        self.assertContains(response, "Manual")
        self.assertEqual(
            self.client.get(
                reverse("integrations:instructions", args=[self.foreign_set.pk])
            ).status_code,
            404,
        )


class RebrickableRateLimitTests(TestCase):
    class FakeTime:
        def __init__(self):
            self.now = 0.0
            self.sleeps = []
            self.lock = threading.Lock()

        def monotonic(self):
            with self.lock:
                return self.now

        def sleep(self, delay):
            with self.lock:
                self.sleeps.append(delay)
                self.now += delay

    @staticmethod
    def response(payload):
        response = MagicMock()
        response.__enter__.return_value = response
        data = json.dumps(payload).encode()
        response.headers = {"Content-Length": str(len(data))}
        response.read.return_value = data
        return response

    @staticmethod
    def http_error(status, retry_after=None):
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        return urllib.error.HTTPError(
            "https://rebrickable.com/api/v3/lego/sets/100-1/",
            status,
            "controlled test error",
            headers,
            io.BytesIO(),
        )

    def timed_limiter(self):
        fake_time = self.FakeTime()
        limiter = _RebrickableRateLimiter(
            1.05, clock=fake_time.monotonic, sleeper=fake_time.sleep
        )
        return fake_time, limiter

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_two_requests_respect_minimum_interval(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.side_effect = [self.response({"id": 1}), self.response({"id": 2})]
        with patch("apps.integrations.services._rebrickable_rate_limiter", limiter):
            self.assertEqual(_rebrickable_json("colors/?page_size=1", "key")["id"], 1)  # noqa: S106
            self.assertEqual(_rebrickable_json("colors/?page_size=1", "key")["id"], 2)  # noqa: S106
        self.assertEqual(fake_time.sleeps, [1.05])

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_429_retry_after_is_respected(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.side_effect = [
            self.http_error(429, "2"),
            self.response({"ok": True}),
        ]
        with (
            patch("apps.integrations.services._rebrickable_rate_limiter", limiter),
            patch("apps.integrations.services.time.sleep", fake_time.sleep),
        ):
            result = _rebrickable_json("sets/100-1/", "key")  # noqa: S106
        self.assertTrue(result["ok"])
        self.assertEqual(fake_time.sleeps, [2.0])
        self.assertEqual(opener.return_value.open.call_count, 2)

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_429_without_retry_after_uses_fallback(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.side_effect = [
            self.http_error(429),
            self.response({"ok": True}),
        ]
        with (
            patch("apps.integrations.services._rebrickable_rate_limiter", limiter),
            patch("apps.integrations.services.time.sleep", fake_time.sleep),
        ):
            _rebrickable_json("sets/100-1/", "key")  # noqa: S106
        self.assertEqual(fake_time.sleeps, [2])

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_429_retry_then_success_returns_normal_payload(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.side_effect = [
            self.http_error(429, "invalid"),
            self.response({"results": [1]}),
        ]
        with (
            patch("apps.integrations.services._rebrickable_rate_limiter", limiter),
            patch("apps.integrations.services.time.sleep", fake_time.sleep),
        ):
            result = _rebrickable_json("sets/100-1/parts/?page_size=1000", "key")  # noqa: S106
        self.assertEqual(result, {"results": [1]})

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_permanent_429_stops_after_five_retries(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.side_effect = [self.http_error(429) for _ in range(6)]
        with (
            patch("apps.integrations.services._rebrickable_rate_limiter", limiter),
            patch("apps.integrations.services.time.sleep", fake_time.sleep),
            self.assertRaises(RebrickableError) as raised,
        ):
            _rebrickable_json("sets/100-1/", "key")  # noqa: S106
        self.assertEqual(fake_time.sleeps, [2, 5, 10, 20, 40])
        self.assertEqual(opener.return_value.open.call_count, 6)
        self.assertEqual(raised.exception.code, "rate_limit")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertTrue(raised.exception.rate_limit)

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_401_and_403_remain_authentication_errors(self, opener):
        for status in (401, 403):
            with self.subTest(status=status):
                fake_time, limiter = self.timed_limiter()
                opener.return_value.open.side_effect = self.http_error(status)
                with (
                    patch("apps.integrations.services._rebrickable_rate_limiter", limiter),
                    self.assertRaises(RebrickableError) as raised,
                ):
                    _rebrickable_json("sets/100-1/", "key")  # noqa: S106
                self.assertEqual(raised.exception.code, "authentication")
                self.assertEqual(raised.exception.status_code, status)

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_404_remains_not_found(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.side_effect = self.http_error(404)
        with (
            patch("apps.integrations.services._rebrickable_rate_limiter", limiter),
            self.assertRaises(RebrickableError) as raised,
        ):
            _rebrickable_json("sets/missing/", "key")  # noqa: S106
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(raised.exception.status_code, 404)

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_network_error_is_unavailable(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.side_effect = urllib.error.URLError("timeout")
        with (
            patch("apps.integrations.services._rebrickable_rate_limiter", limiter),
            self.assertRaises(RebrickableError) as raised,
        ):
            _rebrickable_json("sets/100-1/", "key")  # noqa: S106
        self.assertEqual(raised.exception.code, "unavailable")
        self.assertIsNone(raised.exception.status_code)

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_successful_request_has_no_regression(self, opener):
        fake_time, limiter = self.timed_limiter()
        opener.return_value.open.return_value = self.response({"set_num": "100-1"})
        with patch("apps.integrations.services._rebrickable_rate_limiter", limiter):
            result = _rebrickable_json("sets/100-1/", "key")  # noqa: S106
        self.assertEqual(result["set_num"], "100-1")
        self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertEqual(fake_time.sleeps, [])

    def test_rate_limiter_serializes_threads(self):
        fake_time, limiter = self.timed_limiter()
        barrier = threading.Barrier(3)
        completed = []

        def worker():
            barrier.wait()
            limiter.wait()
            completed.append(True)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=1)
        self.assertEqual(completed, [True, True])
        self.assertEqual(fake_time.sleeps, [1.05])

    @patch("apps.integrations.services._rebrickable_json")
    def test_sync_request_flow_remains_three_plus_one_per_minifigure(self, remote):
        def payload(path, _api_key):
            if path.endswith("/minifigs/?page_size=1000"):
                return {"results": [{"set_num": "fig-1"}, {"set_num": "fig-2"}]}
            if "/parts/" in path:
                return {"results": []}
            return {"set_num": "100-1"}

        remote.side_effect = payload
        rebrickable_set("100-1", "key")  # noqa: S106
        rebrickable_minifigures("100-1", "key")  # noqa: S106
        self.assertEqual(remote.call_count, 5)
        self.assertEqual(
            [call.args[0] for call in remote.call_args_list],
            [
                "sets/100-1/",
                "sets/100-1/parts/?page_size=1000",
                "sets/100-1/minifigs/?page_size=1000",
                "minifigs/fig-1/parts/?page_size=1000",
                "minifigs/fig-2/parts/?page_size=1000",
            ],
        )


class PricingParityTests(TestCase):
    def _response(self, payload):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode()
        return response

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_brickset_success_and_empty_response(self, opener):
        opener.return_value.open.return_value = self._response(
            {"status": "success", "sets": [{"setNumber": "100-1"}]}
        )
        with self.settings(BRICKSET_API_KEY="test-key"):
            self.assertEqual(brickset_set("100")["setNumber"], "100-1")
        opener.return_value.open.return_value = self._response({"status": "success", "sets": []})
        with self.settings(BRICKSET_API_KEY="test-key"), self.assertRaises(ValueError):
            brickset_set("100")

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_bricklink_oauth_success_and_malformed_response(self, opener):
        opener.return_value.open.return_value = self._response({"data": {"avg_price": "1.23"}})
        configured = self.settings(  # noqa: S106 -- inert unit-test credentials
            BRICKLINK_CONSUMER_KEY="a",
            BRICKLINK_CONSUMER_SECRET="b",  # noqa: S106 -- inert test value
            BRICKLINK_TOKEN="c",  # noqa: S106 -- inert test value
            BRICKLINK_TOKEN_SECRET="d",  # noqa: S106 -- inert test value
        )
        with configured:
            self.assertEqual(bricklink_price("PART", "3001")["avg_price"], "1.23")
            opener.return_value.open.return_value = self._response([])
            with self.assertRaisesRegex(ValueError, "Ungültige"):
                bricklink_price("PART", "3001")

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_external_api_timeout_429_auth_and_500_are_controlled(self, opener):
        cases = [
            (urllib.error.URLError("timeout"), "nicht erreichbar"),
            (urllib.error.HTTPError("https://brickset.com", 429, "", {}, io.BytesIO()), "Rate Limit"),
            (urllib.error.HTTPError("https://brickset.com", 401, "", {}, io.BytesIO()), "Authentifizierung"),
            (urllib.error.HTTPError("https://brickset.com", 500, "", {}, io.BytesIO()), "HTTP 500"),
        ]
        for error, message in cases:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValueError, message):
                _external_json("https://brickset.com/api/v3.asmx/getSets")

    def test_pick_a_brick_is_safe_official_search_replacement(self):
        url = lego_pick_a_brick_url("3001")
        self.assertTrue(url.startswith("https://www.lego.com/de-at/pick-and-build/pick-a-brick?"))
        self.assertIn("query=3001", url)

    def test_rebrickable_set_number_normalization_is_deterministic(self):
        self.assertEqual(normalize_rebrickable_set_number("60069"), "60069-1")
        self.assertEqual(normalize_rebrickable_set_number("60069-2"), "60069-2")
        with self.assertRaisesRegex(ValueError, "ungültig"):
            normalize_rebrickable_set_number("../60069")

    @patch("apps.integrations.services._rebrickable_json")
    def test_rebrickable_metadata_maps_set_theme_subtheme_and_minifigures(self, remote):
        def response(path, api_key):
            self.assertEqual(api_key, "user-key")
            if path == "sets/60069-1/":
                return {"set_num": "60069-1", "name": "Swamp Police Station", "year": 2015, "theme_id": 2, "num_parts": 707, "set_img_url": "https://cdn.rebrickable.com/set.jpg"}
            if path == "themes/2/":
                return {"id": 2, "name": "Swamp Police", "parent_id": 1}
            if path == "themes/1/":
                return {"id": 1, "name": "City", "parent_id": None}
            if path == "sets/60069-1/minifigs/?page_size=1":
                return {"count": 6, "results": []}
            raise AssertionError(path)
        remote.side_effect = response
        result = rebrickable_set_metadata("60069", "user-key")
        self.assertEqual(result, {"set_number": "60069-1", "name": "Swamp Police Station", "year": 2015, "theme": "City", "subtheme": "Swamp Police", "total_parts": 707, "minifigures": 6, "image_url": "https://cdn.rebrickable.com/set.jpg"})

    @patch("apps.integrations.services.urllib.request.build_opener")
    def test_rebrickable_and_brickeconomy_complete_failure_matrix(self, opener):
        with self.assertRaisesRegex(ValueError, "nicht eingerichtet"):
            rebrickable_set("100", "")
        with self.settings(BRICKECONOMY_API_KEY=""), self.assertRaisesRegex(ValueError, "nicht konfiguriert"):
            brickeconomy_set("100")
        error_cases = [
            urllib.error.URLError("timeout"),
            urllib.error.HTTPError("https://rebrickable.com", 401, "", {}, io.BytesIO()),
            urllib.error.HTTPError("https://rebrickable.com", 403, "", {}, io.BytesIO()),
            urllib.error.HTTPError("https://rebrickable.com", 500, "", {}, io.BytesIO()),
        ]
        for error in error_cases:
            opener.return_value.open.side_effect = error
            with self.assertRaises(ValueError):
                rebrickable_set("100", "key")  # noqa: S106
        opener.return_value.open.side_effect = None
        opener.return_value.open.return_value = self._response([])
        with self.assertRaisesRegex(ValueError, "momentan nicht erreichbar"):
            rebrickable_set("100", "key")  # noqa: S106
        opener.return_value.open.return_value = self._response({"data": {}})
        with self.settings(BRICKECONOMY_API_KEY="key"), self.assertRaisesRegex(ValueError, "Keine Preisdaten"):
            brickeconomy_set("100")

    def test_pick_a_brick_is_available_in_normal_owned_ui(self):
        user = User.objects.create_user(
            "pick-owner", "pick@example.test", "A-long-safe-password-123",
            email_verified=True,
        )
        other = User.objects.create_user(
            "pick-other", "pick-other@example.test", "A-long-safe-password-123",
            email_verified=True,
        )
        part = Part.objects.create(
            owner=user, element_id="3001", part_number="3001", name="Brick", quantity=2
        )
        foreign = Part.objects.create(
            owner=other, element_id="3002", part_number="3002", name="Foreign", quantity=2
        )
        self.client.force_login(user)
        page = self.client.get(reverse("catalog:missing_parts"))
        self.assertContains(page, reverse("integrations:pick_a_brick", args=[part.pk]))
        response = self.client.get(reverse("integrations:pick_a_brick", args=[part.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://www.lego.com/"))
        self.assertEqual(
            self.client.get(reverse("integrations:pick_a_brick", args=[foreign.pk])).status_code,
            404,
        )

    @patch("apps.integrations.views.rebrickable_set_metadata")
    def test_user_scoped_lookup_returns_validated_metadata(self, lookup):
        user = User.objects.create_user("lookup", "lookup@example.test", "A-long-safe-password-123", email_verified=True)
        user.rebrickable_api_key_encrypted = encrypt_secret("lookup-secret")  # noqa: S106
        user.save(update_fields=["rebrickable_api_key_encrypted"])
        self.client.force_login(user)
        lookup.return_value = {"set_number": "60069-1", "name": "Swamp Police Station", "year": 2015, "theme": "City", "subtheme": "Swamp Police", "total_parts": 707, "minifigures": 6, "image_url": "https://cdn.rebrickable.com/set.jpg"}
        response = self.client.get(reverse("integrations:rebrickable_set_lookup"), {"set_number": "60069"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["set"]["theme"], "City")
        lookup.assert_called_once_with("60069", "lookup-secret")

    def test_lookup_without_key_is_safe_and_does_not_call_remote(self):
        user = User.objects.create_user("nokey", "nokey@example.test", "A-long-safe-password-123", email_verified=True)
        self.client.force_login(user)
        with patch("apps.integrations.views.rebrickable_set_metadata") as remote:
            response = self.client.get(reverse("integrations:rebrickable_set_lookup"), {"set_number": "60069"})
        self.assertEqual((response.status_code, response.json()["code"]), (400, "missing_key"))
        remote.assert_not_called()

    def test_api_key_is_encrypted_scoped_and_never_rendered(self):
        first = User.objects.create_user("first-key", "first-key@example.test", "A-long-safe-password-123", email_verified=True)
        second = User.objects.create_user("second-key", "second-key@example.test", "A-long-safe-password-123", email_verified=True)
        second.rebrickable_api_key_encrypted = encrypt_secret("second-plain-secret")  # noqa: S106
        second.save(update_fields=["rebrickable_api_key_encrypted"])
        self.client.force_login(first)
        response = self.client.post(reverse("accounts:rebrickable_save"), {"api_key": "first-plain-secret"})  # noqa: S106
        self.assertRedirects(response, reverse("accounts:profile"))
        first.refresh_from_db()
        self.assertNotIn("first-plain-secret", first.rebrickable_api_key_encrypted)
        self.assertEqual(decrypt_secret(first.rebrickable_api_key_encrypted), "first-plain-secret")
        profile = self.client.get(reverse("accounts:profile"))
        self.assertNotContains(profile, "first-plain-secret")
        self.assertNotContains(profile, "second-plain-secret")
        self.assertTrue(second.has_rebrickable_api_key)

    @patch("apps.integrations.services.test_rebrickable_connection")
    def test_connection_test_success_and_remove_do_not_expose_secret(self, connection):
        user = User.objects.create_user("connection", "connection@example.test", "A-long-safe-password-123", email_verified=True)
        user.rebrickable_api_key_encrypted = encrypt_secret("connection-secret")  # noqa: S106
        user.save(update_fields=["rebrickable_api_key_encrypted"])
        self.client.force_login(user)
        response = self.client.post(reverse("accounts:rebrickable_test"), follow=True)
        self.assertContains(response, "Rebrickable-Verbindung erfolgreich")
        connection.assert_called_once_with("connection-secret")
        self.assertNotContains(response, "connection-secret")
        self.client.post(reverse("accounts:rebrickable_remove"))
        user.refresh_from_db()
        self.assertFalse(user.has_rebrickable_api_key)

    def test_connection_test_handles_invalid_key_timeout_and_rate_limit(self):
        user = User.objects.create_user("connection-errors", "connection-errors@example.test", "A-long-safe-password-123", email_verified=True)
        user.rebrickable_api_key_encrypted = encrypt_secret("inert-secret")  # noqa: S106
        user.save(update_fields=["rebrickable_api_key_encrypted"])
        self.client.force_login(user)
        cases = (
            (RebrickableError("invalid", "authentication"), "API-Key ist ungültig"),
            (RebrickableError("timeout", "unavailable"), "momentan nicht erreichbar"),
            (RebrickableError("limited", "rate_limit"), "momentan nicht erreichbar"),
        )
        for error, expected in cases:
            with self.subTest(code=error.code), patch(
                "apps.integrations.services.test_rebrickable_connection", side_effect=error
            ):
                response = self.client.post(reverse("accounts:rebrickable_test"), follow=True)
                self.assertContains(response, expected)

    def test_price_sources_are_selectable_in_normal_set_ui(self):
        user = User.objects.create_user(
            "price-owner", "price@example.test", "A-long-safe-password-123",
            email_verified=True,
        )
        lego_set = LegoSet.objects.create(owner=user, set_number="200-1", name="Set")
        self.client.force_login(user)
        response = self.client.get(reverse("catalog:set_detail", args=[lego_set.pk]))
        for source in ("brickeconomy", "brickset", "bricklink"):
            self.assertContains(response, f'value="{source}"')
