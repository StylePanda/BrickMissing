from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.audit.models import AuditEvent
from apps.core.client_ip import client_ip


def _request_fields(request):
    if request is None:
        return {}
    return {
        "remote_address": client_ip(request),
        "request_id": getattr(request, "request_id", None),
    }


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    AuditEvent.objects.create(
        actor=user, target_user=user, action="account.login_success", **_request_fields(request)
    )


@receiver(user_login_failed)
def audit_login_failure(sender, credentials, request, **kwargs):
    AuditEvent.objects.create(action="account.login_failed", **_request_fields(request))


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    AuditEvent.objects.create(
        actor=user, target_user=user, action="account.logout", **_request_fields(request)
    )
