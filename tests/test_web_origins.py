"""CORS admits every configured web origin (Cloudflare Pages + local dev, ADR 048)."""

from fastapi.testclient import TestClient

from svc.app import create_app, web_origins


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/healthz",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


def test_web_origins_splits_trims_and_drops_trailing_slash(monkeypatch):
    monkeypatch.setenv("UI_BASE_URL", " https://mayos.pages.dev/ , http://localhost:7357,, ")
    assert web_origins() == ["https://mayos.pages.dev", "http://localhost:7357"]


def test_web_origins_defaults_to_local_dev(monkeypatch):
    monkeypatch.delenv("UI_BASE_URL", raising=False)
    assert web_origins() == ["http://localhost:7357"]


def test_cors_allows_each_listed_origin_and_rejects_others(monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("UI_BASE_URL", "https://mayos.pages.dev/,http://localhost:7357")
    client = TestClient(create_app())

    for origin in ("https://mayos.pages.dev", "http://localhost:7357"):
        response = _preflight(client, origin)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

    rejected = _preflight(client, "https://evil.example")
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
