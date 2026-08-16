from urllib.parse import urlencode, urlsplit

from django import template
from django.urls import reverse

register = template.Library()


@register.filter
def proxied_image_url(value):
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return url
    return f"{reverse('integrations:image_proxy')}?{urlencode({'url': url})}"
