from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizer.models import MinifigurePart, SetMinifigure

from .colors import color_category
from .models import LegoSet, Part, SetInventoryItem
from .services import filter_sets_by_missing_colors, with_set_completeness


class SetMissingColorFilterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "missing-colors", "missing-colors@example.test", "A-long-password-123"
        )
        self.client.force_login(self.user)

    def lego_set(self, number, *, theme="Technic"):
        return LegoSet.objects.create(
            owner=self.user, set_number=number, name=f"Set {number}", theme=theme
        )

    def inventory(self, lego_set, color, *, owned=0, required=2, suffix="", spare=False):
        return SetInventoryItem.objects.create(
            lego_set=lego_set,
            part_number=f"part-{color}-{suffix or lego_set.set_number}",
            element_id=f"element-{color}-{suffix or lego_set.set_number}",
            name=f"{color} part",
            color_id=None,
            color_name=color,
            required_quantity=required,
            owned_quantity=owned,
            is_spare=spare,
        )

    def result_ids(self, **params):
        response = self.client.get(reverse("catalog:set_list"), params)
        return response, {item.pk for item in response.context["page_obj"]}

    def test_single_color_uses_any_missing_part_semantics(self):
        black = self.lego_set("black")
        self.inventory(black, "Black")
        black_red = self.lego_set("black-red")
        self.inventory(black_red, "Black")
        self.inventory(black_red, "Red")
        blue_white = self.lego_set("blue-white")
        self.inventory(blue_white, "Blue")
        self.inventory(blue_white, "White")

        _response, black_ids = self.result_ids(missing_color="Black")
        _response, red_ids = self.result_ids(missing_color="Red")
        _response, blue_ids = self.result_ids(missing_color="Purple")

        self.assertEqual(black_ids, {black.pk, black_red.pk})
        self.assertEqual(red_ids, {black_red.pk})
        self.assertEqual(blue_ids, set())

    def test_multiple_colors_are_or_not_all_colors(self):
        black = self.lego_set("or-black")
        self.inventory(black, "Black")
        red = self.lego_set("or-red")
        self.inventory(red, "Red")
        both = self.lego_set("or-both")
        self.inventory(both, "Black")
        self.inventory(both, "Red")
        blue_black = self.lego_set("or-blue-black")
        self.inventory(blue_black, "Blue")
        self.inventory(blue_black, "Black")
        blue = self.lego_set("or-blue")
        self.inventory(blue, "Blue")
        complete = self.lego_set("or-complete")
        self.inventory(complete, "Black", owned=2)

        _response, ids = self.result_ids(missing_color=["Black", "Red"])

        self.assertEqual(ids, {black.pk, red.pk, both.pk, blue_black.pk})

    def test_fully_owned_selected_color_does_not_match_other_missing_color(self):
        lego_set = self.lego_set("owned-black")
        self.inventory(lego_set, "Black", owned=2)
        self.inventory(lego_set, "Red", owned=0)

        _response, ids = self.result_ids(missing_color="Black")

        self.assertNotIn(lego_set.pk, ids)

    def test_existing_filter_is_anded_and_duplicate_matches_return_one_set(self):
        technic = self.lego_set("technic", theme="Technic")
        self.inventory(technic, "Black", suffix="one")
        self.inventory(technic, "Black", suffix="two")
        city = self.lego_set("city", theme="City")
        self.inventory(city, "Black")

        _response, ids = self.result_ids(
            missing_color=["Black", "Red"], theme="Technic"
        )

        self.assertEqual(ids, {technic.pk})

    def test_filter_reads_authoritative_allocation_not_stale_part_mirror(self):
        authoritative_missing = self.lego_set("authority-missing")
        self.inventory(authoritative_missing, "Black", owned=0, required=2)
        Part.objects.create(
            owner=self.user,
            lego_set=authoritative_missing,
            element_id="element-Black-authority-missing",
            part_number="part-Black-authority-missing",
            name="Stale full mirror",
            color="Black",
            quantity=2,
            owned_quantity=2,
        )
        authoritative_full = self.lego_set("authority-full")
        self.inventory(authoritative_full, "Black", owned=2, required=2)
        Part.objects.create(
            owner=self.user,
            lego_set=authoritative_full,
            element_id="element-Black-authority-full",
            part_number="part-Black-authority-full",
            name="Stale missing mirror",
            color="Black",
            quantity=2,
            owned_quantity=0,
        )

        _response, ids = self.result_ids(missing_color="Black")

        self.assertIn(authoritative_missing.pk, ids)
        self.assertNotIn(authoritative_full.pk, ids)

    def test_spares_owner_and_minifigure_allocations_follow_existing_rules(self):
        spare_only = self.lego_set("spare")
        self.inventory(spare_only, "Black", spare=True)
        minifigure_set = self.lego_set("minifigure")
        figure = SetMinifigure.objects.create(
            owner=self.user,
            lego_set=minifigure_set,
            figure_number="fig-filter",
            name="Figure",
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="973",
            name="Torso",
            color_name="Black",
            quantity=1,
            owned_quantity=0,
        )
        foreign = get_user_model().objects.create_user(
            "foreign-colors", "foreign-colors@example.test", "A-long-password-123"
        )
        foreign_set = LegoSet.objects.create(
            owner=foreign, set_number="foreign", name="Foreign"
        )
        SetInventoryItem.objects.create(
            lego_set=foreign_set,
            part_number="foreign",
            name="Foreign",
            color_name="Black",
            required_quantity=1,
            owned_quantity=0,
        )

        _response, ids = self.result_ids(missing_color="Black")

        self.assertEqual(ids, {minifigure_set.pk})

    def test_color_component_uses_central_groups_and_shows_selection(self):
        lego_set = self.lego_set("groups")
        for color in ("Lime", "Light Nougat", "Trans-Clear", "Pearl Gold"):
            self.inventory(lego_set, color)

        response, _ids = self.result_ids(missing_color=["Lime", "Light Nougat"])

        self.assertContains(response, "Fehlende Farben")
        self.assertContains(response, "2 Farben")
        self.assertContains(response, 'name="missing_color" value="Lime" checked')
        self.assertEqual(color_category("Lime"), "GREEN")
        self.assertEqual(color_category("Light Nougat"), "BROWN")
        self.assertEqual(color_category("Trans-Clear"), "TRANS")
        self.assertEqual(color_category("Pearl Gold"), "METALLIC / PEARL / FLAT")

    def test_production_import_spelling_variants_resolve_to_exact_stored_values(self):
        black = self.lego_set("production-black")
        self.inventory(black, "  bLaCk  ")
        transparent = self.lego_set("production-trans")
        self.inventory(transparent, "Trans Clear")

        _response, black_ids = self.result_ids(missing_color="Black")
        _response, trans_ids = self.result_ids(missing_color="trans-clear")

        self.assertEqual(black_ids, {black.pk})
        self.assertEqual(trans_ids, {transparent.pk})

    def test_central_category_value_expands_to_its_exact_stored_colors(self):
        pearl = self.lego_set("category-pearl")
        self.inventory(pearl, "Pearl Gold")
        flat = self.lego_set("category-flat")
        self.inventory(flat, "Flat Silver")
        red = self.lego_set("category-red")
        self.inventory(red, "Red")

        _response, ids = self.result_ids(
            missing_color="METALLIC / PEARL / FLAT"
        )

        self.assertEqual(ids, {pearl.pk, flat.pk})

    def test_blank_colors_are_not_offered_and_unknown_selection_matches_nothing(self):
        blank = self.lego_set("blank")
        self.inventory(blank, "   ")
        black = self.lego_set("known")
        self.inventory(black, "Black")

        response, ids = self.result_ids(missing_color="Unknown production color")

        self.assertEqual(ids, set())
        options = [
            option["value"]
            for group in response.context["missing_color_groups"]
            for option in group["colors"]
        ]
        self.assertNotIn("   ", options)

    def test_search_theme_and_completeness_remain_and_filters(self):
        matching = self.lego_set("combined-match", theme="Technic")
        matching.name = "Black Crane"
        matching.save(update_fields=["name"])
        self.inventory(matching, "Black")
        wrong_theme = self.lego_set("combined-theme", theme="City")
        wrong_theme.name = "Black Crane"
        wrong_theme.save(update_fields=["name"])
        self.inventory(wrong_theme, "Black")
        wrong_query = self.lego_set("combined-query", theme="Technic")
        self.inventory(wrong_query, "Black")
        complete = self.lego_set("combined-complete", theme="Technic")
        complete.name = "Black Crane Complete"
        complete.save(update_fields=["name"])
        self.inventory(complete, "Black", owned=2)

        _response, ids = self.result_ids(
            missing_color="Black",
            q="Crane",
            theme="Technic",
            completeness="incomplete",
        )

        self.assertEqual(ids, {matching.pk})

    def test_pagination_preserves_multiple_color_and_sort_parameters(self):
        for index in range(51):
            lego_set = self.lego_set(f"page-{index:02d}")
            self.inventory(lego_set, "Black")

        response = self.client.get(
            reverse("catalog:set_list"),
            {
                "missing_color": ["Black", "Red"],
                "sort": "set_number",
                "page": 1,
            },
        )

        self.assertEqual(len(response.context["page_obj"]), 50)
        self.assertContains(response, "missing_color=Black")
        self.assertContains(response, "missing_color=Red")
        self.assertContains(response, "sort=set_number")

    def test_filter_evaluation_uses_one_bounded_queryset_query(self):
        matching = self.lego_set("query-match")
        self.inventory(matching, "Black")
        nonmatching = self.lego_set("query-no-match")
        self.inventory(nonmatching, "Blue")
        queryset = with_set_completeness(
            LegoSet.objects.filter(owner=self.user, deleted_at__isnull=True)
        )
        queryset = filter_sets_by_missing_colors(queryset, ["Black", "Red"])

        with self.assertNumQueries(1):
            ids = list(queryset.values_list("pk", flat=True))

        self.assertEqual(ids, [matching.pk])
