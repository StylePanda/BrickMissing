from django.conf import settings
from django.shortcuts import render

LEGAL_SETTING_NAMES = (
    "LEGAL_OPERATOR_NAME",
    "LEGAL_OPERATOR_ADDRESS",
    "LEGAL_OPERATOR_EMAIL",
    "LEGAL_OPERATOR_COUNTRY",
    "LEGAL_COMPANY_NAME",
    "LEGAL_COMPANY_REGISTER_NUMBER",
    "LEGAL_COMPANY_REGISTER_COURT",
    "LEGAL_VAT_ID",
    "LEGAL_AUTHORITY",
    "LEGAL_CHAMBER",
    "LEGAL_PROFESSION",
    "LEGAL_MEDIA_OWNER",
)


def legal_context():
    return {name.removeprefix("LEGAL_").lower(): getattr(settings, name, "") for name in LEGAL_SETTING_NAMES}


def imprint(request):
    return render(request, "legal/imprint.html", legal_context())


def privacy(request):
    context = legal_context()
    context.update(
        {
            "session_cookie_age": settings.SESSION_COOKIE_AGE,
            "password_reset_timeout": settings.PASSWORD_RESET_TIMEOUT,
            "email_verification_timeout": settings.EMAIL_VERIFICATION_TIMEOUT,
            "backup_retention_count": settings.BACKUP_RETENTION_COUNT,
            "pending_email_retention_days": settings.PENDING_EMAIL_RETENTION_DAYS,
            "recovery_code_retention_days": settings.RECOVERY_CODE_RETENTION_DAYS,
            "import_batch_retention_days": settings.IMPORT_BATCH_RETENTION_DAYS,
            "audit_security_retention_days": settings.AUDIT_SECURITY_RETENTION_DAYS,
            "audit_activity_retention_days": settings.AUDIT_ACTIVITY_RETENTION_DAYS,
            "notification_retention_days": settings.NOTIFICATION_RETENTION_DAYS,
            "soft_delete_retention_days": settings.SOFT_DELETE_RETENTION_DAYS,
            "private_document_deleted_retention_days": (
                settings.PRIVATE_DOCUMENT_DELETED_RETENTION_DAYS
            ),
            "legacy_data_retention_days": settings.LEGACY_DATA_RETENTION_DAYS,
        }
    )
    return render(request, "legal/privacy.html", context)
