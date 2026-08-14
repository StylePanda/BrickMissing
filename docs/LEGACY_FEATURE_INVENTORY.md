# BrickMissing 7 legacy feature inventory — final disposition

Ultimate re-audit: every applicable feature is COMPLETE or REPLACED. The manual handler was removed and `brickmissing.web.server` is not importable; reference code is excluded from releases. Missing-parts bulk operations, complete label geometry, saved-view lifecycle, recent resources, price-source UI and Pick a Brick UI are tested. Fragile LEGO scraping is REPLACED; runtime/config/session tables are NOT APPLICABLE to business migration.

Status: 12 August 2026. `MIGRATED` means a Django ORM/view/service path exists;
`REPLACED` means Django provides the safer equivalent; `ARCHIVED` means the old
implementation is reference-only and unreachable from a V8 entry point.

| Area | V8 disposition |
|---|---|
| ThreadingHTTPServer, manual router, `/api/*` | ARCHIVED; `main()` exits, no package/start/batch entry |
| Windows start/setup/stop/diagnose | MIGRATED to Django on 127.0.0.1:8000 |
| auth, sessions, CSRF, password reset, verification | REPLACED by Django; unverified login blocked |
| TOTP, QR setup, challenge, recovery, disable | MIGRATED with encrypted secret and hashed one-use codes |
| users and permissions | MIGRATED to custom User, Django admin and ownership querysets |
| sets, copies, details, parts, history, trash | MIGRATED |
| set inventory Soll/Ist and bulk completeness/missing actions | MIGRATED |
| search, filters, sorting, pagination, global Ctrl+K search | MIGRATED |
| inventory, reservations, movements, locations and QR | MIGRATED |
| orders, order items and transactional receipts | MIGRATED |
| minifigures and component parts | MIGRATED |
| MOCs, parts, versions/data migration | MIGRATED |
| collections/members, wishlist, loans, notes | MIGRATED |
| labels/templates | MIGRATED to owned label-template records and QR endpoints |
| uploads/documents | MIGRATED to private authenticated file delivery with validation |
| JSON and CSV/BrickLink import/export | MIGRATED; atomic, limited, owned, CSV-injection safe |
| Rebrickable set/parts data | MIGRATED; environment key and audited POST sync |
| pricing | MIGRATED to environment-configured BrickEconomy plus typed price history |
| image proxy/cache boundary | REPLACED by authenticated allowlisted proxy, public-IP DNS check, no redirects |
| SMTP test | MIGRATED to Django backend, staff-only UI and command |
| notifications/value snapshots | MIGRATED and imported |
| dashboard/statistics | MIGRATED using bounded ORM aggregates |
| PWA/offline | MIGRATED; only static shell cached, private pages never cached |
| encrypted backup, retention, integrity, restore | MIGRATED; staff, reauthentication, safety backup and maintenance gate |
| legacy settings/secrets/runtime rows | ARCHIVED, deliberately not activated |

The old `frontend/` and `brickmissing/` implementation remain solely as an
offline migration/reference corpus. No V8 URL, launcher, script metadata,
systemd unit, Nginx route, or batch file serves them.
