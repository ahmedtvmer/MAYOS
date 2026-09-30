"""Server-rendered owner admin pages and their separate browser session."""

import asyncio
import hashlib
import html
import ipaddress
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from service import admin_accounts as admin_accounts_service
from service import model_metering as model_metering_service
from service import admin_auth, audit_log, email_sender, password_reset as password_reset_service, periodic_status
from svc.dependencies import get_db
from svc.html import self_contained_html
from svc.rate_limit import LOGIN_LIMIT, client_ip, limiter

router = APIRouter(prefix="/admin", tags=["admin"])
AccountListQuery = admin_accounts_service.AccountListQuery


@dataclass(frozen=True)
class _AccountsPageView:
    rows: list[dict[str, Any]]
    total: int
    csrf_token: str
    query: AccountListQuery


SESSION_COOKIE = "mayos_admin_session"
LOGIN_CSRF_COOKIE = "mayos_admin_login_csrf"
LOGIN_FAILURE_MESSAGE = "Invalid username, password, or verification code."
LOGIN_CSRF_MESSAGE = "Please reload the login page and try again."
_ADMIN_ASSET_DIR = Path(__file__).resolve().parents[1] / "static" / "admin"
_ADMIN_ASSET_TYPES = {
    "admin.css": "text/css",
    "Inter-Variable.ttf": "font/ttf",
    "PlayfairDisplay-Variable.ttf": "font/ttf",
    "mayos-logo-blue.png": "image/png",
    "mayos-logo-white.png": "image/png",
    "favicon.png": "image/png",
    "apple-touch-icon.png": "image/png",
    "OFL-Inter.txt": "text/plain",
    "OFL-PlayfairDisplay.txt": "text/plain",
}
_ADMIN_ASSETS = {
    asset_name: (content_type, (_ADMIN_ASSET_DIR / asset_name).read_bytes())
    for asset_name, content_type in _ADMIN_ASSET_TYPES.items()
}
_ADMIN_ASSET_VERSIONS = {
    asset_name: hashlib.sha256(content).hexdigest()[:12]
    for asset_name, (_, content) in _ADMIN_ASSETS.items()
}
_ADMIN_HOME_SECTIONS = (
    ("Accounts", "/admin/accounts", "Review accounts, plans, and activity."),
    ("Usage", "/admin/usage", "Review model usage, limits, and spend."),
    ("Audit log", "/admin/audit", "Review owner actions and sign-ins."),
)


def not_found_response() -> HTMLResponse:
    return HTMLResponse("Not Found", status_code=404)


@router.api_route("/assets/{asset_name}", methods=["GET", "HEAD"], include_in_schema=False)
async def admin_asset(request: Request, asset_name: str):
    if not request.app.state.admin_security.config.enabled:
        return not_found_response()
    asset = _ADMIN_ASSETS.get(asset_name)
    if asset is None:
        return not_found_response()
    media_type, content = asset
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


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
    health_panel = await asyncio.to_thread(_system_health_panel, request.app.state.db)
    body = (
        _admin_nav(session.csrf_token, security.login_alert_failed, "home")
        + "<main><h1>Owner dashboard</h1>"
        + health_panel
        + _admin_home_sections()
        + "</main>"
    )
    return _document("Owner dashboard", body)


@router.get("/accounts", response_class=HTMLResponse, include_in_schema=False)
async def admin_accounts_list(
    request: Request,
    db: Annotated[Any, Depends(get_db)],
    query: Annotated[AccountListQuery, Query()],
):
    security = request.app.state.admin_security
    session = security.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return not_found_response()
    rows, total = await asyncio.to_thread(
        admin_accounts_service.list_account_rows,
        db,
        query,
    )
    body = _admin_nav(session.csrf_token, security.login_alert_failed, "accounts")
    body += _accounts_page(_AccountsPageView(rows, total, session.csrf_token, query))
    return _document("Accounts", body)


@router.get("/usage", response_class=HTMLResponse, include_in_schema=False)
async def admin_usage_page(request: Request, db: Annotated[Any, Depends(get_db)]):
    security = request.app.state.admin_security
    session = security.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return not_found_response()
    report = await asyncio.to_thread(model_metering_service.usage_dashboard_report, db, _utc_now())
    body = _admin_nav(session.csrf_token, security.login_alert_failed, "usage") + _usage_page(report)
    return _document("Usage and cost", body)


@router.post("/accounts/email", include_in_schema=False)
async def admin_account_email_lookup(request: Request, db: Annotated[Any, Depends(get_db)]):
    security = request.app.state.admin_security
    session_token = request.cookies.get(SESSION_COOKIE)
    if security.get_session(session_token) is None:
        return not_found_response()
    form = await request.form()
    if not security.validate_session_csrf(session_token, _form_text(form, "csrf_token")):
        return HTMLResponse("Forbidden", status_code=403)
    return await _email_lookup_response(db, request, security, _form_text(form, "email"))


