"""Discord alert behavior with fake HTTP, real workers and disposable SQLite."""

import io
import json
import logging
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from types import SimpleNamespace

import httpx
import pytest

from svc.monitoring.runtime import Monitoring, MonitoringView
from svc.monitoring.store import MetricsStore
from svc.monitoring.tiles import outside, sentry_discord
from svc.request_metrics import RequestMetrics

START = datetime(2026, 11, 7, 12, tzinfo=UTC)
TOKEN = "sentry-read-secret"
WEBHOOK_TOKEN = "discord-secret-token"
WEBHOOK = f"https://discord.com/api/webhooks/123/{WEBHOOK_TOKEN}"
VIEW = MonitoringView(24, START, [])


@pytest.fixture
def alert_setup(monkeypatch, tmp_path):
    for name in ("SENTRY_READ_TOKEN", "DISCORD_ALERT_WEBHOOK_URL", "SENTRY_ENVIRONMENT", "MAYOS_ENV",
                 "SENTRY_ORG", "SENTRY_PROJECTS", "SENTRY_API_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SENTRY_READ_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    clock = [0]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return START + timedelta(seconds=clock[0])

    monkeypatch.setattr(sentry_discord, "datetime", Clock)
    monkeypatch.setattr(outside.time, "monotonic", lambda: 1000 + clock[0])
    app = SimpleNamespace(state=SimpleNamespace(
        monitoring=SimpleNamespace(store=MetricsStore(tmp_path / "catalog.db")),
    ))
    return SimpleNamespace(app=app, clock=clock)


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
        assert not worker.is_alive(), "Sentry alert worker did not finish"


@pytest.fixture
def fake_http(monkeypatch):
    client_type = httpx.Client

    def install(sentry_response, discord_response=lambda request: httpx.Response(204)):
        reads, posts = [], []

        def read(request):
            reads.append(request)
            assert request.url.host == "de.sentry.io"
            assert request.headers["authorization"] == f"Bearer {TOKEN}"
            assert request.extensions["timeout"]["read"] == outside.REQUEST_TIMEOUT_SECONDS
            return sentry_response(request)

        class DiscordConnection:
            def __init__(self, host, timeout):
                self.host = host
                assert host in {"discord.com", "discordapp.com"}
                assert timeout == outside.REQUEST_TIMEOUT_SECONDS

            def request(self, method, path, body, headers):
                request = httpx.Request(method, f"https://{self.host}{path}", content=body, headers=headers)
                assert "authorization" not in request.headers
                posts.append(request)
                self.response = discord_response(request)

            def getresponse(self):
                return SimpleNamespace(status=self.response.status_code,
                                       getheader=self.response.headers.get,
                                       read=io.BytesIO(self.response.content).read)

            def close(self):
                pass

        monkeypatch.setattr(sentry_discord, "HTTPSConnection", DiscordConnection)
        monkeypatch.setattr(sentry_discord.httpx, "Client", lambda **kwargs: client_type(
            transport=httpx.MockTransport(read), **kwargs,
        ))
        return SimpleNamespace(reads=reads, posts=posts)

    return install


def _issue(issue_id, *, first=1, last=1, substatus="new", project="mayos-api", title="RuntimeError"):
    return {"id": str(issue_id), "title": title, "count": "12", "project": {"slug": project},
            "firstSeen": (START + timedelta(seconds=first)).isoformat(),
            "lastSeen": (START + timedelta(seconds=last)).isoformat(), "substatus": substatus,
            "permalink": "https://untrusted.example/PRIVATE", "user": {"email": "PRIVATE-EMAIL"}}


def _activity(at):
    return {"type": "set_regression", "dateCreated": (START + timedelta(seconds=at)).isoformat(),
            "user": {"email": "PRIVATE-EMAIL"}}


def _refresh(provider, workers):
    provider.sample()
    for worker in list(workers):
        worker.join(2)
        assert not worker.is_alive()


def _payloads(network):
    return [json.loads(request.content) for request in network.posts]


@pytest.mark.parametrize("host", ["discord.com", "discordapp.com"])
def test_new_issue_posts_plain_title_count_and_safe_link_with_mentions_disabled(
    alert_setup, workers, fake_http, monkeypatch, host,
):
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", WEBHOOK.replace("discord.com", host))
    title = f"**failure**\n@everyone <@123> {TOKEN} {WEBHOOK_TOKEN}"
    network = fake_http(lambda request: httpx.Response(200, json=[_issue(1, title=title)]))
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)

    payload, = _payloads(network)
    assert payload["allowed_mentions"] == {"parse": []}
    content = payload["content"]
    assert "Sentry new | mayos-api" in content and "12 events" in content
    assert "<https://mayos.sentry.io/issues/1/>" in content
    assert r"\*\*failure\*\* @everyone ‹@123›" in content
    assert all(private not in content for private in (TOKEN, WEBHOOK_TOKEN, "PRIVATE", "untrusted.example"))
    assert provider.render(VIEW) == ""
    request, = network.reads
    assert request.url.path == "/api/0/organizations/mayos/issues/"
    assert request.url.params.get_list("project") == ["mayos-api", "mayos-app"]
    assert request.url.params["environment"] == "production"
    assert request.url.params["query"] == f"lastSeen:>{START.isoformat()}"


