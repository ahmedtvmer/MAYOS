"""Hosted account recovery and Android App Link association.

The public ``GET /reset-password`` page lets a person request a reset link or
redeem one on a device that cannot open the app. The public
``GET /.well-known/assetlinks.json`` route proves domain ownership so Android
can open the same link directly in the installed app (ADR 037).
"""

import json
import os
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from service.app_links import build_asset_links
from service.display_language import DisplayLanguage, render_localized, request_language
from service.messages import http_error_message
from service.password_reset import GENERIC_REQUEST_MESSAGE
from svc.html import self_contained_html

router = APIRouter(tags=["recovery"])

SUCCESS_MESSAGE = "Password changed. Sign in to MAYOS with your new password."
ASSET_LINKS_NOT_FOUND_DETAIL = "Not found."

_PAGE_COPY = {
    "en": {
        "pageTitle": "MAYOS account recovery",
        "languageLabel": "Language",
        "requestTitle": "Forgot your password?",
        "requestHelp": "Enter the recovery email for your account to request a reset link.",
        "emailLabel": "Recovery email",
        "requestButton": "Send recovery link",
        "requestConfirmation": GENERIC_REQUEST_MESSAGE,
        "resetTitle": "Reset your password",
        "newPasswordLabel": "New password",
        "passwordHelp": "Use 8–128 characters.",
        "confirmPasswordLabel": "Confirm password",
        "resetButton": "Set new password",
        "requestAnotherLink": "Need a new link? Request one.",
        "switchToReset": "Have a reset link? Set a new password.",
        "passwordTooShort": "Use at least 8 characters.",
        "passwordTooLong": "Use no more than 128 characters.",
        "passwordMismatch": "The passwords do not match.",
        "resetSuccess": SUCCESS_MESSAGE,
        "invalidResetLink": "Invalid or expired reset link.",
        "rateLimited": "Too many requests. Please try again later.",
        "validationFailed": "Check the form and try again.",
        "requestFailed": "The request failed. Please try again.",
        "genericFailure": "We could not complete that request. Please try again.",
        "networkFailure": "Could not reach the service. Check your connection and try again.",
    },
    "ar": {
        "pageTitle": "استرداد حساب MAYOS",
        "languageLabel": "اللغة",
        "requestTitle": "هل نسيت كلمة المرور؟",
        "requestHelp": "أدخل البريد الإلكتروني للاسترداد المرتبط بحسابك لطلب رابط إعادة التعيين.",
        "emailLabel": "البريد الإلكتروني للاسترداد",
        "requestButton": "إرسال رابط الاسترداد",
        "requestConfirmation": "إذا كان هذا البريد الإلكتروني مرتبطًا بحساب في MAYOS، فسيصلك رابط لإعادة تعيين كلمة المرور.",
        "resetTitle": "إعادة تعيين كلمة المرور",
        "newPasswordLabel": "كلمة المرور الجديدة",
        "passwordHelp": "استخدم من 8 إلى 128 حرفًا.",
        "confirmPasswordLabel": "تأكيد كلمة المرور",
        "resetButton": "تعيين كلمة مرور جديدة",
        "requestAnotherLink": "هل تحتاج إلى رابط جديد؟ اطلبه هنا.",
        "switchToReset": "لديك رابط لإعادة التعيين؟ عيّن كلمة مرور جديدة.",
        "passwordTooShort": "استخدم 8 أحرف على الأقل.",
        "passwordTooLong": "استخدم 128 حرفًا على الأكثر.",
        "passwordMismatch": "كلمتا المرور غير متطابقتين.",
        "resetSuccess": "تم تغيير كلمة المرور. سجّل الدخول إلى MAYOS باستخدام كلمة المرور الجديدة.",
        "invalidResetLink": "رابط إعادة تعيين كلمة المرور غير صالح أو انتهت صلاحيته.",
        "rateLimited": "وصل الطلب إلى الحد المسموح. حاول مرة أخرى لاحقًا.",
        "validationFailed": "راجع البيانات المدخلة وحاول مرة أخرى.",
        "requestFailed": "تعذر تنفيذ الطلب. حاول مجددًا.",
        "genericFailure": "تعذر إكمال الطلب. حاول مجددًا.",
        "networkFailure": "تعذر الاتصال بالخدمة. تحقق من اتصالك وحاول مرة أخرى.",
    },
}

# Both locale copies are embedded as JSON, never interpolated into quoted JavaScript.
_ERROR_MESSAGE_KEYS = {
    "recovery.invalid_or_expired_token.v1": "invalidResetLink",
    "http.bad_request.v1": "validationFailed",
    "http.validation_failed.v1": "validationFailed",
    "http.rate_limited.v1": "rateLimited",
    "http.server_error.v1": "requestFailed",
    "http.request_failed.v1": "requestFailed",
}
_JS_CONFIG = json.dumps(
    {"copy": _PAGE_COPY, "errorMessageKeys": _ERROR_MESSAGE_KEYS},
    ensure_ascii=False,
).replace("</", "<\\/")

