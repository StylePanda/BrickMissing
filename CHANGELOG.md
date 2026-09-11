# Changelog

## 8.4.1 — 12 September 2026

### Fixed

- Fixed text overflow and responsive wrapping in the missing-parts saved-view form.
- Restored stable checkbox and color-name alignment in the grouped color filter.
- Changed the cards-view indicator from a button-like pill to non-interactive status text.
- Prevented quantity and status action labels from being squeezed outside their buttons.
- Improved responsive spacing and grouping for missing-part allocation controls.
- No database migration or dependency change.

## 8.4.0 — 12 September 2026

### Added / Changed

- Added a new card-based missing-parts layout in the existing Midnight-Violet design.
- Restructured set and minifigure assignments into readable sub-cards while retaining their existing update endpoints.
- Added accessible visual inventory progress based only on authoritative grouped quantities.
- Modernized the filter, saved-view and result-summary areas.
- Improved responsive behavior from 320 px through wide desktop layouts.

### Fixed

- Reduced redundant and overloaded information in the missing-parts overview.
- No database migration or dependency change.

## 8.3.2 — 11 September 2026

- Fixed dashboard product images so their rendered boxes stay completely inside the image area instead of being clipped by the card wrapper.
- Fixed the present-versus-missing donut so no dark antialiasing gap appears between the two mathematically complementary segments.
- No database migration.

## 8.3.1 — 11 September 2026

- Fixed the dashboard to show only the three most recently created owner-scoped sets.
- Fixed dashboard set images so products remain fully visible without disruptive cropping.
- Renamed the **Farben** shortcut to the correct **Teile** label while retaining the existing parts route.
- Fixed the present-versus-missing donut so both segments represent their percentages mathematically, including small missing shares.
- No database migration.

## 8.3.0 — 10 September 2026

- Redesigned the overview as a responsive Midnight-Violet collection dashboard.
- Added compact owner-scoped collection metrics with authoritative present and missing quantities and percentages.
- Added an accessible present-versus-missing donut and the top five current shortages.
- Added recently created sets, central shortcuts and a top-theme overview.
- Prepared a CSS-only banner slot for future BrickMissing artwork without a missing asset request.
- Kept the existing quantity, reconciliation, export, filtering and size/form behavior unchanged; no database migration.

## 8.2.0 — 9 September 2026

- Added deterministic **Größe/Form** sorting for parts and missing parts in ascending and descending size order.
- Improved the workflow for physical LEGO collections organized by color by keeping similar part families together before ordering their parsed dimensions.
- Aligned the **Fehlende Farben** Set-list filter with the other controls through one shared field structure and correctly scoped nested disclosure margins.
- No database migration.

## 8.1.2 — 9 September 2026

- Fixed the **Fehlende Farben** set filter by resolving UI selections to exact stored colors through the central color rules.
- Made the visible missing-part group status follow authoritative required, owned and missing quantities, so **Erhalten** is never shown while a shortage remains.
- Prevented workflow status and quantity updates from creating new contradictory possession states.
- No database migration.

## 8.1.1 — 9 September 2026

- Hotfixed the release build so tooling can read the central version without initializing Django or database runtime dependencies.
- The release builder and verifier now work with a dependency-free system Python.
- No business data or database schema changes.

## 8.1.0 — 9 September 2026

- Added the Set-list filter **Fehlende Farben** with multi-select OR semantics.
- The filter uses the existing authoritative set/minifigure shortage allocations and central color grouping.
- Established the required MAJOR.MINOR.PATCH versioning rule and one central application version source.

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
