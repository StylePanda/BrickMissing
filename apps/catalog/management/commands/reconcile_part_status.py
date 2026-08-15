from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Part
from apps.catalog.part_status import analyze_part_status, workflow_status_label


class Command(BaseCommand):
    help = "Analysiert Part-Workflowstatus und Bestand; Standard ist ein read-only Dry-run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Korrigiert ausschließlich eindeutig ableitbare redundante Felder.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        counts = Counter()
        changed = 0
        with transaction.atomic():
            queryset = Part.objects.filter(deleted_at__isnull=True).select_related("lego_set")
            if apply_changes:
                queryset = queryset.select_for_update()
            for part in queryset.iterator(chunk_size=200):
                findings = analyze_part_status(part)
                if not findings:
                    continue
                safe_updates = {}
                for finding in findings:
                    counts[finding.category] += 1
                    if finding.safe_apply:
                        safe_updates[finding.field] = finding.value
                    self.stdout.write(
                        " | ".join((
                            f"[{finding.category}] {finding.title}",
                            f"ID={part.pk}",
                            f"Element={part.element_id or '-'}",
                            f"Design/Part={part.design_id or part.part_number or '-'}",
                            f"Name={part.name}",
                            f"Farbe={part.color or '-'}",
                            f"Set={part.lego_set.set_number if part.lego_set else '-'}",
                            f"benötigt={part.quantity}",
                            f"owned={part.owned_quantity}",
                            f"unassigned={part.unassigned_found_quantity}",
                            f"Status={part.status} ({workflow_status_label(part.status)})",
                            f"Erwartet={finding.expected_status}",
                            f"Vorschlag={finding.proposed_change}",
                            "AUTO-SAFE" if finding.safe_apply else "AMBIGUOUS / MANUAL REVIEW",
                        ))
                    )
                if apply_changes and safe_updates:
                    Part.objects.filter(pk=part.pk).update(**safe_updates)
                    changed += 1

        self.stdout.write("KATEGORIEN")
        for category, label in (
            ("A", "Gefunden + Bestand 0"),
            ("B", "Gefunden + Teilbestand"),
            ("C", "Fehlt + vollständig vorhanden"),
            ("D", "Unbekannter Workflowstatus"),
            ("E", "is_present widerspricht Mengen"),
        ):
            self.stdout.write(f"{category}) {label}: {counts[category]}")
        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(self.style.SUCCESS(f"{mode}: {sum(counts.values())} Funde; {changed} Datensätze geändert."))
        if not apply_changes:
            self.stdout.write("Keine Daten wurden verändert. --apply korrigiert ausschließlich AUTO-SAFE-Fälle.")
