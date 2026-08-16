from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.catalog.models import Part
from apps.organizer.models import MinifigurePart


class Command(BaseCommand):
    help = "Prüft die Fehlteile-Daten read-only auf Dubletten und Inkonsistenzen."

    def handle(self, *args, **options):
        normal = defaultdict(list)
        normal_origin = defaultdict(list)
        invalid_normal = []
        for part in Part.objects.filter(deleted_at__isnull=True).iterator():
            identity = (part.element_id or part.design_id or part.part_number).strip().casefold()
            key = (part.owner_id, part.lego_set_id, identity, part.color.strip().casefold(), part.status)
            normal[key].append(str(part.pk))
            normal_origin[(part.owner_id, part.lego_set_id, identity, part.color.strip().casefold())].append(str(part.pk))
            if part.owned_quantity > part.quantity or part.status not in Part.Status.values:
                invalid_normal.append(str(part.pk))

        figures = defaultdict(list)
        cross_source = []
        invalid_figures = []
        for part in MinifigurePart.objects.select_related("minifigure").iterator():
            identity = (part.element_id or part.part_number).strip().casefold()
            key = (
                part.minifigure.owner_id, part.minifigure.lego_set_id,
                part.minifigure_id, identity,
                part.color_id if part.color_id is not None else part.color_name.strip().casefold(),
                part.is_spare,
            )
            figures[key].append(str(part.pk))
            origin = (
                part.minifigure.owner_id, part.minifigure.lego_set_id,
                identity, part.color_name.strip().casefold(),
            )
            if origin in normal_origin:
                cross_source.append(f"minifigure={part.pk}; normal={','.join(normal_origin[origin])}")
            if part.owned_quantity > part.quantity:
                invalid_figures.append(str(part.pk))

        duplicate_normal = [ids for ids in normal.values() if len(ids) > 1]
        duplicate_figures = [ids for ids in figures.values() if len(ids) > 1]
        categories = (
            ("duplicate_normal_parts", duplicate_normal),
            ("duplicate_minifigure_parts", duplicate_figures),
            ("cross_source_representations", cross_source),
            ("inconsistent_normal_parts", invalid_normal),
            ("inconsistent_minifigure_parts", invalid_figures),
        )
        for name, rows in categories:
            self.stdout.write(f"{name}: {len(rows)}")
            for row in rows[:50]:
                self.stdout.write("  " + (",".join(row) if isinstance(row, list) else row))
        self.stdout.write("audit_mode: read-only")