def test_regression_uses_activity_date_deduplicates_after_restart_and_allows_a_later_regression(
    alert_setup, workers, fake_http,
):
    regression_at = [1]

    def respond(request):
        if request.url.path.endswith("/1/"):
            assert request.url.params["environment"] == "production"
            return httpx.Response(200, json={"activity": [_activity(regression_at[0])]})
        return httpx.Response(200, json=[_issue(1, first=-86400, last=601, substatus="regressed")])

    network = fake_http(respond)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    assert "Sentry regressed" in _payloads(network)[0]["content"]
    alert_setup.clock[0] = 301
    restarted = sentry_discord.create_provider(alert_setup.app)
    _refresh(restarted, workers)
    assert len(network.posts) == 1
    regression_at[0] = 302
    alert_setup.clock[0] = 601
    _refresh(restarted, workers)
    assert len(network.posts) == 2


def test_restart_keeps_sent_issues_and_original_cutoff_including_issues_seen_during_downtime(
    alert_setup, workers, fake_http,
):
    issues = [_issue(1)]
    network = fake_http(lambda request: httpx.Response(200, json=issues))
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    alert_setup.clock[0] = 601
    issues.append(_issue(2, first=400, last=400, project="mayos-app"))
    _refresh(sentry_discord.create_provider(alert_setup.app), workers)
    contents = [payload["content"] for payload in _payloads(network)]
    assert len(contents) == 2
    assert "/issues/1/" in contents[0] and "/issues/2/" in contents[1]
    assert all(request.url.params["query"] == f"lastSeen:>{START.isoformat()}" for request in network.reads)


def test_new_issue_can_later_alert_as_regressed_with_the_same_issue_id(alert_setup, workers, fake_http):
    issue = _issue(1)

    def respond(request):
        if request.url.path.endswith("/1/"):
            return httpx.Response(200, json={"activity": [_activity(300)]})
        return httpx.Response(200, json=[issue])

    network = fake_http(respond)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    issue.update(substatus="regressed", lastSeen=(START + timedelta(seconds=300)).isoformat())
    alert_setup.clock[0] = 301
    _refresh(provider, workers)
    contents = [payload["content"] for payload in _payloads(network)]
    assert len(contents) == 2
    assert "Sentry new" in contents[0] and "Sentry regressed" in contents[1]


def test_first_run_does_not_alert_old_or_boundary_issues_or_old_regressions_still_receiving_events(
    alert_setup, workers, fake_http,
):
    issues = [_issue(1, first=-86400), _issue(2, first=0),
              _issue(3, first=-86400, substatus="regressed"),
              _issue(4, first=-86400, substatus="regressed"),
              _issue(5, project="another-project")]

    def respond(request):
        if request.url.path.endswith("/3/"):
            return httpx.Response(200, json={"activity": [_activity(-1)]})
        if request.url.path.endswith("/4/"):
            return httpx.Response(200, json={"activity": [_activity(0)]})
        return httpx.Response(200, json=issues)

    network = fake_http(respond)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    alert_setup.clock[0] = 301
    _refresh(sentry_discord.create_provider(alert_setup.app), workers)
    assert network.posts == []


@pytest.mark.parametrize("count", [5, 6, 9])
def test_cap_sends_five_issue_messages_then_one_summary_and_remembers_summarized_issues(
    alert_setup, workers, fake_http, count,
):
    network = fake_http(lambda request: httpx.Response(200, json=[_issue(index) for index in range(1, count + 1)]))
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    payloads = _payloads(network)
    assert len(payloads) == 5 + (count > 5)
    assert all("/issues/" in payload["content"] for payload in payloads[:5])
    if count > 5:
        assert payloads[-1]["content"] == f"Sentry: and {count - 5} more issues."
    assert all(payload["allowed_mentions"] == {"parse": []} for payload in payloads)
    alert_setup.clock[0] = 301
    _refresh(sentry_discord.create_provider(alert_setup.app), workers)
    assert len(network.posts) == len(payloads)


