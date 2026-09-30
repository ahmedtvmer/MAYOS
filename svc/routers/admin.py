"""Server-rendered owner admin pages and their separate browser session."""

import asyncio
import html
import ipaddress
import math
import os
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from service import admin_auth, audit_log, email_sender
from svc.dependencies import get_db
from svc.html import self_contained_html
from svc.rate_limit import LOGIN_LIMIT, client_ip, limiter

router = APIRouter(prefix="/admin", tags=["admin"])

SESSION_COOKIE = "mayos_admin_session"
LOGIN_CSRF_COOKIE = "mayos_admin_login_csrf"
LOGIN_FAILURE_MESSAGE = "Invalid username, password, or verification code."
LOGIN_CSRF_MESSAGE = "Please reload the login page and try again."
_PAGE_CSS = """body{font-family:system-ui,sans-serif;margin:0;padding:1rem;background:#faf7f5;color:#201a17;line-height:1.5}main{max-width:42rem;margin:0 auto}h1{font-size:1.5rem;margin:.4rem 0 1rem}h2{font-size:1.15rem;margin-top:1.5rem}a{color:#7a3b1e}nav{display:flex;gap:1rem;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:0 0 1.5rem;padding-bottom:.8rem;border-bottom:1px solid #d8cec7}label{display:block;margin:.9rem 0 .25rem;font-weight:600}input,button{box-sizing:border-box;width:100%;font:inherit;padding:.7rem;border:1px solid #84776e;border-radius:6px}button{margin-top:1rem;background:#5d321f;color:#fff;font-weight:600;cursor:pointer}form{margin:1rem 0}.alert{background:#9b1c1c;color:#fff;padding:.8rem;border-radius:6px;font-weight:600}.note{background:#efe7e1;padding:.8rem;border-radius:6px}.audit-list{padding-left:1.4rem}.audit-list li{border-bottom:1px solid #d8cec7;padding:.8rem 0;overflow-wrap:anywhere}.audit-meta{font-size:.92rem;color:#514840}.filters{display:grid;grid-template-columns:1fr;gap:.2rem}@media(min-width:36rem){.filters{grid-template-columns:1fr 1fr}.filters button{grid-column:1/-1}}"""


def not_found_response() -> HTMLResponse:
    return HTMLResponse("Not Found", status_code=404)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def admin_login_page(request: Request):
    security = request.app.state.admin_security
    if not security.config.enabled:
        return not_found_response()
    return _login_form(security)


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
@limiter.limit(LOGIN_LIMIT)
async def admin_login_submit(request: Request, db: Annotated[Any, Depends(get_db)]):
    security = request.app.state.admin_security
    if not security.config.enabled:
        return not_found_response()
    form = await request.form()
    csrf_token = _form_text(form, "csrf_token")
    if not security.consume_login_csrf(csrf_token, request.cookies.get(LOGIN_CSRF_COOKIE, "")):
        return _login_form(security, LOGIN_CSRF_MESSAGE, 403)
    source_ip = _source_ip(request)
    attempt = admin_auth.AdminLoginAttempt(
        _form_text(form, "username"),
        _form_text(form, "password"),
        _form_text(form, "totp_code"),
        source_ip or "unavailable",
    )
    result = await asyncio.to_thread(security.verify_login, attempt)
    if result is not admin_auth.AdminLoginResult.SUCCESS:
        if result is admin_auth.AdminLoginResult.REJECTED:
            await _record_failed_login(security, db, source_ip)
        elif result is admin_auth.AdminLoginResult.LOCKOUT_STARTED:
            await _write_login_audit(db, _owner_actor(security), "login_locked_out", source_ip)
        return _login_form(security, LOGIN_FAILURE_MESSAGE, 401)
    sequence = security.next_login_alert_sequence()
    return await _complete_admin_login(request, db, source_ip, sequence)


async def _record_failed_login(security: admin_auth.AdminSecurity, db: Any, source_ip: str | None) -> None:
    await _write_login_audit(db, _owner_actor(security), "login_failed", source_ip)


