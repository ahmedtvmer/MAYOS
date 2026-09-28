"""Shared construction of the service's self-contained HTML responses.

Every public page (the hosted reset fallback, the privacy policy, the external
deletion form) is one self-contained document: no external assets, no cookies,
``Referrer-Policy: no-referrer``, ``X-Content-Type-Options: nosniff``, and a
Content-Security-Policy whose inline ``<style>`` is scoped by exactly one
source — a per-response ``nonce`` for pages that must not be cached, or a
``sha256-`` style hash for the publicly cacheable policy page, where a fresh
nonce per response would be pointless (the cached copy would carry a nonce the
later response never repeats).
"""

from fastapi.responses import HTMLResponse


def self_contained_html(
    page: str,
    *,
    cache_control: str,
    style_src: str,
    script_src: str | None = None,
    connect_src: str | None = None,
    form_action: str | None = None,
) -> HTMLResponse:
    """Wraps one rendered page in the shared security headers and CSP.

    ``style_src`` / ``script_src`` are bare CSP sources (``nonce-…`` or
    ``sha256-…``); the helper quotes them. ``connect_src`` and ``form_action``
    are omitted entirely when ``None``, so each caller keeps the exact policy it
    had before the helper existed.
    """
    directives = ["default-src 'none'", f"style-src '{style_src}'"]
    if script_src is not None:
        directives.append(f"script-src '{script_src}'")
    if connect_src is not None:
        directives.append(f"connect-src '{connect_src}'")
    directives.append("base-uri 'none'")
    if form_action is not None:
        directives.append(f"form-action '{form_action}'")
    directives.append("frame-ancestors 'none'")
    return HTMLResponse(
        content=page,
        headers={
            "Cache-Control": cache_control,
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "; ".join(directives),
        },
    )
