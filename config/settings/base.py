from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_optional_positive_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-not-for-production")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.audit",
    "apps.core",
    "apps.catalog",
    "apps.inventory",
    "apps.orders",
    "apps.organizer",
    "apps.media_library",
    "apps.data_portability",
    "apps.backups",
    "apps.integrations",
    "apps.legal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "apps.core.middleware.MaintenanceMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.AccountSessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "builtins": ["apps.core.templatetags.privacy"],
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.application_meta",
            ],
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "apps.accounts.hashers.LegacyBrickMissingPBKDF2Hasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

LANGUAGE_CODE = "de"
LANGUAGES = [("de", "Deutsch"), ("en", "English")]
TIME_ZONE = "Europe/Vienna"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "var" / "static"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "var" / "media"
# PrivateDocument uses Django's FileField storage. The application restore must
# stage the exact same root; there is deliberately no second private-file tree.
PRIVATE_MEDIA_ROOT = MEDIA_ROOT
BACKUP_ROOT = BASE_DIR / "var" / "backups"
BACKUP_ENCRYPTION_KEY = os.getenv("BACKUP_ENCRYPTION_KEY", SECRET_KEY)
TOTP_ENCRYPTION_KEY = os.getenv("TOTP_ENCRYPTION_KEY", SECRET_KEY)
BACKUP_RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "10"))
PENDING_EMAIL_RETENTION_DAYS = env_optional_positive_int("PENDING_EMAIL_RETENTION_DAYS")
RECOVERY_CODE_RETENTION_DAYS = env_optional_positive_int("RECOVERY_CODE_RETENTION_DAYS")
IMPORT_BATCH_RETENTION_DAYS = env_optional_positive_int("IMPORT_BATCH_RETENTION_DAYS")
LEGAL_OPERATOR_NAME = os.getenv("LEGAL_OPERATOR_NAME", "").strip()
LEGAL_OPERATOR_ADDRESS = os.getenv("LEGAL_OPERATOR_ADDRESS", "").strip()
LEGAL_OPERATOR_EMAIL = os.getenv("LEGAL_OPERATOR_EMAIL", "").strip()
LEGAL_OPERATOR_COUNTRY = os.getenv("LEGAL_OPERATOR_COUNTRY", "Österreich").strip()
LEGAL_COMPANY_NAME = os.getenv("LEGAL_COMPANY_NAME", "").strip()
LEGAL_COMPANY_REGISTER_NUMBER = os.getenv("LEGAL_COMPANY_REGISTER_NUMBER", "").strip()
LEGAL_COMPANY_REGISTER_COURT = os.getenv("LEGAL_COMPANY_REGISTER_COURT", "").strip()
LEGAL_VAT_ID = os.getenv("LEGAL_VAT_ID", "").strip()
LEGAL_AUTHORITY = os.getenv("LEGAL_AUTHORITY", "").strip()
LEGAL_CHAMBER = os.getenv("LEGAL_CHAMBER", "").strip()
LEGAL_PROFESSION = os.getenv("LEGAL_PROFESSION", "").strip()
LEGAL_MEDIA_OWNER = os.getenv("LEGAL_MEDIA_OWNER", "").strip()
BRICKECONOMY_API_KEY = os.getenv("BRICKECONOMY_API_KEY", "")
BRICKSET_API_KEY = os.getenv("BRICKSET_API_KEY", "")
BRICKLINK_CONSUMER_KEY = os.getenv("BRICKLINK_CONSUMER_KEY", "")
BRICKLINK_CONSUMER_SECRET = os.getenv("BRICKLINK_CONSUMER_SECRET", "")
BRICKLINK_TOKEN = os.getenv("BRICKLINK_TOKEN", "")
BRICKLINK_TOKEN_SECRET = os.getenv("BRICKLINK_TOKEN_SECRET", "")
IMAGE_PROXY_ALLOWED_HOSTS = env_list("IMAGE_PROXY_ALLOWED_HOSTS", "rebrickable.com,brickset.com,lego.com")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "BrickMissing <noreply@localhost>")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
PASSWORD_RESET_TIMEOUT = int(os.getenv("PASSWORD_RESET_TIMEOUT", "3600"))
EMAIL_VERIFICATION_TIMEOUT = int(os.getenv("EMAIL_VERIFICATION_TIMEOUT", "86400"))

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "brickmissing-v8",
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} request_id={request_id} {message}",
            "style": "{",
        }
    },
    "filters": {"request_id": {"()": "apps.core.logging.RequestIDFilter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}
