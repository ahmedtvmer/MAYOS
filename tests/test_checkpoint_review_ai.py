"""Checkpoint review wording, evaluation gate, and read-path tests (#222)."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from database.database_manager import DatabaseManager
from service import checkpoint_review_ai
from service import coach as coach_service
from svc.app import create_app
from svc.dependencies import get_db
from utils import model_downloader
from utils.model_metering import MeteringCallback

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
REVIEW_FACTS = {
    "workouts_in_period": 10,
    "weeks_met": 4,
    "weeks_counted": 5,
    "personal_records": 2,
    "regressed_exercises": 1,
    "volume_first_half": 4200.0,
    "volume_second_half": 4500.0,
}
REVIEW_RATING = [
    {"part": "Consistency", "label": "Steady"},
    {"part": "Progression", "label": "Strong"},
    {"part": "Volume trend", "label": "Rising"},
]


class _ReviewModel(BaseChatModel):
    reply: str = "Your consistency stayed steady. The recorded progression also held."
    payloads: list[list[Any]] = []
    failures_remaining: int = 0

    @property
    def _llm_type(self) -> str:
        return "checkpoint-review-test"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.payloads.append(list(messages))
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("model unavailable")
        content = AIMessage(
            content=self.reply,
            usage_metadata={"input_tokens": 40, "output_tokens": 18, "total_tokens": 58},
        )
        return ChatResult(generations=[ChatGeneration(message=content)])


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("CHECKPOINT_REVIEW_AI_ENABLED", raising=False)
    monkeypatch.delenv("CHECKPOINT_REVIEW_EVAL_REPORT", raising=False)
    from service.model_limits import reset_model_limits
    from svc.rate_limit import limiter

    limiter._storage.reset()
    reset_model_limits()
    catalog_path = tmp_path / "catalog.db"
    catalog = sqlite3.connect(catalog_path)
    catalog.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT, "
        "equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT)"
    )
    catalog.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT)")
    catalog.commit()
    catalog.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    checkpoint_review_ai._report_cache.clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, db: DatabaseManager, username: str) -> tuple[dict[str, str], str]:
    response = client.post("/auth/register", json={"trainee_id": username, "password": "correct-horse-1"})
    assert response.status_code == 201, response.text
    account = db.get_active_account_by_username(username)
    assert account is not None
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, account["account_id"]


def _seed_review(db: DatabaseManager, username: str) -> None:
    account = db.get_active_account_by_username(username)
    assert account is not None
    with db.open_ledger(account["ledger_id"]) as ledger:
        now = datetime.now(UTC).isoformat()
        ledger.log_workout_session(
            session_id="review-session",
            session_date="2026-09-01",
            split_name="Full body",
            started_at=now,
            completed_at=now,
            notes="PRIVATE_REVIEW_NOTE_31a7",
        )
        ledger.conn.execute(
            "INSERT INTO checkpoint_reviews "
            "(checkpoint, session_id, period_start, period_end, facts_json, rating_json, created_at, opened_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                10,
                "review-session",
                "2026-08-01",
                "2026-09-01",
                json.dumps(REVIEW_FACTS),
                json.dumps(REVIEW_RATING),
                now,
                None,
            ),
        )
        ledger.add_chat_message("user", "PRIVATE_REVIEW_CHAT_78c2")
        ledger.add_chat_message("assistant", "PRIVATE_REVIEW_CHAT_REPLY_14ed")


def _report(path: Path) -> Path:
    model_id, backend = checkpoint_review_ai.checkpoint_review_model_identity()
    runs = [
        {"case_id": f"case_{index}", "checks": {"pass": {"passed": True}}, "passed": True}
        for index in range(8)
    ]
    report = {
        "report_version": checkpoint_review_ai.REPORT_VERSION,
        "suite": "checkpoint_review",
        "mode": "live",
        "prompt_hash": checkpoint_review_ai.prompt_version_hash(),
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {"pass": True},
            "evaluation": {"pass": True, "threshold": 8, "total": 8, "passed": 8},
        },
        "runs": runs,
        "pass": True,
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _enable(monkeypatch, tmp_path: Path) -> Path:
    report_path = _report(tmp_path / "checkpoint_review_eval.json")
    monkeypatch.setenv("CHECKPOINT_REVIEW_AI_ENABLED", "true")
    monkeypatch.setenv("CHECKPOINT_REVIEW_EVAL_REPORT", str(report_path))
    return report_path


def _model(monkeypatch, *, reply: str | None = None, failures: int = 0) -> _ReviewModel:
    model_id, _backend = checkpoint_review_ai.checkpoint_review_model_identity()
    stub = _ReviewModel(callbacks=[MeteringCallback(model_id)], failures_remaining=failures)
    if reply is not None:
        stub.reply = reply
    monkeypatch.setattr(model_downloader, "get_llm", lambda *args, **kwargs: stub)
    return stub


def _rendered(payload: list[Any]) -> str:
    return "\n".join(str(getattr(message, "content", message)) for message in payload)


def test_render_is_allowlisted_and_prompt_hash_is_stable(monkeypatch):
    facts = {**REVIEW_FACTS, "username": "private-player", "notes": "private notes", "email": "private@example.com"}
    rendered = checkpoint_review_ai.render_review(facts, REVIEW_RATING, "ar")
    assert "Arabic" in rendered
    assert "4200" in rendered
    assert "private-player" not in rendered
    assert "private notes" not in rendered
    assert "private@example.com" not in rendered
    initial_hash = checkpoint_review_ai.prompt_version_hash()
    assert initial_hash == checkpoint_review_ai.prompt_version_hash()
    assert len(initial_hash) == 64
    monkeypatch.setattr(checkpoint_review_ai, "SYSTEM_PROMPT", checkpoint_review_ai.SYSTEM_PROMPT + "\nA changed prompt.")
    assert checkpoint_review_ai.prompt_version_hash() != initial_hash


def test_review_model_binding_disables_thinking_only_for_cloud():
    class BindingModel:
        def __init__(self):
            self.kwargs = None

        def bind(self, **kwargs):
            self.kwargs = kwargs
            return self

    cloud_model = BindingModel()
    assert checkpoint_review_ai.bind_review_model(cloud_model, backend="openai") is cloud_model
    assert cloud_model.kwargs == {
        "max_tokens": 200,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }

    local_model = BindingModel()
    assert checkpoint_review_ai.bind_review_model(local_model, backend="local") is local_model
    assert local_model.kwargs == {"max_tokens": 200}


def test_gate_binds_the_report_to_the_hosted_player_model(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_MODEL", "configured-player-model")

    assert checkpoint_review_ai.checkpoint_review_model_identity() == (
        "configured-player-model",
        "openai",
    )


def test_validate_report_accepts_only_current_live_verdict(tmp_path: Path):
    path = _report(tmp_path / "report.json")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert checkpoint_review_ai.validate_report(report)[0] is True

    for mutation in (
        {"mode": "mock"},
        {"prompt_hash": "wrong"},
        {"model": "another-model"},
        {"backend": "another-backend"},
    ):
        changed = {**report, **mutation}
        assert checkpoint_review_ai.validate_report(changed)[0] is False

    disagree = json.loads(json.dumps(report))
    disagree["runs"][0]["passed"] = False
    assert checkpoint_review_ai.validate_report(disagree)[0] is False
    assert any("disagrees" in reason for reason in checkpoint_review_ai.validate_report(disagree)[1])


def test_gate_off_returns_template_without_calling_model(api, monkeypatch):
    client, db, _tmp_path = api
    headers, _account_id = _register(client, db, "review-off")
    _seed_review(db, "review-off")
    stub = _model(monkeypatch)

    response = client.get("/checkpoint-reviews/10", headers=headers)

    assert response.status_code == 200
    assert response.json()["text_is_template"] is True
    assert response.json()["text"] == "Checkpoint 10: 10 workouts since you started logging in MAYOS."
    assert not stub.payloads
    with db.open_ledger("review-off") as ledger:
        row = ledger.get_checkpoint_review_row(10)
        assert row["text"] is None
        assert row["last_attempt_at"] is None


def test_missing_live_report_keeps_feature_off(api, monkeypatch):
    client, db, tmp_path = api
    headers, _account_id = _register(client, db, "review-no-report")
    _seed_review(db, "review-no-report")
    monkeypatch.setenv("CHECKPOINT_REVIEW_AI_ENABLED", "true")
    monkeypatch.setenv("CHECKPOINT_REVIEW_EVAL_REPORT", str(tmp_path / "missing.json"))
    stub = _model(monkeypatch)

    response = client.get("/checkpoint-reviews/10", headers=headers)

    assert response.status_code == 200
    assert response.json()["text_is_template"] is True
    assert not stub.payloads
    with db.open_ledger("review-no-report") as ledger:
        assert ledger.get_checkpoint_review_row(10)["last_attempt_at"] is None


def test_enabled_first_read_stores_text_and_second_read_reuses_it(api, monkeypatch):
    client, db, tmp_path = api
    headers, account_id = _register(client, db, "review-on")
    _seed_review(db, "review-on")
    _enable(monkeypatch, tmp_path)
    stub = _model(monkeypatch)

    first = client.get("/checkpoint-reviews/10", headers=headers)
    second = client.get("/checkpoint-reviews/10", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["text"] == stub.reply
    assert first.json()["text_is_template"] is False
    assert second.json()["text"] == stub.reply
    assert len(stub.payloads) == 1
    with db.open_ledger("review-on") as ledger:
        row = ledger.get_checkpoint_review_row(10)
        assert row["text"] == stub.reply
        assert row["text_language"] == "en"
        assert row["last_attempt_at"] is not None
    usage = db.catalog_conn.execute(
        "SELECT account_id, role, purpose FROM model_usage WHERE purpose = 'checkpoint_review'"
    ).fetchone()
    assert tuple(usage) == (account_id, "player", "checkpoint_review")


def test_generation_failure_returns_template_and_retries_after_ten_minutes(api, monkeypatch):
    client, db, tmp_path = api
    headers, _account_id = _register(client, db, "review-retry")
    _seed_review(db, "review-retry")
    _enable(monkeypatch, tmp_path)
    stub = _model(monkeypatch, failures=1)

    first = client.get("/checkpoint-reviews/10", headers=headers)
    second = client.get("/checkpoint-reviews/10", headers=headers)
    assert first.json()["text_is_template"] is True
    assert second.json()["text_is_template"] is True
    assert len(stub.payloads) == 1
    with db.open_ledger("review-retry") as ledger:
        ledger.conn.execute(
            "UPDATE checkpoint_reviews SET last_attempt_at = ? WHERE checkpoint = 10",
            ((datetime.now(UTC) - timedelta(minutes=11)).isoformat(),),
        )
        ledger.commit_ledger()

    third = client.get("/checkpoint-reviews/10", headers=headers)
    assert third.json()["text_is_template"] is False
    assert third.json()["text"] == stub.reply
    assert len(stub.payloads) == 2


def test_concurrent_first_reads_share_one_stored_text(api, monkeypatch):
    client, db, tmp_path = api
    headers, _account_id = _register(client, db, "review-concurrent")
    _seed_review(db, "review-concurrent")
    _enable(monkeypatch, tmp_path)
    stub = _model(monkeypatch)
    original = stub._generate

    def slow_generate(*args, **kwargs):
        import time

        time.sleep(0.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(stub, "_generate", slow_generate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.get("/checkpoint-reviews/10", headers=headers), range(2)))

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["text"] == stub.reply for response in responses)
    assert len(stub.payloads) == 1
    with db.open_ledger("review-concurrent") as ledger:
        assert ledger.get_checkpoint_review_row(10)["text"] == stub.reply


def test_generation_uses_the_display_language(api, monkeypatch):
    client, db, tmp_path = api
    headers, _account_id = _register(client, db, "review-arabic")
    _seed_review(db, "review-arabic")
    _enable(monkeypatch, tmp_path)
    arabic_reply = "كان التزامك ثابتًا خلال هذه الفترة. وظل التقدم مسجلًا دون تغيير."
    stub = _model(monkeypatch, reply=arabic_reply)
    monkeypatch.setattr("service.checkpoint_reviews.resolve_display_language", lambda _account_id: "ar")

    response = client.get("/checkpoint-reviews/10", headers=headers)

    assert response.status_code == 200
    assert response.json()["text"] == arabic_reply
    assert _rendered(stub.payloads[0]).count("Arabic (Modern Standard Arabic)") == 1
    with db.open_ledger("review-arabic") as ledger:
        assert ledger.get_checkpoint_review_row(10)["text_language"] == "ar"


def test_review_usage_does_not_reduce_daily_allowance(api, monkeypatch):
    client, db, tmp_path = api
    headers, account_id = _register(client, db, "review-allowance")
    _seed_review(db, "review-allowance")
    _enable(monkeypatch, tmp_path)
    _model(monkeypatch)

    client.get("/checkpoint-reviews/10", headers=headers)
    db.record_model_usage(
        account_id, "player", "test-model", 400, 200, 0, False, purpose="checkpoint_review"
    )
    db.record_model_usage(account_id, "player", "test-model", 100, 50, 0, False, purpose="chat")

    start = "2000-01-01T00:00:00+00:00"
    assert db.sum_model_tokens_for_account(account_id, start) == 150
    usage = db.summarize_model_usage(start)
    assert sum(
        row["input_tokens"] + row["output_tokens"]
        for row in usage
        if row["account_id"] == account_id
    ) >= 750


def test_coach_read_attributes_generation_to_players_account(api, monkeypatch):
    client, db, tmp_path = api
    coach = client.post("/auth/register", json={"trainee_id": "review-coach", "password": "correct-horse-1"})
    assert coach.status_code == 201, coach.text
    coach_headers = {"Authorization": f"Bearer {coach.json()['access_token']}"}
    invite = coach_service.issue_coach_invite(db, "review-coach", actor="cli")
    assert invite["ok"]
    assert client.post("/coach/invite/redeem", headers=coach_headers, json={"token": invite["token"]}).status_code == 200
    assert client.put(
        "/coach/profile",
        headers=coach_headers,
        json={"display_name": "Coach", "bio": "", "specialization": "", "capacity": 3},
    ).status_code == 200
    assignment_invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert assignment_invite.status_code == 200, assignment_invite.text
    player_headers, player_account_id = _register(client, db, "review-assigned-player")
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": assignment_invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    _seed_review(db, "review-assigned-player")
    _enable(monkeypatch, tmp_path)
    _model(monkeypatch)

    response = client.get(
        f"/coach/assignments/{redeemed.json()['assignment']['assignment_id']}/player/checkpoint-reviews/10",
        headers=coach_headers,
    )

    assert response.status_code == 200, response.text
    usage = db.catalog_conn.execute(
        "SELECT account_id, role FROM model_usage WHERE purpose = 'checkpoint_review'"
    ).fetchone()
    assert tuple(usage) == (player_account_id, "player")
