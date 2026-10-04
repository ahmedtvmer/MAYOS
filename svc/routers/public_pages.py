"""Public, unauthenticated pages: the privacy policy and the external
account-deletion request (issue #43).

Both follow ``svc/routers/recovery.py``: self-contained HTML with no external
assets, strict CSP, and no cookie or session. Because the deletion form carries
no ambient credential, a plain same-origin form POST is CSRF-safe by
construction; an explicit confirmation checkbox is the deliberate act, and the
password is still verified by the same service code the in-app
``DELETE /auth/account`` uses.

The page chrome (templates, CSS, response headers) lives here in the router
layer; ``service.privacy_policy`` only produces the policy's body HTML.
"""

import asyncio
import base64
import hashlib
import html
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from service import account_deletion as deletion_service
from service import analytics as analytics_service
from service.privacy_policy import policy_body_html
from svc.dependencies import get_db
from svc.html import self_contained_html
from svc.rate_limit import PASSWORD_LIMIT, limiter

router = APIRouter(tags=["public"])

DELETE_PAGE_TITLE = "Delete your MAYOS account"
SUCCESS_MESSAGE = (
    "Your account and its active data have been deleted, and every session has been ended. "
    "This cannot be undone."
)
UNCONFIRMED_MESSAGE = (
    "Please tick the confirmation box to confirm that you want to permanently delete this account."
)
GENERIC_FAILURE_MESSAGE = (
    "We could not complete that request. Check your username and password and try again. "
    "If you have forgotten your password, reset it first from the MAYOS app "
    "(\"Forgot password\"), or contact the address shown in the privacy policy."
)

# --------------------------------------------------------------------------
# Privacy policy page (publicly cacheable, so the style source is a hash of the
# static CSS rather than a per-response nonce that a cached copy would outlive).
# --------------------------------------------------------------------------

_PRIVACY_CSS = """body { font-family: system-ui, sans-serif; margin: 0; padding: 2rem 1rem; background: #faf7f5; color: #201a17; line-height: 1.55; }
main { max-width: 44rem; margin: 0 auto; }
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.2rem; margin-top: 2rem; }
h3 { font-size: 1.02rem; margin-top: 1.4rem; }
p { margin: 0.7rem 0; }
ul { margin: 0.5rem 0 0.7rem; padding-left: 1.2rem; }
li { margin: 0.3rem 0; }
a { color: #7a3b1e; }
code { background: #efe7e1; padding: 0.05rem 0.25rem; border-radius: 4px; }"""

_PRIVACY_STYLE_SRC = "sha256-" + base64.b64encode(hashlib.sha256(_PRIVACY_CSS.encode("utf-8")).digest()).decode(
    "ascii"
)

_PRIVACY_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MAYOS Privacy Policy</title>
<style>__STYLE__</style>
</head>
<body>
<main>
__BODY__
</main>
</body>
</html>
"""

# --------------------------------------------------------------------------
# Deletion-request pages (never cached; the form POSTs to this origin).
# --------------------------------------------------------------------------

_FORM_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>__TITLE__</title>
<style nonce="__NONCE__">
body { font-family: system-ui, sans-serif; margin: 0; padding: 2rem 1rem; background: #faf7f5; color: #201a17; line-height: 1.55; }
main { max-width: 30rem; margin: 0 auto; }
h1 { font-size: 1.35rem; }
label { display: block; margin: 0.85rem 0 0.25rem; font-weight: 600; }
input[type="text"], input[type="password"] { width: 100%; padding: 0.6rem; font-size: 1rem; box-sizing: border-box; }
.check { display: flex; gap: 0.5rem; align-items: flex-start; margin: 1rem 0; font-weight: 400; }
.check label { font-weight: 400; margin: 0; }
.check input { margin-top: 0.25rem; }
button { width: 100%; margin-top: 0.75rem; padding: 0.75rem; font-size: 1rem; cursor: pointer; }
.note { background: #efe7e1; border-radius: 8px; padding: 0.75rem 0.9rem; font-size: 0.95rem; }
#m { margin-top: 1rem; font-weight: 600; }
footer { margin-top: 1.5rem; font-size: 0.95rem; }
</style>
</head>
<body>
<main>
"""

