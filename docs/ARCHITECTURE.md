# BrickMissing 8.0 architecture

Immutable releases use `/var/www/brickmissing/releases/<timestamp>`, shared state uses `/var/www/brickmissing/shared`, and `current` switches atomically after verification. systemd uses `current`; Nginx paths match active/shared state. Failed smoke checks restore, restart and recheck the prior release.

Production:

```text
HTTPS client → Nginx :443 → Gunicorn 127.0.0.1:8000
             → config.wsgi → Django apps → MariaDB
```

Private uploads and encrypted application backups are delivered only through
authenticated/staff Django views. Static files may be served by Nginx. The PWA
service worker caches static shell assets only.

Development launchers (`START_WEBSITE.bat`, root `server.py`, and
`python -m brickmissing`) all invoke Django at `127.0.0.1:8000` with development
settings. Production is fail-closed and requires MariaDB, host, CSRF and three
independent cryptographic secrets from the environment.

The `brickmissing/` and `frontend/` trees are inert V7 migration references.
They are absent from the Django import graph and have no active HTTP entry point.
