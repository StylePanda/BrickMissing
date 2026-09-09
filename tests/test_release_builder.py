import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from brickmissing_version import APP_VERSION
from scripts.build_release import FORBIDDEN_SUFFIXES, FORBIDDEN_TOP_LEVEL, build_release
from scripts.release_switch import switch_release
from scripts.verify_release import ReleaseVerificationError, verify_release


class ReleaseBuilderTests(TestCase):
    def test_release_tools_read_version_without_site_packages_or_config_initialization(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="bm811-system-python-") as temporary:
            exact_output_root = Path(temporary) / "exact-output"
            exact_build = subprocess.run(  # noqa: S603 -- exact production-style invocation
                [
                    sys.executable,
                    str(project / "scripts" / "build_release.py"),
                    "--output-root",
                    str(exact_output_root),
                ],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                exact_build.returncode, 0, exact_build.stdout + exact_build.stderr
            )
            self.assertTrue((exact_output_root / f"brickmissing-{APP_VERSION}").is_dir())

            output_root = Path(temporary) / "isolated-output"
            build = subprocess.run(  # noqa: S603 -- fixed current interpreter and project script
                [
                    sys.executable,
                    "-S",
                    str(project / "scripts" / "build_release.py"),
                    "--output-root",
                    str(output_root),
                ],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            release = output_root / f"brickmissing-{APP_VERSION}"
            self.assertTrue(release.is_dir())

            verify = subprocess.run(  # noqa: S603 -- fixed current interpreter and release script
                [
                    sys.executable,
                    "-S",
                    str(release / "scripts" / "verify_release.py"),
                    str(release),
                ],
                cwd=release,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            self.assertIn(f"Verified BrickMissing {APP_VERSION}", verify.stdout)

            smoke_help = subprocess.run(  # noqa: S603 -- import check without runtime dependencies
                [sys.executable, "-S", str(release / "scripts" / "smoke_test.py"), "--help"],
                cwd=release,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(smoke_help.returncode, 0, smoke_help.stdout + smoke_help.stderr)

            import_probe = subprocess.run(  # noqa: S603 -- isolated import-side-effect check
                [
                    sys.executable,
                    "-S",
                    "-c",
                    (
                        "import runpy,sys; "
                        "[runpy.run_path(path) for path in sys.argv[1:]]; "
                        "assert 'config' not in sys.modules"
                    ),
                    str(project / "scripts" / "build_release.py"),
                    str(project / "scripts" / "verify_release.py"),
                    str(project / "scripts" / "smoke_test.py"),
                ],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                import_probe.returncode, 0, import_probe.stdout + import_probe.stderr
            )

            self.assertNotIn("config", build.stderr)
            self.assertNotIn("pymysql", build.stderr.lower())

    def test_mariadb_rehearsal_uses_clean_test_database_and_production_runner(self):
        project = Path(__file__).resolve().parents[1]
        rehearsal = (project / "scripts" / "rehearse_mariadb.py").read_text(encoding="utf-8")
        production = (project / "config" / "settings" / "production.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"--keepdb"', rehearsal)
        self.assertIn("config.test_runner.ProductionSettingsDiscoverRunner", production)

    @staticmethod
    def _link(source, destination, *, target_is_directory=True):
        del target_is_directory
        if os.name == "nt":
            result = subprocess.run(  # noqa: S603 -- test-only fixed cmd executable
                [os.environ.get("COMSPEC", "C:\\Windows\\System32\\cmd.exe"), "/c", "mklink", "/J", str(destination), str(source)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode:
                raise OSError(result.stderr or result.stdout)
        else:
            os.symlink(source, destination, target_is_directory=True)

    def test_atomic_deployment_and_systemd_use_the_same_current_release(self):
        source = Path(__file__).resolve().parents[1]
        script = (source / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        unit = (source / "deploy" / "systemd" / "brickmissing.service").read_text(
            encoding="utf-8"
        )
        self.assertIn('CURRENT="$ROOT/current"', script)
        self.assertIn('release_switch.py "$ROOT" "$RELEASE"', script)
        self.assertIn('release_switch.py "$ROOT" "$PREVIOUS"', script)
        self.assertLess(script.index("manage.py migrate --noinput"), script.index('release_switch.py "$ROOT" "$RELEASE"'))
        self.assertIn("WorkingDirectory=/var/www/brickmissing/current", unit)
        self.assertIn("/var/www/brickmissing/current/.venv/bin/gunicorn", unit)

    def test_allowlist_release_has_manifest_no_secrets_and_passes_django_check(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="bm8-release-test-") as temporary:
            release = build_release(source, Path(temporary))
            self.assertTrue((release / "manage.py").is_file())
            self.assertTrue((release / "static").is_dir())
            self.assertTrue((release / "deploy" / "nginx" / "brickmissing.conf").is_file())
            self.assertTrue(list((release / "apps").glob("*/migrations/*.py")))
            forbidden = [
                path for path in release.rglob("*")
                if path.relative_to(release).parts[0] in FORBIDDEN_TOP_LEVEL
                or path.suffix.lower() in FORBIDDEN_SUFFIXES
            ]
            self.assertEqual(forbidden, [])
            manifest = json.loads((release / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], APP_VERSION)
            self.assertTrue(manifest["files"])
            self.assertEqual(verify_release(release)["files"], len(manifest["files"]))
            result = subprocess.run(  # noqa: S603 -- fixed current interpreter and literal command
                [sys.executable, "manage.py", "check"], cwd=release,
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_manifest_tampering_missing_extra_and_invalid_hash_are_rejected(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="bm8-manifest-test-") as temporary:
            output = Path(temporary)
            release = build_release(source, output / "one")
            (release / "README.md").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ReleaseVerificationError, "size mismatch|hash mismatch"):
                verify_release(release)
            release = build_release(source, output / "two")
            (release / "README.md").unlink()
            with self.assertRaisesRegex(ReleaseVerificationError, "missing"):
                verify_release(release)
            release = build_release(source, output / "three")
            (release / "undeclared.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(ReleaseVerificationError, "undeclared"):
                verify_release(release)
            release = build_release(source, output / "four")
            manifest_path = release / "RELEASE_MANIFEST.json"
            changed = json.loads(manifest_path.read_text(encoding="utf-8"))
            changed["files"][0]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ReleaseVerificationError, "hash mismatch"):
                verify_release(release)

    def test_successful_activation_and_post_activation_rollback(self):
        with tempfile.TemporaryDirectory(prefix="bm8-switch-test-") as temporary:
            root = Path(temporary)
            old = root / "releases" / "old"
            new = root / "releases" / "new"
            old.mkdir(parents=True)
            new.mkdir()
            self._link(old, root / "current")
            real_replace = os.replace

            def replace_link(source, destination):
                if os.name == "nt":
                    os.rmdir(destination)
                    os.rename(source, destination)
                else:
                    real_replace(source, destination)

            with patch("scripts.release_switch.os.symlink", side_effect=self._link), patch(
                "scripts.release_switch.os.replace", side_effect=replace_link
            ):
                switch_release(root, new, temporary_name=".activate")
            self.assertEqual((root / "current").resolve(), new.resolve())
            with patch("scripts.release_switch.os.symlink", side_effect=self._link), patch(
                "scripts.release_switch.os.replace", side_effect=replace_link
            ):
                switch_release(root, old, temporary_name=".rollback")
            self.assertEqual((root / "current").resolve(), old.resolve())

    def test_pre_activation_failure_leaves_current_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="bm8-switch-failure-") as temporary:
            root = Path(temporary)
            old = root / "releases" / "old"
            new = root / "releases" / "new"
            old.mkdir(parents=True)
            new.mkdir()
            self._link(old, root / "current")
            with self.assertRaises((ValueError, FileNotFoundError)):
                switch_release(root, root / "not-a-release", temporary_name=".activate")
            self.assertEqual((root / "current").resolve(), old.resolve())
