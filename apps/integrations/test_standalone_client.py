from unittest.mock import patch

from django.test import SimpleTestCase

from apps.integrations.services import (
    RebrickableError,
    normalize_rebrickable_minifigure_number,
    rebrickable_minifigure,
    rebrickable_minifigure_search,
)


class StandaloneRebrickableClientTests(SimpleTestCase):
    @patch("apps.integrations.services._rebrickable_json")
    def test_name_and_identifier_search_use_minifigure_endpoint(self, remote):
        remote.return_value = {"results": [{"set_num": "fig-123", "name": "Bride"}]}
        self.assertEqual(rebrickable_minifigure_search("Bride", "test-key")[0]["set_num"], "fig-123")
        self.assertIn("minifigs/?search=Bride", remote.call_args.args[0])
        remote.return_value = {"set_num": "fig-123", "name": "Bride"}
        self.assertEqual(rebrickable_minifigure_search("FIG-123", "test-key")[0]["name"], "Bride")
        self.assertEqual(remote.call_args.args[0], "minifigs/fig-123/")
        with self.assertRaises(RebrickableError):
            normalize_rebrickable_minifigure_number("col07-4")

    @patch("apps.integrations.services._rebrickable_json")
    def test_detail_fetches_all_inventory_pages(self, remote):
        remote.side_effect = [
            {"set_num": "fig-123", "name": "Bride"},
            {"results": [{"part": {"part_num": "head"}}], "next": "next"},
            {"results": [{"part": {"part_num": "veil"}}], "next": None},
        ]
        figure, parts = rebrickable_minifigure("fig-123", "test-key")
        self.assertEqual(figure["set_num"], "fig-123")
        self.assertEqual(len(parts), 2)
        self.assertEqual(remote.call_count, 3)

    @patch("apps.integrations.services._rebrickable_json")
    def test_invalid_or_empty_inventory_is_clean_error(self, remote):
        remote.side_effect = [{"set_num": "fig-123", "name": "Bride"}, {"results": []}]
        with self.assertRaises(RebrickableError) as ctx:
            rebrickable_minifigure("fig-123", "test-key")
        self.assertEqual(ctx.exception.code, "no_inventory")