@router.get("/accounts/{account_id}", response_class=HTMLResponse, include_in_schema=False)
async def admin_account_detail(
    request: Request,
    account_id: str,
    db: Annotated[Any, Depends(get_db)],
):
    security = request.app.state.admin_security
    session = security.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return not_found_response()
    account = await asyncio.to_thread(_load_admin_account, db, account_id)
    if account is None:
        return not_found_response()
    body = _admin_nav(session.csrf_token, security.login_alert_failed, "accounts")
    if account["deleted_at"] is not None:
        body += _deleted_account_page(account)
        return _document("Deleted account", body)
    metadata = await asyncio.to_thread(admin_accounts_service.account_metadata, db, account)
    outcome = request.query_params.get("reset", "")
    if outcome not in {"sent", "send_failed", "no_recovery_email"}:
        outcome = ""
    reset_result = {"outcome": outcome}
    body += _account_detail_page(account, metadata, session.csrf_token, reset_result)
    return _document(f"Account · {account['username']}", body)


def _load_admin_account(db: Any, account_id: str) -> dict[str, Any] | None:
    if re.fullmatch(r"[0-9a-f]{32}", account_id, re.IGNORECASE) is None:
        return None
    account = db.get_account(account_id)
    if account is None or (account["deleted_at"] is None and not db.is_live_account(account)):
        return None
    return account


@router.post("/accounts/{account_id}/reset-email", include_in_schema=False)
async def admin_account_reset_email(request: Request, account_id: str, db: Annotated[Any, Depends(get_db)]):
    security = request.app.state.admin_security
    access = await _admin_account_reset_access(request, account_id, db)
    if isinstance(access, Response):
        return access
    outcome = await asyncio.to_thread(
        password_reset_service.owner_send_reset_email,
        db,
        account_id,
        _owner_actor(security),
        _source_ip(request),
    )
    if outcome["outcome"] == "not_found":
        return not_found_response()
    return RedirectResponse(f"/admin/accounts/{account_id}?reset={outcome['outcome']}", status_code=303)


@router.post("/accounts/{account_id}/reset-link", include_in_schema=False)
async def admin_account_reset_link(request: Request, account_id: str, db: Annotated[Any, Depends(get_db)]):
    security = request.app.state.admin_security
    access = await _admin_account_reset_access(request, account_id, db)
    if isinstance(access, Response):
        return access
    session, account = access
    outcome = await asyncio.to_thread(
        password_reset_service.owner_issue_reset_link,
        db,
        account_id,
        _owner_actor(security),
        _source_ip(request),
    )
    if outcome["outcome"] == "not_found":
        return not_found_response()
    metadata = await asyncio.to_thread(admin_accounts_service.account_metadata, db, account)
    body = _admin_nav(session.csrf_token, security.login_alert_failed, "accounts")
    body += _account_detail_page(account, metadata, session.csrf_token, outcome)
    response = _document(f"Account · {account['username']}", body)
    response.headers["Cache-Control"] = "no-store"
    return response


async def _admin_account_reset_access(
    request: Request,
    account_id: str,
    db: Any,
) -> tuple[admin_auth.AdminSession, dict[str, Any]] | Response:
    security = request.app.state.admin_security
    session_token = request.cookies.get(SESSION_COOKIE)
    session = security.get_session(session_token)
    if session is None:
        return not_found_response()
    form = await request.form()
    if not security.validate_session_csrf(session_token, _form_text(form, "csrf_token")):
        return HTMLResponse("Forbidden", status_code=403)
    account = await asyncio.to_thread(_load_admin_account, db, account_id)
    if account is None or account["deleted_at"] is not None:
        return not_found_response()
    return session, account


async def _email_lookup_response(
    db: Any,
    request: Request,
    security: admin_auth.AdminSecurity,
    email: str,
) -> RedirectResponse:
    account = await asyncio.to_thread(admin_accounts_service.find_by_recovery_email, db, email)
    await _write_admin_audit(
        db,
        audit_log.AuditEvent(
            actor=_owner_actor(security),
            action="account_lookup_by_email",
            target_account_id=account["account_id"] if account else None,
            source_ip=_source_ip(request),
        ),
    )
    destination = f"/admin/accounts/{account['account_id']}" if account else "/admin/accounts?lookup=not_found"
    return RedirectResponse(destination, status_code=303)


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
    body = _admin_nav(session.csrf_token, security.login_alert_failed, "audit")
    body += _audit_page(entries, total, query)
    return _document("Audit log", body)


