"""Read-only outside services; only cached, allow-listed summaries reach the page."""

from __future__ import annotations

import html
import math
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from svc.monitoring.measurements import HourlyMeasurements
from svc.monitoring.runtime import MonitoringView

REFRESH_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 3.0
MAX_PAGES = 20
RECENT_LIMIT = 5
MONITOR_STATUSES = {0: "Paused", 1: "Not checked yet", 2: "Up", 8: "Seems down", 9: "Down"}


def _https_url(raw: str) -> str:
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Expected an HTTPS URL without credentials")
    if any(character.isspace() or ord(character) < 32 for character in raw):
        raise ValueError("Invalid URL")
    return raw


def _slug(raw: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", raw):
        raise ValueError("Invalid Sentry slug")
    return raw


def _integer(raw: Any) -> int:
    if isinstance(raw, bool) or not re.fullmatch(r"[0-9]+", str(raw)):
        raise ValueError("Expected a non-negative integer")
    return int(raw)


def _text(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("Expected text")
    return html.escape(raw[:500])


def _objects(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or any(not isinstance(entry, dict) for entry in raw):
        raise ValueError("Expected a list of objects")
    return raw


class _CachedSource:
    def __init__(self, loader: Callable[[], str] | None, notice: str) -> None:
        self._loader = loader
        self._notice = notice
        self._body = ""
        self._updated = ""
        self._next_refresh = 0.0
        self._running = False
        self._lock = Lock()

    def sample(self) -> None:
        with self._lock:
            if self._loader is None or self._running or time.monotonic() < self._next_refresh:
                return
            self._running = True
            self._next_refresh = time.monotonic() + REFRESH_SECONDS
        # Monitoring.flush holds the page's I/O lock: never do network I/O there.
        try:
            Thread(target=self._refresh, name="monitoring-outside", daemon=True).start()
        except RuntimeError:
            self._failed()

    def _failed(self) -> None:
        with self._lock:
            self._notice = "Refresh unavailable; will retry in a few minutes."
            self._running = False

    def _refresh(self) -> None:
        try:
            body = self._loader()
            updated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            # External failures must not escape into threading/runtime logging:
            # exception messages can include credentials or response bodies.
            self._failed()
            return
        with self._lock:
            self._body, self._updated, self._notice = body, updated, ""
            self._running = False

    def render(self, title: str) -> str:
        with self._lock:
            body, updated, notice = self._body, self._updated, self._notice
        warning = " monitoring-warning" if "unavailable" in notice else ""
        freshness = f"<p>Last successful refresh: {updated}." if updated else ""
        if freshness:
            freshness += (" Cached values may be stale." if notice else "") + "</p>"
        return (f'<section class="health-panel monitoring-tile{warning}"><h2>{title}</h2>'
                + (f"<p>{notice}</p>" if notice else "") + freshness + body + "</section>")


def _sentry_issues(client: httpx.Client, path: str) -> tuple[int, list[dict[str, Any]]]:
    count = 0
    newest: list[dict[str, Any]] = []
    params = {"query": "is:unresolved", "sort": "new", "statsPeriod": "", "limit": "100"}
    for _ in range(MAX_PAGES):
        response = client.get(path, params=params)
        response.raise_for_status()
        issues = _objects(response.json())
        count += len(issues)
        newest.extend(issues[:max(0, RECENT_LIMIT - len(newest))])
        following = response.links.get("next", {})
        if following.get("results") != "true":
            return count, newest
        # Only reuse the cursor, never an upstream URL that could receive our token.
        params["cursor"] = parse_qs(urlsplit(following["url"]).query)["cursor"][0]
    raise ValueError("Too many Sentry issue pages")


def _sentry_project(client: httpx.Client, org: str, project: str) -> str:
    count, newest = _sentry_issues(client, f"/api/0/projects/{org}/{project}/issues/")
    project_url = f"https://{org}.sentry.io/issues/?query=is%3Aunresolved%20project%3A{project}"
    rows = "".join(
        f'<li><a href="https://{org}.sentry.io/issues/{_integer(issue["id"])}/">'
        f'{_text(issue["title"])}</a> — {_integer(issue["count"]):,} events</li>'
        for issue in newest
    )
    return (f'<h3><a href="{html.escape(project_url)}">{_text(project)}</a>: {count:,} unresolved</h3>'
            + (f"<ul>{rows}</ul>" if rows else "<p>No unresolved issues.</p>"))


def _uptime_cells(raw: Any) -> str:
    # Missing ratios mean no coverage, never an invented 100% uptime.
    if raw in (None, ""):
        return "<td>Not available</td>" * 3
    ratios = str(raw).split("-")
    if len(ratios) != 3:
        raise ValueError("Expected three uptime ratios")
    percentages = [float(ratio) for ratio in ratios]
    if any(not math.isfinite(ratio) or not 0 <= ratio <= 100 for ratio in percentages):
        raise ValueError("Invalid uptime ratio")
    return "".join(f"<td>{ratio:.3f}%</td>" for ratio in percentages)


def _downtime(monitor: dict[str, Any]) -> str:
    logs = [entry for entry in _objects(monitor.get("logs", [])) if _integer(entry["type"]) == 1]
    logs.sort(key=lambda entry: _integer(entry["datetime"]), reverse=True)
    entries = []
    for index, entry in enumerate(logs[:RECENT_LIMIT]):
        started = datetime.fromtimestamp(_integer(entry["datetime"]), UTC)
        duration = _integer(entry["duration"])
        # A tentative failure (8) can still have only an older, closed outage.
        ongoing = index == 0 and _integer(monitor["status"]) == 9 and duration == 0
        if ongoing:
            duration = max(duration, int((datetime.now(UTC) - started).total_seconds()), 0)
        entries.append(f'<li>{started:%Y-%m-%d %H:%M:%S UTC} — {duration:,} seconds'
                       + (" (ongoing)" if ongoing else "") + "</li>")
    return "<ul>" + "".join(entries) + "</ul>" if entries else "No recent downtime returned."


def _monitor_row(monitor: dict[str, Any]) -> str:
    status = _integer(monitor["status"])
    warning = ' class="monitoring-warning"' if status in (8, 9) else ""
    return (f'<tr{warning}><td>{_text(monitor["friendly_name"])}</td>'
            f'<td>{MONITOR_STATUSES.get(status, "Unknown")}</td>'
            + _uptime_cells(monitor.get("custom_uptime_ratios", monitor.get("custom_uptime_ratio")))
            + f'<td>{_downtime(monitor)}</td></tr>')


def _uptimerobot_monitors(client: httpx.Client, key: str) -> list[dict[str, Any]]:
    monitors: list[dict[str, Any]] = []
    for _ in range(MAX_PAGES):
        response = client.post("https://api.uptimerobot.com/v2/getMonitors", data={
            "api_key": key, "format": "json", "custom_uptime_ratios": "1-7-30",
            "logs": "1", "log_types": "1", "logs_limit": str(RECENT_LIMIT),
            "offset": str(len(monitors)), "limit": "50",
        })
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("stat") != "ok":
            raise ValueError("UptimeRobot rejected the request")
        batch = _objects(payload["monitors"])
        monitors.extend(batch)
        if len(monitors) >= _integer(payload["pagination"]["total"]):
            return monitors
        if not batch:
            raise ValueError("Incomplete UptimeRobot pagination")
    raise ValueError("Too many UptimeRobot monitor pages")


class OutsideProvider:
    key = "outside"

    def __init__(self) -> None:
        self.measurements = HourlyMeasurements()
        self._sentry_token = os.getenv("SENTRY_READ_TOKEN", "").strip()
        self._uptimerobot_key = os.getenv("UPTIMEROBOT_READ_KEY", "").strip()
        self._org = os.getenv("SENTRY_ORG", "mayos").strip()
        self._projects = os.getenv("SENTRY_PROJECTS", "mayos-api,mayos-app").split(",")
        self._sentry_host = os.getenv("SENTRY_API_BASE_URL", "https://de.sentry.io").strip()
        project_id = os.getenv("POSTHOG_PROJECT_ID", "").strip()
        self._posthog_url = os.getenv("POSTHOG_PROJECT_URL", "").strip() or (
            f"https://eu.posthog.com/project/{project_id}" if project_id else "")
        self._sentry = _CachedSource(self._sentry_summary if self._sentry_token else None,
                                     "Waiting for first refresh." if self._sentry_token
                                     else "Not configured: set SENTRY_READ_TOKEN on the server.")
        self._uptimerobot = _CachedSource(self._uptimerobot_summary if self._uptimerobot_key else None,
                                          "Waiting for first refresh." if self._uptimerobot_key
                                          else "Not configured: set UPTIMEROBOT_READ_KEY on the server.")

    def _without_secrets(self, markup: str) -> str:
        for secret in (self._sentry_token, self._uptimerobot_key):
            if secret:
                markup = markup.replace(html.escape(secret), "[redacted]").replace(secret, "[redacted]")
        return markup

    def _sentry_summary(self) -> str:
        host = _https_url(self._sentry_host).rstrip("/")
        parsed = urlsplit(host)
        if parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Sentry API base must be an HTTPS origin")
        org = _slug(self._org)
        projects = list(dict.fromkeys(_slug(project.strip()) for project in self._projects))
        with httpx.Client(base_url=host, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
                          headers={"Authorization": f"Bearer {self._sentry_token}"}) as client:
            summary = "".join(_sentry_project(client, org, project) for project in projects)
        return self._without_secrets("<p>Newest unresolved issues; counts are events, not people.</p>" + summary)

    def _uptimerobot_summary(self) -> str:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
            monitors = _uptimerobot_monitors(client, self._uptimerobot_key)
        rows = "".join(_monitor_row(monitor) for monitor in monitors)
        summary = ('<p><a href="https://dashboard.uptimerobot.com/">Open UptimeRobot</a>. '
                   'Checks and alerts remain in UptimeRobot. Recent downtime is limited by its log retention.</p>')
        summary += ('<div class="table-scroll"><table><thead><tr><th>Monitor</th><th>Status</th>'
                    '<th>24 hour uptime</th><th>7 day uptime</th><th>30 day uptime</th>'
                    '<th>Recent downtime</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
                    if monitors else '<p>No monitors returned.</p>')
        return self._without_secrets(summary)

    def sample(self) -> None:
        self._sentry.sample()
        self._uptimerobot.sample()

    def _posthog_link(self) -> str:
        if not self._posthog_url:
            return "<p>Set POSTHOG_PROJECT_URL to link to product analytics.</p>"
        try:
            url = _https_url(self._posthog_url)
            if any(secret and secret in url for secret in (self._sentry_token, self._uptimerobot_key)):
                raise ValueError("Credential in project URL")
        except ValueError:
            return "<p>POSTHOG_PROJECT_URL must be an HTTPS project link without credentials.</p>"
        return f'<p><a href="{html.escape(url)}">Open PostHog product analytics</a></p>'

    def render(self, view: MonitoringView) -> str:
        return ('<div class="monitoring-grid">' + self._sentry.render("Sentry issues")
                + self._uptimerobot.render("UptimeRobot uptime")
                + '<section class="health-panel monitoring-tile"><h2>PostHog</h2>'
                + self._posthog_link() + '</section></div>')


def create_provider(app: Any) -> OutsideProvider:
    return OutsideProvider()
