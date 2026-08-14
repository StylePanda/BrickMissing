from __future__ import annotations

import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Required production environment variable {name} is missing")
    return value


DEBUG = False
TEST_RUNNER = "config.test_runner.ProductionSettingsDiscoverRunner"
SECRET_KEY = required("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must contain at least 50 characters")
BACKUP_ENCRYPTION_KEY = required("BACKUP_ENCRYPTION_KEY")
TOTP_ENCRYPTION_KEY = required("TOTP_ENCRYPTION_KEY")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")  # noqa: F405
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")  # noqa: F405
PUBLIC_URL = required("DJANGO_PUBLIC_URL").rstrip("/")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must not be empty in production")
public = urlsplit(PUBLIC_URL)
if public.scheme != "https" or not public.hostname or public.hostname not in ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_PUBLIC_URL must be HTTPS and use an allowed host")
if PUBLIC_URL not in CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured("DJANGO_PUBLIC_URL must be a trusted CSRF origin")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "HOST": required("DB_HOST"),
        "PORT": required("DB_PORT"),
        "NAME": required("DB_NAME"),
        "USER": required("DB_USER"),
        "PASSWORD": required("DB_PASSWORD"),
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"},
    }
}

if os.getenv("LEGACY_DB_NAME", "").strip():
    DATABASES["legacy_v7"] = {
        "ENGINE": "django.db.backends.mysql",
        "HOST": required("LEGACY_DB_HOST"),
        "PORT": required("LEGACY_DB_PORT"),
        "NAME": required("LEGACY_DB_NAME"),
        "USER": required("LEGACY_DB_USER"),
        "PASSWORD": required("LEGACY_DB_PASSWORD"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"charset": "utf8mb4", "init_command": "SET SESSION TRANSACTION READ ONLY"},
    }

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)  # noqa: F405
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)  # noqa: F405
