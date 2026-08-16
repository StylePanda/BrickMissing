import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.email import absolute_public_url, send_templated_email

from .models import AccountSession, PendingEmailChange
from .tokens import email_verification_token


def send_verification_email(request, user) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    url = absolute_public_url(
        reverse("accounts:verify", kwargs={"uidb64": uid, "token": token}), request
    )
    send_templated_email(
        to=[user.email],
        subject="BrickMissing – E-Mail-Adresse bestätigen",
        template_name="verify_email",
        context={
            "username": user.username,
            "action_url": url,
            "expiry_seconds": settings.EMAIL_VERIFICATION_TIMEOUT,
        },
        request=request,
    )


def create_email_change(request, user, email):
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    timeout = getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", 86400)
    with transaction.atomic():
        PendingEmailChange.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        pending = PendingEmailChange.objects.create(
            user=user,
            email=email,
            token_digest=digest,
            expires_at=timezone.now() + timedelta(seconds=timeout),
        )
    url = absolute_public_url(
        reverse("accounts:confirm_email_change", args=[pending.pk, token]), request
    )
    send_templated_email(
        to=[email],
        subject="BrickMissing – Neue E-Mail-Adresse bestätigen",
        template_name="email_change",
        context={
            "username": user.username,
            "action_url": url,
            "expiry_seconds": timeout,
        },
        request=request,
    )
    return pending


def revoke_session(account_session):
    from django.contrib.sessions.models import Session

    Session.objects.filter(session_key=account_session.session_key).delete()
    account_session.delete()


def track_session(request, user):
    if not request.session.session_key:
        request.session.save()
    return AccountSession.objects.update_or_create(
        session_key=request.session.session_key,
        defaults={"user": user, "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255]},
    )[0]
