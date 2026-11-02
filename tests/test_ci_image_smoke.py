"""The container smoke scenario also runs against the in-process API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from scripts.ci_image_smoke import ApiRequest, SmokeFailure, request, run, wait_until_ready
from svc.app import create_app
from svc.dependencies import get_db


@pytest.fixture
def smoke_store(tmp_path):
    root = Path(__file__).resolve().parent.parent
    fixtures = root / "tests" / "fixtures"
    database = DatabaseManager(
        catalog_path=tmp_path / "catalog.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    database.initialize_and_seed(
        csv_path=fixtures / "smoke_exercises.csv",
        curation_path=fixtures / "smoke_exercise_curation.csv",
        food_path=fixtures / "smoke_food_library.csv",
        portion_path=fixtures / "smoke_food_portions.csv",
        food_curation_path=root / "data" / "food_curation.csv",
        recipe_path=root / "data" / "food_recipes.csv",
    )
    try:
        yield database
    finally:
        database.catalog_conn.close()


def test_smoke_scenario_exercises_api_contracts(smoke_store, monkeypatch):
    monkeypatch.delenv("SKIP_LLM_LOAD", raising=False)
    monkeypatch.setenv("JWT_SECRET", "ci-smoke-test-secret-0123456789")
    monkeypatch.delenv("MAYOS_DATA_DIR", raising=False)
    monkeypatch.delenv("MAYOS_REQUIRE_PERSISTENT_DATA", raising=False)
    db = smoke_store

    async def skip_hosted_model_warmup():
        return None

    monkeypatch.setattr("svc.llm.warmup_llm", skip_hosted_model_warmup)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as client:
        def in_process_request(_base_url, path, options=ApiRequest()):
            headers = {"Authorization": f"Bearer {options.token}"} if options.token else None
            response = client.request(options.method, path, headers=headers, json=options.body)
            if not response.is_success:
                raise AssertionError(f"{options.method} {path} returned {response.status_code}: {response.text}")
            return response.json() if response.content else None

        run("http://testserver", timeout=1, request_func=in_process_request)


def test_wait_until_ready_retries_connection_resets(monkeypatch):
    calls = 0

    class ReadyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"status": "ready"}'

    def flaky_urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise ConnectionResetError("peer reset")
        return ReadyResponse()

    monkeypatch.setattr("scripts.ci_image_smoke.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("scripts.ci_image_smoke.urllib.request.urlopen", flaky_urlopen)
    wait_until_ready("http://example.test", timeout=5)
    assert calls == 4


def test_request_converts_connection_reset_to_smoke_failure(monkeypatch):
    def reset(*_args, **_kwargs):
        raise ConnectionResetError("peer reset")

    monkeypatch.setattr("scripts.ci_image_smoke.urllib.request.urlopen", reset)
    with pytest.raises(SmokeFailure, match=r"GET /readyz failed: peer reset"):
        request("http://example.test", "/readyz")
