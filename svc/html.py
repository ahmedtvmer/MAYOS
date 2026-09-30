"""Shared construction of server-rendered HTML responses and their CSP.

The hosted reset, privacy, and deletion pages use inline styles scoped by a
per-response nonce or a style hash and make no external asset requests. The
admin surface opts into a same-origin stylesheet, fonts, and images; optional
CSP sources let it allow those assets without widening the public-page policies.
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
    img_src: str | None = None,
    font_src: str | None = None,
) -> HTMLResponse:
    """Wraps one rendered page in the shared security headers and CSP.

    CSP source arguments are bare values such as ``self``, ``nonce-…``, or
    ``sha256-…``; the helper adds the directive quoting.
    Optional directives are omitted when their source is ``None``, preserving
    existing policies unless a caller opts into that resource type.
    """
    directives = ["default-src 'none'", f"style-src '{style_src}'"]
    if img_src is not None:
        directives.append(f"img-src '{img_src}'")
    if font_src is not None:
        directives.append(f"font-src '{font_src}'")
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
