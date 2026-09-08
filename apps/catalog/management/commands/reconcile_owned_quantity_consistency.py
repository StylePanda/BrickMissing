from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.owned_quantity_reconciliation import (
    AMBIGUOUS,
    EXACTLY_EQUAL_AFTER_NORMALIZATION,
    apply_reconciliation,
    classify_owned_quantity_consistency,
)


class Command(BaseCommand):
    help = "Classify and explicitly reconcile proven owned-quantity divergences."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply proven changes.")
        parser.add_argument("--user-id")
        parser.add_argument("--part-id")
        parser.add_argument("--set-number")
        parser.add_argument(
            "--resolve-ambiguous-from-authority",
            action="store_true",
            help=(
                "Explicit user-approved historical policy: retain authoritative "
                "allocation ownership for otherwise ambiguous rows."
            ),
        )

    def _user(self, identifier):
        if not identifier:
            return None
        try:
            return get_user_model().objects.get(pk=identifier)
        except (ValueError, get_user_model().DoesNotExist) as exc:
            raise CommandError("User was not found.") from exc

    def _write_plan(self, plan):
        row = plan.row
        values = (
            plan.classification,
            row["part_id"],
            row["set_number"],
            row["element_id"],
            row["design_or_part_number"],
            row["color"],
            row["part_required"],
            row["part_owned"],
            row["authoritative_required"],
            row["authoritative_owned"],
            plan.proposed_winner,
            "" if plan.proposed_final_owned is None else plan.proposed_final_owned,
            plan.reason,
            row["allocation_types"],
            "yes" if plan.would_write else "no",
        )
        self.stdout.write("\t".join(str(value) for value in values))

    def handle(self, *args, **options):
        user = self._user(options["user_id"])
        filters = {
            "user": user,
            "part_id": options["part_id"],
            "set_number": options["set_number"],
            "resolve_ambiguous_from_authority": options[
                "resolve_ambiguous_from_authority"
            ],
        }
        plans = classify_owned_quantity_consistency(**filters)
        self.stdout.write(
            "classification\tpart_id\tset\telement_id\tdesign_or_part_number\tcolor\t"
            "part_required\tpart_owned\tauthoritative_required\tauthoritative_owned\t"
            "proposed_winner\tproposed_final_owned\tprovenance_reason\tallocation_type\t"
            "would_write"
        )
        for plan in plans:
            self._write_plan(plan)

        ambiguities = sum(plan.classification == AMBIGUOUS for plan in plans)
        proposed = sum(plan.would_write for plan in plans)
        self.stdout.write(f"mode: {'APPLY' if options['apply'] else 'DRY-RUN'}")
        self.stdout.write(f"proposed_writes: {proposed}")
        self.stdout.write(f"unresolved_ambiguities: {ambiguities}")

        if not options["apply"]:
            if ambiguities:
                raise CommandError(
                    f"Dry-run found {ambiguities} unresolved ambiguities; review required."
                )
            return

        changed = apply_reconciliation(plans, **filters)
        remaining = classify_owned_quantity_consistency(**filters)
        remaining_ambiguous = sum(
            plan.classification == AMBIGUOUS for plan in remaining
        )
        remaining_divergences = sum(
            plan.classification != EXACTLY_EQUAL_AFTER_NORMALIZATION
            for plan in remaining
        )
        self.stdout.write(f"applied_writes: {changed}")
        self.stdout.write(f"divergences: {remaining_divergences}")
        self.stdout.write(f"ambiguous: {remaining_ambiguous}")
        self.stdout.write(f"unresolved_ambiguities: {remaining_ambiguous}")
        self.stdout.write("failed: 0")
        if remaining_divergences or remaining_ambiguous:
            raise CommandError(
                "Post-apply verification failed: unresolved ownership divergences remain."
            )
        self.stdout.write(self.style.SUCCESS("Owned-quantity reconciliation verified."))
