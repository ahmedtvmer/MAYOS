"""Contract tests for the structured, resumable onboarding intake (ADR 021, #50).

Hermetic: temporary ledgers, real auth, generation stubbed. Covers validation,
per-answer persistence, resume progress, edits, the disclosure gate, legacy
prefill, confirmation (once, idempotent), and the unchanged program rules
(proportions are coaching context; specialization keeps its split effect).
"""

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

#: One valid, complete set of answers reused by the confirmation tests.
VALID_ANSWERS: dict[str, Any] = {
    "gender": "female",
    "proportions": "long_legs",
    "age": 29,
    "height_cm": 168.0,
    "weight_kg": 64.5,
    "training_age_years": 3.0,
    "current_goal": "build glutes and legs",
    "long_term_goal": "stronger and more muscular",
    "weekly_frequency": 4,
    "equipment_access": "commercial gym",
    "injuries_or_limitations": "None",
    "stress_and_sleep": "moderate stress, 7 hours sleep",
}


def _exercise(idx: int) -> ProgramExerciseSchema:
    return ProgramExerciseSchema(
        exercise_id=f"ex{idx}",
        exercise_name=f"Exercise {idx}",
        target_reps_min=8,
        target_reps_max=12,
    )


def _program(name: str = "Player Plan", frequency: int = 4) -> GeneratedProgramSchema:
    day = ProgramDaySchema(
        day_name="Day 1",
        day_order=1,
        exercises=[_exercise(1), _exercise(2), _exercise(3)],
    )
    return GeneratedProgramSchema(
        program_name=name,
        split_type=name,
        weekly_frequency=frequency,
        days=[day],
    )


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('ex1', 'Exercise 1', 'Chest', 'Chest'), ('ex2', 'Exercise 2', 'Back', 'Back'),"
        " ('ex3', 'Exercise 3', 'Upper Legs', 'Quads');"
    )
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post(
        "/auth/register", json={"trainee_id": username, "password": "correct-horse-1"}
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.parametrize("answer, expected_status", [(30, 200), ("invalid-age", 400)])
def test_answer_save_mounts_once_off_event_loop_and_closes_on_success_or_error(api, monkeypatch, answer, expected_status):
    client, db, _ = api
    headers = _register(client, "single-mount-intake")
    client.post("/onboarding/intake/disclosure", headers=headers).raise_for_status()
    opened = []
    real_open = db.open_ledger

    def open_in_worker(ledger_id):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        ledger = real_open(ledger_id)
        opened.append(ledger)
        return ledger

    monkeypatch.setattr(db, "open_ledger", open_in_worker)
    response = client.put("/onboarding/intake/answers/age", headers=headers, json={"value": answer})
    assert response.status_code == expected_status, response.text
    assert len(opened) == 1
    with pytest.raises(RuntimeError, match="closed"):
        _ = opened[0].conn
    with real_open("single-mount-intake") as ledger:
        saved = ledger.load_intake_answers()
        assert saved.get("age", {}).get("value") == (30 if expected_status == 200 else None)


@pytest.mark.parametrize("denial", ["revoked", "stale_epoch", "deleted", "not_player"])
def test_shared_intake_ledger_keeps_authentication_gates(api, monkeypatch, denial):
    from svc.auth import token_claims

    client, db, _ = api
    headers = _register(client, "gated-intake")
    client.post("/onboarding/intake/disclosure", headers=headers).raise_for_status()
    claims = token_claims(headers["Authorization"].removeprefix("Bearer "))
    with db.open_ledger("gated-intake") as ledger:
        if denial == "revoked":
            ledger.revoke_token(claims["jti"], datetime.fromtimestamp(claims["exp"], UTC).isoformat())
    if denial == "stale_epoch":
        db.bump_account_session_epoch(claims["sub"])
    elif denial == "deleted":
        db.record_account_deletion(claims["sub"], "gated-intake")
    elif denial == "not_player":
        with db.catalog_transaction():
            db.catalog_conn.execute("UPDATE accounts SET is_player = 0 WHERE account_id = ?", (claims["sub"],))

    opened = []
    real_open = db.open_ledger

    def track_open(ledger_id):
        ledger = real_open(ledger_id)
        opened.append(ledger)
        return ledger

    monkeypatch.setattr(db, "open_ledger", track_open)
    response = client.put("/onboarding/intake/answers/age", headers=headers, json={"value": 30})
    assert response.status_code == 401, response.text
    assert len(opened) == (1 if denial == "revoked" else 0)
    for ledger in opened:
        with pytest.raises(RuntimeError, match="closed"):
            _ = ledger.conn
    with sqlite3.connect(db.ledgers_dir / "gated-intake.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM intake_answers WHERE field = 'age'").fetchone()[0] == 0


def test_repeated_onboarding_start_needs_no_ledger_write(api):
    _, db, _ = api
    with db.open_ledger("read-only-start") as ledger:
        started = ledger.start_onboarding_analytics("2026-11-08T10:00:00+00:00")

        def deny_writes(action, _table, _column, _database, _trigger):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT else sqlite3.SQLITE_OK

        ledger.conn.set_authorizer(deny_writes)
        try:
            repeated = ledger.start_onboarding_analytics("2026-11-08T10:01:00+00:00")
        finally:
            ledger.conn.set_authorizer(None)
        assert started.first_write is True
        assert repeated.first_write is False
        assert repeated.started_at == started.started_at


def test_weak_points_profile_round_trip_and_validation(api):
    client, _, _ = api
    headers = _register(client, "weakpoint-player")
    assert client.get("/profile", headers=headers).status_code == 404
    saved = client.put("/profile", headers=headers, json={"weak_points": [
        {"muscle": "glutes", "source": "named"},
        {"muscle": "chest", "source": "named"},
    ]})
    assert saved.status_code == 200, saved.text
    assert client.get("/profile", headers=headers).json()["weak_points"] == [
        {"muscle": "glutes", "source": "named"},
        {"muscle": "chest", "source": "named"},
    ]
    assert client.put("/profile", headers=headers, json={"weak_points": []}).status_code == 200
    assert client.get("/profile", headers=headers).json()["weak_points"] == []
    for value in (
        [{"muscle": "chest", "source": "named"}] * 3,
        [{"muscle": "chest", "source": "named"}, {"muscle": "chest", "source": "named"}],
        [{"muscle": "pecs", "source": "named"}],
        [{"muscle": "chest", "source": "bad"}],
        [{"muscle": "glutes", "source": "default"}, {"muscle": "chest", "source": "named"}],
        [{"muscle": "glutes", "source": "migrated"}, {"muscle": "back", "source": "named"}],
    ):
        assert client.put("/profile", headers=headers, json={"weak_points": value}).status_code == 422
    rejected_default = client.put("/profile", headers=headers, json={
        "weak_points": [{"muscle": "glutes", "source": "default"}],
    })
    assert rejected_default.status_code == 422
    assert "female profiles" in rejected_default.json()["detail"]


def test_weak_points_are_optional_intake_answers_and_can_be_cleared(api):
    client, db, _ = api
    headers = _register(client, "weakpoint-intake")
    db.switch_user("weakpoint-intake")
    db.ledger.upsert_player_profile({"gender": "female"})
    initial = client.get("/onboarding/intake", headers=headers).json()
    field = next(item for item in initial["fields"] if item["name"] == "weak_points")
    assert field["required"] is False and field["answered"] is False
    client.post("/onboarding/intake/disclosure", headers=headers)
    for invalid in (
        [{"muscle": "chest", "source": "named"}] * 3,
        [{"muscle": "chest", "source": "named"}, {"muscle": "chest", "source": "named"}],
        [{"muscle": "unknown", "source": "named"}],
        [{"muscle": "chest", "source": "unknown"}],
    ):
        rejected = client.put("/onboarding/intake/answers/weak_points", headers=headers,
                              json={"value": invalid})
        assert rejected.status_code == 400
    saved = client.put("/onboarding/intake/answers/weak_points", headers=headers,
                       json={"value": [{"muscle": "glutes", "source": "default"}]})
    assert saved.status_code == 200, saved.text
    field = next(item for item in saved.json()["fields"] if item["name"] == "weak_points")
    assert field["answer"] == [{"muscle": "glutes", "source": "default"}]
    cleared = client.put("/onboarding/intake/answers/weak_points", headers=headers,
                         json={"value": []})
    field = next(item for item in cleared.json()["fields"] if item["name"] == "weak_points")
    assert field["answered"] is True and field["answer"] == []


def test_intake_exposes_deterministic_goal_weak_point_suggestions(api):
    client, _, _ = api
    headers = _register(client, "goal_suggestion")
    client.post("/onboarding/intake/disclosure", headers=headers)
    client.put("/onboarding/intake/answers/current_goal", headers=headers,
               json={"value": "grow my glutes and arms"})
    view = client.put("/onboarding/intake/answers/long_term_goal", headers=headers,
                      json={"value": "عايز صدر أكبر"})
    assert view.status_code == 200, view.text
    assert view.json()["suggested_weak_points"] == ["glutes", "biceps", "triceps", "chest"]


def test_intake_returns_movement_suggestions_and_rejects_unknown_confirmation_before_claim(api):
    client, _, _ = api
    headers = _register(client, "movement_intake_suggestions")
    _ack(client, headers)
    client.put("/onboarding/intake/answers/injuries_or_limitations", headers=headers,
               json={"value": "FAI syndrome and torn ACL"})
    view = client.get("/onboarding/intake", headers=headers)
    assert view.json()["suggested_movement_restrictions"] == [
        "Knee flexion", "Loaded knee extension", "Deep hip flexion"
    ]
    invalid = client.post("/onboarding/intake/confirm", headers=headers,
                          json={"movement_restrictions": ["unknown"]})
    assert invalid.status_code == 422
    retry = client.post("/onboarding/intake/confirm", headers=headers,
                        json={"movement_restrictions": ["Knee flexion"]})
    assert retry.status_code == 400
    assert "Missing required" in retry.json()["detail"]


def test_skipping_weak_points_keeps_the_confirmed_profile_unanswered(api, monkeypatch):
    client, _, _ = api
    headers = _register(client, "weakpoint-skip")
    _spy_generation_from_profile(api[1], monkeypatch)
    client.post("/onboarding/intake/disclosure", headers=headers)
    for name, value in VALID_ANSWERS.items():
        response = client.put(f"/onboarding/intake/answers/{name}", headers=headers,
                              json={"value": value})
        assert response.status_code == 200, response.text
    confirmed = client.post("/onboarding/intake/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    profile = client.get("/profile", headers=headers).json()
    assert profile["weak_points"] is None


def _spy_generation(db: Any, monkeypatch) -> dict[str, Any]:
    """Stubs first-program generation and counts calls, saving through the ledger."""
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        program = _program()
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "markdown"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", fake)
    return calls


def _spy_generation_from_profile(db: Any, monkeypatch) -> dict[str, Any]:
    """Stubs generation, capturing the profile the program was generated from."""
    seen: dict[str, Any] = {"n": 0, "gender": None, "weekly_frequency": None}

    def fake(**kwargs):
        seen["n"] += 1
        profile = kwargs["ledger"].get_player_profile()
        seen["gender"] = profile["gender"]
        seen["weekly_frequency"] = profile["weekly_frequency"]
        program = _program(frequency=profile["weekly_frequency"])
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "markdown"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", fake)
    return seen


def _ack(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.post("/onboarding/intake/disclosure", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _answer(client: TestClient, headers: dict[str, str], field: str, value: Any):
    return client.put(f"/onboarding/intake/answers/{field}", headers=headers, json={"value": value})


def _fill(client: TestClient, headers: dict[str, str], values: dict[str, Any] = VALID_ANSWERS):
    for field, value in values.items():
        resp = _answer(client, headers, field, value)
        assert resp.status_code == 200, (field, resp.text)
    return resp


def _field(view: dict[str, Any], name: str) -> dict[str, Any]:
    return next(field for field in view["fields"] if field["name"] == name)


# --------------------------------------------------------------------------
# Auth and isolation
# --------------------------------------------------------------------------


def test_intake_requires_auth(api):
    client, _, _ = api
    assert client.get("/onboarding/intake").status_code == 401
    assert client.put(
        "/onboarding/intake/answers/gender", json={"value": "male"}
    ).status_code == 401
    assert client.post("/onboarding/intake/confirm").status_code == 401


def test_other_account_isolation(api):
    client, _, _ = api
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    _ack(client, alice)
    assert _answer(client, alice, "gender", "female").status_code == 200

    alice_view = client.get("/onboarding/intake", headers=alice).json()
    bob_view = client.get("/onboarding/intake", headers=bob).json()
    assert _field(alice_view, "gender")["answer"] == "female"
    assert _field(bob_view, "gender")["answer"] is None
    assert bob_view["progress"]["answered_required"] == 0


# --------------------------------------------------------------------------
# Contract and validation
# --------------------------------------------------------------------------


def test_intake_contract_lists_fields_and_explanations(api):
    client, _, _ = api
    headers = _register(client, "alice")
    view = client.get("/onboarding/intake", headers=headers).json()

    assert view["status"] == "in_progress"
    assert view["disclosure_acknowledged"] is False
    names = [field["name"] for field in view["fields"]]
    assert names[0] == "gender" and "proportions" in names and "weekly_frequency" in names
    gender = _field(view, "gender")
    assert gender["allowed_values"] == ["male", "female"]
    assert gender["required"] is True
    assert "does not change" in gender["explanation"]
    assert "Full Body" in gender["explanation"]
    assert "Upper/Lower" in gender["explanation"]
    assert "PPL" in gender["explanation"]
    # Every enum value carries the training-effect description shown on its card.
    assert set(gender["option_descriptions"]) == {"male", "female"}
    assert all(gender["option_descriptions"].values())
    assert gender["option_descriptions"]["male"] == gender["option_descriptions"]["female"]
    assert "glute priority" in gender["option_descriptions"]["female"].casefold()
    proportions = _field(view, "proportions")
    assert proportions["allowed_values"] == [
        "long_legs",
        "balanced",
        "long_torso",
    ]
    assert set(proportions["option_descriptions"]) == {
        "long_legs",
        "balanced",
        "long_torso",
    }
    assert all(proportions["option_descriptions"].values())
    assert set(_field(view, "rep_preference")["option_descriptions"]) == {
        "low",
        "balanced",
        "high",
    }
    assert _field(view, "age")["option_descriptions"] == {}
    assert _field(view, "rep_preference")["required"] is False
    assert view["progress"]["required_total"] == 12
    assert view["progress"]["next_unanswered"] == "gender"
    # Free-text fields carry a hint/examples; "None" is documented as valid.
    injuries = _field(view, "injuries_or_limitations")
    assert injuries["hint"] and "None" in injuries["hint"]
    assert injuries["examples"]
    assert _field(view, "current_goal")["hint"]
    assert _field(view, "gender")["hint"] is None

    # Server-owned copy carries the shared stable-message shape alongside its
    # unchanged English text. Raw player answers never enter translation values.
    explanation = gender["explanation_message"]
    assert explanation == {
        "message_code": "intake.gender.explanation.v1",
        "message_params": {},
        "message_fallback": gender["explanation"],
    }
    option = gender["option_description_messages"]["female"]
    assert option == {
        "message_code": "intake.gender.option.female.v1",
        "message_params": {},
        "message_fallback": gender["option_descriptions"]["female"],
    }
    goal = _field(view, "current_goal")
    assert goal["hint_message"]["message_code"] == "intake.current_goal.hint.v1"
    assert [message["message_code"] for message in goal["example_messages"]] == [
        "intake.current_goal.example.1.v1",
        "intake.current_goal.example.2.v1",
        "intake.current_goal.example.3.v1",
    ]
    assert all(message["message_params"] == {} for message in goal["example_messages"])


def _intake_copy_contract(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": field["name"],
            "explanation_message": field["explanation_message"],
            "hint_message": field["hint_message"],
            "example_messages": field["example_messages"],
            "option_description_messages": field["option_description_messages"],
        }
        for field in view["fields"]
    ]


def _intake_copy_messages(field: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        message
        for message in (
            field["explanation_message"],
            field["hint_message"],
            *field["example_messages"],
            *field["option_description_messages"].values(),
        )
        if message is not None
    ]


def test_intake_copy_contract_survives_disclosure_answers_resume_and_confirm(
    api, monkeypatch
):
    client, _, _ = api
    headers = _register(client, "alice")
    original = client.get("/onboarding/intake", headers=headers).json()
    original_copy = _intake_copy_contract(original)
    for field in original["fields"]:
        assert all(
            message["message_params"] == {}
            for message in _intake_copy_messages(field)
        )

    acknowledged = _ack(client, headers)
    assert _intake_copy_contract(acknowledged) == original_copy

    answers = dict(VALID_ANSWERS)
    answers["current_goal"] = "Build strength for climbing"
    for field, value in answers.items():
        response = _answer(client, headers, field, value)
        assert response.status_code == 200, response.text
        body = response.json()
        assert _intake_copy_contract(body) == original_copy

    resumed = client.get("/onboarding/intake", headers=headers).json()
    assert _intake_copy_contract(resumed) == original_copy
    assert _field(resumed, "current_goal")["answer"] == "Build strength for climbing"

    _spy_generation_from_profile(None, monkeypatch)
    confirmed = client.post("/onboarding/intake/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert _intake_copy_contract({"fields": confirmed.json()["fields"]}) == original_copy
    assert _field({"fields": confirmed.json()["fields"]}, "current_goal")["answer"] == (
        "Build strength for climbing"
    )


def test_display_language_does_not_change_intake_facts_or_program(api, monkeypatch):
    client, _, _ = api
    _spy_generation_from_profile(None, monkeypatch)
    results = {}
    copy_contracts = {}
    for username, language in (("english_player", "en"), ("arabic_player", "ar")):
        headers = _register(client, username)
        changed = client.put(
            "/auth/display-language",
            headers=headers,
            json={"display_language": language},
        )
        assert changed.status_code == 200, changed.text
        acknowledged = _ack(client, headers)
        copy_contracts[language] = _intake_copy_contract(acknowledged)
        _fill(client, headers)
        confirmed = client.post("/onboarding/intake/confirm", headers=headers)
        assert confirmed.status_code == 200, confirmed.text
        profile = client.get("/profile", headers=headers).json()
        program = client.get("/programs/active", headers=headers).json()
        results[language] = (
            {
                key: profile[key]
                for key in (
                    "gender",
                    "proportions",
                    "age",
                    "height_cm",
                    "weight_kg",
                    "training_age_years",
                    "current_goal",
                    "long_term_goal",
                    "weekly_frequency",
                    "equipment_access",
                    "injuries_or_limitations",
                    "stress_and_sleep",
                )
            },
            {
                key: program[key]
                for key in ("program_name", "split_type", "weekly_frequency", "days")
            },
        )

    assert results["en"] == results["ar"]
    assert copy_contracts["en"] == copy_contracts["ar"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("gender", "other"),
        ("gender", 7),
        ("proportions", "wide"),
        ("age", 5),
        ("age", "abc"),
        ("height_cm", 400),
        ("weight_kg", 0),
        ("training_age_years", 99),
        ("weekly_frequency", 9),
        ("weekly_frequency", 2.5),
        ("rep_preference", "medium"),
        ("current_goal", ""),
        ("current_goal", "a"),
        ("injuries_or_limitations", "x"),
    ],
)
def test_validation_rejects_bad_answers_per_field(api, field, value):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)

    resp = _answer(client, headers, field, value)
    assert resp.status_code == 400, resp.text
    assert field in resp.json()["detail"]
    assert resp.json()["message_code"] == "http.bad_request.v1"
    assert resp.json()["message_params"] == {}


@pytest.mark.parametrize("frequency", [0, 6])
def test_weekly_frequency_bounds_reject_without_persisting(api, frequency):
    client, db, _ = api
    player = f"frequency-{frequency}"
    headers = _register(client, player)
    _ack(client, headers)

    response = _answer(client, headers, "weekly_frequency", frequency)

    assert response.status_code == 400, response.text
    assert "weekly_frequency" in response.json()["detail"]
    with db.open_ledger(player) as ledger:
        assert "weekly_frequency" not in ledger.load_intake_answers()
        assert ledger.get_player_profile() is None


def test_unknown_field_rejected(api):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)
    resp = _answer(client, headers, "favourite_colour", "blue")
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# Persistence, resume, edits
# --------------------------------------------------------------------------


def test_answers_persist_and_resume_with_progress(api):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)
    assert _answer(client, headers, "gender", "female").status_code == 200
    saved = _answer(client, headers, "age", "31").json()

    assert _field(saved, "age")["answer"] == 31
    assert _field(saved, "age")["updated_at"]
    assert saved["progress"]["answered_required"] == 2
    assert saved["progress"]["next_unanswered"] == "proportions"

    # A fresh read (as after a restart) returns the same saved answers.
    resumed = client.get("/onboarding/intake", headers=headers).json()
    assert _field(resumed, "gender")["answer"] == "female"
    assert _field(resumed, "age")["answer"] == 31