# Self-contained: no external assets; the token is read from ``location`` in JS,
# scrubbed from the URL, and never reflected server-side; a per-response nonce
# scopes the inline style/script. ``__NONCE__``/``__CONFIG__`` are substituted
# at request time.
_RESET_PAGE = """<!doctype html>
<html lang="{{lang}}" dir="{{dir}}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{{pageTitle}}</title>
<style nonce="__NONCE__">
body { font-family: system-ui, sans-serif; margin: 0; padding: 2rem 1rem; background: #faf7f5; color: #201a17; }
main { max-width: 22rem; margin: 0 auto; }
h1 { font-size: 1.3rem; }
label { display: block; margin: 0.75rem 0; }
input { width: 100%; padding: 0.6rem; font-size: 1rem; box-sizing: border-box; }
select { padding: 0.45rem; font-size: 1rem; }
button { width: 100%; margin-top: 0.75rem; padding: 0.7rem; font-size: 1rem; }
#request-message, #reset-message { margin-top: 1rem; font-weight: 600; }
</style>
</head>
<body>
<main>
<label for="language" id="language-label" data-copy="languageLabel">{{languageLabel}}</label>
<select id="language" name="display_language">
<option value="en" {{en_selected}}>English</option>
<option value="ar" {{ar_selected}}>العربية</option>
</select>
<section id="request-panel" {{requestHidden}}>
<h1 id="request-title" data-copy="requestTitle">{{requestTitle}}</h1>
<p id="request-help" data-copy="requestHelp">{{requestHelp}}</p>
<form id="request-form">
<label for="email" id="email-label" data-copy="emailLabel">{{emailLabel}}</label>
<input id="email" type="email" autocomplete="email" maxlength="254" required>
<button id="request-button" type="submit" data-copy="requestButton">{{requestButton}}</button>
</form>
<p id="request-message" role="status"></p>
<p id="request-reset-link-wrap" {{resetLinkHidden}}><a id="request-reset-link" href="#reset" data-copy="switchToReset">{{switchToReset}}</a></p>
</section>
<section id="reset-panel" {{resetHidden}}>
<h1 id="reset-title" data-copy="resetTitle">{{resetTitle}}</h1>
<form id="reset-form">
<label for="p" id="new-password-label" data-copy="newPasswordLabel">{{newPasswordLabel}}</label>
<input id="p" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
<p id="password-help" data-copy="passwordHelp">{{passwordHelp}}</p>
<label for="c" id="confirm-password-label" data-copy="confirmPasswordLabel">{{confirmPasswordLabel}}</label>
<input id="c" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
<button id="reset-button" type="submit" data-copy="resetButton">{{resetButton}}</button>
</form>
<p id="reset-message" role="status"></p>
<p><a id="request-another-link" href="#request" data-copy="requestAnotherLink">{{requestAnotherLink}}</a></p>
</section>
</main>
<script nonce="__NONCE__">
(function () {
  var CONFIG = __CONFIG__;
  var COPY = CONFIG.copy;
  var languagePicker = document.getElementById('language');
  var localizedElements = document.querySelectorAll('[data-copy]');
  var requestPanel = document.getElementById('request-panel');
  var resetPanel = document.getElementById('reset-panel');
  var requestForm = document.getElementById('request-form');
  var requestMessage = document.getElementById('request-message');
  var resetForm = document.getElementById('reset-form');
  var resetMessage = document.getElementById('reset-message');
  var pw = document.getElementById('p');
  var confirm = document.getElementById('c');
  var resetButton = document.getElementById('reset-button');
  var token = new URLSearchParams(window.location.search).get('token') || '';
  var currentRequestMessage = '';
  var currentResetMessage = '';
  var errorMessageKeys = CONFIG.errorMessageKeys;
  if (token) {
    // Keep the token in this variable only; drop it from the URL so it never
    // lands in browser history, a bookmark, or a shared address bar.
    history.replaceState(null, '', location.pathname);
  }

  function updateLanguage() {
    var language = languagePicker.value === 'ar' ? 'ar' : 'en';
    var copy = COPY[language];
    document.documentElement.lang = language;
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
    document.title = copy.pageTitle;
    localizedElements.forEach(function (element) {
      element.textContent = copy[element.dataset.copy];
    });
    if (currentRequestMessage) requestMessage.textContent = copy[currentRequestMessage];
    if (currentResetMessage) resetMessage.textContent = copy[currentResetMessage];
  }

  function showPanel(panel) {
    requestPanel.hidden = panel !== 'request';
    resetPanel.hidden = panel !== 'reset';
  }

  function showRequestMessage(key) {
    currentRequestMessage = key;
    requestMessage.textContent = COPY[languagePicker.value][key];
  }

  function showResetMessage(key) {
    currentResetMessage = key;
    resetMessage.textContent = COPY[languagePicker.value][key];
  }

  function errorMessageKey(status, body) {
    var code = body && typeof body.message_code === 'string' ? body.message_code : '';
    var params = body && body.message_params;
    if (Object.prototype.hasOwnProperty.call(errorMessageKeys, code) && hasNoMessageParameters(params)) {
      return errorMessageKeys[code];
    }
    if (status === 429) return 'rateLimited';
    return 'genericFailure';
  }

  function hasNoMessageParameters(params) {
    return params && typeof params === 'object' && !Array.isArray(params) && Object.keys(params).length === 0;
  }

  languagePicker.addEventListener('change', updateLanguage);
  document.getElementById('request-another-link').addEventListener('click', function (event) {
    event.preventDefault();
    showPanel('request');
    document.getElementById('email').focus();
  });
  document.getElementById('request-reset-link').addEventListener('click', function (event) {
    event.preventDefault();
    showPanel('reset');
    pw.focus();
  });

  requestForm.addEventListener('submit', function (event) {
    event.preventDefault();
    currentRequestMessage = '';
    requestMessage.textContent = '';
    var email = document.getElementById('email').value;
    var language = languagePicker.value === 'ar' ? 'ar' : 'en';
    fetch('/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, display_language: language })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (response.ok) showRequestMessage('requestConfirmation');
        else showRequestMessage(errorMessageKey(response.status, body));
      });
    }).catch(function () {
      showRequestMessage('networkFailure');
    });
  });

  resetForm.addEventListener('submit', function (event) {
    event.preventDefault();
    currentResetMessage = '';
    resetMessage.textContent = '';
    if (pw.value.length < 8) { showResetMessage('passwordTooShort'); return; }
    if (pw.value.length > 128) { showResetMessage('passwordTooLong'); return; }
    if (pw.value !== confirm.value) { showResetMessage('passwordMismatch'); return; }
    if (!token) { showResetMessage('invalidResetLink'); return; }
    resetButton.disabled = true;
    fetch('/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token, new_password: pw.value })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (response.ok) {
          resetForm.hidden = true;
          showResetMessage('resetSuccess');
        } else {
          resetButton.disabled = false;
          showResetMessage(errorMessageKey(response.status, body));
        }
      });
    }).catch(function () {
      resetButton.disabled = false;
      showResetMessage('networkFailure');
    });
  });

  showPanel(token ? 'reset' : 'request');
  if (token) document.getElementById('request-reset-link-wrap').hidden = false;
  updateLanguage();
})();
</script>
</body>
</html>
"""

