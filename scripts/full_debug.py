#!/usr/bin/env python3
"""BrickMissing full diagnostic bundle. Production mode is strictly read-only."""

from __future__ import annotations

import argparse
import ast
import contextlib
import datetime as dt
import importlib
import inspect
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEVERITIES = ("CRITICAL", "ERROR", "WARNING", "PASS", "INFO")
SECRET_RE = re.compile(
    r"(?i)(secret|password|passwd|token|api[_-]?key|authorization|cookie|csrf|session)[^\n=:\s]*\s*[=:]\s*[^\s]+"
)
EMAIL_RE = re.compile(r"\b([A-Z0-9._%+-])[^@\s]*@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.I)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def sanitize(value: object) -> str:
    text = ANSI_RE.sub("", str(value))
    text = SECRET_RE.sub(lambda match: match.group(0).split(":", 1)[0].split("=", 1)[0] + "=[MASKED]", text)
    return EMAIL_RE.sub(r"\1***@\2", text)


@dataclass
class Finding:
    severity: str
    area: str
    message: str
    detail: str = ""
    recommendation: str = ""


class Report:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.sections: list[tuple[str, list[str]]] = []
        self.findings: list[Finding] = []

    def add(self, severity: str, area: str, message: str, detail: object = "", recommendation: str = ""):
        finding = Finding(severity, area, sanitize(message), sanitize(detail), sanitize(recommendation))
        self.findings.append(finding)
        if self.verbose:
            print(f"[{severity}] {area}: {finding.message}")

    def section(self, title: str, lines: list[object]):
        self.sections.append((title, [sanitize(line) for line in lines]))

    @contextlib.contextmanager
    def guarded(self, area: str):
        try:
            yield
        except Exception:
            self.add("ERROR", area, "Audit-Schritt ist fehlgeschlagen.", traceback.format_exc(), "Schritt isoliert prüfen.")

    def render(self) -> str:
        counts = Counter(item.severity for item in self.findings)
        priority = {name: index for index, name in enumerate(SEVERITIES)}
        issues = sorted(
            (item for item in self.findings if item.severity in {"CRITICAL", "ERROR", "WARNING"}),
            key=lambda item: priority[item.severity],
        )[:20]
        lines = ["BRICKMISSING FULL APPLICATION DIAGNOSTIC", "=" * 44, "", "TOP 20 PROBLEME"]
        if not issues:
            lines.append("[PASS] Keine kritischen, fehlerhaften oder warnenden Funde.")
        for number, item in enumerate(issues, 1):
            lines.extend([
                f"{number}. [{item.severity}] {item.area}: {item.message}",
                f"   Ursache/Detail: {item.detail or 'nicht näher bestimmt'}",
                f"   Empfehlung: {item.recommendation or 'prüfen'}",
            ])
        for title, content in self.sections:
            lines.extend(["", "=" * 80, title, "=" * 80, *content])
        lines.extend(["", "=" * 80, "ZUSAMMENFASSUNG", "=" * 80])
        for severity in SEVERITIES:
            lines.append(f"{severity}: {counts[severity]}")
        lines.extend(["", "ALLE FUNDE"])
        for item in self.findings:
            lines.append(f"[{item.severity}] {item.area}: {item.message}")
            if item.detail:
                lines.append(f"  {item.detail}")
        return "\n".join(lines) + "\n"


def command(report: Report, title: str, argv: list[str], timeout: int = 600) -> tuple[int, str, float]:
    started = time.perf_counter()
    try:
        result = subprocess.run(  # noqa: S603 - fixed internal argv, never a shell
            argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
        )
        output = sanitize((result.stdout + "\n" + result.stderr).strip())
        elapsed = time.perf_counter() - started
        report.section(title, [f"Befehl: {' '.join(argv)}", f"Exit-Code: {result.returncode}", f"Laufzeit: {elapsed:.3f} s", output or "(keine Ausgabe)"])
        report.add("PASS" if result.returncode == 0 else "ERROR", title, f"Exit-Code {result.returncode}", recommendation="Befehlsausgabe prüfen.")
        return result.returncode, output, elapsed
    except Exception:
        elapsed = time.perf_counter() - started
        detail = traceback.format_exc()
        report.section(title, [f"Befehl: {' '.join(argv)}", f"Laufzeit: {elapsed:.3f} s", detail])
        report.add("ERROR", title, "Befehl konnte nicht abgeschlossen werden.", detail)
        return 127, sanitize(detail), elapsed


def django_setup(settings_name: str):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_name)
    import django

    django.setup()
    return django


