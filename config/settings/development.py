from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "brickmissing-v8-local-development-key")  # noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "var" / "development.sqlite3",  # noqa: F405
        "OPTIONS": {"timeout": 20},
    }
}
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")  # noqa: F405
