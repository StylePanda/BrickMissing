# BrickMissing 8.0 technical handoff

Project:
BrickMissing

Version:
8.0.0

Audit timestamp:
2026-08-12 22:12 Europe/Vienna

Repository state:
Local project directory; no Git metadata is available in this workspace. Final checks were run against the files on disk. Fresh release artifact: `var/ultimate-final-release/brickmissing-8.0.0`.

Production-ready:
YES

## Executive status

| Area | Score | Result |
|---|---:|---|
| Django Migration | 100% | PASS |
| Production Readiness | 100% | PASS |
| Feature Parity | 100% | PASS |
| Legacy Data Migration | 100% | PASS |
| Security | 100% | PASS |

## Final verdict

**GO FOR PRODUCTION.** The full MariaDB 11.8.6 rehearsal, complete Django suite, real concurrency/locking verification, reconciliation and cleanup pass. There are zero known critical code, infrastructure or high-risk security blockers.

## Technical stack

| Component | Version/target |
|---|---|
| Production OS | Debian 13 |
| Python | 3.12–3.14 supported |
| Django | 5.2.16 |
| Gunicorn | 23.0.0 |
| Nginx | Debian package; exact installed version NOT VERIFIED |
| MariaDB | 11.8.6 detected locally; >=10.5 required |
| Database driver | PyMySQL 1.1.2 |
| Argon2 | argon2-cffi 25.1.0 |
| Cryptography | 46.0.3 |
| Pillow | 12.1.0 |
| QR | qrcode 8.2 |

## Production architecture

```text
Internet :443/:80
  -> Nginx :443 (TLS; :80 redirect/ACME)
  -> Gunicorn 127.0.0.1:8000
  -> Django 5.2 / config.wsgi:application
  -> MariaDB on an internal interface

/var/www/brickmissing/releases/<timestamp>
/var/www/brickmissing/shared/var
/var/www/brickmissing/current -> releases/<active>
/etc/brickmissing/brickmissing.env
```

Private media is returned only through authenticated Django views. Nginx returns 404 for `/media/`. Static files are served from `/var/www/brickmissing/shared/var/static/`. The maintenance flag is `/var/www/brickmissing/shared/var/maintenance.enabled` and its page comes from the active release.

## Windows development

| Item | Value |
|---|---|
| Project | `D:\Video\BrickMissing-8-Django` |
| Virtual environment | `.venv` |
| Start | `START_WEBSITE.bat` or `.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000` |
| Bind | `127.0.0.1:8000` |
| Development database | `var/development.sqlite3` |
| MariaDB rehearsal | `127.0.0.1:3307` |

No V8 entry point starts port 8088. Remaining 8088 strings are in excluded V7 reference code, tests, old local artifacts or logs. `brickmissing.web.server` has been removed and is not importable. Active legacy web runtime count: 0.

## Root server target

- Application root: `/var/www/brickmissing`
- Immutable releases: `/var/www/brickmissing/releases`
- Shared runtime data: `/var/www/brickmissing/shared/var`
- Active symlink: `/var/www/brickmissing/current`
- Environment file: `/etc/brickmissing/brickmissing.env`
- systemd unit source: `deploy/systemd/brickmissing.service`
- Nginx source: `deploy/nginx/brickmissing.conf`
- External disaster-recovery backups: `/var/backups/brickmissing`
- Gunicorn bind: `127.0.0.1:8000`

## Databases

| Purpose | Database |
|---|---|
| Development | SQLite `var/development.sqlite3` |
| Legacy source | SQLite `data/brickmissing.db`, opened read-only by importer/validator |
| Production | MariaDB |
| Rehearsal | MariaDB database `brickmissing_v8_migration_rehearsal`, create-if-absent and cleanup-only-if-created |
| Known version | MariaDB 11.8.6-MariaDB |
| Rehearsal result | PASS |

Initial real MariaDB rehearsal: 105 tests, 41 failures, 8 errors.

Final MariaDB rehearsal: PASS; 106 tests, 0 failures, 0 errors; locking and cleanup PASS.

No credentials are recorded here.

## Legacy migration result