def header(report: Report, django, settings_name: str, production: bool):
    from django.conf import settings

    def git(*args):
        result = subprocess.run(  # noqa: S603,S607 - fixed read-only git invocation
            ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],  # noqa: S607
            cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        return result.stdout.strip() or result.stderr.strip()

    database = settings.DATABASES["default"].get("ENGINE", "unbekannt").rsplit(".", 1)[-1]
    report.section("REPORT HEADER", [
        f"Datum/Uhrzeit UTC: {dt.datetime.now(dt.UTC).isoformat()}",
        f"Hostname: {socket.gethostname()}",
        f"Python: {platform.python_version()}",
        f"Django: {django.get_version()}",
        f"Git Commit: {git('rev-parse', 'HEAD')}",
        f"Branch: {git('branch', '--show-current')}",
        "Working Tree Status:", git("status", "--short") or "sauber",
        f"Settings: {settings_name}", f"Production-Modus: {production}",
        f"DEBUG: {settings.DEBUG}", f"Datenbank-Backend: {database}",
        "Secrets: [MASKED] (Werte werden grundsätzlich nicht ausgegeben)",
    ])


def framework_commands(report: Report, python: str, production: bool):
    command(report, "DJANGO SYSTEM CHECK", [python, "manage.py", "check"])
    command(report, "DJANGO DEPLOY CHECK", [python, "manage.py", "check", "--deploy"])
    command(report, "MIGRATION DRIFT", [python, "manage.py", "makemigrations", "--check", "--dry-run"])
    try:
        importlib.import_module("ruff")
    except ModuleNotFoundError:
        report.section("RUFF", ["SKIPPED: Python-Modul ruff ist nicht installiert."])
        report.add("WARNING", "RUFF", "SKIPPED: Ruff ist nicht installiert.")
    else:
        command(report, "RUFF", [python, "-m", "ruff", "check", "--no-cache", "."])
    python_syntax_audit(report)
    command(report, "COLLECTSTATIC DRY RUN", [python, "manage.py", "collectstatic", "--dry-run", "--noinput"])
    if production:
        report.add("INFO", "TEST SUITE", "Im Production-Modus nicht gegen die Production-Datenbank gestartet.", recommendation="Tests in CI/Staging mit isolierter Testdatenbank ausführen.")
    else:
        code, output, elapsed = command(report, "TEST SUITE", [python, "manage.py", "test"], timeout=1200)
        match = re.search(r"Ran\s+(\d+)\s+tests?", output)
        failed = int((re.search(r"failures=(\d+)", output) or [0, 0])[1])
        errors = int((re.search(r"errors=(\d+)", output) or [0, 0])[1])
        skipped = int((re.search(r"skipped=(\d+)", output) or [0, 0])[1])
        total = int(match.group(1)) if match else 0
        report.section("TEST SUMMARY", [f"Gesamt: {total}", f"Passed: {max(total-failed-errors-skipped, 0)}", f"Failed: {failed}", f"Errors: {errors}", f"Skipped: {skipped}", f"Laufzeit: {elapsed:.3f} s", f"Status: {'PASS' if code == 0 else 'FAIL'}"])


def python_syntax_audit(report: Report):
    failures = []
    files = []
    for base in (ROOT / "apps", ROOT / "config", ROOT / "scripts"):
        for path in base.rglob("*.py"):
            files.append(path)
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeError) as exc:
                failures.append(f"{path.relative_to(ROOT)}: {exc}")
    report.section("PYTHON SYNTAX (read-only AST)", [f"Dateien: {len(files)}", *failures] or ["Keine Python-Dateien."])
    report.add("ERROR" if failures else "PASS", "PYTHON SYNTAX", f"Syntaxfehler: {len(failures)}")