@router.post("/logout", include_in_schema=False)
async def admin_logout(request: Request, db: Annotated[Any, Depends(get_db)]):
    security = request.app.state.admin_security
    session_token = request.cookies.get(SESSION_COOKIE)
    if security.get_session(session_token) is None:
        return not_found_response()
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
    body = _login_form_markup(csrf_token, message, security.login_alert_failed)
    response = _document("Owner login", body, page_class="login-page")
    response.status_code = status_code
    _set_admin_cookie(response, LOGIN_CSRF_COOKIE, csrf_token, max_age=admin_auth.LOGIN_CSRF_SECONDS)
    return response


def _login_form_markup(csrf_token: str, message: str, alert_failed: bool) -> str:
    escaped_message = f'<p class="alert" role="alert">{html.escape(message)}</p>' if message else ""
    return (
        '<main class="login-card">'
        + _brand_lockup()
        + _alert_banner(alert_failed)
        + '<p class="login-intro">Owner access</p><h1>Sign in</h1>'
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


def _document(title: str, body: str, *, page_class: str = "") -> HTMLResponse:
    body_class = f' class="{html.escape(page_class, quote=True)}"' if page_class else ""
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        + _document_head(title)
        + f"</head><body{body_class}>{body}</body></html>"
    )
    response = self_contained_html(
        page,
        cache_control="no-store",
        style_src="self",
        form_action="self",
        img_src="self",
        font_src="self",
    )
    return response


def _document_head(title: str) -> str:
    return (
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f'<link rel="icon" type="image/png" href="{_asset_url("favicon.png")}">'
        f'<link rel="apple-touch-icon" href="{_asset_url("apple-touch-icon.png")}">'
        f'<link rel="stylesheet" href="{_asset_url("admin.css")}">'
        f"<title>{html.escape(title)}</title>"
    )


def _asset_url(asset_name: str) -> str:
    return f"/admin/assets/{asset_name}?v={_ADMIN_ASSET_VERSIONS[asset_name]}"


def _brand_lockup() -> str:
    return (
        '<div class="brand-lockup" role="img" aria-label="MAYOS">'
        "<picture>"
        f'<source media="(prefers-color-scheme: dark)" srcset="{_asset_url("mayos-logo-white.png")}">'
        f'<img src="{_asset_url("mayos-logo-blue.png")}" alt="">'
        '</picture><span class="brand-wordmark" aria-hidden="true">MAYOS</span></div>'
    )


def _admin_nav(csrf_token: str, alert_failed: bool, active_page: str) -> str:
    brand_current = ' aria-current="page"' if active_page == "home" else ""
    nav = (
        '<nav class="admin-nav"><div class="admin-nav-main">'
        f'<a class="brand-link" href="/admin" aria-label="MAYOS owner dashboard"{brand_current}>'
        + _brand_lockup()
        + '</a><div class="admin-nav-links">'
        + _admin_nav_link("Accounts", "/admin/accounts", "accounts", active_page)
        + _admin_nav_link("Usage", "/admin/usage", "usage", active_page)
        + _admin_nav_link("Audit log", "/admin/audit", "audit", active_page)
        + '</div></div><form method="post" action="/admin/logout">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">'
        '<button type="submit">Log out</button></form></nav>'
    )
    return _alert_banner(alert_failed) + nav


def _admin_nav_link(label: str, href: str, page: str, active_page: str) -> str:
    current = ' aria-current="page"' if page == active_page else ""
    return f'<a class="nav-link" href="{href}"{current}>{html.escape(label)}</a>'


def _admin_home_sections() -> str:
    cards = "".join(
        f'<a class="dashboard-card" href="{href}">'
        f"<h2>{html.escape(title)}</h2><p>{html.escape(description)}</p></a>"
        for title, href, description in _ADMIN_HOME_SECTIONS
    )
    return f'<section class="dashboard-grid" aria-label="Owner dashboard sections">{cards}</section>'


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _usage_page(report: dict[str, Any]) -> str:
    empty_note = '<p class="note">No usage recorded yet.</p>' if not report["has_usage"] else ""
    return (
        '<main class="usage-page"><h1>Usage and cost</h1>'
        + empty_note
        + _spend_alert_panel(report["spend_alert"])
        + _limit_hits_panel(report["limit_hits"])
        + '<h2>Model usage totals</h2><div class="usage-period-grid">'
        + "".join(_usage_period_panel(period) for period in report["periods"])
        + "</div>"
        + _top_usage_accounts_panel(report["top_accounts"])
        + "</main>"
    )