async def _complete_admin_login(
    request: Request,
    db: Any,
    source_ip: str | None,
    sequence: int,
):
    security = request.app.state.admin_security
    actor = _owner_actor(security)
    await _write_login_audit(db, actor, "login", source_ip)
    delivered = await _send_login_alert(request, source_ip)
    security.record_login_alert(sequence, not delivered)
    if not delivered:
        await _write_login_audit(db, actor, "login_alert_failed", source_ip)
    return _start_session(security)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def admin_home(request: Request):
    security = request.app.state.admin_security
    session = security.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return not_found_response()
    body = (
        _admin_nav(session.csrf_token, security.login_alert_failed)
        + "<main><h1>Owner dashboard</h1>"
        + "<p class=\"note\">The owner dashboard is ready. Account tools will appear here.</p>"
        + "<p><a href=\"/admin/audit\">Audit log</a></p></main>"
    )
    return _document("Owner dashboard", body)


def _audit_query(
    action: Annotated[str, Query(max_length=64)] = "",
    account_id: Annotated[str, Query(max_length=128)] = "",
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
) -> audit_log.AuditQuery:
    return audit_log.AuditQuery(action.strip() or None, account_id.strip() or None, page)


@router.get("/audit", response_class=HTMLResponse, include_in_schema=False)
async def admin_audit_viewer(
    request: Request,
    db: Annotated[Any, Depends(get_db)],
    query: Annotated[audit_log.AuditQuery, Depends(_audit_query)],
):
    security = request.app.state.admin_security
    session = security.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return not_found_response()
    entries, total = await asyncio.to_thread(audit_log.list_audit_entries, db, query)
    body = _admin_nav(session.csrf_token, security.login_alert_failed)
    body += _audit_page(entries, total, query)
    return _document("Audit log", body)


@router.post("/logout", include_in_schema=False)
async def admin_logout(request: Request, db: Annotated[Any, Depends(get_db)]):
    security = request.app.state.admin_security
    session_token = request.cookies.get(SESSION_COOKIE)
    form = await request.form()
    if not security.validate_session_csrf(session_token, _form_text(form, "csrf_token")):
        return HTMLResponse("Forbidden", status_code=403)
    await _write_login_audit(db, _owner_actor(security), "logout", _source_ip(request))
    security.logout(session_token)
    response = RedirectResponse("/admin/login", status_code=303)
    _clear_cookie(response, SESSION_COOKIE)
    _clear_cookie(response, LOGIN_CSRF_COOKIE)
    return response


def _login_form(security: admin_auth.AdminSecurity, message: str = "", status_code: int = 200) -> HTMLResponse:
    csrf_token = security.issue_login_csrf()
    body = _alert_banner(security.login_alert_failed) + _login_form_markup(csrf_token, message)
    response = _document("Owner login", body)
    response.status_code = status_code
    _set_admin_cookie(response, LOGIN_CSRF_COOKIE, csrf_token, max_age=admin_auth.LOGIN_CSRF_SECONDS)
    return response


def _login_form_markup(csrf_token: str, message: str) -> str:
    escaped_message = f'<p class="alert" role="alert">{html.escape(message)}</p>' if message else ""
    return (
        "<main><h1>Owner login</h1>"
        f"{escaped_message}<form method=\"post\" action=\"/admin/login\">"
        f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">'
        '<label for="username">Username</label><input id="username" name="username" '
        'autocomplete="username" maxlength="64" required>'
        '<label for="password">Password</label><input id="password" name="password" '
        'type="password" autocomplete="current-password" maxlength="128" required>'
        '<label for="totp_code">Verification code</label><input id="totp_code" name="totp_code" '
        'inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required>'
        '<button type="submit">Sign in</button></form></main>'
    )


def _start_session(security: admin_auth.AdminSecurity) -> RedirectResponse:
    tokens = security.create_session()
    response = RedirectResponse("/admin", status_code=303)
    _set_admin_cookie(response, SESSION_COOKIE, tokens.session_token, max_age=admin_auth.SESSION_ABSOLUTE_SECONDS)
    _clear_cookie(response, LOGIN_CSRF_COOKIE)
    return response


def _clear_cookie(response: RedirectResponse, name: str) -> None:
    _set_admin_cookie(response, name, "", max_age=0)