def javascript_audit(report: Report):
    files = sorted((ROOT / "static" / "js").glob("*.js")) + sorted(ROOT.glob("static/service-worker.js"))
    if shutil.which("node") is None:
        report.section("JAVASCRIPT DATEIEN", [f"SKIPPED: Node.js ist nicht installiert ({len(files)} Dateien nicht geprüft)."])
        report.add("WARNING", "JAVASCRIPT", "SKIPPED: Node.js ist nicht verfügbar.")
        return
    lines = []
    for path in files:
        code, output, elapsed = command(report, f"NODE CHECK {path.relative_to(ROOT)}", ["node", "--check", str(path)], timeout=30)
        lines.append(f"{'PASS' if code == 0 else 'FAIL'} {path.relative_to(ROOT)} ({elapsed:.3f} s) {output[:300]}")
    report.section("JAVASCRIPT DATEIEN", lines or ["Keine eigenen JavaScript-Dateien gefunden."])


def url_audit(report: Report):
    from django.urls import URLPattern, URLResolver, get_resolver, reverse

    rows, names = [], Counter()

    def walk(patterns, prefix="", namespace=""):
        for item in patterns:
            route = prefix + str(item.pattern)
            if isinstance(item, URLResolver):
                child_namespace = f"{namespace}{item.namespace}:" if item.namespace else namespace
                walk(item.url_patterns, route, child_namespace)
            elif isinstance(item, URLPattern):
                full_name = f"{namespace}{item.name}" if item.name else ""
                if full_name:
                    names[full_name] += 1
                view = getattr(item.callback, "__module__", "") + "." + getattr(item.callback, "__name__", item.callback.__class__.__name__)
                reversible = "N/A"
                if full_name and not item.pattern.converters and "(?P<" not in str(item.pattern):
                    try:
                        reverse(full_name)
                        reversible = "PASS"
                    except Exception as exc:
                        reversible = f"N/A (Argumente erforderlich: {exc})"
                rows.append(f"{route} | {full_name or '-'} | {view} | reverse={reversible}")

    walk(get_resolver().url_patterns)
    for name, count in names.items():
        if count > 1:
            report.add("WARNING", "URL AUDIT", f"Doppelter URL-Name: {name} ({count})")
    report.section("URL AUDIT – ROUTE | NAME | VIEW", rows)
    report.add("PASS", "URL AUDIT", f"{len(rows)} URL-Patterns rekursiv erfasst.")


def forms_and_models(report: Report):
    from django import forms
    from django.apps import apps
    from django.db import models as django_models

    form_lines, model_lines = [], []
    for config in apps.get_app_configs():
        with contextlib.suppress(ModuleNotFoundError):
            module = importlib.import_module(f"{config.name}.forms")
            for name, cls in inspect.getmembers(module, inspect.isclass):
                if not issubclass(cls, forms.BaseForm) or cls.__module__ != module.__name__:
                    continue
                try:
                    instance = cls()
                    model = getattr(getattr(cls, "_meta", None), "model", None)
                    for field_name, field in instance.fields.items():
                        choices = "yes" if getattr(field, "choices", None) else "no"
                        form_lines.append(f"{cls.__module__}.{name} | model={getattr(model, '__name__', '-')} | {field_name} | {field.widget.__class__.__name__} | required={field.required} | choices={choices} | label={field.label}")
                        if isinstance(field, forms.DateField) and not isinstance(field.widget, forms.DateInput):
                            report.add("WARNING", "FORM AUDIT", f"DateField ohne DateInput: {name}.{field_name}")
                        if (
                            isinstance(field.widget, forms.NumberInput)
                            and field.widget.attrs.get("min") is None
                            and getattr(field, "min_value", None) is None
                            and not field_name.endswith("_id")
                        ):
                            report.add("WARNING", "FORM AUDIT", f"NumberInput ohne sichtbares min: {name}.{field_name}")
                except Exception as exc:
                    expected_user_forms = {
                        "AdminPasswordChangeForm", "PasswordChangeForm", "SetPasswordForm"
                    }
                    report.add(
                        "INFO" if name in expected_user_forms else "WARNING",
                        "FORM AUDIT",
                        (
                            f"SKIPPED: {name} benötigt erwartungsgemäß einen Benutzer."
                            if name in expected_user_forms
                            else f"Formular nicht parameterlos instanziierbar: {name}"
                        ),
                        "" if name in expected_user_forms else exc,
                    )
    for model in apps.get_models():
        owns_str = model.__str__ is not django_models.Model.__str__
        sample = "kein sicherer Beispieldatensatz erzeugt"
        model_lines.append(f"{model._meta.label} | __str__={'JA' if owns_str else 'GEERBT/NEIN'} | {sample}")
        if not owns_str and model._meta.app_config.name.startswith("apps."):
            report.add("WARNING", "MODEL STRING AUDIT", f"Kein eigener __str__: {model._meta.label}", recommendation="Sichtbare ModelChoice-Darstellung prüfen.")
    report.section("FORM AUDIT", form_lines or ["Keine Forms erfasst."])
    report.section("MODEL STRING AUDIT", model_lines)