def _spend_alert_panel(spend: dict[str, Any]) -> str:
    threshold = float(spend["threshold_usd"])
    actual = float(spend["actual_usd"])
    projected = float(spend["projected_usd"])
    progress_fill = min(max(projected, 0.0), threshold)
    threshold_ratio = projected / threshold * 100
    alert = spend["alert"]
    alert_state = _spend_alert_state(alert)
    fired = bool(alert and alert.get("fired_at"))
    notified = bool(alert and alert.get("notified_at"))
    return (
        '<section class="health-panel usage-panel" data-spend-alert '
        f'data-actual-usd="{actual:.2f}" data-projected-usd="{projected:.2f}" '
        f'data-alert-fired="{str(fired).lower()}" data-alert-notified="{str(notified).lower()}">'
        '<h2>Monthly spend alert</h2>'
        f'<p>Actual: {_usd(actual)} · Projected: {_usd(spend["projected_usd"])} · '
        f'Threshold: {_usd(threshold)} (MODEL_SPEND_ALERT_USD)</p>'
        f'<meter class="usage-progress" min="0" max="{threshold:.2f}" value="{progress_fill:.2f}" '
        'aria-label="Projected monthly spend against monthly alert threshold">'
        f'{_usd(projected)} of {_usd(threshold)}</meter>'
        f'<p>Projected spend is {threshold_ratio:.1f}% of the threshold. Monthly alert: {alert_state}</p></section>'
    )


def _spend_alert_state(alert: dict[str, Any] | None) -> str:
    if alert is None:
        return "Not fired"
    if alert.get("notified_at"):
        notified_at = html.escape(str(alert["notified_at"]))
        return f"Fired and notified at {notified_at}"
    fired_at = html.escape(str(alert.get("fired_at") or ""))
    return f"Fired at {fired_at}; notification pending"


def _limit_hits_panel(counts: dict[str, Any]) -> str:
    rows = counts["top_accounts"]
    account_rows = "".join(_limit_hit_row(row) for row in rows)
    table = _limit_hits_table(account_rows) if rows else '<p>No limit hits recorded this month.</p>'
    return (
        '<section class="health-panel usage-panel" data-limit-hits><h2>Limit hits this UTC month</h2>'
        f'<p>Daily token cap: {counts["daily_tokens"]:,} · Rate limit: {counts["rate"]:,}</p>'
        f'{table}</section>'
    )


def _limit_hits_table(rows: str) -> str:
    return (
        '<div class="table-scroll"><table class="usage-table"><thead><tr><th>Account</th>'
        '<th>Daily-cap hits</th><th>Rate-limit hits</th><th>Total hits</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
    )


def _limit_hit_row(row: dict[str, Any]) -> str:
    total = row["rate"] + row["daily_tokens"]
    account = _usage_account_link(row)
    return (
        f"<tr><td>{account}</td><td>{row['daily_tokens']:,}</td>"
        f"<td>{row['rate']:,}</td><td>{total:,}</td></tr>"
    )


def _usage_period_panel(period: dict[str, Any]) -> str:
    report = period["report"]
    return (
        f'<section class="health-panel usage-panel" data-period="{html.escape(period["key"], quote=True)}">'
        f'<h2>{html.escape(period["label"])}</h2>{_usage_totals(report)}'
        '<h3>By model (all usage)</h3>'
        f'{_usage_breakdown_table(period["by_model"], (("model", "Model"),), "model")}'
        '<h3>By role (all usage)</h3>'
        f'{_usage_breakdown_table(period["by_role"], (("role", "Role"),), "role")}'
        '<h3>Unattributed usage</h3><p>Calls without an account id, shown separately.</p>'
        f'{_usage_breakdown_table(period["unattributed"], (("role", "Role"), ("model", "Model")), "unattributed")}'
        '</section>'
    )


def _usage_totals(report: dict[str, Any]) -> str:
    return (
        '<dl class="usage-totals">'
        + _usage_metric("calls", "Model calls", report["total_requests"])
        + _usage_metric("input-tokens", "Input tokens", report["total_input_tokens"])
        + _usage_metric("output-tokens", "Output tokens", report["total_output_tokens"])
        + _usage_metric("cost", "Cost", _usd(report["total_cost_usd"]))
        + "</dl>"
    )


def _usage_metric(metric_key: str, metric_label: str, metric_value: Any) -> str:
    metric_text = f"{metric_value:,}" if isinstance(metric_value, int) else str(metric_value)
    return (
        f'<div data-metric="{html.escape(metric_key, quote=True)}">'
        f"<dt>{html.escape(metric_label)}</dt><dd>{html.escape(metric_text)}</dd></div>"
    )


