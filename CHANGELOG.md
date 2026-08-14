# Changelog

## 8.0.0 — 12 August 2026

- Added one shared read-only Legacy source abstraction for SQLite and Django MariaDB/MySQL aliases.
- Added source/target identity protection, source fingerprints and alias reconciliation.
- Hardened V7 password adoption to supported PBKDF2; unknown hashes require reset.

- Completed full MariaDB 11.8.6 rehearsal: migrations, Legacy reconciliation, 106 tests, real locking/concurrency and cleanup PASS.
- Fixed production-settings test transport without weakening production HTTPS enforcement.
- Moved destructive restore tests to real transaction boundaries for deterministic MariaDB isolation.
- Removed rehearsal `--keepdb` and added explicit blocking-lock, concurrent-delta and reservation-contention verification.

- Final audit: 105 tests and all local Django/Ruff/drift gates pass; fresh 216-file release verifies.
- Added executable atomic rollback and complete manifest verification.
- Completed all-domain restore, actual commit-failure rollback and immutable audit attribution.
- Completed reconciliation and integration/labels/saved views/data quality/IDOR/upload/import/SSRF matrices.
- MariaDB 11.8.6 is supported and the complete rehearsal now passes.

- Added atomic timestamped releases, a single `current` systemd target and automatic smoke-test rollback.
- Defined and tested business-state snapshot restore with append-only security audit history.
- Replaced count-only validation with normalized field, ownership, relationship and orphan-payload reconciliation.
- Added Brickset and BrickLink clients; replaced fragile Pick a Brick scraping with an official LEGO search link.
- Expanded label layouts, data-quality checks, saved-view CRUD, resend auditing and hostile upload/import tests.
- Added a guarded MariaDB rehearsal that only deletes databases it created.
- Production sign-off completed after the supported MariaDB rehearsal passed.

- Completed the Django 5.2/MariaDB rebuild and disabled all V7 web entry points.
- Migrated accounts, verified login, rate limits and complete TOTP/recovery flow.
- Added full owned domain models/UI for sets, inventory, orders, organizers and media.
- Added transactional receipts, QR, global search, dashboard and safe PWA offline shell.
- Added JSON/CSV/Rebrickable migration paths, price history and SSRF-safe image proxy.
- Added encrypted integrity-checked backups, retention, staff restore and email tests.
- Extended the read-only legacy importer to every populated business table with a
  row-count matrix and explicit handling for obsolete runtime/config rows.
- Replaced Windows V7 launchers with Django 8 launch/setup/stop/diagnose scripts.
- Expanded security/regression coverage; full test, Ruff and Django checks pass.