def test_editing_an_earlier_answer_keeps_the_others(api):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)
    _answer(client, headers, "gender", "male")
    _answer(client, headers, "age", 40)
    _answer(client, headers, "proportions", "balanced")

    updated = _answer(client, headers, "gender", "female").json()
    assert _field(updated, "gender")["answer"] == "female"
    assert _field(updated, "age")["answer"] == 40
    assert _field(updated, "proportions")["answer"] == "balanced"


def test_answer_is_idempotent(api):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)
    first = _answer(client, headers, "gender", "male").json()
    second = _answer(client, headers, "gender", "male").json()
    assert _field(first, "gender")["answer"] == _field(second, "gender")["answer"] == "male"
    assert second["progress"]["answered"] == 1


# --------------------------------------------------------------------------
# Disclosure gate
# --------------------------------------------------------------------------


def test_disclosure_gate_precedes_answers_and_confirm(api):
    client, _, _ = api
    headers = _register(client, "alice")

    blocked = _answer(client, headers, "gender", "male")
    assert blocked.status_code == 403
    assert client.post("/onboarding/intake/confirm", headers=headers).status_code == 403

    view = _ack(client, headers)
    assert view["disclosure_acknowledged"] is True
    assert _answer(client, headers, "gender", "male").status_code == 200