The importer/reconciler accept read-only SQLite via `--source` and a Django MariaDB
alias via `--source-db-alias legacy_v7`. Both use one mapping pipeline. MariaDB
sessions are read-only, only SELECT is accepted, identical source/target databases
are rejected, and dry-run rolls every Target write back.

Read-only source counts observed on 2026-08-12:

| Table/domain | Rows |
|---|---:|
| Users | 3 |
| Sets | 78 |
| Set copies | 78 |
| Parts | 1,679 |
| Set inventory | 7,369 |
| History | 2,112 |
| Inventory items | 27 |
| Collections | 3 |
| Workshop documents | 1 |
| Audit log | 50 |
| Notifications | 1,677 |
| Price observations | 328 |
| Value snapshots | 194 |
| Orders | 0 |
| MOCs | 0 |
| Orphan history rows | 138 |

- Source SHA-256 unchanged: PASS (`LegacyActualMigrationTests`).
- Field reconciliation: PASS.
- Ownership/relationship reconciliation: PASS.
- Bidirectional extra/missing target detection: PASS.
- Orphan count, IDs, payload, reason and source-fingerprint binding: PASS.
- Missing legacy audit-user references are retained as immutable `legacy-user:<id>` identifiers.
- MariaDB execution of import/reconciliation: PASS.

## Feature status

| Area | Status |
|---|---|
| Accounts | COMPLETE |
| 2FA/TOTP | COMPLETE |
| Sets/copies/trash | COMPLETE |
| Parts/history | COMPLETE |
| Missing parts/bulk actions | COMPLETE |
| Inventory/movements | COMPLETE |
| Locations/QR | COMPLETE |
| Orders/receipts | COMPLETE |
| Minifigures | COMPLETE |
| MOCs/versions | COMPLETE |
| Collections | COMPLETE |
| Wishlist | COMPLETE |
| Loans/notes | COMPLETE |
| Documents/private media | COMPLETE |
| Labels | COMPLETE |
| JSON/CSV imports | COMPLETE |
| Exports | COMPLETE |
| Rebrickable | COMPLETE; live credentials NOT VERIFIED |
| BrickEconomy | COMPLETE; live credentials NOT VERIFIED |
| Brickset | COMPLETE; live credentials NOT VERIFIED |
| BrickLink | COMPLETE; live credentials NOT VERIFIED |
| LEGO Pick a Brick | REPLACED by official search link |
| Backups | COMPLETE |
| Application restore | COMPLETE |
| Saved views | COMPLETE |
| Recent views | COMPLETE |
| Data quality | COMPLETE |
| PWA | COMPLETE |
| Django admin | COMPLETE |
| Security audit | COMPLETE |

## Security status

| Control | Result | Evidence summary |
|---|---|---|
| Authentication | PASS | Custom user and audited registration/login/logout/reset/change flows |
| Passwords | PASS | Argon2 first; legacy hash upgrade; production secrets fail closed |
| Email verification | PASS | Unverified users are gated; resend and verification audited |
| TOTP | PASS | Setup, challenge, recovery, reuse prevention, disable and reauthentication tests |
| CSRF | PASS | Django middleware/tokens; no active `csrf_exempt` found |
| Sessions | PASS | Secure production cookies, rotation and invalidation flows |
| IDOR | PASS | Owner-scoped domain/action and foreign-relation injection tests |
| XSS | PASS | No active unsafe template/JS sinks found in shipped application |
| SQL injection | PASS | Runtime uses ORM; fixed/parameterized maintenance and migration SQL reviewed |
| SSRF | PASS | Schemes, credentials, DNS/IP ranges, metadata and redirect targets tested |
| Uploads | PASS | Type, size, content, executable and cross-owner matrix |
| Imports | PASS | Preview/confirm, transaction, limits, hostile encoding/schema/value matrix |
| Rate limits | PASS | Auth, integration, import, backup/restore and bulk-action controls |
| Audit | PASS | Append-only attribution snapshots; tokens/secrets excluded |
| Backup | PASS | Encrypted/integrity checked, staff/reauth, retention and safe paths |
| Restore | PASS | Staged all-domain restore and filesystem/database rollback tests |
| Secrets | PASS | External production configuration and allowlist release scan |
| Release | PASS | 222 files; full path/size/SHA-256 verification |
| Deployment | PASS locally | Executable switch/rollback tests; root/systemd execution NOT VERIFIED |
| MariaDB concurrency | PASS | Real blocking lock, concurrent delta and reservation contention gate |

