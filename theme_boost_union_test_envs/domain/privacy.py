"""Data protection declaration (privacy page).

Administrators edit the declaration in the frontend; it is stored as the
``privacy`` section of ``settings.yaml``::

    privacy:
      html: "<h2>…</h2><p>…</p>"
      updated_at: "2026-11-22T10:00:00+00:00"
      updated_by: "Jane Doe"

The HTML is reduced to a small whitelist of tags on every save, so the page
can be rendered as-is and nothing can inject scripts, styles or attributes.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

SECTION = "privacy"
MAX_HTML_LENGTH = 100_000

ALLOWED_TAGS = {"p", "br", "strong", "em", "u", "h2", "h3", "ul", "ol", "li", "a"}
# Tags browsers' editing commands produce, mapped onto the whitelist.
RENAMED_TAGS = {"b": "strong", "i": "em", "h1": "h2", "h4": "h3", "h5": "h3", "h6": "h3", "div": "p"}
# Tags whose content is dropped together with the tag.
DROPPED_WITH_CONTENT = {
    "script", "style", "iframe", "object", "embed", "template", "noscript",
    "svg", "math", "head", "title", "textarea", "select", "button",
}
VOID_TAGS = {"br"}
# Block-level tags; opening one closes an open <p> (as HTML parsers do), so
# editor output like <p><ul>…</ul></p> becomes valid <ul>…</ul>.
BLOCK_TAGS = {"p", "ul", "ol", "h2", "h3"}
SAFE_LINK_PREFIXES = ("http://", "https://", "mailto:", "/", "#")


def _safe_href(value: str | None) -> str | None:
    href = (value or "").strip()
    if href and href.lower().startswith(SAFE_LINK_PREFIXES) and not href.startswith("//"):
        return href
    return None


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROPPED_WITH_CONTENT:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        tag = RENAMED_TAGS.get(tag, tag)
        if tag not in ALLOWED_TAGS:
            return
        if tag in VOID_TAGS:
            self.out.append(f"<{tag}>")
            return
        if tag in BLOCK_TAGS and "p" in self.stack:
            self._close_until("p")
        if tag == "a":
            href = _safe_href(dict(attrs).get("href"))
            if href is None:
                # Keep the text, drop the link.
                self.stack.append("#dropped-a")
                return
            extra = (
                ' target="_blank" rel="noopener noreferrer"'
                if href.lower().startswith(("http://", "https://"))
                else ""
            )
            self.out.append(f'<a href="{html.escape(href, quote=True)}"{extra}>')
        else:
            self.out.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.skip_depth and RENAMED_TAGS.get(tag, tag) in VOID_TAGS:
            self.out.append("<br>")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROPPED_WITH_CONTENT:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        tag = RENAMED_TAGS.get(tag, tag)
        if tag == "a":
            # Close the innermost link, whether it was kept or dropped.
            innermost = next((t for t in reversed(self.stack) if t in ("a", "#dropped-a")), None)
            if innermost:
                self._close_until(innermost)
            return
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS and tag in self.stack:
            self._close_until(tag)

    def _close_until(self, tag: str) -> None:
        while self.stack:
            open_tag = self.stack.pop()
            if open_tag != "#dropped-a":
                self.out.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        self.close()
        self._close_until("")  # close anything left open
        return re.sub(r"<p>(\s|<br>)*</p>", "", "".join(self.out)).strip()


def sanitize_html(value: str) -> str:
    """Reduce ``value`` to the whitelisted tags (see module docstring)."""
    parser = _Sanitizer()
    parser.feed(value or "")
    return parser.result()


def load() -> dict[str, Any]:
    from ..cross_cutting import settings_store

    section = settings_store.get_section(SECTION)
    return {
        "html": str(section.get("html") or ""),
        "updated_at": str(section.get("updated_at") or ""),
        "updated_by": str(section.get("updated_by") or ""),
    }


def save(raw_html: str, updated_by: str) -> dict[str, Any]:
    from ..cross_cutting import settings_store

    section = {
        "html": sanitize_html(raw_html),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated_by": updated_by,
    }
    settings_store.set_section(SECTION, section)
    return section
