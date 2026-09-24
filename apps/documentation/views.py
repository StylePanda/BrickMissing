from pathlib import Path

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from .pages import PAGES, PAGES_BY_SLUG
from .rendering import render_document


def document_root() -> Path:
    return Path(settings.BASE_DIR) / "docs"


def documentation_page(request, slug):
    page = PAGES_BY_SLUG.get(slug)
    if page is None:
        raise Http404("Dokumentationsseite nicht gefunden.")
    try:
        root = document_root().resolve(strict=True)
        source = (root / page.source).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise Http404("Dokumentationsseite nicht gefunden.")
        markdown = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise Http404("Dokumentationsseite nicht gefunden.") from exc

    navigation = [
        {
            "title": title,
            "pages": [
                {"title": item.title, "url": reverse(f"documentation:{item.route_name}"),
                 "active": item.slug == page.slug}
                for item in PAGES if is_member(item)
            ],
        }
        for title, is_member in (
            ("Benutzer", lambda item: not item.slug.startswith("developer")),
            ("Entwickler", lambda item: item.slug.startswith("developer")),
        )
    ]
    response = render(request, "documentation/page.html", {
        "page": page,
        "navigation": navigation,
        "document_html": mark_safe(render_document(page.source, markdown)),  # noqa: S308 - raw HTML is disabled and every URL is constrained by render_document
    })
    response["Cache-Control"] = "public, max-age=300"
    return response
