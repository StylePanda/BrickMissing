from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.services import owned_quantity_consistency_rows


class Command(BaseCommand):
    help = "Prüft Part-/Setinventar-Bestandsabweichungen vollständig read-only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-id",
            help="Optional auf genau eine Benutzer-ID begrenzen.",
        )

    def handle(self, *args, **options):
        user = None
        if options["user_id"]:
            try:
                user = get_user_model().objects.get(pk=options["user_id"])
            except (ValueError, get_user_model().DoesNotExist) as exc:
                raise CommandError("Benutzer wurde nicht gefunden.") from exc

        rows = owned_quantity_consistency_rows(user=user)
        columns = (
            "part_id",
            "owner_id",
            "set_id",
            "set_number",
            "element_id",
            "design_or_part_number",
            "color",
            "part_required",
            "part_owned",
            "authoritative_required",
            "authoritative_owned",
            "difference",
            "part_updated_at",
            "authoritative_updated_at",
            "allocation_count",
            "allocation_types",
        )
        self.stdout.write("\t".join(columns))
        for row in rows:
            self.stdout.write(
                "\t".join(
                    "" if row[column] is None else str(row[column])
                    for column in columns
                )
            )
        self.stdout.write(f"divergences: {len(rows)}")
        self.stdout.write("audit_mode: read-only")