def database_audit(report: Report):
    from django.db import connection
    from django.db.models import F

    from apps.accounts.models import User
    from apps.catalog.models import LegoSet, Part, SetInventoryItem
    from apps.catalog.part_status import analyze_part_status
    from apps.inventory.models import InventoryItem
    from apps.orders.models import Order
    from apps.organizer.models import MinifigurePart, SetMinifigure

    checks = {
        "Sets ohne Nummer": LegoSet.objects.filter(set_number="").count,
        "Sets ohne Namen": LegoSet.objects.filter(name="").count,
        "Setinventar owned > required": SetInventoryItem.objects.filter(owned_quantity__gt=F("required_quantity")).count,
        "Parts owned > required": Part.objects.filter(owned_quantity__gt=F("quantity")).count,
        "Minifigurteile owned > required": MinifigurePart.objects.filter(owned_quantity__gt=F("quantity")).count,
        "Minifiguren Menge 0": SetMinifigure.objects.filter(quantity=0).count,
        "Inventar ungültige Menge": InventoryItem.objects.filter(quantity__lt=0).count,
        "Bestellungen ungültiger Status": Order.objects.exclude(status__in=Order.STATUS_LABELS).count,
        "Legacy-Platzhalter-E-Mails": User.objects.filter(email__iendswith="@invalid.local").count,
    }
    lines = [f"Datenbank: {connection.vendor} (ausschließlich SELECT)"]
    for label, function in checks.items():
        try:
            count = function()
            lines.append(f"{label}: {count}")
            report.add("WARNING" if count else "PASS", "DATABASE CONSISTENCY", f"{label}: {count}")
        except Exception as exc:
            report.add("ERROR", "DATABASE CONSISTENCY", f"Prüfung fehlgeschlagen: {label}", exc)
    status_counts = Counter()
    for part in Part.objects.filter(deleted_at__isnull=True).iterator(chunk_size=500):
        for finding in analyze_part_status(part):
            status_counts[finding.category] += 1
    for category, label in (
        ("A", "Gefunden + Bestand 0"), ("B", "Gefunden + Teilbestand"),
        ("C", "Fehlt + vollständig vorhanden"), ("D", "Unbekannter Workflowstatus"),
        ("E", "is_present widerspricht Mengen"),
    ):
        count = status_counts[category]
        lines.append(f"Part-Status {category} – {label}: {count}")
        report.add(
            "WARNING" if count else "PASS", "PART STATUS CONSISTENCY",
            f"Kategorie {category} ({label}): {count}",
            recommendation="python manage.py reconcile_part_status (read-only Dry-run)",
        )
    mismatch = 0
    completeness_lines = []
    from apps.catalog.services import set_completeness
    for lego_set in LegoSet.objects.prefetch_related("inventory_items", "minifigures_inventory__parts").iterator(chunk_size=200):
        value = set_completeness(lego_set)
        stored = lego_set.completeness
        differs = stored.casefold() not in {value["key"], value["label"].casefold(), "vollständig" if value["key"] == "complete" else "unvollständig" if value["key"] == "incomplete" else "unbekannt"}
        mismatch += int(differs)
        completeness_lines.append(f"Set {lego_set.set_number}: required={value['required']} available={value['owned']} missing={value['missing']} computed={value['label']} stored={stored} mismatch={differs}")
    lines.append(f"Set-Vollständigkeitsabweichungen: {mismatch}")
    report.section("DATABASE CONSISTENCY / SET COMPLETENESS", [*lines, *completeness_lines[:1000]])
    report.add("WARNING" if mismatch else "PASS", "SET COMPLETENESS", f"Abweichungen: {mismatch}")


