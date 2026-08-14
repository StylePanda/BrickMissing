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
        return response
