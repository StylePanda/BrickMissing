import json
import os
import shutil
import subprocess
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import LegoSet, Part, SetInventoryItem
from apps.organizer.models import MinifigurePart, SetMinifigure


class ResponsiveBrowserTests(StaticLiveServerTestCase):
    password = "Browser-audit-password-8492"  # noqa: S105 - ephemeral test credential

    def setUp(self):
        self.user = User.objects.create_user(
            username="responsive-audit",
            email="responsive-audit@example.test",
            password=self.password,
            email_verified=True,
        )
        self.lego_set = LegoSet.objects.create(
            owner=self.user,
            set_number="10307-1",
            name="Eiffelturm mit einem absichtlich langen responsiven Testnamen",
            theme="Icons",
            year=2022,
            total_parts=10001,
            image_url="/static/img/dashboard-banner.webp",
        )
        SetInventoryItem.objects.create(
            lego_set=self.lego_set,
            part_number="browser-donut",
            name="Browser donut allocation",
            required_quantity=995,
            owned_quantity=975,
        )
        related_sets = []
        for index in range(2):
            related_sets.append(LegoSet.objects.create(
                owner=self.user,
                set_number=f"responsive-{index}",
                name=f"Responsive dashboard card {index}",
                theme="Icons",
                image_url=(
                    "/static/img/dashboard-banner.webp"
                    if index == 0
                    else "/static/icons/brickmissing.svg"
                ),
            ))
        for index, lego_set in enumerate((self.lego_set, *related_sets)):
            Part.objects.create(
                owner=self.user,
                lego_set=lego_set,
                part_number="3001",
                element_id="browser-missing-card",
                name="Responsive missing-part card with a deliberately long descriptive name",
                color="Dark Bluish Gray",
                quantity=3,
                owned_quantity=1 if index == 0 else 0,
            )
        for index, color in enumerate(("Black", "Glow in Dark White", "White")):
            Part.objects.create(
                owner=self.user,
                element_id=f"complete-color-{index}",
                name=f"Completed {color} fixture",
                color=color,
                quantity=0,
                owned_quantity=0,
            )
        figure = SetMinifigure.objects.create(
            owner=self.user,
            lego_set=self.lego_set,
            figure_number="responsive-figure",
            name="Responsive Minifigure",
            image_url="/static/icons/brickmissing.svg",
        )
        MinifigurePart.objects.create(
            minifigure=figure,
            part_number="973",
            element_id="responsive-mini-part",
            name="Responsive Minifigure Torso",
            color_name="White",
            quantity=2,
            owned_quantity=0,
            image_url="/static/icons/brickmissing.svg",
        )
        MinifigurePart.objects.create(
            minifigure=figure, part_number="responsive-spare", name="Responsive Spare",
            quantity=1, owned_quantity=0, is_spare=True,
        )
        second_figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=self.lego_set, figure_number="responsive-second",
            name="Second Responsive Minifigure",
        )
        MinifigurePart.objects.create(
            minifigure=second_figure, part_number="3626", name="Responsive Head",
            quantity=2, owned_quantity=1,
        )
        complete_figure = SetMinifigure.objects.create(
            owner=self.user, lego_set=related_sets[0], figure_number="responsive-complete",
            name="Complete Responsive Minifigure", image_url="/static/icons/brickmissing.svg",
        )
        MinifigurePart.objects.create(
            minifigure=complete_figure, part_number="3626b", name="Complete Head",
            quantity=1, owned_quantity=1, image_url="/static/icons/brickmissing.svg",
        )

    def test_application_layout_at_supported_viewports(self):
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        node = shutil.which("node")
        if not edge.exists() or not node:
            self.skipTest("Microsoft Edge and Node.js are required for real layout assertions.")

        routes = {
            "login": reverse("accounts:login"),
            "authenticated": {
                "dashboard": reverse("dashboard"),
                "sets": reverse("catalog:set_list"),
                "setForm": reverse("catalog:set_create"),
                "setDetail": reverse("catalog:set_detail", args=[self.lego_set.pk]),
                "parts": reverse("catalog:part_list"),
                "missingParts": reverse("catalog:missing_parts"),
                "inventory": reverse("inventory:list"),
                "minifigures": reverse("organizer:minifigure_list"),
                "mocs": reverse("organizer:list", args=["mocs"]),
                "orders": reverse("orders:list"),
                "profile": reverse("accounts:profile"),
                "imprint": reverse("legal:imprint"),
            },
        }
        root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.update(
            {
                "BRICKMISSING_AUDIT_USERNAME": self.user.username,
                "BRICKMISSING_AUDIT_PASSWORD": self.password,
            }
        )
        result = subprocess.run(  # noqa: S603 - fixed local executable and arguments
            [
                node,
                str(root / "scripts" / "responsive_ui_audit.mjs"),
                self.live_server_url,
                str(edge),
                json.dumps(routes),
                str(root / "var" / "responsive-artifacts"),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
