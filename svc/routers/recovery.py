"""Hosted password-recovery fallback and Android App Link association.

Both routes are public and logged-out: ``GET /reset-password`` completes the
reset round trip on a device that cannot open the app, and
``GET /.well-known/assetlinks.json`` proves domain ownership so Android can open
the same link directly in the installed app (ADR 037).
"""

import json
import secrets

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from service.app_links import build_asset_links
from service.password_reset import GENERIC_TOKEN_ERROR

router = APIRouter(tags=["recovery"])

SUCCESS_MESSAGE = "Password changed. Sign in to MAYOS with your new password."

# Server-owned strings are embedded as a JSON object, never interpolated into
# quoted JS, so any quote/newline in a message can never break the script.
_JS_CONFIG = json.dumps({"generic": GENERIC_TOKEN_ERROR, "success": SUCCESS_MESSAGE})

# Self-contained: no external assets; the token is read from ``location`` in JS,
# scrubbed from the URL, and never reflected server-side; a per-response nonce
# scopes the inline style/script. ``__NONCE__``/``__CONFIG__`` are substituted
# at request time.
_RESET_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Reset password</title>
<style nonce="__NONCE__">
body { font-family: system-ui, sans-serif; margin: 0; padding: 2rem 1rem; background: #faf7f5; color: #201a17; }
main { max-width: 22rem; margin: 0 auto; }
h1 { font-size: 1.3rem; }
label { display: block; margin: 0.75rem 0; }
input { width: 100%; padding: 0.6rem; font-size: 1rem; box-sizing: border-box; }
button { width: 100%; margin-top: 0.75rem; padding: 0.7rem; font-size: 1rem; }
#m { margin-top: 1rem; font-weight: 600; }
</style>
</head>
<body>
<main>
<h1>Reset your password</h1>
<form id="f">
<label>New password<input id="p" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label>
<label>Confirm password<input id="c" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label>
<button id="b" type="submit">Set new password</button>
</form>
<p id="m" role="status"></p>
<p id="hint">Need a new link? Open the MAYOS app and choose &ldquo;Forgot password&rdquo;.</p>
</main>
<script nonce="__NONCE__">
(function () {
  var CONFIG = __CONFIG__;
  var form = document.getElementById('f');
  var pw = document.getElementById('p');
  var confirm = document.getElementById('c');
  var msg = document.getElementById('m');
  var button = document.getElementById('b');
  var token = new URLSearchParams(window.location.search).get('token') || '';
  if (token) {
    // Keep the token in this variable only; drop it from the URL so it never
    // lands in browser history, a bookmark, or a shared address bar.
    history.replaceState(null, '', location.pathname);
  }
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    msg.textContent = '';
    if (pw.value.length < 8) { msg.textContent = 'Use at least 8 characters.'; return; }
    if (pw.value !== confirm.value) { msg.textContent = 'The passwords do not match.'; return; }
    if (!token) { msg.textContent = CONFIG.generic; return; }
    button.disabled = true;
    fetch('/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token, new_password: pw.value })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (response.ok) {
          form.hidden = true;
          msg.textContent = CONFIG.success;
        } else {
          button.disabled = false;
          var detail = body && body.detail;
          msg.textContent = (typeof detail === 'string' && detail) ? detail : CONFIG.generic;
        }
      });
    }).catch(function () {
      button.disabled = false;
      msg.textContent = 'Could not reach the service. Check your connection and try again.';
    });
  });
})();
</script>
</body>
</html>
"""


@router.get("/.well-known/assetlinks.json")
async def asset_links():
    """Serves the Android App Link statement, or 404 when unconfigured."""
    statement = build_asset_links()
    if statement is None:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    return JSONResponse(content=statement)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page():
    """Minimal hosted fallback page. The token is never reflected into the HTML."""
    nonce = secrets.token_urlsafe(16)
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": (
            "default-src 'none'; "
            f"style-src 'nonce-{nonce}'; "
            f"script-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        ),
    }
    page = _RESET_PAGE.replace("__NONCE__", nonce).replace("__CONFIG__", _JS_CONFIG)
    return HTMLResponse(content=page, headers=headers)