def _set_admin_cookie(response: HTMLResponse | RedirectResponse, name: str, value: str, *, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/admin",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def _document(title: str, body: str) -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex"><title>'
        + html.escape(title)
        + f'</title><style nonce="{nonce}">{_PAGE_CSS}</style></head><body>{body}</body></html>'
    )
    return self_contained_html(page, cache_control="no-store", style_src=f"nonce-{nonce}", form_action="self")


def _admin_nav(csrf_token: str, alert_failed: bool) -> str:
    nav = (
        '<nav><a href="/admin">Owner dashboard</a><a href="/admin/audit">Audit log</a>'
        '<form method="post" action="/admin/logout">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">'
        '<button type="submit">Log out</button></form></nav>'
    )
    return _alert_banner(alert_failed) + nav


def _alert_banner(alert_failed: bool) -> str:
    if not alert_failed:
        return ""
    return '<p class="alert" role="alert">Login alert email could not be delivered.</p>'


def _audit_page(entries: list[dict[str, Any]], total: int, query: audit_log.AuditQuery) -> str:
    filters = _audit_filters(query)
    rows = "".join(_audit_entry(entry) for entry in entries)
    listing = f'<ol class="audit-list">{rows}</ol>' if rows else "<p>No audit entries match.</p>"
    page_count = max(1, math.ceil(total / query.page_size))
    pager = _pagination(query, page_count)
    return (
        "<main><h1>Audit log</h1>"
        f"<p>{total} matching entries · Page {query.page} of {page_count}</p>"
        f"{filters}{listing}{pager}</main>"
    )


def _audit_filters(query: audit_log.AuditQuery) -> str:
    action = html.escape(query.action or "", quote=True)
    account_id = html.escape(query.account_id or "", quote=True)
    return (
        '<form class="filters" method="get" action="/admin/audit">'
        f'<label for="action">Action</label><input id="action" name="action" value="{action}" maxlength="64">'
        '<label for="account_id">Account id</label>'
        f'<input id="account_id" name="account_id" value="{account_id}" maxlength="128">'
        '<button type="submit">Filter</button></form>'
    )


def _audit_entry(entry: dict[str, Any]) -> str:
    fields = (
        ("Time", entry["created_at"]),
        ("Actor", entry["actor"]),
        ("Action", entry["action"]),
        ("Account id", entry["target_account_id"]),
        ("Source IP", entry["source_ip"]),
        ("Reason", entry["reason"]),
    )
    details = " · ".join(
        f"<span><strong>{label}:</strong> {html.escape(str(value))}</span>"
        for label, value in fields
        if value is not None
    )
    return f'<li><div class="audit-meta">{details}</div></li>'


def _pagination(query: audit_log.AuditQuery, page_count: int) -> str:
    links = []
    for label, page_number in (("Previous", query.page - 1), ("Next", query.page + 1)):
        if 1 <= page_number <= page_count:
            params = {"page": page_number}
            if query.action:
                params["action"] = query.action
            if query.account_id:
                params["account_id"] = query.account_id
            links.append(f'<a href="/admin/audit?{urlencode(params)}">{label}</a>')
    return f'<p>{" · ".join(links)}</p>' if links else ""


async def _send_login_alert(request: Request, source_ip: str | None) -> bool:
    destination = os.getenv("OWNER_ALERT_EMAIL", "").strip()
    if not destination:
        return False
    security = request.app.state.admin_security
    login_time = datetime.fromtimestamp(security.clock(), UTC).isoformat(timespec="seconds")
    return await asyncio.to_thread(
        email_sender.send_owner_login_alert_email,
        destination,
        login_time,
        source_ip or "unavailable",
        request.headers.get("user-agent", "unavailable"),
    )


async def _write_login_audit(db: Any, actor: str, action: str, source_ip: str | None) -> None:
    event = audit_log.AuditEvent(actor=actor, action=action, source_ip=source_ip)
    await asyncio.to_thread(audit_log.write_audit_entry, db, event)


def _form_text(form: Any, name: str) -> str:
    value = form.get(name, "")
    return value if isinstance(value, str) else ""


def _source_ip(request: Request) -> str | None:
    try:
        return ipaddress.ip_address(client_ip(request)).compressed
    except ValueError:
        return None


def _owner_actor(security: admin_auth.AdminSecurity) -> str:
    return security.config.username or "owner"
