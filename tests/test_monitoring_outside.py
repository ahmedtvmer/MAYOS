"""Outside summaries use fake HTTP, real workers and no service credentials."""

import logging
from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from svc.monitoring.runtime import Monitoring, MonitoringView
from svc.monitoring.tiles import outside
from svc.request_metrics import RequestMetrics

VIEW = MonitoringView(24, datetime(2026, 11, 7, 12, tzinfo=UTC), [])


@pytest.fixture
def outside_environment(monkeypatch):
    for name in ("SENTRY_READ_TOKEN", "SENTRY_ORG", "SENTRY_PROJECTS", "SENTRY_API_BASE_URL",
                 "UPTIMEROBOT_READ_KEY", "POSTHOG_PROJECT_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SENTRY_READ_TOKEN", "sentry-secret-token")
    monkeypatch.setenv("UPTIMEROBOT_READ_KEY", "uptimerobot-secret-key")
    clock = [1000.0]
    monkeypatch.setattr(outside.time, "monotonic", lambda: clock[0])
    return clock


@pytest.fixture
def workers(monkeypatch):
    started = []

    def create_worker(**kwargs):
        worker = Thread(**kwargs)
        started.append(worker)
        return worker

    monkeypatch.setattr(outside, "Thread", create_worker)
    yield started
    for worker in started:
        worker.join(2)
        assert not worker.is_alive(), "Outside refresh worker did not finish"


@pytest.fixture
def fake_http(monkeypatch):
    client_type = httpx.Client

    def install(respond):
        transport = httpx.MockTransport(respond)
        monkeypatch.setattr(outside.httpx, "Client", lambda **kwargs: client_type(transport=transport, **kwargs))

    return install


def _refresh(provider, workers):
    provider.sample()
    for worker in list(workers):
        worker.join(2)
        assert not worker.is_alive()


def _issue(issue_id, title="RuntimeError"):
    return {"id": str(issue_id), "title": title, "count": "12",
            "userCount": 99, "culprit": "PRIVATE-CULPRIT", "message": "PRIVATE-MESSAGE",
            "permalink": "javascript:alert(1)", "user": {"email": "PRIVATE-EMAIL"}}


def _monitor(name="API", status=2):
    return {"friendly_name": name, "status": status, "custom_uptime_ratios": "99.5-99.9-99.95",
            "url": "https://PRIVATE-MONITOR-URL", "http_password": "PRIVATE-PASSWORD",
            "logs": [{"type": 1, "datetime": 1794052800, "duration": 125, "reason": "PRIVATE-REASON"}]}


def _uptime_response(monitors, total=None):
    return httpx.Response(200, json={"stat": "ok", "monitors": monitors,
                                    "pagination": {"total": len(monitors) if total is None else total}})


