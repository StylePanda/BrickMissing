"""Real browser checks for the public documentation layout."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from apps.accounts.models import User


class DocumentationBrowserTests(StaticLiveServerTestCase):
    password = "Browser-docs-password-8492"  # noqa: S105 - ephemeral test credential

    def setUp(self):
        self.normal_user = User.objects.create_user(
            username="browser-docs-reader", email="browser-docs-reader@example.test",
            password=self.password, email_verified=True,
        )
        self.admin_user = User.objects.create_user(
            username="browser-docs-admin", email="browser-docs-admin@example.test",
            password=self.password, email_verified=True, is_staff=True,
        )

    def test_documentation_at_supported_viewports(self):
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        node = shutil.which("node")
        if not edge.exists() or not node:
            self.skipTest("Microsoft Edge and Node.js are required for real layout assertions.")

        root = Path(__file__).resolve().parents[1]
        routes = {
            "login": reverse("accounts:login"),
            "docs": {
                "index": reverse("documentation:index"),
                "parts": reverse("documentation:parts"),
                "testing": reverse("documentation:developer_testing"),
            },
        }
        for role, user in (("anonymous", None), ("normal", self.normal_user),
                           ("admin", self.admin_user)):
            with self.subTest(role=role):
                environment = os.environ.copy()
                environment["BRICKMISSING_AUDIT_DOCS_ONLY"] = "1"
                environment["BRICKMISSING_AUDIT_DOCS_ROLE"] = role
                if user:
                    environment["BRICKMISSING_AUDIT_USERNAME"] = user.username
                    environment["BRICKMISSING_AUDIT_PASSWORD"] = self.password
                result = subprocess.run(  # noqa: S603 - fixed local executable and arguments
                    [node, str(root / "scripts" / "responsive_ui_audit.mjs"),
                     self.live_server_url, str(edge), json.dumps(routes),
                     str(root / "var" / "responsive-artifacts")],
                    cwd=root, env=environment, capture_output=True, text=True,
                    timeout=90, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
