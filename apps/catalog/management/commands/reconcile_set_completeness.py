from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import LegoSet
from apps.catalog.services import set_completeness, stored_completeness_value


class Command(BaseCommand):
    help = "Vergleicht gespeicherte und berechnete Set-Vollständigkeit (standardmäßig Dry-run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Speichert die berechnete Vollständigkeit. Ohne diese Option bleibt der Lauf read-only.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        queryset = LegoSet.objects.filter(deleted_at__isnull=True).prefetch_related(
            "inventory_items", "minifigures_inventory__parts"
        )
        mismatches = []
        for lego_set in queryset.iterator(chunk_size=200):
            result = set_completeness(lego_set)
            expected = stored_completeness_value(result)
            if lego_set.completeness.casefold() != expected.casefold():
                mismatches.append((lego_set, result, expected))
                self.stdout.write(
                    f"Set {lego_set.set_number} (ID {lego_set.pk}): "
                    f"required={result['required']} available={result['owned']} "
                    f"missing={result['missing']} stored={lego_set.completeness!r} "
                    f"expected={expected!r}"
                )

        if apply_changes and mismatches:
            with transaction.atomic():
                for lego_set, _result, expected in mismatches:
                    LegoSet.objects.filter(pk=lego_set.pk).update(completeness=expected)

        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(self.style.SUCCESS(f"{mode}: {len(mismatches)} Abweichungen gefunden."))
        if not apply_changes:
            self.stdout.write("Keine Daten wurden verändert. Zum Anwenden ausdrücklich --apply verwenden.")