def test_fake_services_render_paginated_totals_newest_issues_uptime_and_safe_links(
    outside_environment, workers, fake_http, monkeypatch, caplog,
):
    monkeypatch.setenv("SENTRY_API_BASE_URL", "https://eu-errors.example.test")
    monkeypatch.setenv("SENTRY_PROJECTS", "mayos-api, mayos-app")
    monkeypatch.setenv("POSTHOG_PROJECT_URL", "https://eu.posthog.com/project/42?x=1&y=2")
    caplog.set_level(logging.DEBUG)

    def respond(request):
        assert all(secret not in str(request.url) for secret in ("sentry-secret-token", "uptimerobot-secret-key"))
        assert request.extensions["timeout"]["read"] == outside.REQUEST_TIMEOUT_SECONDS
        if request.method == "POST":
            form = parse_qs(request.content.decode())
            assert form["custom_uptime_ratios"] == ["1-7-30"]
            assert form["api_key"] == ["uptimerobot-secret-key"]
            if form["offset"] == ["0"]:
                return _uptime_response([_monitor('<b>API & "web"</b>')], total=2)
            return _uptime_response([_monitor("App", 0)], total=2)
        assert request.url.host == "eu-errors.example.test"
        assert request.headers["authorization"] == "Bearer sentry-secret-token"
        assert request.url.params["query"] == "is:unresolved"
        assert request.url.params["sort"] == "new"
        if "mayos-app" in request.url.path:
            return httpx.Response(200, json=[])
        if "cursor" in request.url.params:
            return httpx.Response(200, json=[_issue(101), _issue(102)])
        return httpx.Response(200, json=[_issue(index, '<script>alert("x")</script> & sentry-secret-token')
                                        for index in range(1, 101)], headers={
            "Link": '<https://untrusted.example/issues/?cursor=next-page>; rel="next"; results="true"',
        })

    fake_http(respond)
    provider = outside.create_provider(None)
    _refresh(provider, workers)
    page = provider.render(VIEW)
    assert "102 unresolved" in page and "0 unresolved" in page
    assert page.count("12 events") == 5
    assert 'href="https://mayos.sentry.io/issues/1/"' in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; [redacted]" in page
    assert "&lt;b&gt;API &amp; &quot;web&quot;&lt;/b&gt;" in page
    assert all(fragment in page for fragment in ("Up</td>", "Paused</td>", "99.500%", "99.900%", "99.950%",
                                                 "125 seconds", "2026-11-07", "UTC", "Last successful refresh"))
    assert 'href="https://eu.posthog.com/project/42?x=1&amp;y=2"' in page
    assert all(private not in page for private in ("PRIVATE-", "javascript:", "userCount", "<script>"))
    assert "sentry-secret-token" not in page + caplog.text
    assert "uptimerobot-secret-key" not in page + caplog.text
    assert provider.measurements.snapshot() == []


@pytest.mark.parametrize(("failed_service", "failure"), [
    ("sentry", "timeout"), ("uptimerobot", "timeout"), ("sentry", "http"),
    ("uptimerobot", "api"), ("sentry", "malformed"),
])
def test_failed_refresh_is_local_keeps_stale_values_and_never_exposes_exception_text(
    outside_environment, workers, fake_http, caplog, failed_service, failure,
):
    fail = [False]
    caplog.set_level(logging.DEBUG)

    def respond(request):
        service = "sentry" if request.method == "GET" else "uptimerobot"
        if fail[0] and service == failed_service:
            if failure == "timeout":
                raise httpx.ReadTimeout("sentry-secret-token uptimerobot-secret-key PRIVATE-ERROR", request=request)
            if failure == "http":
                return httpx.Response(403, text="sentry-secret-token PRIVATE-ERROR")
            if failure == "malformed":
                return httpx.Response(200, json={"detail": "sentry-secret-token PRIVATE-ERROR"})
            return httpx.Response(200, json={"stat": "fail", "error": "uptimerobot-secret-key PRIVATE-ERROR"})
        return httpx.Response(200, json=[_issue(1)]) if service == "sentry" else _uptime_response([_monitor()])

    fake_http(respond)
    provider = outside.create_provider(None)
    _refresh(provider, workers)
    fail[0] = True
    outside_environment[0] += outside.REFRESH_SECONDS
    _refresh(provider, workers)
    page = provider.render(VIEW)
    assert page.count("Refresh unavailable") == 1
    assert page.count("Cached values may be stale") == 1
    assert "RuntimeError" in page and "99.500%" in page
    for secret in ("sentry-secret-token", "uptimerobot-secret-key", "PRIVATE-ERROR"):
        assert secret not in page + caplog.text


@pytest.mark.parametrize("missing", [("SENTRY_READ_TOKEN",), ("UPTIMEROBOT_READ_KEY",),
                                     ("SENTRY_READ_TOKEN", "UPTIMEROBOT_READ_KEY")])
