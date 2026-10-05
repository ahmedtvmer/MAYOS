"""HTTP prompt privacy proof for model-written Checkpoint reviews (#222)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import checkpoint_review_ai
from svc.app import create_app
from svc.dependencies import get_db
from tests.fakes.chat_model import ScriptedChatModel
from utils.model_metering import MeteringCallback

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
PLAYER_USERNAME = "reviewprivacyplayer"
PLAYER_EMAIL = "reviewprivacy@example.com"
SESSION_NOTE = "PRIVATE_REVIEW_NOTE_31a7"
PLAYER_CHAT = "PRIVATE_REVIEW_CHAT_78c2"
ASSISTANT_CHAT = "PRIVATE_REVIEW_CHAT_REPLY_14ed"
PROFILE_GOAL = "PRIVATE_PROFILE_GOAL"
PROFILE_LIMITATION = "PRIVATE_PROFILE_LIMITATION"
PREFERRED_NAME = "PRIVATE_PREFERRED_NAME"


def _write_live_report(path: Path) -> Path:
    # Synthetic fixture used only with the fake model, never live evidence.
    model_id, backend = checkpoint_review_ai.checkpoint_review_model_identity()
    runs = [{"case_id": str(index), "checks": {}, "passed": True} for index in range(8)]
    report = {
        "report_version": checkpoint_review_ai.REPORT_VERSION,
        "suite": "checkpoint_review",
        "mode": "live",
        "prompt_hash": checkpoint_review_ai.prompt_version_hash(),
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {"pass": True},
            "evaluation": {"pass": True, "threshold": 8},
        },
        "runs": runs,
        "pass": True,
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_review_model_input_excludes_account_and_ledger_private_text(
    tmp_path: Path, monkeypatch, scripted_chat_model: ScriptedChatModel
):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
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
    report = _write_live_report(tmp_path / "checkpoint_review_eval.json")
    monkeypatch.setenv("CHECKPOINT_REVIEW_AI_ENABLED", "true")
    monkeypatch.setenv("CHECKPOINT_REVIEW_EVAL_REPORT", str(report))
    model_id, _backend = checkpoint_review_ai.checkpoint_review_model_identity()
    model = scripted_chat_model
    model.reset(["Your consistency stayed steady. The recorded progression also held."])
    model.usage_metadata = {"input_tokens": 40, "output_tokens": 18, "total_tokens": 58}
    model.callbacks = [MeteringCallback(model_id)]

    try:
        with TestClient(app) as client:
            registered = client.post(
                "/auth/register",
                json={"trainee_id": PLAYER_USERNAME, "password": "correct-horse-1"},
            )
            assert registered.status_code == 201, registered.text
            account = db.get_active_account_by_username(PLAYER_USERNAME)
            assert account is not None
            account_id = account["account_id"]
            headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
            db.set_account_email(account_id, PLAYER_EMAIL)
            with db.open_ledger(PLAYER_USERNAME) as ledger:
                ledger.upsert_player_profile({
                    "current_goal": PROFILE_GOAL,
                    "injuries_or_limitations": PROFILE_LIMITATION,
                    "long_term_goal": "PRIVATE_LONG_TERM_GOAL",
                })
                ledger.set_assistant_memory("preferred_name", PREFERRED_NAME)
                now = datetime.now(UTC).isoformat()
                ledger.log_workout_session(
                    "private-review-session",
                    "2026-09-01",
                    "Full body",
                    now,
                    now,
                    notes=SESSION_NOTE,
                )
                ledger.conn.execute(
                    "INSERT INTO checkpoint_reviews "
                    "(checkpoint, session_id, period_start, period_end, facts_json, rating_json, created_at) "
                    "VALUES (10, ?, '2026-08-01', '2026-09-01', ?, ?, ?)",
                    (
                        "private-review-session",
                        json.dumps({
                            "workouts_in_period": 10,
                            "weeks_met": 4,
                            "weeks_counted": 5,
                            "personal_records": 2,
                            "regressed_exercises": 1,
                            "volume_first_half": 4200,
                            "volume_second_half": 4500,
                        }),
                        json.dumps([
                            {"part": "Consistency", "label": "Steady"},
                            {"part": "Progression", "label": "Strong"},
                            {"part": "Volume trend", "label": "Rising"},
                        ]),
                        now,
                    ),
                )
                ledger.add_chat_message("user", PLAYER_CHAT)
                ledger.add_chat_message("assistant", ASSISTANT_CHAT)

            assert client.put("/profile/persona", headers=headers, json={
                "coach_tone": "scientific", "custom_instructions": "Explain the evidence briefly.",
            }).status_code == 200
            response = client.get("/checkpoint-reviews/10", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["text_is_template"] is False

        rendered = "\n".join(
            str(getattr(message, "content", message)) for message in model.calls[0]["messages"]
        )
        for private_value in (PLAYER_USERNAME, PLAYER_EMAIL, SESSION_NOTE, PLAYER_CHAT, ASSISTANT_CHAT, account_id,
                              PROFILE_GOAL, PROFILE_LIMITATION, PREFERRED_NAME, "PRIVATE_LONG_TERM_GOAL"):
            assert private_value not in rendered, private_value
        assert "Explain the evidence briefly." in rendered
        assert "4200" in rendered
        assert "Steady" in rendered
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()
