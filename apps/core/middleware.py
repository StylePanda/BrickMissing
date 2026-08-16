import uuid

from django.core.cache import cache
from django.http import JsonResponse

from .client_ip import client_ip
from .logging import request_id_var


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4()
        request.client_ip = client_ip(request)
        token = request_id_var.set(str(request.request_id))
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = str(request.request_id)
            return response
        finally:
            request_id_var.reset(token)


class MaintenanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if cache.get("maintenance_mode") and request.path != "/health/":
            return JsonResponse({"status": "maintenance"}, status=503)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    CSP = "; ".join(
        [
            "default-src 'self'",
            "base-uri 'self'",
            "connect-src 'self'",
            "font-src 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "img-src 'self' data: https:",
            "object-src 'none'",
            "script-src 'self'",
            "style-src 'self'",
            "upgrade-insecure-requests",
        ]
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        private_prefixes = ("/admin/", "/konto/", "/daten/", "/system/")
        if request.user.is_authenticated or request.path.startswith(private_prefixes):
            response.setdefault("X-Robots-Tag", "noindex, nofollow")
        return response


class AccountSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated and request.session.session_key:
            from apps.accounts.models import AccountSession

            AccountSession.objects.update_or_create(
                session_key=request.session.session_key,
                defaults={
                    "user": request.user,
                    "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
                },
            )
        return response