def test_missing_credentials_show_local_setup_notes_while_other_sources_work(
    outside_environment, workers, fake_http, monkeypatch, missing,
):
    for credential in missing:
        monkeypatch.delenv(credential)

    def respond(request):
        credential = "SENTRY_READ_TOKEN" if request.method == "GET" else "UPTIMEROBOT_READ_KEY"
        assert credential not in missing
        return httpx.Response(200, json=[_issue(1)]) if request.method == "GET" else _uptime_response([_monitor()])

    fake_http(respond)
    provider = outside.create_provider(None)
    _refresh(provider, workers)
    page = provider.render(VIEW)
    for credential in missing:
        assert f"set {credential} on the server" in page
    if "SENTRY_READ_TOKEN" not in missing:
        assert "RuntimeError" in page
    if "UPTIMEROBOT_READ_KEY" not in missing:
        assert "99.500%" in page
    assert "Set POSTHOG_PROJECT_URL" in page
    assert "unavailable" not in page


def test_cached_reads_and_minute_samples_do_not_refresh_until_five_minutes(
    outside_environment, workers, fake_http,
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[_issue(len(requests))]) if request.method == "GET" else _uptime_response([])

    fake_http(respond)
    provider = outside.create_provider(None)
    _refresh(provider, workers)
    first_page = provider.render(VIEW)
    first_count = len(requests)
    for minute in range(1, 5):
        outside_environment[0] = 1000 + minute * 60
        _refresh(provider, workers)
        assert provider.render(VIEW) == first_page
    assert len(requests) == first_count
    outside_environment[0] = 1300
    _refresh(provider, workers)
    assert provider.render(VIEW) != first_page


def test_slow_refresh_does_not_hold_monitoring_page_lock_or_duplicate_workers(
    outside_environment, workers, fake_http, monkeypatch,
):
    entered, release = Event(), Event()

    def respond(request):
        entered.set()
        if not release.wait(2):
            raise httpx.ReadTimeout("fake timeout", request=request)
        return httpx.Response(200, json=[]) if request.method == "GET" else _uptime_response([])

    fake_http(respond)
    monkeypatch.delenv("UPTIMEROBOT_READ_KEY")
    app = SimpleNamespace(state=SimpleNamespace(request_metrics=RequestMetrics()))
    monitoring = Monitoring(app)
    provider = next(provider for provider in monitoring.providers if provider.key == "outside")
    # Other tickets add providers in parallel; keep this integration case focused.
    monitoring.providers = [provider]
    try:
        monitoring.flush()
        assert entered.wait(1)
        page = monitoring.render(24)
        assert "Waiting for first refresh" in page and not release.is_set()
        outside_environment[0] += outside.REFRESH_SECONDS
        monitoring.flush()
        assert len(workers) == 1
    finally:
        release.set()
    for worker in workers:
        worker.join(2)
    assert "No unresolved issues" in monitoring.render(24)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://secret@example.test/project/1",
                                "https://eu.posthog.com/project/sentry-secret-token"])
def test_invalid_posthog_link_has_no_clickable_or_secret_content(outside_environment, url, monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_URL", url)
    page = outside.create_provider(None).render(VIEW)
    assert "must be an HTTPS project link without credentials" in page
    assert "href=" not in page
    assert "sentry-secret-token" not in page


@pytest.mark.parametrize(("status", "duration", "ratios", "expected"), [
    (9, 0, "100-99-98", "90 seconds (ongoing)"),
    (8, 125, None, "125 seconds</li>"),
])
def test_current_downtime_and_missing_uptime_are_not_misreported(
    outside_environment, workers, fake_http, monkeypatch, status, duration, ratios, expected,
):
    monkeypatch.delenv("SENTRY_READ_TOKEN")
    instant = datetime.fromtimestamp(1794052890, UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(outside, "datetime", Clock)
    monitor = _monitor(status=status)
    monitor["logs"][0]["duration"] = duration
    # Older v2 responses use the singular spelling.
    monitor.pop("custom_uptime_ratios")
    monitor["custom_uptime_ratio"] = ratios
    fake_http(lambda request: _uptime_response([monitor]))
    provider = outside.create_provider(None)
    _refresh(provider, workers)
    page = provider.render(VIEW)
    assert expected in page
    assert '<tr class="monitoring-warning">' in page
    if ratios is None:
        assert page.count("Not available</td>") == 3
        assert "ongoing" not in page
    else:
        assert all(ratio in page for ratio in ("100.000%", "99.000%", "98.000%"))
