# Tests und Prüfungen

Die Django-Tests liegen in `apps/*/tests.py`, zusätzlichen `test_*.py` sowie `tests/`. Sie prüfen unter anderem Ownership, Mengen, Status, CSV/JSON, Rebrickable, Accounts, Backups und Release-Werkzeuge. `apps/documentation/tests.py` prüft zusätzlich die freigegebenen Dokumentationsseiten, Links und Sicherheitsgrenzen. `tests/test_responsive_browser.py`, `tests/test_documentation_browser.py` und `scripts/responsive_ui_audit.mjs` decken Browser-/Responsive-Verhalten ab; dafür kann eine Browserumgebung nötig sein. Eine bestandene Django-Suite ersetzt keinen visuellen Browserdurchlauf.

Lokale Grundprüfung vom Repository-Root:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
ruff check .
git diff --check
```

Releaseprüfung:

```powershell
python scripts/build_release.py
python scripts/verify_release.py dist/brickmissing-8.6.0
python -S scripts/verify_release.py dist/brickmissing-8.6.0
```

`-S` unterbindet das Laden von `site` und prüft die beabsichtigte Unabhängigkeit der Release-Verifikation von Drittanbieterpaketen. Für Produktion kommen `manage.py check --deploy`, Migrationsplan, Smoke Test und ein MariaDB-Rehearsal unter passenden Umgebungsbedingungen hinzu. Reconciliation-Kommandos sind Datenpflegewerkzeuge und keine pauschalen Testschritte.