def source_audit(report: Report):
    patterns = {
        "form.as_p/as_table": re.compile(r"form\.as_(?:p|table)"),
        "object (...)": re.compile(r"object\s*\(", re.I),
        "localhost/127.0.0.1": re.compile(r"localhost|127\.0\.0\.1", re.I),
        "Inline-JavaScript": re.compile(r"javascript:|\son(?:click|change|submit|input|keydown|keyup|load|error)\s*=", re.I),
        "sichtbare UUID": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I),
    }
    hits = []
    roots = [ROOT / "templates", ROOT / "apps", ROOT / "static" / "js"]
    for base in roots:
        for path in base.rglob("*"):
            if path.suffix not in {".html", ".py", ".js"} or "migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                for label, pattern in patterns.items():
                    if pattern.search(line):
                        hits.append(f"{label}: {path.relative_to(ROOT)}:{number}: {line.strip()[:240]}")
                        severity = "WARNING" if label != "Inline-JavaScript" else "ERROR"
                        is_test = path.name.startswith("test") or "tests" in path.parts
                        if not is_test:
                            report.add(severity, "SOURCE/TEMPLATE AUDIT", f"{label} in {path.relative_to(ROOT)}:{number}")
    report.section("TEMPLATE / TRANSLATION / SOURCE AUDIT", hits or ["Keine Treffer."])


def security_audit(report: Report, production: bool):
    from django.conf import settings

    checks = {
        "DEBUG deaktiviert": not settings.DEBUG if production else True,
        "ALLOWED_HOSTS gesetzt": bool(settings.ALLOWED_HOSTS),
        "SESSION_COOKIE_SECURE": bool(settings.SESSION_COOKIE_SECURE) if production else True,
        "CSRF_COOKIE_SECURE": bool(settings.CSRF_COOKIE_SECURE) if production else True,
        "SECURE_SSL_REDIRECT": bool(settings.SECURE_SSL_REDIRECT) if production else True,
        "HSTS gesetzt": int(getattr(settings, "SECURE_HSTS_SECONDS", 0)) > 0 if production else True,
        "CSP Middleware/Settings": any(
            token in item.casefold()
            for item in settings.MIDDLEWARE
            for token in ("csp", "securityheadersmiddleware")
        ) or hasattr(settings, "CONTENT_SECURITY_POLICY"),
        "SECRET_KEY Mindestlänge": len(settings.SECRET_KEY) >= 32,
    }
    lines = []
    for label, valid in checks.items():
        lines.append(f"{label}: {'VALID/SET' if valid else 'WARNING/NOT SET'}")
        report.add("PASS" if valid else "WARNING", "SECURITY AUDIT", label)
    report.section("SECURITY AUDIT (keine Secret-Werte)", lines)