_FORM_PAGE = _FORM_HEAD + """<h1>__TITLE__</h1>
<p>MAYOS deletes accounts on request, from the app or from this page. Deletion is
immediate and permanent: it removes your training ledger (profile, program,
workouts, schedule, assistant chat), your recovery email and reset tokens, your
invites, and ends any active coaching assignment. Every signed-in session is ended.</p>
<p><strong>What is kept.</strong> A small deletion record (internal ids and the time)
is kept outside the backups so a restore cannot bring the account back; per-account
model-usage rows keyed only by an opaque id stay for cost reconciliation; and
whole-catalog recovery snapshots may briefly retain deleted rows for up to
<strong>30 days</strong>. Nothing else about you is retained.</p>
<p class="note">We answer the same way whether or not your username exists, so this page never
reveals whether an account is registered. <a href="/privacy">Read the privacy policy</a>
for the full disclosure.</p>
<form method="post" action="/account/delete-request">
<label for="username">Username</label>
<input id="username" name="username" type="text" autocomplete="username" maxlength="64" required>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" minlength="8" maxlength="128" required>
<div class="check">
<input id="confirm" name="confirm" type="checkbox" value="yes" required>
<label for="confirm">I understand this permanently deletes my account and cannot be undone.</label>
</div>
<button type="submit">Delete my account</button>
</form>
<p id="m" role="status"></p>
<footer><strong>Lost your password?</strong> Reset it first from the MAYOS app
(&ldquo;Forgot password&rdquo;), then come back here. The privacy policy linked
above also lists how to contact the operator.</footer>
</main>
</body>
</html>
"""

_RESULT_PAGE = _FORM_HEAD + """<h1>__TITLE__</h1>
<p id="m" role="status">__MESSAGE__</p>
<footer><a href="/account/delete-request">Try again</a> &middot;
<a href="/privacy">Privacy policy</a></footer>
</main>
</body>
</html>
"""


def _form_page(template: str, *, title: str, message: str = "") -> HTMLResponse:
    """One nonce-scoped, never-cached response for the deletion form."""
    nonce = secrets.token_urlsafe(16)
    page = (
        template.replace("__NONCE__", nonce)
        .replace("__TITLE__", html.escape(title))
        .replace("__MESSAGE__", html.escape(message))
    )
    return self_contained_html(
        page,
        cache_control="no-store",
        style_src=f"nonce-{nonce}",
        form_action="self",
    )


@router.get("/privacy", response_class=HTMLResponse, name="privacy_page")
async def privacy_page():
    """The privacy policy, cacheable and reachable without a session (#43)."""
    page = _PRIVACY_PAGE.replace("__STYLE__", _PRIVACY_CSS).replace("__BODY__", policy_body_html())
    return self_contained_html(
        page,
        cache_control="public, max-age=3600",
        style_src=_PRIVACY_STYLE_SRC,
    )


@router.get("/account/delete-request", response_class=HTMLResponse, name="delete_request_page")
async def delete_request_page():
    """The external account-deletion form Play Console links to (#43)."""
    return _form_page(_FORM_PAGE, title=DELETE_PAGE_TITLE)


@router.post("/account/delete-request", response_class=HTMLResponse, name="delete_request_submit")
@limiter.limit(PASSWORD_LIMIT)
async def delete_request_submit(request: Request, db: Annotated[Any, Depends(get_db)]):
    """Runs the same password-confirmed deletion as the in-app path.

    Rate-limited with the password limit (one shared budget for every password
    proving action from this client), never revealing whether the username
    exists: an unknown username, a wrong password, and a missing confirmation
    all render a page that discloses nothing about registry state. Non-string
    form values are normalised by the service, in one place.
    """
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    confirmed = form.get("confirm")

    if confirmed is None:
        return _form_page(_RESULT_PAGE, title=DELETE_PAGE_TITLE, message=UNCONFIRMED_MESSAGE)

    result = await asyncio.to_thread(
        deletion_service.delete_account_by_username,
        db,
        username,
        password,
        client=analytics_service.client_context(request),
    )
    if not result["ok"]:
        return _form_page(_RESULT_PAGE, title=DELETE_PAGE_TITLE, message=GENERIC_FAILURE_MESSAGE)
    return _form_page(_RESULT_PAGE, title=DELETE_PAGE_TITLE, message=SUCCESS_MESSAGE)