def test_pagination_reuses_only_cursor_and_counts_overflow_across_projects(alert_setup, workers, fake_http):
    def respond(request):
        if "cursor" in request.url.params:
            assert request.url.params["cursor"] == "page-two"
            return httpx.Response(200, json=[_issue(6, project="mayos-app"), _issue(7, project="mayos-app")])
        return httpx.Response(200, json=[_issue(index) for index in range(1, 6)], headers={
            "Link": '<https://untrusted.example/?cursor=page-two>; rel="next"; results="true"',
        })

    network = fake_http(respond)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    assert len(network.reads) == 2
    assert _payloads(network)[-1]["content"] == "Sentry: and 2 more issues."


@pytest.mark.parametrize(("header", "body", "wait"), [("600", 900, 900), ("900", 600, 900), (None, None, 300)])
def test_discord_429_stops_batch_and_retries_after_deadline_even_after_restart(
    alert_setup, workers, fake_http, header, body, wait,
):
    attempts = []

    def discord_response(request):
        attempts.append(request)
        if len(attempts) == 2:
            return httpx.Response(429, headers={"Retry-After": header} if header else {},
                                  json={"retry_after": body, "message": "PRIVATE-BODY"})
        return httpx.Response(204)

    network = fake_http(lambda request: httpx.Response(200, json=[_issue(1), _issue(2), _issue(3)]), discord_response)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    assert len(network.posts) == 2
    alert_setup.clock[0] = wait
    restarted = sentry_discord.create_provider(alert_setup.app)
    _refresh(restarted, workers)
    assert len(network.posts) == 2 and len(network.reads) == 1
    # Its first sample scheduled another refresh; the retry deadline is persisted,
    # while the cadence remains once per five minutes after a process starts.
    alert_setup.clock[0] = wait + 300
    _refresh(restarted, workers)
    contents = [payload["content"] for payload in _payloads(network)]
    assert len(contents) == 4
    assert sum("/issues/1/" in content for content in contents) == 1
    assert "/issues/2/" in contents[2] and "/issues/3/" in contents[3]


@pytest.mark.parametrize("missing", [("SENTRY_READ_TOKEN",), ("DISCORD_ALERT_WEBHOOK_URL",),
                                     ("SENTRY_READ_TOKEN", "DISCORD_ALERT_WEBHOOK_URL")])
def test_missing_credentials_are_off_without_workers_http_or_database_writes(
    alert_setup, workers, fake_http, monkeypatch, missing,
):
    for name in missing:
        monkeypatch.delenv(name)
    network = fake_http(lambda request: httpx.Response(200, json=[_issue(1)]))
    provider = sentry_discord.create_provider(alert_setup.app)
    _refresh(provider, workers)
    assert workers == [] and network.reads == [] and network.posts == []
    assert not alert_setup.app.state.monitoring.store.path.exists()
    assert provider.render(VIEW) == ""


@pytest.mark.parametrize(("sentry_environment", "mayos_environment", "expected"), [
    ("staging", "production", "staging"), ("", "production", "production"), ("", "", None),
])
def test_environment_is_scoped_with_fallback_and_never_queries_all_environments(
    alert_setup, workers, fake_http, monkeypatch, sentry_environment, mayos_environment, expected,
):
    monkeypatch.setenv("SENTRY_ENVIRONMENT", sentry_environment)
    monkeypatch.setenv("MAYOS_ENV", mayos_environment)
    network = fake_http(lambda request: httpx.Response(200, json=[]))
    _refresh(sentry_discord.create_provider(alert_setup.app), workers)
    assert [request.url.params["environment"] for request in network.reads] == ([] if expected is None else [expected])
    assert network.posts == []


@pytest.mark.parametrize("url", [
    "http://discord.com/api/webhooks/123/token", "https://discord.com.evil.test/api/webhooks/123/token",
    "https://discordapp.com@evil.test/api/webhooks/123/token", "https://discord.com:8443/api/webhooks/123/token",
    "https://discord.com/other/123/token", "https://discord.com/api/webhooks/123/token?redirect=evil",
    "https://discord.com/api/webhooks/123/token#fragment", "https://discord.com/api/webhooks/123/to\nken",
])
def test_invalid_webhooks_never_make_network_requests(alert_setup, workers, fake_http, monkeypatch, url):
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", url)
    network = fake_http(lambda request: httpx.Response(200, json=[_issue(1)]))
    provider = sentry_discord.create_provider(alert_setup.app)
    _refresh(provider, workers)
    assert network.reads == [] and network.posts == []
    assert provider.render(VIEW) == ""