def _usage_breakdown_table(
    rows: list[dict[str, Any]], dimensions: tuple[tuple[str, str], ...], kind: str
) -> str:
    if not rows:
        return '<p>No usage recorded.</p>'
    headings = "".join(f"<th>{html.escape(label)}</th>" for _, label in dimensions)
    body = "".join(_usage_breakdown_row(row, dimensions) for row in rows)
    return (
        f'<div class="table-scroll"><table class="usage-table" data-breakdown="{html.escape(kind, quote=True)}"><thead><tr>'
        f"{headings}<th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Cost</th><th>Estimated</th>"
        f"</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _usage_breakdown_row(row: dict[str, Any], dimensions: tuple[tuple[str, str], ...]) -> str:
    labels = "".join(f"<td>{html.escape(str(row[key]))}</td>" for key, _ in dimensions)
    estimate = _estimated_usage(row["estimated_calls"])
    return (
        f"<tr>{labels}<td>{row['requests']:,}</td><td>{row['input_tokens']:,}</td>"
        f"<td>{row['output_tokens']:,}</td><td>{_usd(row['cost_usd'])}</td><td>{estimate}</td></tr>"
    )


def _estimated_usage(calls: int) -> str:
    if not calls:
        return "—"
    call_label = "call" if calls == 1 else "calls"
    return f'<span class="usage-estimate">Estimated tokens</span> · {calls:,} {call_label}'


def _top_usage_accounts_panel(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<section class="health-panel usage-panel" data-top-accounts>'
            '<h2>Top 20 accounts by cost this UTC month</h2><p>No account usage recorded this month.</p></section>'
        )
    body = "".join(_top_usage_account_row(row) for row in rows)
    return (
        '<section class="health-panel usage-panel" data-top-accounts>'
        '<h2>Top 20 accounts by cost this UTC month</h2>'
        '<div class="table-scroll"><table class="usage-table"><thead><tr><th>Account</th>'
        '<th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Cost</th><th>Estimated</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div></section>'
    )


def _top_usage_account_row(row: dict[str, Any]) -> str:
    account = _usage_account_link(row)
    estimate = _estimated_usage(row["estimated_calls"])
    return (
        f"<tr><td>{account}</td><td>{row['requests']:,}</td><td>{row['input_tokens']:,}</td>"
        f"<td>{row['output_tokens']:,}</td><td>{_usd(row['cost_usd'])}</td><td>{estimate}</td></tr>"
    )


def _account_link(name: str, account_id: str) -> str:
    escaped_id = html.escape(account_id, quote=True)
    return f'<a href="/admin/accounts/{escaped_id}">{html.escape(name)}</a> · {escaped_id}'


def _usage_account_link(row: dict[str, Any]) -> str:
    account_id = row["account_id"]
    if account_id is None:
        return "Unattributed"
    name = "Deleted account" if row["deleted"] else row["username"]
    return _account_link(name or "Deleted account", account_id)


def _usd(amount: Any) -> str:
    return f"${float(amount):,.2f}"


def _system_health_panel(db: Any) -> str:
    now = datetime.now(UTC)
    rows = (
        _safe_health_row("readiness", "Readiness", _readiness_health_value),
        _safe_health_row("backup", "Last backup", lambda: _backup_health_value(db, now)),
        _periodic_job_health_row("backup-job", "Backup job", periodic_status.DAILY_BACKUP_JOB, now),
        _safe_health_row("offsite", "Off-site (R2) upload", lambda: _offsite_health_value(db)),
        _periodic_job_health_row("alert-sweep", "Last alert sweep", periodic_status.ALERT_SWEEP_JOB, now),
        _safe_health_row("coach-ai", "Coach AI", _coach_ai_health_value),
    )
    return (
        '<section class="health-panel" aria-labelledby="system-health-title">'
        '<h2 id="system-health-title">System health</h2>'
        f'<dl class="health-list">{"".join(rows)}</dl></section>'
    )


def _safe_health_row(
    key: str,
    label: str,
    source: Callable[[], tuple[str, Literal["normal", "warning"]]],
) -> str:
    try:
        value, emphasis = source()
    except Exception as exc:
        value, emphasis = f"Unknown ({type(exc).__name__})", "warning"
    return _health_row(key, label, value, emphasis)


def _readiness_health_value() -> tuple[str, Literal["normal", "warning"]]:
    from svc.app import readiness_snapshot

    status, _ = readiness_snapshot()
    if status == "ready":
        return "Ready", "normal"
    return "Not ready", "warning"


def _backup_health_value(db: Any, now: datetime) -> tuple[str, Literal["normal", "warning"]]:
    if db is None:
        return "Unknown (DatabaseNotReady)", "warning"
    from database.backup import list_daily_backups

    snapshots = list_daily_backups(db.backups_dir)
    if not snapshots:
        return "Never", "warning"
    latest = snapshots[-1]
    created_at = datetime.fromtimestamp(latest.stat().st_mtime, UTC)
    age = now - created_at
    value = f"{created_at:%Y-%m-%d %H:%M UTC} ({_hours_ago(age)} ago)"
    emphasis = "warning" if age > timedelta(hours=26) else "normal"
    return value, emphasis


def _periodic_job_health_row(key: str, label: str, job: str, now: datetime) -> str:
    return _safe_health_row(key, label, lambda: _periodic_job_health_value(job, now))


def _periodic_job_health_value(job: str, now: datetime) -> tuple[str, Literal["normal", "warning"]]:
    run = periodic_status.get(job)
    if run is None:
        interval = periodic_status.configured_interval_seconds(job)
        age = now - periodic_status.process_started_at()
        emphasis = "warning" if age > timedelta(seconds=2 * interval) else "normal"
        return "Not run since restart", emphasis
    age = now - run.finished_at
    result = "ok" if run.ok else run.error_class or "Failed"
    value = f"{result} · {_health_time(run.finished_at, age)}"
    stale = age > timedelta(seconds=2 * run.interval_seconds)
    emphasis = "warning" if stale or not run.ok else "normal"
    return value, emphasis


def _offsite_health_value(db: Any) -> tuple[str, Literal["normal", "warning"]]:
    if db is None:
        return "Unknown (DatabaseNotReady)", "warning"
    configured = getattr(db, "offsite_backup", None) is not None
    return ("Configured" if configured else "Not configured"), "normal"


def _coach_ai_health_value() -> tuple[str, Literal["normal", "warning"]]:
    from service.coach_ai import resolve_enable_gate

    gate = resolve_enable_gate()
    enabled = gate.enabled
    value = "On" if enabled else "Off"
    if not enabled or enabled != gate.requested:
        value += f" — {gate.reason}"
    emphasis = "warning" if not enabled or enabled != gate.requested else "normal"
    return value, emphasis


def _health_row(key: str, label: str, value: str, emphasis: Literal["normal", "warning"] = "normal") -> str:
    warning_class = ' class="health-warning"' if emphasis == "warning" else ""
    return (
        f'<div class="health-row" data-health="{html.escape(key, quote=True)}">'
        f"<dt>{html.escape(label)}</dt><dd{warning_class}>{html.escape(value)}</dd></div>"
    )


def _hours_ago(age: timedelta) -> str:
    hours = max(0, int(age.total_seconds() // 3600))
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _health_time(finished_at: datetime, age: timedelta) -> str:
    return f"{finished_at:%Y-%m-%d %H:%M UTC} ({_hours_ago(age)} ago)"


def _alert_banner(alert_failed: bool) -> str:
    if not alert_failed:
        return ""
    return '<p class="alert" role="alert">Login alert email could not be delivered.</p>'


def _audit_page(entries: list[dict[str, Any]], total: int, query: audit_log.AuditQuery) -> str:
    filters = _audit_filters(query)
    rows = "".join(_audit_entry(entry) for entry in entries)
    listing = f'<ol class="audit-list">{rows}</ol>' if rows else "<p>No audit entries match.</p>"
    page_count = max(1, math.ceil(total / query.page_size))
    pager = _pagination("/admin/audit", query.page, page_count, _audit_filter_params(query))
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


def _audit_filter_params(query: audit_log.AuditQuery) -> dict[str, str]:
    params = {}
    if query.action:
        params["action"] = query.action
    if query.account_id:
        params["account_id"] = query.account_id
    return params


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


def _accounts_page(view: _AccountsPageView) -> str:
    query = view.query
    page_count = max(1, math.ceil(view.total / admin_accounts_service.ACCOUNT_PAGE_SIZE))
    items = _account_rows(view.rows, query.show_deleted)
    empty = "No deleted accounts match." if query.show_deleted else "No accounts match."
    listing = f'<ol class="audit-list">{items}</ol>' if items else f"<p>{empty}</p>"
    summary = f"<p>{view.total} matching accounts · Page {query.page} of {page_count}</p>"
    deleted_note = (
        '<p class="note">The username, coach, onboarding, and inactivity filters do not apply to deleted accounts.</p>'
        if query.show_deleted
        else ""
    )
    return (
        "<main><h1>Accounts</h1>"
        + _account_filter_forms(query, view.csrf_token)
        + deleted_note
        + _account_lookup_notice(query.lookup)
        + summary
        + listing
        + _pagination(
            "/admin/accounts", query.page, page_count, _account_filter_params(query)
        )
        + "</main>"
    )


def _account_filter_forms(query: AccountListQuery, csrf_token: str) -> str:
    return _username_filter_form(query) + _email_lookup_form(csrf_token)


def _username_filter_form(query: AccountListQuery) -> str:
    search_value = html.escape(query.q, quote=True)
    deleted_checked = " checked" if query.show_deleted else ""
    coach_checked = " checked" if query.coach else ""
    onboarding_checked = " checked" if query.not_onboarded else ""
    inactive_value = html.escape(str(query.inactive_days or ""), quote=True)
    return (
        '<form class="filters" method="get" action="/admin/accounts">'
        '<label for="q">Username</label>'
        f'<input id="q" name="q" value="{search_value}" maxlength="64">'
        f'<label><input type="checkbox" name="coach" value="1"{coach_checked}> Coach</label>'
        f'<label><input type="checkbox" name="not_onboarded" value="1"{onboarding_checked}> Not onboarded</label>'
        '<label for="inactive_days">Inactive for at least N days</label>'
        f'<input id="inactive_days" name="inactive_days" type="number" min="1" max="3650" value="{inactive_value}">'
        f'<label><input type="checkbox" name="show_deleted" value="1"{deleted_checked}> Show deleted accounts</label>'
        '<button type="submit">Search accounts</button></form>'
    )


def _email_lookup_form(csrf_token: str) -> str:
    return (
        '<form method="post" action="/admin/accounts/email">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">'
        '<label for="recovery_email">Find by recovery email</label>'
        '<input id="recovery_email" name="email" type="email" autocomplete="off" required>'
        '<button type="submit">Find account</button></form>'
    )


def _account_lookup_notice(lookup: str) -> str:
    if lookup == "not_found":
        return '<p class="note">No account found for that recovery email.</p>'
    return ""


def _account_rows(rows: list[dict[str, Any]], show_deleted: bool) -> str:
    render_row = _deleted_account_row if show_deleted else _live_account_row
    return "".join(render_row(account) for account in rows)


def _live_account_row(account: dict[str, Any]) -> str:
    account_id = html.escape(account["account_id"], quote=True)
    username = html.escape(account["username"])
    created = html.escape(account["created_at"])
    last_seen = html.escape(account["last_seen_at"] or "Never")
    return (
        "<li>"
        f'<p><a href="/admin/accounts/{account_id}">{username}</a></p>'
        f"<p>Account id: {account_id}</p><p>Created: {created}</p>"
        f"<p>Last active day: {last_seen}</p>"
        f"<p>Capabilities: {html.escape(', '.join(_capability_labels(account)))}</p>"
        "</li>"
    )


def _deleted_account_row(account: dict[str, Any]) -> str:
    return (
        "<li>"
        f"<p>Account id: {html.escape(account['account_id'])}</p>"
        f"<p>Username: {html.escape(account['username'])}</p>"
        f"<p>Deleted at: {html.escape(str(account['deleted_at']))}</p>"
        "</li>"
    )


def _deleted_account_page(account: dict[str, Any]) -> str:
    return (
        "<main><h1>Deleted account</h1>"
        f"<p>Account id: {html.escape(account['account_id'])}</p>"
        f"<p>Username: {html.escape(account['username'])}</p>"
        f"<p>Deleted at: {html.escape(str(account['deleted_at']))}</p></main>"
    )


def _account_detail_page(
    account: dict[str, Any],
    metadata: dict[str, Any],
    csrf_token: str,
    reset_result: dict[str, str],
) -> str:
    return (
        "<main><h1>Account</h1><dl>"
        + _account_metadata_fields(account, metadata)
        + "</dl><h2>Model usage</h2>"
        + _usage_summary("This UTC month", metadata["usage_month"])
        + _usage_summary("All time", metadata["usage_all_time"])
        + "<h2>Limit hits this UTC month</h2><ul>"
        + _limit_hit_summary(metadata["limit_hits_month"])
        + "</ul>"
        + _password_card(account, metadata, csrf_token, reset_result)
        + "</main>"
    )


def _password_card(
    account: dict[str, Any],
    metadata: dict[str, Any],
    csrf_token: str,
    reset_result: dict[str, str],
) -> str:
    account_id = html.escape(account["account_id"], quote=True)
    masked_email = metadata["recovery_email"]
    if not account["is_player"]:
        return '<section class="health-panel"><h2>Password</h2><p>Password reset is unavailable.</p></section>'
    action, label = ("reset-link", "Create reset link") if masked_email == "Not set" else ("reset-email", "Send reset email")
    outcome = reset_result.get("outcome", "")
    return (
        '<section class="health-panel" aria-labelledby="password-title">'
        '<h2 id="password-title">Password</h2>'
        + _password_reset_notice(outcome, masked_email)
        + (_issued_reset_link(reset_result) if outcome == "issued" else "")
        + _password_form(account_id, action, label, csrf_token)
        + "</section>"
    )


def _password_form(account_id: str, action: str, label: str, csrf_token: str) -> str:
    return (
        f'<form method="post" action="/admin/accounts/{account_id}/{action}">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">'
        f'<button type="submit">{label}</button></form>'
    )


def _password_reset_notice(outcome: str, masked_email: str) -> str:
    messages = {
        "sent": f"Reset email sent to {masked_email}",
        "send_failed": "Couldn't send the email; try again or create a link",
        "no_recovery_email": "No recovery email is linked; create a reset link instead.",
    }
    message = messages.get(outcome)
    if message is None:
        return ""
    return f'<p class="note" role="status">{html.escape(message, quote=False)}</p>'


def _issued_reset_link(reset_result: dict[str, str]) -> str:
    link = reset_result["link"]
    expires_at = datetime.fromisoformat(reset_result["expires_at"]).astimezone(UTC)
    expires_display = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    message = f"Your MAYOS password reset link: {link} It works once and expires {expires_display}."
    share_url = f"https://wa.me/?{urlencode({'text': message})}"
    return (
        '<label for="issued_reset_link">Reset link</label>'
        f'<input id="issued_reset_link" type="text" readonly value="{html.escape(link, quote=True)}">'
        '<label for="reset_message">Ready-to-send message</label>'
        f'<textarea id="reset_message" rows="4" readonly>{html.escape(message)}</textarea>'
        f'<p><a href="{html.escape(share_url, quote=True)}" target="_blank" rel="noopener noreferrer">'
        "Share on WhatsApp</a></p>"
    )


def _account_metadata_fields(account: dict[str, Any], metadata: dict[str, Any]) -> str:
    return (
        _metadata_field("Username", account["username"])
        + _metadata_field("Immutable id", account["account_id"])
        + _metadata_field("Created", account["created_at"])
        + _metadata_field("Last active day", account["last_seen_at"] or "Never")
        + _metadata_field("Capabilities", ", ".join(_capability_labels(account)) or "None")
        + _metadata_field("Plans", ", ".join(_plan_labels(metadata["plans"])) or "None")
        + _metadata_field("Onboarded", "Yes" if metadata["onboarded"] else "No")
        + _metadata_field("Active assignment", _assignment_summary(metadata["assignments"]))
        + _metadata_field("Recovery email", metadata["recovery_email"])
    )


def _capability_labels(account: dict[str, Any]) -> list[str]:
    labels = []
    if account["is_player"]:
        labels.append("Player")
    if account["is_coach"]:
        labels.append("Coach")
    return labels


def _plan_labels(plans: dict[str, Any]) -> list[str]:
    labels = []
    for capability, label in (("lifter", "Lifter"), ("coach", "Coach")):
        plan = plans.get(capability)
        if plan is not None:
            labels.append(f"{label}: {plan['plan'].capitalize()}")
    return labels


def _assignment_summary(assignments: dict[str, int]) -> str:
    summary = []
    coach_count = assignments["as_coach"]
    if coach_count:
        noun = "player" if coach_count == 1 else "players"
        summary.append(f"Coach of {coach_count} active {noun}")
    if assignments["as_player"]:
        summary.append("Has an active coach")
    return "; ".join(summary) or "None"


def _limit_hit_summary(counts: dict[str, int]) -> str:
    return (
        f"<li>Daily token cap hits: {counts['daily_tokens']}</li>"
        f"<li>Rate limit hits: {counts['rate']}</li>"
    )


def _metadata_field(label: str, value: Any) -> str:
    return f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"


def _usage_summary(label: str, usage: dict[str, int | float]) -> str:
    calls = int(usage["calls"])
    call_label = "call" if calls == 1 else "calls"
    return (
        f"<section><h3>{html.escape(label)}</h3><ul>"
        f"<li>Calls: {calls} {call_label}</li>"
        f"<li>Input tokens: {int(usage['input_tokens'])}</li>"
        f"<li>Output tokens: {int(usage['output_tokens'])}</li>"
        f"<li>Total tokens: {int(usage['tokens'])}</li>"
        f"<li>Cost: ${float(usage['cost_usd']):.2f}</li>"
        "</ul></section>"
    )


def _account_filter_params(query: AccountListQuery) -> dict[str, str | int]:
    values = query.model_dump(exclude={"page", "lookup"}, exclude_defaults=True, exclude_none=True)
    return {key: 1 if value is True else value for key, value in values.items()}


def _pagination(path: str, page: int, page_count: int, params: dict[str, str | int]) -> str:
    links = []
    for label, page_number in (("Previous", page - 1), ("Next", page + 1)):
        if 1 <= page_number <= page_count:
            page_params = {**params, "page": page_number}
            links.append(f'<a href="{path}?{urlencode(page_params)}">{label}</a>')
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
    await _write_admin_audit(db, event)


async def _write_admin_audit(db: Any, event: audit_log.AuditEvent) -> None:
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