# --------------------------------------------------------------------------
# Confirmation
# --------------------------------------------------------------------------


def test_confirm_requires_every_required_answer(api):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)
    _answer(client, headers, "gender", "female")

    resp = client.post("/onboarding/intake/confirm", headers=headers)
    assert resp.status_code == 400
    assert "proportions" in resp.json()["detail"]


def test_confirm_writes_profile_and_creates_program_once(api, monkeypatch):
    client, db, _ = api
    headers = _register(client, "alice")
    calls = _spy_generation(db, monkeypatch)
    _ack(client, headers)
    _fill(client, headers)

    confirmed = client.post("/onboarding/intake/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["program_name"] == "Player Plan"
    assert body["weekly_frequency"] == 4
    assert calls["n"] == 1

    # The program was generated from the confirmed values.
    db.switch_user("alice")
    profile = db.ledger.get_player_profile()
    assert profile["gender"] == "female"
    assert profile["weekly_frequency"] == 4
    assert profile["proportions"] == "long_legs"
    assert db.ledger.get_active_program() is not None

    # Re-confirming replays the stored result and never generates again.
    again = client.post("/onboarding/intake/confirm", headers=headers)
    assert again.status_code == 200
    assert again.json()["program_name"] == "Player Plan"
    assert calls["n"] == 1


def test_generation_unavailable_message_is_structured_on_confirm_and_resume(
    api, monkeypatch
):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)
    _fill(client, headers)
    fallback = "Your assigned coach controls your program. Ask your coach for changes."
    metadata = {
        "message_code": "intake.program_generation_unavailable.v1",
        "message_params": {},
        "message_fallback": fallback,
    }

    def no_program_generation(**kwargs):
        return None, "Generation returned no program."

    monkeypatch.setattr("service.programs.generate_program_pipeline", no_program_generation)
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", no_program_generation)
    confirmed = client.post("/onboarding/intake/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["program_message"] == fallback
    assert confirmed.json()["program_message_metadata"] == metadata

    replayed = client.post("/onboarding/intake/confirm", headers=headers)
    resumed = client.get("/onboarding/intake", headers=headers)
    assert replayed.json()["program_message_metadata"] == metadata
    assert resumed.json()["program"]["program_message_metadata"] == metadata


def test_non_confirmed_confirmation_response_keeps_intake_copy_contract(
    api, monkeypatch
):
    client, _, _ = api
    headers = _register(client, "alice")
    _ack(client, headers)
    original = client.get("/onboarding/intake", headers=headers).json()
    monkeypatch.setattr(
        "service.intake.confirm_intake", lambda *args, **kwargs: {"status": "in_progress"}
    )

    response = client.post("/onboarding/intake/confirm", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "in_progress"
    assert _intake_copy_contract(response.json()) == _intake_copy_contract(original)


@pytest.mark.parametrize(
    ("replacement", "expected_descriptions"),
    [
        ("Left knee pain", []),
        ("New shoulder pain", ["New shoulder pain"]),
    ],
)
def test_intake_confirmation_handles_deleted_legacy_injury_by_text(
    api, monkeypatch, replacement, expected_descriptions
):
    client, db, _ = api
    headers = _register(client, "legacy-intake-player")
    _spy_generation(db, monkeypatch)
    _ack(client, headers)
    answers = dict(VALID_ANSWERS)
    answers["injuries_or_limitations"] = "Left knee pain"
    _fill(client, headers, answers)
    injury = client.get("/profile/injuries", headers=headers).json()[0]
    deleted = client.delete(f"/profile/injuries/{injury['id']}", headers=headers)
    assert deleted.status_code == 204
    if replacement != "Left knee pain":
        db.switch_user("legacy-intake-player")
        db.ledger.save_intake_answer(
            "injuries_or_limitations", replacement, prefilled=False
        )

    confirmed = client.post("/onboarding/intake/confirm", headers=headers)

    assert confirmed.status_code == 200, confirmed.text
    injuries = client.get("/profile/injuries", headers=headers).json()
    assert [item["description"] for item in injuries] == expected_descriptions


def test_editing_before_confirm_flows_into_profile_and_program(api, monkeypatch):
    """AC2: editing an earlier answer must change the confirmed profile and program."""
    client, db, _ = api
    headers = _register(client, "editor")
    seen = _spy_generation_from_profile(db, monkeypatch)
    _ack(client, headers)

    values = dict(VALID_ANSWERS)
    values["gender"] = "male"
    values["weekly_frequency"] = 3
    _fill(client, headers, values)

    # Edit an earlier answer: frequency 3 -> 4 and gender male -> female.
    assert _answer(client, headers, "weekly_frequency", 4).status_code == 200
    assert _answer(client, headers, "gender", "female").status_code == 200

    confirmed = client.post("/onboarding/intake/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text

    db.switch_user("editor")
    profile = db.ledger.get_player_profile()
    assert profile["weekly_frequency"] == 4
    assert profile["gender"] == "female"
    # Generation read the edited values, and the saved program matches.
    assert seen["weekly_frequency"] == 4
    assert seen["gender"] == "female"
    assert db.ledger.get_active_program().weekly_frequency == 4


def test_concurrent_confirm_generates_exactly_one_program(api, monkeypatch):
    """Two simultaneous confirms: one claims, the other gets 409, one generation."""
    client, db, _ = api
    headers = _register(client, "racer")
    _ack(client, headers)
    _fill(client, headers)

    calls = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    def fake(**kwargs):
        calls["n"] += 1
        started.set()
        assert release.wait(timeout=10), "generation was never released"
        program = _program()
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "markdown"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", fake)

    results: list[Any] = []

    def first():
        results.append(client.post("/onboarding/intake/confirm", headers=headers))

    thread = threading.Thread(target=first)
    thread.start()
    assert started.wait(timeout=10), "first confirm never began generating"

    second = client.post("/onboarding/intake/confirm", headers=headers)
    assert second.status_code == 409, second.text
    assert second.json() == {
        "error": "confirm_in_progress",
        "message_code": "intake.in_progress.v1",
        "message_params": {},
        "message_fallback": "The service rejected this request.",
    }

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert calls["n"] == 1
    assert results and results[0].status_code == 200


def test_failed_generation_releases_claim_for_retry(api, monkeypatch):
    """A generation failure resets the claim so a retry can still generate."""

    client, db, _ = api
    headers = _register(client, "retry")
    _ack(client, headers)
    _fill(client, headers)

    state = {"fail": True}

    def fake(**kwargs):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("program generation failed")
        program = _program()
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "markdown"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", fake)

    with pytest.raises(RuntimeError, match="program generation failed"):
        client.post("/onboarding/intake/confirm", headers=headers)
    assert client.get("/onboarding/intake", headers=headers).json()["status"] == "in_progress"

    second = client.post("/onboarding/intake/confirm", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["program_name"] == "Player Plan"


def test_confirmed_intake_reads_program_and_refuses_edits(api, monkeypatch):
    client, db, _ = api
    headers = _register(client, "alice")
    _spy_generation(db, monkeypatch)
    _ack(client, headers)
    _fill(client, headers)
    assert client.post("/onboarding/intake/confirm", headers=headers).status_code == 200

    view = client.get("/onboarding/intake", headers=headers).json()
    assert view["status"] == "confirmed"
    assert view["program"]["program_name"] == "Player Plan"

    refused = _answer(client, headers, "gender", "male")
    assert refused.status_code == 409


# --------------------------------------------------------------------------
# Legacy prefill and completed accounts
# --------------------------------------------------------------------------


def test_legacy_prefill_maps_unambiguous_values_and_asks_again(api):
    client, db, _ = api
    headers = _register(client, "legacy")
    db.switch_user("legacy")
    db.ledger.save_onboarding_state(
        {
            "intake_step": 3,
            "is_complete": False,
            "profile_data": {
                "gender": "female",
                "age": 30,
                "height_cm": 170.0,
                "weight_kg": 68.0,
                "training_age_years": 2.0,
                # The legacy graph fills "balanced" when the player never
                # compared, so it is ambiguous and must be asked again.
                "proportions": "balanced",
                "current_goal": "get stronger",
                "long_term_goal": "stay healthy",
                "weekly_frequency": 3,
                "equipment_access": "home gym",
                "injuries_or_limitations": "None",
                "stress_and_sleep": "low stress",
                "rep_preference": "balanced",
            },
            "messages": [],
        }
    )

    view = client.get("/onboarding/intake", headers=headers).json()
    assert view["status"] == "in_progress"
    assert _field(view, "gender")["prefilled"] is True
    assert _field(view, "gender")["answer"] == "female"
    assert _field(view, "age")["answer"] == 30
    # Ambiguous legacy defaults are left unanswered, never guessed.
    assert _field(view, "proportions")["answered"] is False
    assert _field(view, "rep_preference")["answered"] is False
    assert view["progress"]["next_unanswered"] == "proportions"


def test_legacy_prefill_keeps_explicit_proportions(api):
    client, db, _ = api
    headers = _register(client, "legacy")
    db.switch_user("legacy")
    db.ledger.save_onboarding_state(
        {
            "intake_step": 1,
            "is_complete": False,
            "profile_data": {"proportions": "long_torso", "gender": "male"},
            "messages": [],
        }
    )
    view = client.get("/onboarding/intake", headers=headers).json()
    assert _field(view, "proportions")["prefilled"] is True
    assert _field(view, "proportions")["answer"] == "long_torso"


def test_completed_account_is_confirmed_and_unaffected(api, monkeypatch):
    client, db, _ = api
    headers = _register(client, "done")
    db.switch_user("done")
    db.ledger.upsert_player_profile(
        {
            "gender": "male",
            "proportions": "balanced",
            "age": 35,
            "weight_kg": 90.0,
            "height_cm": 183.0,
            "rep_preference": "balanced",
            "current_goal": "hypertrophy",
            "long_term_goal": "progressive overload",
            "weekly_frequency": 4,
            "training_age_years": 6.0,
            "equipment_access": "commercial gym",
            "injuries_or_limitations": "None",
            "stress_and_sleep": "normal",
        }
    )
    # A profile *and* an active program is the only confirmed synthesis (2c).
    db.ledger.save_training_program(_program().model_dump())
    calls = _spy_generation(db, monkeypatch)

    view = client.get("/onboarding/intake", headers=headers).json()
    assert view["status"] == "confirmed"
    assert view["disclosure_acknowledged"] is True
    assert _field(view, "gender")["answer"] == "male"
    assert _field(view, "weekly_frequency")["answer"] == 4

    # Already confirmed: no edits, and confirming never regenerates.
    assert _answer(client, headers, "gender", "female").status_code == 409
    assert client.post("/onboarding/intake/confirm", headers=headers).status_code == 200
    assert calls["n"] == 0


def test_profile_without_program_resumes_in_progress_then_confirms(api, monkeypatch):
    """2c: profile written but /complete never ran -> resumable, not confirmed."""
    client, db, _ = api
    headers = _register(client, "graphonly")
    db.switch_user("graphonly")
    db.ledger.upsert_player_profile(
        {
            "gender": "male",
            "proportions": "balanced",
            "age": 35,
            "weight_kg": 90.0,
            "height_cm": 183.0,
            "rep_preference": "balanced",
            "current_goal": "hypertrophy",
            "long_term_goal": "progressive overload",
            "weekly_frequency": 4,
            "training_age_years": 6.0,
            "equipment_access": "commercial gym",
            "injuries_or_limitations": "None",
            "stress_and_sleep": "normal",
        }
    )
    calls = _spy_generation(db, monkeypatch)

    view = client.get("/onboarding/intake", headers=headers).json()
    assert view["status"] == "in_progress"
    assert view["disclosure_acknowledged"] is True
    assert _field(view, "gender")["answer"] == "male"
    assert _field(view, "gender")["prefilled"] is True
    assert _field(view, "weekly_frequency")["answer"] == 4

    # Confirming generates the missing first program from the prefilled answers.
    confirmed = client.post("/onboarding/intake/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["program_name"] == "Player Plan"
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# Program rules unchanged (proportions vs specialization)
# --------------------------------------------------------------------------


def _generation_profile(**overrides: Any) -> dict[str, Any]:
    profile = {
        "gender": "male",
        "proportions": "balanced",
        "age": 28,
        "weight_kg": 80.0,
        "height_cm": 178.0,
        "rep_preference": "balanced",
        "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload",
        "weekly_frequency": 4,
        "training_age_years": 3.0,
        "equipment_access": "commercial gym",
        "injuries_or_limitations": "None",
        "stress_and_sleep": "normal",
    }
    profile.update(overrides)
    return profile


@pytest.fixture
def generation_db(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    from agent import program_generator

    yield db, program_generator
    if db.ledger_conn is not None:
        db.ledger_conn.close()
    db.catalog_conn.close()


def _stub_day_assembly(program_generator, monkeypatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def assemble(**kwargs):
        seen.append(kwargs)
        day = kwargs["day"]
        return ProgramDaySchema(
            day_name=day.day_name,
            day_order=day.day_order,
            exercises=[_exercise(1), _exercise(2), _exercise(3)],
        ), []

    monkeypatch.setattr(program_generator, "assemble_program_day", assemble)
    return seen


def test_proportions_do_not_change_generated_program(generation_db, monkeypatch):
    db, program_generator = generation_db
    seen = _stub_day_assembly(program_generator, monkeypatch)

    programs = {}
    for proportions in ("long_legs", "balanced", "long_torso"):
        db.switch_user(f"prop_{proportions}")
        db.ledger.upsert_player_profile(_generation_profile(proportions=proportions))
        program, _ = program_generator.generate_program_pipeline(ledger=db.ledger)
        programs[proportions] = program.model_dump()

    assert programs["long_legs"] == programs["balanced"] == programs["long_torso"]
    # Day assembly never receives proportions; only the coaching inputs do.
    assert seen and "proportions" not in seen[0]


def test_specialization_does_not_change_the_default_split(generation_db, monkeypatch):
    db, program_generator = generation_db
    _stub_day_assembly(program_generator, monkeypatch)

    db.switch_user("spec_male")
    db.ledger.upsert_player_profile(_generation_profile(gender="male"))
    male, _ = program_generator.generate_program_pipeline(ledger=db.ledger)

    db.switch_user("spec_female")
    db.ledger.upsert_player_profile(_generation_profile(gender="female"))
    female, _ = program_generator.generate_program_pipeline(ledger=db.ledger)

    assert male.split_type == female.split_type == "Upper / Lower (Arms & Delts Augmented)"


def test_confirm_intake_appends_weight_history(api, monkeypatch):
    client, db, _ = api
    headers = _register(client, "weight_intake")
    _ack(client, headers)
    _fill(client, headers)
    _spy_generation(db, monkeypatch)
    before_confirmation = datetime.now(UTC).date().isoformat()

    response = client.post("/onboarding/intake/confirm", headers=headers)

    assert response.status_code == 200, response.text
    with db.open_ledger("weight_intake") as ledger:
        profile = ledger.get_player_profile()
        history = ledger.list_weight_history("0000-01-01", "9999-12-31")
    valid_confirmation_days = {
        before_confirmation,
        datetime.now(UTC).date().isoformat(),
    }
    assert profile["weight_kg"] == 64.5
    assert profile["target_weight_kg"] is None
    assert history[0]["entry_date"] in valid_confirmation_days
    assert history[0]["weight_kg"] == 64.5
    assert len(history) == 1


def test_weight_entry_uses_players_local_day_at_utc_rollover(api, monkeypatch):
    from service import weight_history

    class FrozenDateTime(datetime):
        current = datetime(2026, 10, 5, 23, 30, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(weight_history, "datetime", FrozenDateTime)
    client, db, _ = api
    headers = _register(client, "local_weight_day")
    with db.open_ledger("local_weight_day") as ledger:
        ledger.upsert_player_profile({"weight_kg": 70.0})
        ledger.append_training_schedule(
            "local_weight_day",
            [1],
            "Asia/Riyadh",
            "2026-01-01",
            "2026-01-01T00:00:00+00:00",
        )

    response = client.post(
        "/profile/weight", headers=headers, json={"weight_kg": 71.0}
    )

    assert response.status_code == 200, response.text
    assert response.json()["entry_date"] == "2026-10-06"
    trend = client.get("/profile/weight/trend", headers=headers)
    assert trend.status_code == 200, trend.text
    assert trend.json()["points"] == [
        {"date": "2026-10-06", "weight_kg": 71.0},
    ]


def test_optional_target_weight_can_be_set_during_intake(api, monkeypatch):
    client, db, _ = api
    headers = _register(client, "target_intake")
    _ack(client, headers)
    _fill(client, headers)
    _spy_generation(db, monkeypatch)

    answer = client.put(
        "/onboarding/intake/answers/target_weight_kg",
        headers=headers,
        json={"value": 68.5},
    )
    assert answer.status_code == 200, answer.text
    response = client.post("/onboarding/intake/confirm", headers=headers)

    assert response.status_code == 200, response.text
    with db.open_ledger("target_intake") as ledger:
        assert ledger.get_player_profile()["target_weight_kg"] == 68.5


def test_profile_weight_edit_appends_history(api):
    client, db, _ = api
    headers = _register(client, "weight_profile")
    baseline_day = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    with db.open_ledger("weight_profile") as ledger:
        ledger.upsert_player_profile({"weight_kg": 70.0})
        ledger.upsert_weight_history_entry(baseline_day, 70.0)

    response = client.put("/profile", headers=headers, json={"weight_kg": 71.5})

    assert response.status_code == 200, response.text
    with db.open_ledger("weight_profile") as ledger:
        profile = ledger.get_player_profile()
        history = ledger.list_weight_history(baseline_day, "9999-12-31")
    assert profile["weight_kg"] == 71.5
    assert history[0] == {"entry_date": baseline_day, "weight_kg": 70.0}
    assert len(history) == 2
    assert history[-1]["weight_kg"] == 71.5


def test_weight_entry_endpoint_updates_profile_and_replaces_same_day(api):
    client, db, _ = api
    headers = _register(client, "weight_endpoint")
    with db.open_ledger("weight_endpoint") as ledger:
        ledger.upsert_player_profile({"weight_kg": 70.0})

    recorded_dates = []
    for value in (72.0, 73.5):
        response = client.post("/profile/weight", headers=headers, json={"weight_kg": value})
        assert response.status_code == 200, response.text
        assert response.json()["weight_kg"] == value
        recorded_dates.append(response.json()["entry_date"])

    invalid_low = client.post("/profile/weight", headers=headers, json={"weight_kg": 29.9})
    invalid_high = client.post("/profile/weight", headers=headers, json={"weight_kg": 250.1})
    assert invalid_low.status_code == invalid_high.status_code == 422

    with db.open_ledger("weight_endpoint") as ledger:
        profile = ledger.get_player_profile()
        entries = ledger.list_weight_history(recorded_dates[0], recorded_dates[0])
    assert profile["weight_kg"] == 73.5
    assert recorded_dates[0] == recorded_dates[1]
    assert entries == [{"entry_date": recorded_dates[0], "weight_kg": 73.5}]


def test_profile_target_weight_is_nullable_and_uses_intake_range(api):
    client, db, _ = api
    headers = _register(client, "target_profile")
    with db.open_ledger("target_profile") as ledger:
        ledger.upsert_player_profile({"weight_kg": 70.0})

    for target in (30, 250):
        response = client.put(
            "/profile", headers=headers, json={"target_weight_kg": target}
        )
        assert response.status_code == 200, response.text
        assert response.json()["profile"]["target_weight_kg"] == target

    for target in (29.9, 250.1):
        response = client.put(
            "/profile", headers=headers, json={"target_weight_kg": target}
        )
        assert response.status_code == 422

    cleared = client.put(
        "/profile", headers=headers, json={"target_weight_kg": None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["profile"]["target_weight_kg"] is None


def test_weight_trend_endpoint_returns_points_change_and_target(api):
    client, db, _ = api
    headers = _register(client, "weight_trend_route")
    today = datetime.now(UTC).date()
    earlier = (today - timedelta(days=7)).isoformat()
    older = (today - timedelta(days=30)).isoformat()
    with db.open_ledger("weight_trend_route") as ledger:
        ledger.upsert_player_profile({"weight_kg": 73.0, "target_weight_kg": 70.0})
        ledger.upsert_weight_history_entry(older, 71.0)
        ledger.upsert_weight_history_entry(earlier, 72.0)
        ledger.upsert_weight_history_entry(today.isoformat(), 73.0)

    response = client.get("/profile/weight/trend", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "points": [
            {"date": older, "weight_kg": 71.0},
            {"date": earlier, "weight_kg": 72.0},
            {"date": today.isoformat(), "weight_kg": 73.0},
        ],
        "change_kg": 2.0,
        "target_weight_kg": 70.0,
    }

    short = client.get("/profile/weight/trend?weeks=1", headers=headers)
    assert short.status_code == 200, short.text
    assert [point["date"] for point in short.json()["points"]] == [
        earlier,
        today.isoformat(),
    ]
    assert client.get("/profile/weight/trend?weeks=0", headers=headers).status_code == 422
    assert client.get("/profile/weight/trend?weeks=53", headers=headers).status_code == 422


def test_weight_trend_route_checks_profile_before_reading_history(api, monkeypatch):
    from service import weight_history

    client, _, _ = api
    headers = _register(client, "profile_missing_weight_trend")
    monkeypatch.setattr(
        weight_history,
        "get_weight_trend",
        lambda *args, **kwargs: pytest.fail("history loaded without a profile"),
    )

    response = client.get("/profile/weight/trend", headers=headers)

    assert response.status_code == 404