@pytest.mark.parametrize("failure", ["success", "sentry-timeout", "sentry-body", "discord-body", "discord-timeout"])
def test_success_and_failures_never_log_secrets_response_bodies_or_exception_text(
    alert_setup, workers, fake_http, caplog, failure,
):
    private = f"{TOKEN} {WEBHOOK} PRIVATE-BODY"
    caplog.set_level(logging.DEBUG)

    def sentry_response(request):
        if failure == "sentry-timeout":
            raise httpx.ReadTimeout(private, request=request)
        if failure == "sentry-body":
            return httpx.Response(403, text=private)
        return httpx.Response(200, json=[_issue(1, title=private)])

    def discord_response(request):
        if failure == "discord-timeout":
            raise OSError(private)
        return httpx.Response(500 if failure == "discord-body" else 204, text=private)

    network = fake_http(sentry_response, discord_response)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    assert provider.render(VIEW) == ""
    assert all(secret not in caplog.text for secret in (TOKEN, WEBHOOK, WEBHOOK_TOKEN, "PRIVATE-BODY"))
    if failure == "success":
        assert len(network.posts) == 1


def test_ambiguous_post_failure_keeps_durable_claim_to_prevent_a_repeat_on_restart(
    alert_setup, workers, fake_http,
):
    def discord_response(request):
        raise OSError("connection lost after Discord may have accepted the alert")

    network = fake_http(lambda request: httpx.Response(200, json=[_issue(1)]), discord_response)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    alert_setup.clock[0] = 301
    _refresh(sentry_discord.create_provider(alert_setup.app), workers)
    assert len(network.posts) == 1


@pytest.mark.parametrize("status", [302, 500])
def test_explicit_discord_rejection_retries_without_following_redirects(
    alert_setup, workers, fake_http, status,
):
    attempts = []

    def discord_response(request):
        attempts.append(request)
        return (httpx.Response(status, headers={"Location": "https://untrusted.example/"})
                if len(attempts) == 1 else httpx.Response(204))

    network = fake_http(lambda request: httpx.Response(200, json=[_issue(1)]), discord_response)
    provider = sentry_discord.create_provider(alert_setup.app)
    alert_setup.clock[0] = 1
    _refresh(provider, workers)
    assert len(network.posts) == 1
    alert_setup.clock[0] = 301
    _refresh(sentry_discord.create_provider(alert_setup.app), workers)
    assert len(network.posts) == 2
    assert all(request.url.host == "discord.com" for request in network.posts)


def test_slow_http_never_holds_monitoring_lock_or_starts_a_duplicate_worker(alert_setup, workers, fake_http):
    entered, release = Event(), Event()

    def respond(request):
        entered.set()
        if not release.wait(2):
            raise httpx.ReadTimeout("fake timeout", request=request)
        return httpx.Response(200, json=[])

    fake_http(respond)
    app = SimpleNamespace(state=SimpleNamespace(request_metrics=RequestMetrics()))
    monitoring = Monitoring(app)
    app.state.monitoring = monitoring
    monitoring.store = alert_setup.app.state.monitoring.store
    monitoring.providers = [provider for provider in monitoring.providers if provider.key == "sentry_discord"]
    assert len(monitoring.providers) == 1
    try:
        monitoring.flush()
        assert entered.wait(1)
        assert "Measurement unavailable" not in monitoring.render(24)
        assert not release.is_set()
        alert_setup.clock[0] = 301
        monitoring.flush()
        assert len(workers) == 1
    finally:
        release.set()


def test_minute_samples_and_page_reads_do_not_repeat_refreshes(alert_setup, workers, fake_http):
    network = fake_http(lambda request: httpx.Response(200, json=[]))
    provider = sentry_discord.create_provider(alert_setup.app)
    _refresh(provider, workers)
    for minute in range(1, 5):
        alert_setup.clock[0] = minute * 60
        _refresh(provider, workers)
        assert provider.render(VIEW) == ""
    assert len(network.reads) == 1
    alert_setup.clock[0] = 300
    _refresh(provider, workers)
    assert len(network.reads) == 2


def test_unavailable_monitoring_database_does_not_post_or_break_rendering(alert_setup, workers, fake_http):
    alert_setup.app.state.monitoring.store = MetricsStore(
        alert_setup.app.state.monitoring.store.path.parent / "missing-directory" / "catalog.db",
    )
    network = fake_http(lambda request: httpx.Response(200, json=[_issue(1)]))
    provider = sentry_discord.create_provider(alert_setup.app)
    _refresh(provider, workers)
    assert network.reads == [] and network.posts == []
    assert provider.render(VIEW) == ""
