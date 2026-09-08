from django.conf import settings


def application_meta(_request):
    return {
        "application_name": "BrickMissing",
        "application_version": settings.BRICKMISSING_VERSION,
    }
