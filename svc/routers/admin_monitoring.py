"""Owner Monitoring page using the existing admin session and document shell."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from svc.monitoring.runtime import WINDOWS
from svc.routers.admin import SESSION_COOKIE, _admin_nav, _document, not_found_response

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/monitoring", response_class=HTMLResponse, include_in_schema=False)
async def admin_monitoring_page(request: Request):
    security = request.app.state.admin_security
    session = security.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return not_found_response()
    selected = request.query_params.get("hours", "168")
    hours = next((hours for hours in WINDOWS if str(hours) == selected), 24)
    links = "".join(
        f'<a class="nav-link" href="/admin/monitoring?hours={window}"'
        + (' aria-current="page"' if window == hours else '') + f'>{label}</a>'
        for window, label in WINDOWS.items()
    )
    panels = await asyncio.to_thread(request.app.state.monitoring.render, hours)
    body = (
        _admin_nav(session.csrf_token, security.login_alert_failed, "monitoring")
        + '<main><h1>Monitoring</h1><nav class="monitoring-windows" aria-label="Measurement window">'
        + links + '</nav><p>UTC hourly totals, including the current partial hour. '
        'The 1 hour window is the current UTC hour; longer windows include the preceding 23 or 167 hours. '
        'Trends run oldest to newest. History is retained for 30 days.</p>' + panels + '</main>'
    )
    return _document("Monitoring", body)
