from __future__ import annotations

from collections.abc import Mapping, Sequence

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def public_base_url(request=None) -> str:
    configured = getattr(settings, "PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return "http://localhost:8000"


def absolute_public_url(path: str, request=None) -> str:
    return f"{public_base_url(request)}/{path.lstrip('/')}"


def email_context(context: Mapping | None = None, *, request=None) -> dict:
    base_url = public_base_url(request)
    return {
        **dict(context or {}),
        "public_url": base_url,
        "privacy_url": f"{base_url}/datenschutz/",
        "imprint_url": f"{base_url}/impressum/",
    }


def send_templated_email(
    *,
    to: Sequence[str],
    subject: str,
    template_name: str,
    context: Mapping | None = None,
    request=None,
    fail_silently: bool = False,
) -> int:
    rendered_context = email_context(context, request=request)
    text_body = render_to_string(f"emails/{template_name}.txt", rendered_context)
    html_body = render_to_string(f"emails/{template_name}.html", rendered_context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(to),
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=fail_silently)
