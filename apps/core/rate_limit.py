from django.core.cache import cache

from .client_ip import client_ip


def limited(request, scope, limit, seconds, *, per_user=False):
    identity = (
        f"user:{request.user.pk}"
        if per_user and request.user.is_authenticated
        else f"ip:{client_ip(request)}"
    )
    key = f"rate:{scope}:{identity}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, seconds)
        count = 1
    return count > limit
