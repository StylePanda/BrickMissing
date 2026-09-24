"""Render repository-owned Markdown with HTML disabled and constrained links."""

from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from django.urls import reverse
from markdown_it import MarkdownIt

from .pages import PAGES_BY_SOURCE

MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


def _table_open(_tokens, _index, _options, _environment):
    return '<div class="docs-table-wrap" role="region" tabindex="0" aria-label="Tabelle"><table>'


def _table_close(_tokens, _index, _options, _environment):
    return "</table></div>"


MARKDOWN.renderer.rules["table_open"] = _table_open
MARKDOWN.renderer.rules["table_close"] = _table_close


def _doc_target(current_source: str, target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
            return target
        return "#"
    if not parsed.path:
        return f"#{parsed.fragment}" if parsed.fragment else "#"
    path = unquote(parsed.path)
    if path.startswith(("/", "\\")) or "\\" in path or parsed.query:
        return "#"
    parts = list(PurePosixPath(current_source).parent.parts)
    for component in PurePosixPath(path).parts:
        if component == "..":
            if not parts:
                return "#"
            parts.pop()
        elif component != ".":
            parts.append(component)
    destination = PAGES_BY_SOURCE.get(PurePosixPath(*parts).as_posix())
    if destination is None:
        return "#"
    url = reverse(f"documentation:{destination.route_name}")
    return f"{url}#{parsed.fragment}" if parsed.fragment else url


def render_document(source: str, markdown: str) -> str:
    tokens = MARKDOWN.parse(markdown)
    for token in tokens:
        for child in token.children or ():
            if child.type == "link_open":
                child.attrSet("href", _doc_target(source, child.attrGet("href") or ""))
            elif child.type == "image":
                url = child.attrGet("src") or ""
                parsed = urlsplit(url)
                if parsed.scheme != "https" or not parsed.netloc:
                    child.attrSet("src", "")
    return MARKDOWN.renderer.render(tokens, MARKDOWN.options, {})
