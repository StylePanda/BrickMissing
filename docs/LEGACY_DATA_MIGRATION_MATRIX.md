# BrickMissing 8.0 final legacy data migration matrix

Audit: 2026-08-12. Score: **100% / PASS**.

The full MariaDB 11.8.6 rehearsal passes migrations, read-only Legacy import, field reconciliation, ownership/foreign-key reconciliation, NULL/empty/zero/False handling, Decimal/timestamps, bidirectional extra targets, source-bound orphan validation, the complete test suite, real locking tests, unchanged source SHA-256 and cleanup.

Observed source counts: 3 users, 78 sets, 78 copies, 1,679 parts, 7,369 set-inventory rows, 2,112 history rows, 1,677 notifications, 328 prices, 194 value snapshots and 138 orphan history rows.