def static_and_service_worker(report: Report):
    from django.contrib.staticfiles import finders

    references, missing = [], []
    static_root = ROOT / "static"
    for template in (ROOT / "templates").rglob("*.html"):
        text = template.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"{[%]\s*static\s+['\"]([^'\"]+)", text):
            value = match.group(1)
            references.append(value)
            if not (static_root / value).exists() and finders.find(value) is None:
                missing.append(f"{template.relative_to(ROOT)} -> {value}")
    worker = static_root / "service-worker.js"
    worker_text = worker.read_text(encoding="utf-8", errors="replace") if worker.exists() else ""
    cache = re.search(r"CACHE[^=]*=\s*['\"]([^'\"]+)", worker_text)
    report.section("STATIC FILES / SERVICE WORKER", [f"Referenzen: {len(references)}", f"Fehlend: {len(missing)}", *missing, f"service-worker.js: {'vorhanden' if worker.exists() else 'fehlt'}", f"Cache-Version: {cache.group(1) if cache else 'nicht erkannt'}"])
    report.add("ERROR" if missing else "PASS", "STATIC FILES", f"Fehlende referenzierte Assets: {len(missing)}")


def idor_audit(report: Report):
    hits = []
    pattern = re.compile(r"(?:objects\.get|get_object_or_404)\([^\n]*(?:pk|id)\s*=")
    for path in (ROOT / "apps").rglob("views.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not any(token in line for token in ("owner=", "user=", "actor=")):
                hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    report.section("PERMISSION / IDOR STATIC AUDIT", hits or ["Keine offensichtlichen Einzeilentreffer ohne User-Scoping."])
    report.add("WARNING" if hits else "PASS", "PERMISSION / IDOR", f"Manuell zu prüfende Treffer: {len(hits)}", recommendation="Mehrzeilige Querysets und Parent-Scoping einzeln verifizieren.")


def public_http(report: Report, base_url: str):
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("--base-url muss eine gültige HTTPS-Adresse sein")
    paths = ("/", "/konto/anmelden/", "/konto/registrieren/", "/sets/", "/fehlteile/", "/organisation/minifiguren/", "/organisation/etiketten-qr/", "/admin/")
    lines = []
    for path in paths:
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        started = time.perf_counter()
        try:
            request = urllib.request.Request(url, method="GET", headers={"User-Agent": "BrickMissing-ReadOnly-Diagnostic/8"})  # noqa: S310 - HTTPS validated above
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - HTTPS validated above
                lines.append(f"{url} | {response.status} | {time.perf_counter()-started:.3f}s | {response.headers.get('Content-Type', '-')}")
        except urllib.error.HTTPError as exc:
            lines.append(f"{url} | {exc.code} | {time.perf_counter()-started:.3f}s | {exc.headers.get('Content-Type', '-')}")
        except Exception as exc:
            lines.append(f"{url} | ERROR | {time.perf_counter()-started:.3f}s | {exc}")
            report.add("WARNING", "PRODUCTION HTTP", f"GET fehlgeschlagen: {url}", exc)
    report.section("PRODUCTION HTTP SMOKE (ausschließlich GET)", lines)


def system_read_only(report: Report):
    command(report, "SYSTEMD ACTIVE", ["systemctl", "is-active", "brickmissing"], 30)
    command(report, "SYSTEMD ENABLED", ["systemctl", "is-enabled", "brickmissing"], 30)
    command(
        report,
        "SYSTEMD UNIT METADATA",
        [
            "systemctl", "show", "brickmissing", "--no-pager",
            "--property=FragmentPath,User,Group,WorkingDirectory,ExecStart",
        ],
        30,
    )
    if shutil.which("nginx") is None:
        report.section("NGINX TEST", ["SKIPPED: nginx ist nicht installiert oder nicht im PATH."])
        report.add("WARNING", "NGINX TEST", "SKIPPED: nginx ist nicht verfügbar.")
    else:
        code, output, _elapsed = command(report, "NGINX TEST", ["nginx", "-t"], 30)
        if code and re.search(r"permission denied|access is denied", output, re.I):
            finding = report.findings[-1]
            finding.severity = "WARNING"
            finding.message = "Prüfung benötigt erhöhte Leserechte; sudo wurde nicht aufgerufen."
    started = time.perf_counter()
    journalctl = shutil.which("journalctl")
    if journalctl is None:
        report.section("JOURNAL SUMMARY", ["SKIPPED: journalctl ist nicht verfügbar."])
        report.add("WARNING", "JOURNAL SUMMARY", "SKIPPED: journalctl ist nicht verfügbar.")
        return
    result = subprocess.run(  # noqa: S603 - fixed read-only system command
        [journalctl, "-u", "brickmissing.service", "-n", "200", "--no-pager"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    journal = result.stdout + result.stderr
    counts = {
        "HTTP 5xx": len(re.findall(r"\b5\d\d\b", journal)),
        "Traceback": journal.count("Traceback"),
        "Timeout": len(re.findall(r"timeout|timed out", journal, re.I)),
        "Restart/Start": len(re.findall(r"started|restarted|restart", journal, re.I)),
    }
    report.section(
        "JOURNAL SUMMARY (Inhalte werden nicht ausgegeben)",
        [
            "Befehl: journalctl -u brickmissing.service -n 200 --no-pager",
            f"Exit-Code: {result.returncode}",
            f"Laufzeit: {time.perf_counter() - started:.3f} s",
            *[f"{label}: {count}" for label, count in counts.items()],
        ],
    )
    permission_denied = bool(re.search(r"permission denied|not permitted|no entries", journal, re.I))
    report.add(
        "PASS" if result.returncode == 0 and not permission_denied else "WARNING",
        "JOURNAL SUMMARY",
        (
            "Logs konnten wegen fehlender Leserechte nicht vollständig gelesen werden; sudo wurde nicht aufgerufen."
            if permission_denied
            else f"Exit-Code {result.returncode}; Log-Inhalte aus Datenschutzgründen nicht ausgegeben."
        ),
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="BRICKMISSING_FULL_DEBUG.txt")
    parser.add_argument("--production", action="store_true", help="Strictly read-only production audit")
    parser.add_argument("--base-url", default="https://brickmissing.stylepanda.me")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--settings", default=None)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = Report(args.verbose)
    settings_name = args.settings or os.environ.get("DJANGO_SETTINGS_MODULE") or "config.settings.development"
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    try:
        django = django_setup(settings_name)
        with report.guarded("HEADER"):
            header(report, django, settings_name, args.production)
        with report.guarded("COMMANDS"):
            framework_commands(report, sys.executable, args.production)
        for area, function in (
            ("JAVASCRIPT", javascript_audit), ("URL AUDIT", url_audit),
            ("FORMS/MODELS", forms_and_models), ("DATABASE", database_audit),
            ("SOURCE", source_audit), ("SECURITY", lambda value: security_audit(value, args.production)),
            ("STATIC", static_and_service_worker), ("IDOR", idor_audit),
        ):
            with report.guarded(area):
                function(report)
        if args.production:
            with report.guarded("PRODUCTION HTTP"):
                public_http(report, args.base_url)
            with report.guarded("SYSTEM READ ONLY"):
                system_read_only(report)
        else:
            report.section("READ-ONLY CRAWLER / DIAGNOSTICS", [
                "Authentifizierte Schreibdiagnosen werden ausschließlich von der Django-Test-Suite in einer isolierten Testdatenbank ausgeführt.",
                "MinifigureInventoryInteractionTests prüft 0→1/komplett, JSON, refresh_from_db-äquivalente Persistenz, Status und Set-Vollständigkeit.",
                "LabelStudioTests prüft alle vier Modi, Partials, Startpositionen, QR-Ziele, Auswahl und sichere Origin-Erzeugung.",
                "Production-Modus führt niemals POST/PUT/PATCH/DELETE aus.",
            ])
        report.add("PASS", "SAFETY", "Audit beendet; keine Migration, kein Import, kein Deployment und keine E-Mail ausgelöst.")
    except Exception:
        report.add("CRITICAL", "BOOTSTRAP", "Django/Audit konnte nicht vollständig initialisiert werden.", traceback.format_exc())
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.render(), encoding="utf-8")
        if args.verbose:
            print(f"Bericht: {output}")
    return 2 if any(item.severity in {"CRITICAL", "ERROR"} for item in report.findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
