"""Privacy policy body rendering for ``GET /privacy`` (issue #43).

``docs/PRIVACY_POLICY.md`` is the single source of truth: the owner reviews and
signs that file, and the API renders it. The owner contact comes from
``PRIVACY_CONTACT_EMAIL``; when unset the page still renders with an explicit
placeholder and logs a warning **once** instead of failing boot.

The renderer understands the Markdown subset the policy file uses — headings,
bullets, paragraphs, ``**strong**``, ```code` `` and ``[text](url)`` links — and
escapes every piece of text, so the source file cannot inject markup.

Rendering (read + parse + substitute) is cached per contact value, so a public,
cacheable route does not re-read and re-parse the Markdown on every hit; the
side effects that must not repeat — the missing-contact warning — live inside
the cached call. ``clear_policy_cache`` exists for tests and for a process that
must pick up an edited file without restarting.
"""

import html
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

#: Bumped whenever the policy text changes; rendered at the top of the page.
POLICY_VERSION = "1.5"
POLICY_EFFECTIVE_DATE = "2026-10-10"

POLICY_PATH = Path(__file__).resolve().parent.parent / "docs" / "PRIVACY_POLICY.md"

_CONTACT_TOKEN = "{{PRIVACY_CONTACT}}"
_CONTACT_FALLBACK = (
    "the operator of MAYOS (this deployment has no contact email configured: "
    "PRIVACY_CONTACT_EMAIL is unset)"
)

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^- \s?(.*)$")
# One capturing group only: re.split must return the matched inline tokens, and
# nested groups would put their internals in the result instead.
_INLINE = re.compile(r"(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SAFE_URL = re.compile(r"^(?:/[^\s]*|https://[^\s]+|mailto:[^\s]+)$")


def privacy_contact_email() -> str | None:
    """The configured owner contact, or ``None`` when the deployment has none."""
    value = os.getenv("PRIVACY_CONTACT_EMAIL", "").strip()
    return value or None


def contact_html() -> str:
    """The contact as safe HTML (never raises; a placeholder when unset)."""
    return _contact_html(privacy_contact_email())


def _contact_html(contact: str | None) -> str:
    if contact is not None:
        return f'<a href="mailto:{html.escape(contact, quote=True)}">{html.escape(contact)}</a>'
    return f"<em>{html.escape(_CONTACT_FALLBACK)}</em>"


def _inline(text: str) -> str:
    """Renders inline Markdown on already-untrusted ``text`` to escaped HTML."""
    rendered: list[str] = []
    for part in _INLINE.split(text):
        if len(part) > 2 and part.startswith("`") and part.endswith("`"):
            rendered.append(f"<code>{html.escape(part[1:-1])}</code>")
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            rendered.append(f"<strong>{html.escape(part[2:-2])}</strong>")
        elif part.startswith("["):
            match = _LINK.fullmatch(part)
            if match is not None and _SAFE_URL.match(match.group(2)):
                href = html.escape(match.group(2), quote=True)
                rendered.append(f'<a href="{href}">{html.escape(match.group(1))}</a>')
            else:
                rendered.append(html.escape(part))
        else:
            rendered.append(html.escape(part))
    return "".join(rendered)


def render_markdown(markdown: str) -> str:
    """Renders the policy Markdown subset to HTML (every text piece escaped)."""
    out: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_items() -> None:
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + "</ul>")
            items.clear()

    def flush_all() -> None:
        flush_paragraph()
        flush_items()

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush_all()
            continue
        heading = _HEADING.match(line)
        if heading is not None:
            flush_all()
            level = min(len(heading.group(1)), 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        bullet = _BULLET.match(line)
        if bullet is not None:
            flush_paragraph()
            items.append(bullet.group(1).strip())
            continue
        if items:
            # A wrapped bullet continues its last item rather than breaking out.
            items[-1] = f"{items[-1]} {line}"
        else:
            paragraph.append(line)
    flush_all()
    return "\n".join(out)


@lru_cache(maxsize=4)
def _render_body(contact: str | None) -> str:
    """Reads, renders, and substitutes the policy once per contact value.

    The missing-contact warning lives here rather than in the request path so a
    crawl of ``/privacy`` logs it once instead of once per hit.
    """
    source = POLICY_PATH.read_text(encoding="utf-8")
    source = source.replace("{{POLICY_VERSION}}", POLICY_VERSION)
    source = source.replace("{{POLICY_EFFECTIVE_DATE}}", POLICY_EFFECTIVE_DATE)
    body = render_markdown(source)
    if contact is None:
        logger.warning(
            "PRIVACY_CONTACT_EMAIL is not set; /privacy renders a placeholder contact instead of a real address."
        )
    # The contact token survives escaping ({ } are not HTML metacharacters), so
    # a mailto link can be injected after rendering without double-escaping.
    return body.replace(_CONTACT_TOKEN, _contact_html(contact))


def policy_body_html() -> str:
    """The rendered policy body: version, date, and contact substituted."""
    return _render_body(privacy_contact_email())


def clear_policy_cache() -> None:
    """Drops the cached bodies so a test (or an operator) re-reads the file."""
    _render_body.cache_clear()
