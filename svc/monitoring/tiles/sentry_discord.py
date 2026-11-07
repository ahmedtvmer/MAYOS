"""Best-effort Sentry alerts, isolated from requests and the Monitoring lock."""

from __future__ import annotations

import html
import json
import math
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.client import HTTPException, HTTPSConnection, HTTPResponse
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from svc.monitoring.measurements import HourlyMeasurements
from svc.monitoring.runtime import MonitoringView
from svc.monitoring.tiles.outside import (
    MAX_PAGES,
    REFRESH_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    _CachedSource,
    _https_url,
    _integer,
    _objects,
    _slug,
)

MAX_ALERTS = 5
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentry_discord_alerts (
    issue_id TEXT NOT NULL,
    alert_kind TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (issue_id, alert_kind)
)
"""
State = dict[tuple[str, str], datetime]


@dataclass(frozen=True)
class _Alert:
    issue_id: str
    kind: str
    occurred_at: datetime
    content: str


def _instant(raw: str) -> datetime:
    instant = datetime.fromisoformat(raw)
    if instant.tzinfo is None:
        raise ValueError("Expected an aware timestamp")
    return instant.astimezone(UTC)


def _webhook_url(raw: str) -> str:
    parsed = urlsplit(_https_url(raw))
    if (parsed.netloc not in {"discord.com", "discordapp.com"}
            or not re.fullmatch(r"/api/webhooks/[0-9]+/[a-zA-Z0-9._-]+", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("Expected a Discord webhook URL")
    return raw


def _record(connection: sqlite3.Connection, rows: list[tuple[str, str, datetime]]) -> None:
    with connection:
        connection.executemany(
            """INSERT INTO sentry_discord_alerts VALUES (?, ?, ?)
            ON CONFLICT(issue_id, alert_kind) DO UPDATE SET occurred_at=excluded.occurred_at""",
            [(issue_id, kind, at.isoformat()) for issue_id, kind, at in rows],
        )


def _state(connection: sqlite3.Connection, started: datetime) -> State:
    connection.execute(_SCHEMA)
    # Empty issue ids are reserved for the durable startup cutoff and retry time.
    with connection:
        connection.execute(
            "INSERT OR IGNORE INTO sentry_discord_alerts VALUES ('', 'started', ?)", (started.isoformat(),),
        )
    return {(issue_id, kind): _instant(at) for issue_id, kind, at in connection.execute(
        "SELECT issue_id, alert_kind, occurred_at FROM sentry_discord_alerts",
    )}


def _retry_delay(response: HTTPResponse) -> float:
    delays = [float(REFRESH_SECONDS)]
    header = response.getheader("Retry-After")
    try:
        # Discord supplies seconds, including fractional seconds, in both forms.
        payload = json.loads(response.read(4096))
        body_delay = payload.get("retry_after") if isinstance(payload, dict) else None
    except (ValueError, UnicodeError, OSError, HTTPException):
        body_delay = None
    for raw in (header, body_delay):
        try:
            delay = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(delay) and delay >= 0:
            delays.append(delay)
    return max(delays)


def _post(webhook: str, content: str) -> tuple[int, float]:
    parsed = urlsplit(webhook)
    payload = json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode("utf-8")
    # HTTPX logs full request URLs at INFO. The webhook path is a credential;
    # http.client has no request logger and never follows redirects.
    with closing(HTTPSConnection(parsed.netloc, timeout=REQUEST_TIMEOUT_SECONDS)) as connection:
        connection.request("POST", parsed.path, body=payload, headers={
            "Content-Type": "application/json", "User-Agent": "MAYOS-Sentry-Alerts",
        })
        response = connection.getresponse()
        return response.status, _retry_delay(response) if response.status == 429 else 0.0


def _issues(client: httpx.Client, org: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for _ in range(MAX_PAGES):
        response = client.get(f"/api/0/organizations/{org}/issues/", params=params)
        response.raise_for_status()
        yield from _objects(response.json())
        following = response.links.get("next", {})
        if following.get("results") != "true":
            return
        # Never send the Sentry credential to a URL from a pagination response.
        params["cursor"] = parse_qs(urlsplit(following["url"]).query)["cursor"][0]
    raise ValueError("Too many Sentry alert pages")


def _regressed_at(client: httpx.Client, path: str, environment: str) -> datetime | None:
    response = client.get(path, params={"environment": environment})
    response.raise_for_status()
    activity = _objects(response.json()["activity"])
    # lastSeen is not the regression time: old regressions may keep receiving events.
    return max((_instant(entry["dateCreated"]) for entry in activity
                if entry.get("type") == "set_regression"), default=None)


class SentryDiscordProvider:
    key = "sentry_discord"

    def __init__(self, database_path: Callable[[], Path | None]) -> None:
        self.measurements = HourlyMeasurements()
        self._database_path = database_path
        self._started = datetime.now(UTC)
        self._token = os.getenv("SENTRY_READ_TOKEN", "").strip()
        self._webhook = os.getenv("DISCORD_ALERT_WEBHOOK_URL", "").strip()
        self._environment = (os.getenv("SENTRY_ENVIRONMENT", "").strip()
                             or os.getenv("MAYOS_ENV", "").strip())
        self._org = os.getenv("SENTRY_ORG", "mayos").strip()
        self._projects = os.getenv("SENTRY_PROJECTS", "mayos-api,mayos-app").split(",")
        self._host = os.getenv("SENTRY_API_BASE_URL", "https://de.sentry.io").strip()
        # Reuse outside.py's worker, cadence and credential-safe exception boundary.
        self._source = _CachedSource(self._refresh if self._token and self._webhook else None, "")

    def sample(self) -> None:
        self._source.sample()

    def render(self, view: MonitoringView) -> str:
        return ""

    def _title(self, raw: Any) -> str:
        if not isinstance(raw, str):
            raise ValueError("Expected an issue title")
        webhook_token = urlsplit(self._webhook).path.rsplit("/", 1)[-1]
        for secret in (self._token, self._webhook, webhook_token):
            if secret:
                raw = raw.replace(html.escape(secret), "[redacted]").replace(secret, "[redacted]")
        title = " ".join(raw.split())[:160].replace("<", "‹").replace(">", "›")
        return re.sub(r"([\\`*_{}\[\]()#+\-.!|~])", r"\\\1", title)

    def _pending(self, client: httpx.Client, state: State) -> list[_Alert]:
        started = state[("", "started")]
        projects = list(dict.fromkeys(_slug(project.strip()) for project in self._projects))
        params = {"project": projects, "environment": self._environment, "limit": "100",
                  "query": f"lastSeen:>{started.isoformat()}", "sort": "date", "statsPeriod": ""}
        pending: dict[str, _Alert] = {}
        for issue in _issues(client, self._org, params):
            project = _slug(issue["project"]["slug"])
            if project not in projects or _instant(issue["lastSeen"]) <= started:
                continue
            issue_id = str(_integer(issue["id"]))
            kind, occurred_at = "new", _instant(issue["firstSeen"])
            if occurred_at <= max(started, state.get((issue_id, kind), started)):
                if issue.get("substatus") != "regressed":
                    continue
                kind = "regressed"
                occurred_at = _regressed_at(
                    client, f"/api/0/organizations/{self._org}/issues/{issue_id}/", self._environment,
                )
                if occurred_at is None or occurred_at <= max(started, state.get((issue_id, kind), started)):
                    continue
            content = (f"Sentry {kind} | {project} | {self._title(issue['title'])} | "
                       f"{_integer(issue['count']):,} events | <https://{self._org}.sentry.io/issues/{issue_id}/>")
            pending[issue_id] = _Alert(issue_id, kind, occurred_at, content)
        return sorted(pending.values(), key=lambda alert: (alert.occurred_at, alert.issue_id))

    def _restore(self, connection: sqlite3.Connection, alerts: list[_Alert], state: State) -> None:
        with connection:
            for alert in alerts:
                previous = state.get((alert.issue_id, alert.kind))
                if previous is None:
                    connection.execute("DELETE FROM sentry_discord_alerts WHERE issue_id=? AND alert_kind=?",
                                       (alert.issue_id, alert.kind))
                else:
                    connection.execute("UPDATE sentry_discord_alerts SET occurred_at=? WHERE issue_id=? AND alert_kind=?",
                                       (previous.isoformat(), alert.issue_id, alert.kind))

    def _send(self, connection: sqlite3.Connection, alerts: list[_Alert], state: State, content: str) -> None:
        # Claim durably before sending: a crash or ambiguous network failure must
        # not repeat a message on restart. Known rejections release the claim.
        _record(connection, [(alert.issue_id, alert.kind, alert.occurred_at) for alert in alerts])
        status, delay = _post(self._webhook, content)
        if 200 <= status < 300:
            return
        self._restore(connection, alerts, state)
        if status == 429:
            _record(connection, [("", "retry", datetime.now(UTC) + timedelta(seconds=delay))])
        raise ValueError("Discord rejected an alert")

    def _refresh(self) -> str:
        _webhook_url(self._webhook)
        self._org = _slug(self._org)
        host = _https_url(self._host).rstrip("/")
        parsed = urlsplit(host)
        if parsed.path or parsed.query or parsed.fragment or not self._environment:
            raise ValueError("Expected a Sentry API origin and deployment environment")
        path = self._database_path()
        if path is None:
            raise ValueError("Monitoring storage is not ready")
        with closing(sqlite3.connect(path, timeout=1)) as connection:
            state = _state(connection, self._started)
            if datetime.now(UTC) < state.get(("", "retry"), self._started):
                return ""
            with httpx.Client(base_url=host, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
                              headers={"Authorization": f"Bearer {self._token}"}) as client:
                pending = self._pending(client, state)
            for alert in pending[:MAX_ALERTS]:
                self._send(connection, [alert], state, alert.content)
            if len(pending) > MAX_ALERTS:
                overflow = pending[MAX_ALERTS:]
                self._send(connection, overflow, state, f"Sentry: and {len(overflow)} more issues.")
        return ""


def create_provider(app: Any) -> SentryDiscordProvider:
    # Provider discovery precedes assignment of app.state.monitoring and its store.
    def database_path() -> Path | None:
        monitoring = getattr(app.state, "monitoring", None)
        store = getattr(monitoring, "store", None)
        return store.path if store is not None else None

    return SentryDiscordProvider(database_path)
