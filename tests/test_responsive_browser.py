import json
import os
import shutil
import subprocess
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import LegoSet


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
