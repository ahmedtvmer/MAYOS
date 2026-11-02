"""Sentry's API boundary keeps only a purpose-limited account identifier."""

import json

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

pytest.importorskip("sentry_sdk")

import sentry_sdk

from svc.app import create_app
from svc.error_tracking import SERVER_ERROR_MESSAGE, anonymous_account_id, set_account_user


class CapturingTransport(sentry_sdk.transport.Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(json.loads(item.get_bytes()))


def test_api_event_scrubs_request_and_keeps_only_anonymous_id(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-anonymous-id")
    monkeypatch.setenv("SENTRY_RELEASE", "abc123")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    transport = CapturingTransport()
    app = create_app(sentry_transport=transport)

    @app.post("/privacy-probe/{user_name}")
    async def privacy_probe(user_name: str):
        set_account_user("account-secret")
        raise RuntimeError("username-secret email-secret body-secret")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/privacy-probe/username-secret?query-secret=yes",
            headers={"Authorization": "Bearer auth-secret", "X-Username": "username-secret"},
            cookies={"session": "cookie-secret"},
            json={"message": "body-secret", "email": "email-secret"},
        )
        assert client.get("/missing-route?should-not-report=1").status_code == 404
    assert response.status_code == 502
    assert len(transport.events) == 1
    failure_counts = [
        row for row in app.state.request_metrics.snapshot()["since_start"]
        if row["route"] == "/privacy-probe/{user_name}" and row["status_class"] == "5xx"
    ]
    assert len(failure_counts) == 1
    assert failure_counts[0]["count"] == 1
    event = transport.events[0]
    serialized = json.dumps(event)
    for secret in (
        "query-secret", "auth-secret", "username-secret", "cookie-secret",
        "body-secret", "email-secret", "account-secret",
    ):
        assert secret not in serialized
    assert event["user"] == {"id": anonymous_account_id("account-secret")}
    assert [value["type"] for value in event["exception"]["values"]] == ["RuntimeError"]
    assert event["release"] == "abc123"
    assert event["environment"] == "test"
    assert event["transaction"] == "/privacy-probe/{user_name}"


def test_logger_error_does_not_create_event(monkeypatch):
    import logging

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-anonymous-id")
    transport = CapturingTransport()
    app = create_app(sentry_transport=transport)

    @app.get("/log-probe")
    async def log_probe():
        logging.getLogger("privacy-test").error("email-secret username-secret")
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/log-probe").status_code == 200
    assert transport.events == []


def test_handled_503_emits_one_fixed_message_with_route_template(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-anonymous-id")
    transport = CapturingTransport()
    app = create_app(sentry_transport=transport)

    @app.get("/failure/{user_name}")
    async def failure(user_name: str):
        set_account_user("account-secret")
        raise HTTPException(status_code=503, detail="email-secret username-secret")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/failure/username-secret?query-secret=yes",
            headers={"Authorization": "Bearer auth-secret"},
            cookies={"session": "cookie-secret"},
        )
    assert response.status_code == 503
    assert len(transport.events) == 1
    event = transport.events[0]
    serialized = json.dumps(event)
    for secret in ("query-secret", "auth-secret", "username-secret", "cookie-secret", "email-secret"):
        assert secret not in serialized
    assert event["message"] == SERVER_ERROR_MESSAGE
    assert event["transaction"] == "/failure/{user_name}"


def test_anonymous_id_is_stable_and_secret_keyed(monkeypatch):
    monkeypatch.setenv("ANONYMOUS_ID_SECRET", "secret-one")
    first = anonymous_account_id("account-123")
    assert anonymous_account_id("account-123") == first
    monkeypatch.setenv("ANONYMOUS_ID_SECRET", "secret-two")
    assert anonymous_account_id("account-123") != first
    assert "account-123" not in first
