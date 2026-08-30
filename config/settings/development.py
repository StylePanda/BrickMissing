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
LEGAL_OPERATOR_NAME = os.getenv("LEGAL_OPERATOR_NAME", "[Betreibername vor Veröffentlichung eintragen]")  # noqa: F405,E501
LEGAL_OPERATOR_ADDRESS = os.getenv("LEGAL_OPERATOR_ADDRESS", "[Geografische Anschrift vor Veröffentlichung eintragen]")  # noqa: F405,E501
LEGAL_OPERATOR_CITY = os.getenv("LEGAL_OPERATOR_CITY", "[Wohnort vor Veröffentlichung eintragen]")  # noqa: F405,E501
LEGAL_OPERATOR_EMAIL = os.getenv("LEGAL_OPERATOR_EMAIL", "betreiber@example.invalid")  # noqa: F405