_REGISTER_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Sign up for MAYOS</title>
<style nonce="__NONCE__">
body { font-family: system-ui, sans-serif; margin: 0; padding: 2rem 1rem; background: #faf7f5; color: #201a17; }
main { max-width: 30rem; margin: 0 auto; }
h1 { font-size: 1.3rem; }
</style>
</head>
<body>
<main>
<h1>Sign up for MAYOS</h1>
<p>Open the MAYOS app to create your account.</p>
</main>
</body>
</html>
"""


@router.get("/.well-known/assetlinks.json")
async def asset_links():
    """Serves the Android App Link statement, or 404 when unconfigured."""
    statement = build_asset_links()
    if statement is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": ASSET_LINKS_NOT_FOUND_DETAIL,
                **http_error_message(404, ASSET_LINKS_NOT_FOUND_DETAIL),
            },
        )
    return JSONResponse(content=statement)


def _localize_reset_markup(page: str, language: DisplayLanguage, mode: str) -> str:
    copy = {
        **_PAGE_COPY[language],
        "requestHidden": "" if mode == "request" else "hidden",
        "resetHidden": "" if mode == "reset" else "hidden",
        "resetLinkHidden": "" if mode == "reset" else "hidden",
    }
    return render_localized(page, copy, language)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    """Serves browser recovery and reset forms without reflecting reset tokens."""
    language = request_language(request, request.query_params.get("display_language"))
    mode = "reset" if request.query_params.get("token") else "request"
    nonce = secrets.token_urlsafe(16)
    page = _RESET_PAGE.replace("__NONCE__", nonce).replace("__CONFIG__", _JS_CONFIG)
    page = _localize_reset_markup(page, language, mode)
    return self_contained_html(
        page,
        cache_control="no-store",
        style_src=f"nonce-{nonce}",
        script_src=f"nonce-{nonce}",
        connect_src="self",
        form_action="none",
    )


@router.get("/register")
async def register_page():
    """Redirects to the web sign-up page or serves an app sign-up hint."""
    ui_base = next(
        (origin.strip().rstrip("/") for origin in os.getenv("UI_BASE_URL", "").split(",") if origin.strip()),
        None,
    )
    if ui_base:
        return RedirectResponse(f"{ui_base}/register", status_code=302)
    nonce = secrets.token_urlsafe(16)
    page = _REGISTER_PAGE.replace("__NONCE__", nonce)
    return self_contained_html(
        page,
        cache_control="no-store",
        style_src=f"nonce-{nonce}",
        form_action="none",
    )
