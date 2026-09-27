"""Contract tests for the structured, resumable onboarding intake (ADR 021, #50).

Hermetic: temporary ledgers, real auth, generation stubbed. Covers validation,
per-answer persistence, resume progress, edits, the disclosure gate, legacy
prefill, confirmation (once, idempotent), and the unchanged program rules
(proportions are coaching context; specialization keeps its split effect).
"""

import sqlite3
import threading
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
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _register(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post(
        "/auth/register", json={"trainee_id": username, "password": "correct-horse-1"}
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


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
        profile = kwargs["ledger"].get_user_profile()
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
    assert gender["explanation"] and "female" in gender["explanation"]
    # Every enum value carries the training-effect description shown on its card.
    assert set(gender["option_descriptions"]) == {"male", "female"}
    assert all(gender["option_descriptions"].values())
    assert "frequency" in gender["option_descriptions"]["female"]
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
    profile = db.ledger.get_user_profile()
    assert profile["gender"] == "female"
    assert profile["weekly_frequency"] == 4
    assert profile["proportions"] == "long_legs"
    assert db.ledger.get_active_program() is not None

    # Re-confirming replays the stored result and never generates again.
    again = client.post("/onboarding/intake/confirm", headers=headers)
    assert again.status_code == 200
    assert again.json()["program_name"] == "Player Plan"
    assert calls["n"] == 1


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
    profile = db.ledger.get_user_profile()
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
    assert second.json() == {"error": "confirm_in_progress"}

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert calls["n"] == 1
    assert results and results[0].status_code == 200


def test_failed_generation_releases_claim_for_retry(api, monkeypatch):
    """A 429 during generation resets the claim so a retry can still generate."""
    from service.model_limits import ModelLimitExceeded

    client, db, _ = api
    headers = _register(client, "retry")
    _ack(client, headers)
    _fill(client, headers)

    state = {"fail": True}

    def fake(**kwargs):
        if state["fail"]:
            state["fail"] = False
            raise ModelLimitExceeded("Too many AI requests. Please wait a minute and try again.")
        program = _program()
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "markdown"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", fake)

    first = client.post("/onboarding/intake/confirm", headers=headers)
    assert first.status_code == 429, first.text
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
    db.ledger.upsert_user_profile(
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
    db.ledger.upsert_user_profile(
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


def test_legacy_complete_marks_structured_intake_confirmed(api, monkeypatch):
    """2a: legacy /complete confirms an existing structured intake and stores its program."""
    client, db, _ = api
    headers = _register(client, "legacycomplete")
    db.switch_user("legacycomplete")
    db.ledger.save_onboarding_state(
        {"intake_step": 3, "is_complete": True, "profile_data": {"gender": "female"}, "messages": []}
    )
    _ack(client, headers)
    assert _answer(client, headers, "gender", "female").status_code == 200
    calls = _spy_generation(db, monkeypatch)

    completed = client.post("/onboarding/complete", headers=headers)
    assert completed.status_code == 200, completed.text

    view = client.get("/onboarding/intake", headers=headers).json()
    assert view["status"] == "confirmed"
    assert view["program"]["program_name"] == "Player Plan"
    # Post-confirm edits are refused and confirming replays; no second program.
    assert _answer(client, headers, "gender", "male").status_code == 409
    again = client.post("/onboarding/intake/confirm", headers=headers)
    assert again.status_code == 200
    assert calls["n"] == 1


def test_legacy_routes_refused_while_structured_intake_active(api, monkeypatch):
    """2b: /start and /step (incl. reset) refuse once a structured intake exists."""
    from langchain_core.messages import AIMessage

    from service import onboarding as onboarding_service

    def fake_start(db, trainee_id, player_account_id=None, ledger=None):
        return {
            "messages": [AIMessage(content="Q1?")],
            "trainee_id": trainee_id,
            "intake_step": 1,
            "is_complete": False,
            "profile_data": None,
        }

    monkeypatch.setattr(onboarding_service, "start_onboarding", fake_start)
    client, _, _ = api

    active = _register(client, "active")
    _ack(client, active)
    _answer(client, active, "gender", "female")
    for path, body in (
        ("/onboarding/start", None),
        ("/onboarding/step", {"content": "x"}),
        ("/onboarding/step", {"content": "x", "reset": True}),
    ):
        resp = client.post(path, headers=active, json=body) if body else client.post(path, headers=active)
        assert resp.status_code == 409, (path, resp.text)
        assert resp.json() == {"error": "structured_intake_active"}

    # An account with no structured row keeps the legacy routes (backward compat).
    fresh = _register(client, "fresh")
    assert client.post("/onboarding/start", headers=fresh).status_code == 200


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
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    from agent import program_generator

    yield db, program_generator
    if db.user_conn is not None:
        db.user_conn.close()
    db.catalog_conn.close()


def _stub_day_assembly(program_generator, monkeypatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def fake_day(**kwargs):
        seen.append(kwargs)
        return ProgramDaySchema(
            day_name=kwargs["day"].day_name,
            day_order=1,
            exercises=[_exercise(1), _exercise(2), _exercise(3)],
        )

    monkeypatch.setattr(program_generator, "assemble_deterministic_day", fake_day)
    return seen


def test_proportions_do_not_change_generated_program(generation_db, monkeypatch):
    db, program_generator = generation_db
    seen = _stub_day_assembly(program_generator, monkeypatch)

    programs = {}
    for proportions in ("long_legs", "balanced", "long_torso"):
        db.switch_user(f"prop_{proportions}")
        db.ledger.upsert_user_profile(_generation_profile(proportions=proportions))
        program, _ = program_generator.generate_program_pipeline(ledger=db.ledger)
        programs[proportions] = program.model_dump()

    assert programs["long_legs"] == programs["balanced"] == programs["long_torso"]
    # Day assembly never receives proportions; only the coaching inputs do.
    assert seen and "proportions" not in seen[0]


def test_specialization_still_changes_the_split(generation_db, monkeypatch):
    db, program_generator = generation_db
    _stub_day_assembly(program_generator, monkeypatch)

    db.switch_user("spec_male")
    db.ledger.upsert_user_profile(_generation_profile(gender="male"))
    male, _ = program_generator.generate_program_pipeline(ledger=db.ledger)

    db.switch_user("spec_female")
    db.ledger.upsert_user_profile(_generation_profile(gender="female"))
    female, _ = program_generator.generate_program_pipeline(ledger=db.ledger)

    assert male.split_type != female.split_type