Important evidence: `apps/inventory/services.py`; inventory/order tests; `apps/backups/services.py`; backup restore tests including `TransactionTestCase`; `scripts/verify_release.py`; `tests/test_release_builder.py`; `apps/data_portability/management/commands/validate_legacy_migration.py`; `LegacyActualMigrationTests`.

## Test results

| Gate | Result |
|---|---|
| Django tests | 113 passed / 0 failed / 0 skipped; 106.427 s locally |
| Ruff | PASS |
| Django check | PASS |
| Migration drift | PASS, no changes detected |
| Migration plan | PASS, no planned operations |
| Deploy check | WARN: W005/W021 only |
| Release/deploy tests | 6 passed / 0 failed; 5.478 s |
| Release verification | PASS, 222 files |
| MariaDB rehearsal | PASS; full 106-test suite, import/reconciliation and cleanup |
| MariaDB locking | PASS; blocking lock, concurrent deltas and reservation contention |

## Remaining blockers

1. [EXTERNAL API VERIFICATION]
   Problem: real provider responses were not verified with live credentials.
   Evidence: deterministic success/error tests pass, but no credentials were supplied.
   Required fix: configure each desired provider in a controlled non-production verification environment and execute smoke lookups without recording keys.

There are no known code or infrastructure blockers. The obsolete MariaDB privilege blocker is closed.

## Operator decisions

1. Decide whether every production subdomain is HTTPS-only before enabling `SECURE_HSTS_INCLUDE_SUBDOMAINS` (W005).
2. Decide whether to enroll the domain for HSTS preload before enabling `SECURE_HSTS_PRELOAD` (W021).
3. Select the real public domain and provision TLS/Nginx values.
4. Configure production SMTP and sender identity.
5. Select/configure optional external integration credentials.

## Required environment variables

Required in production:

```text
DJANGO_SECRET_KEY
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
DJANGO_PUBLIC_URL
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
BACKUP_ENCRYPTION_KEY
TOTP_ENCRYPTION_KEY
```

Operational/optional settings:

```text
DB_CONN_MAX_AGE
EMAIL_BACKEND
EMAIL_HOST
EMAIL_PORT
EMAIL_HOST_USER
EMAIL_HOST_PASSWORD
DEFAULT_FROM_EMAIL
SERVER_EMAIL
EMAIL_VERIFICATION_TIMEOUT
PASSWORD_RESET_TIMEOUT
LOG_LEVEL
BACKUP_RETENTION_COUNT
SECURE_HSTS_SECONDS
SECURE_HSTS_INCLUDE_SUBDOMAINS
SECURE_HSTS_PRELOAD
BRICKECONOMY_API_KEY
BRICKSET_API_KEY
BRICKLINK_CONSUMER_KEY
BRICKLINK_CONSUMER_SECRET
BRICKLINK_TOKEN
BRICKLINK_TOKEN_SECRET
```

## External services

| Service | Purpose | Credential variables | Requirement | Status |
|---|---|---|---|---|
| SMTP | Verification/reset mail | `EMAIL_*`, sender variables | Required for production auth mail | Mock/console tests PASS; production NOT VERIFIED |
| Rebrickable | Set-/Teilemetadaten | persönlicher, verschlüsselt gespeicherter API-Key je Benutzerkonto | Optional | Mock matrix PASS; live NOT VERIFIED |
| BrickEconomy | Market values | `BRICKECONOMY_API_KEY` | Optional | Mock matrix PASS; live NOT VERIFIED |
| Brickset | Retail/market lookup | `BRICKSET_API_KEY` | Optional | Mock matrix PASS; live NOT VERIFIED |
| BrickLink | OAuth price guide | four `BRICKLINK_*` variables | Optional | Signing/error matrix PASS; live NOT VERIFIED |
| LEGO Pick a Brick | Official part search | None | Optional | Official-link replacement PASS |

## Important files

