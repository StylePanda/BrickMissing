from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.organizer.models import MinifigurePart, SetMinifigure

from .models import LegoSet, SetInventoryItem


class SetCompletenessFilterTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create_user(
            "set-filter", "set-filter@example.test", "Strong-password-123"
        )
        self.other = users.objects.create_user(
            "set-filter-other",
            "set-filter-other@example.test",
            "Strong-password-456",
        )
        self.client.force_login(self.user)
        self.url = reverse("catalog:set_list")

    def make_set(
        self,
        number,
        name,
        *,
        required=None,
        owned=0,
        owner=None,
        theme="Space",
        year=None,
    ):
        lego_set = LegoSet.objects.create(
            owner=owner or self.user,
            set_number=number,
            name=name,
            theme=theme,
            year=year,
        )
        if required is not None:
            SetInventoryItem.objects.create(
                lego_set=lego_set,
                part_number=f"part-{number}",
                name="Testteil",
                required_quantity=required,
                owned_quantity=owned,
            )
        return lego_set

    @staticmethod
    def result_ids(response):
        return {item.pk for item in response.context["page_obj"].object_list}

    def test_default_all_and_invalid_values_keep_the_normal_set_scope(self):
        complete = self.make_set("100-1", "Complete", required=1, owned=1)
        incomplete = self.make_set("101-1", "Incomplete", required=1, owned=0)
        empty = self.make_set("102-1", "Empty")
        self.make_set(
            "999-1", "Foreign", required=1, owned=1, owner=self.other
        )
        expected = {complete.pk, incomplete.pk, empty.pk}

        for params in ({}, {"completeness": "all"}, {"completeness": "invalid"}):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.result_ids(response), expected)
                self.assertEqual(
                    response.context["completeness"],
                    "all" if params.get("completeness") == "invalid" else params.get("completeness", "all"),
                )

    def test_complete_and_incomplete_filters_are_disjoint_and_quantity_aware(self):
        equal = self.make_set("200-1", "Equal", required=4, owned=4)
        exceeded = self.make_set("201-1", "Exceeded", required=4, owned=7)
        missing = self.make_set("202-1", "Missing", required=1, owned=0)
        partial = self.make_set("203-1", "Partial", required=4, owned=1)
        empty = self.make_set("204-1", "No inventory")

        complete_response = self.client.get(self.url, {"completeness": "complete"})
        incomplete_response = self.client.get(
            self.url, {"completeness": "incomplete"}
        )
        complete_ids = self.result_ids(complete_response)
        incomplete_ids = self.result_ids(incomplete_response)

        self.assertEqual(complete_ids, {equal.pk, exceeded.pk})
        self.assertEqual(incomplete_ids, {missing.pk, partial.pk, empty.pk})
        self.assertFalse(complete_ids & incomplete_ids)
        self.assertContains(complete_response, "Vollständig")
        self.assertContains(incomplete_response, "Unvollständig · 1 Teil fehlt")
        self.assertContains(incomplete_response, "Unvollständig · 3 Teile fehlen")
        self.assertContains(incomplete_response, ">Unvollständig</span>")

    def test_reloading_reflects_current_inventory_quantities(self):
        lego_set = self.make_set("205-1", "Live", required=2, owned=0)
        item = lego_set.inventory_items.get()
        self.assertIn(
            lego_set.pk,
            self.result_ids(
                self.client.get(self.url, {"completeness": "incomplete"})
            ),
        )

        item.owned_quantity = 2
        item.save(update_fields=["owned_quantity"])

        self.assertIn(
            lego_set.pk,
            self.result_ids(self.client.get(self.url, {"completeness": "complete"})),
        )

    def test_minifigure_parts_follow_central_semantics_without_parent_double_counting(self):
        lego_set = self.make_set("300-1", "Minifigure", required=2, owned=2)
        figure = SetMinifigure.objects.create(
            owner=self.user,
            lego_set=lego_set,
            figure_number="fig-1",
            name="Figure",
            quantity=5,
            owned_quantity=0,
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="head",
            name="Head",
            quantity=2,
            owned_quantity=1,
        )

        response = self.client.get(self.url, {"completeness": "incomplete"})
        item = next(iter(response.context["page_obj"].object_list))
        self.assertEqual(item.pk, lego_set.pk)
        self.assertEqual(item.completeness_missing, 1)
        self.assertContains(response, "Unvollständig · 1 Teil fehlt")

    def test_foreign_sets_and_foreign_owned_minifigures_do_not_affect_results(self):
        own = self.make_set("400-1", "Own", required=1, owned=1)
        foreign = self.make_set(
            "401-1", "Foreign", required=5, owned=0, owner=self.other
        )
        anomalous_figure = SetMinifigure.objects.create(
            owner=self.other,
            lego_set=own,
            figure_number="foreign-figure",
            name="Foreign figure",
        )
        MinifigurePart.objects.create(
            minifigure=anomalous_figure,
            part_number="foreign-head",
            name="Foreign head",
            quantity=9,
            owned_quantity=0,
        )

        complete = self.client.get(self.url, {"completeness": "complete"})
        incomplete = self.client.get(self.url, {"completeness": "incomplete"})
        self.assertEqual(self.result_ids(complete), {own.pk})
        self.assertNotIn(foreign.pk, self.result_ids(incomplete))
        self.assertNotContains(incomplete, "Foreign")

    def test_search_theme_and_sorting_combine_with_completeness(self):
        beta = self.make_set(
            "500-1", "Beta Castle", required=2, owned=0, theme="Castle", year=2020
        )
        alpha = self.make_set(
            "501-1", "Alpha Castle", required=2, owned=1, theme="Castle", year=2024
        )
        self.make_set(
            "502-1", "Complete Castle", required=1, owned=1, theme="Castle"
        )
        self.make_set(
            "503-1", "Alpha Space", required=1, owned=0, theme="Space"
        )

        response = self.client.get(
            self.url,
            {
                "q": "Castle",
                "theme": "Castle",
                "completeness": "incomplete",
                "sort": "name",
            },
        )
        self.assertEqual(
            [item.pk for item in response.context["page_obj"].object_list],
            [alpha.pk, beta.pk],
        )

    def test_pagination_preserves_completeness_and_other_query_parameters(self):
        for index in range(51):
            self.make_set(
                f"6{index:03d}-1",
                f"Paged {index:02d}",
                required=1,
                owned=1,
                theme="Space",
            )
        response = self.client.get(
            self.url,
            {
                "q": "Paged",
                "theme": "Space",
                "completeness": "complete",
                "sort": "name",
                "view": "cards",
            },
        )
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertContains(response, "completeness=complete")
        self.assertContains(response, "q=Paged")
        self.assertContains(response, "theme=Space")
        self.assertContains(response, "sort=name")
        self.assertContains(response, "view=cards")
        self.assertContains(response, "page=2")

    def test_empty_filter_states_are_specific(self):
        response = self.client.get(self.url, {"completeness": "complete"})
        self.assertContains(response, "Keine vollständigen Sets gefunden.")
        self.make_set("700-1", "Complete", required=1, owned=1)
        response = self.client.get(self.url, {"completeness": "incomplete"})
        self.assertContains(response, "Keine unvollständigen Sets gefunden.")

    def test_list_query_count_does_not_grow_with_number_of_cards(self):
        for index in range(5):
            self.make_set(
                f"8{index:03d}-1", f"Small {index}", required=2, owned=index % 2
            )
        with CaptureQueriesContext(connection) as small_queries:
            self.client.get(self.url)

        for index in range(55):
            self.make_set(
                f"9{index:03d}-1", f"Large {index}", required=2, owned=index % 2
            )
        with CaptureQueriesContext(connection) as large_queries:
            self.client.get(self.url)

        self.assertEqual(len(large_queries), len(small_queries))