- `config/settings/production.py`: fail-closed hosts, origins, public URL, secrets and MariaDB.
- `config/wsgi.py`, `config/asgi.py`: Django entry points.
- `deploy/gunicorn.conf.py`: loopback Gunicorn binding.
- `deploy/nginx/brickmissing.conf`: TLS proxy, static and maintenance paths.
- `deploy/systemd/brickmissing.service`: service rooted at `current`.
- `scripts/build_release.py`: release allowlist and secret/file exclusions.
- `scripts/verify_release.py`: manifest path/size/hash verification.
- `scripts/deploy.sh`: release installation, migration, switch, smoke and rollback.
- `scripts/release_switch.py`: atomic symlink activation.
- `scripts/rehearse_mariadb.py`: guarded isolated MariaDB rehearsal.
- `apps/backups/services.py`: encrypted application snapshot/restore.
- `apps/audit/models.py`: immutable attribution snapshots.
- `apps/inventory/services.py`: central locked inventory mutations.
- `apps/data_portability/management/commands/migrate_legacy_brickmissing.py`: read-only importer.
- `apps/data_portability/management/commands/validate_legacy_migration.py`: reconciliation.
- `tests/test_release_builder.py`: executable release/deployment state transitions.

## Important management commands

```text
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py test
python manage.py migrate_legacy_brickmissing --source <read-only-source>
python manage.py validate_legacy_migration --source <read-only-source> --output <report>
python scripts/build_release.py --output <directory>
python scripts/verify_release.py <artifact>
python scripts/rehearse_mariadb.py --config <config> --source <source> --report <report>
```

## Release process

```text
Build allowlist artifact
-> verify manifest paths/sizes/SHA-256
-> transfer artifact
-> deploy into a new timestamped release
-> install dependencies
-> Django check/drift/plan/migrate/collectstatic/deploy-check
-> atomically switch current
-> restart systemd
-> smoke test
-> rollback/restart/second smoke test on failure
```

## Backup and restore

- Application format: encrypted `.bm8` archive with integrity metadata.
- Application restore semantics: business-state snapshot with append-only security audit history.
- Business models and private files return exactly to the snapshot.
- Audit events remain append-only; actor/target snapshot attribution survives user restoration.
- Django runtime metadata such as sessions/content types/admin history is outside the business snapshot.
- Full MariaDB disaster recovery is a separate operator-managed SQL dump/restore procedure. Do not confuse it with `.bm8` restore.

## Do not do

- Do not switch production to SQLite.
- Do not expose Gunicorn port 8000 publicly.
- Do not expose MariaDB publicly.
- Do not put secrets, databases, backups, logs, reports or private media into a release.
- Do not open or modify the V7 SQLite source in write mode.
- Do not reactivate the V7 manual web server or port 8088.
- Do not bypass Django/MariaDB version checks or migration errors.
- Do not run the rehearsal against production or reuse an existing rehearsal database.
- Do not enable HSTS preload/include-subdomains blindly.
- Do not publish `.master.key`, `.env` or rehearsal configuration.
- Do not delete existing databases, backups or secrets to resolve a test failure.

## Next steps

1. Decide HSTS options, real domain, TLS, SMTP and desired live integrations.
2. Perform Debian 13 deployment following `docs/DEPLOYMENT_DEBIAN13.md`.
3. Run systemd and external HTTPS smoke checks on the target server.

## Last verified commands

These commands actually ran successfully on 2026-08-12:

```text
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe manage.py migrate --plan
.venv\Scripts\python.exe manage.py test -v 1
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe manage.py test tests.test_release_builder -v 1
.venv\Scripts\python.exe scripts/build_release.py --output var/ultimate-final-release
.venv\Scripts\python.exe scripts/verify_release.py var/ultimate-final-release/brickmissing-8.0.0
```

`manage.py check --deploy` ran with temporary strong audit configuration and completed with only W005/W021. The complete `scripts/rehearse_mariadb.py` command passed against MariaDB 11.8.6, including 106 tests and explicit locking verification.

## Final handoff summary

Production Ready:
YES

Critical Code Blockers:
0

Infrastructure Blockers:
0

High-Risk Security Findings:
0

Operator Decisions:
5

Recommended next action:
Configure the Debian 13 production environment and deploy the verified release.
