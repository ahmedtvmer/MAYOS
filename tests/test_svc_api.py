"""FastAPI route tests: isolated DB, bypassed JWT subject, mocked LLM-bound calls."""

import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_current_trainee, get_db


TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
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
        active_user="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_trainee] = lambda: "alice"
    with TestClient(app) as test_client:
        yield test_client
    if db.user_conn is not None:
        db.user_conn.close()
    db.catalog_conn.close()


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "draining"}


def test_register_login_roundtrip(client):
    assert client.post("/auth/register", json={"trainee_id": "Alice!", "password": "correct-horse-1"}).status_code == 201
    assert client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 409
    assert client.post("/auth/register", json={"trainee_id": "shorty", "password": "short"}).status_code == 422
    login = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert login.status_code == 200
    assert login.json()["trainee_id"] == "alice"
    assert login.json()["token_type"] == "bearer"
    # Unknown user and wrong password are indistinguishable.
    ghost = client.post("/auth/login", json={"trainee_id": "ghost", "password": "correct-horse-9"})
    wrong = client.post("/auth/login", json={"trainee_id": "alice", "password": "wrong-horse-99"})
    assert ghost.status_code == wrong.status_code == 401
    assert ghost.json() == wrong.json()


def test_remember_me_token_lifetime(client, monkeypatch):
    import jwt as pyjwt

    def lifetime_hours(token):
        claims = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
        return (claims["exp"] - claims["iat"]) / 3600

    registered = client.post(
        "/auth/register",
        json={"trainee_id": "alice", "password": "correct-horse-1", "remember_me": True},
    )
    assert registered.status_code == 201
    assert lifetime_hours(registered.json()["access_token"]) == 720  # 30 days remembered

    default_login = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert lifetime_hours(default_login.json()["access_token"]) == 2

    remembered = client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1", "remember_me": True}
    )
    assert lifetime_hours(remembered.json()["access_token"]) == 720

    monkeypatch.setenv("JWT_REMEMBER_ME_HOURS", "48")
    overridden = client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1", "remember_me": True}
    )
    assert lifetime_hours(overridden.json()["access_token"]) == 48


def test_legacy_claim_flow(client):
    from database.database_manager import DatabaseManager

    # Simulate a pre-password ledger: user file exists, no hash stored.
    client.post("/auth/register", json={"trainee_id": "legacy", "password": "correct-horse-1"})
    db = DatabaseManager()
    db.switch_user("legacy")
    db.conn.execute("DELETE FROM auth_credentials WHERE id = 1")
    db.conn.commit()
    claimed_login = client.post("/auth/login", json={"trainee_id": "legacy", "password": "correct-horse-1"})
    assert claimed_login.status_code == 403
    assert client.post("/auth/claim", json={"trainee_id": "legacy", "password": "short"}).status_code in {400, 422}
    claim = client.post("/auth/claim", json={"trainee_id": "legacy", "password": "new-horse-22"})
    assert claim.status_code == 200
    assert client.post("/auth/login", json={"trainee_id": "legacy", "password": "new-horse-22"}).status_code == 200
    # Claim is single-use.
    assert client.post("/auth/claim", json={"trainee_id": "legacy", "password": "another-33"}).status_code == 401
    # Hash stored, never plaintext.
    db.switch_user("legacy")
    stored = db.get_password_hash()
    assert stored and stored != "new-horse-22" and stored.startswith("$2")


def test_cross_user_isolation_with_real_jwt(tmp_path, monkeypatch):
    import sqlite3
    import threading

    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path, users_dir=tmp_path / "users", backups_dir=tmp_path / "backups", active_user="bootstrap"
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as api:
            alice = api.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()
            bob_token = api.post("/auth/register", json={"trainee_id": "bob", "password": "correct-horse-2"}).json()["access_token"]
            alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
            bob_headers = {"Authorization": f"Bearer {bob_token}"}
            assert api.put("/profile", json={"current_goal": "AliceGoal"}, headers=alice_headers).status_code == 200
            # Bob sees none of Alice's data.
            assert api.get("/profile", headers=bob_headers).status_code == 404
            assert api.get("/chat/history", headers=bob_headers).json() == []
            assert api.get("/profile", headers=alice_headers).json()["current_goal"] == "AliceGoal"
            # No token at all is rejected.
            assert api.get("/profile").status_code in {401, 403}
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _real_jwt_app(tmp_path, monkeypatch):
    """App with real JWT verification (no subject override) on an isolated DB."""
    import sqlite3
    import threading

    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute(
        "INSERT INTO exercises (id, name) VALUES ('sq', 'Squat'), ('bp', 'Bench Press'), ('row', 'Row')"
    )
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path, users_dir=tmp_path / "users", backups_dir=tmp_path / "backups", active_user="bootstrap"
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return app, db


def test_active_program_served_for_returning_user(tmp_path, monkeypatch):
    app, db = _real_jwt_app(tmp_path, monkeypatch)
    try:
        with TestClient(app) as api:
            token = api.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            db.switch_user("alice")
            db.upsert_user_profile({"current_goal": "Strength"})
            db.save_training_program(
                {
                    "program_name": "Saved Split",
                    "weekly_frequency": 3,
                    "split_type": "Full Body",
                    "days": [
                        {
                            "day_name": "Full A",
                            "day_order": 1,
                            "exercises": [
                                {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                                {"exercise_id": "bp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                                {"exercise_id": "row", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                            ],
                        }
                    ],
                }
            )
            resp = api.get("/programs/active", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["program_name"] == "Saved Split"
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _exercise_payload(exercise_id, exercise_name):
    return {
        "exercise_id": exercise_id,
        "exercise_name": exercise_name,
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rpe": 8.5,
        "rest_seconds": 120,
        "notes": None,
    }


def _saved_split_payload():
    return {
        "program_name": "Saved Split",
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": "Full A",
                "day_order": 1,
                "exercises": [
                    {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "bp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "row", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                ],
            }
        ],
    }


def test_workout_commit_detects_prs_and_dashboard_serves_them(tmp_path, monkeypatch):
    app, db = _real_jwt_app(tmp_path, monkeypatch)
    try:
        with TestClient(app) as api:
            token = api.post(
                "/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            db.switch_user("alice")
            db.upsert_user_profile({"current_goal": "Strength"})
            db.save_training_program(_saved_split_payload())

            commit = api.post(
                "/workouts/sessions",
                headers=headers,
                json={
                    "day_order": 1,
                    "readiness": 4,
                    "session_notes": "",
                    "sets": [
                        {
                            "exercise": _exercise_payload("sq", "Squat"),
                            "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}],
                        }
                    ],
                },
            )
            assert commit.status_code == 201
            body = commit.json()
            assert {event["record_type"] for event in body["new_prs"]} == {"max_weight", "max_e1rm"}
            assert "🏆 New PR: Squat" in body["debrief"]

            shelf = api.get("/dashboard/personal-records", headers=headers)
            assert shelf.status_code == 200
            assert any(record["exercise_id"] == "sq" for record in shelf.json())

            history = api.get("/dashboard/exercises/sq/history", headers=headers).json()
            assert history["records"]
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def test_session_export_csv_json_and_404(tmp_path, monkeypatch):
    app, db = _real_jwt_app(tmp_path, monkeypatch)
    try:
        with TestClient(app) as api:
            token = api.post(
                "/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            assert api.get("/workouts/sessions/export.csv", headers=headers).status_code == 404
            assert api.get("/workouts/sessions/export.json", headers=headers).status_code == 404

            db.switch_user("alice")
            db.upsert_user_profile({"current_goal": "Strength"})
            db.save_training_program(_saved_split_payload())
            commit = api.post(
                "/workouts/sessions",
                headers=headers,
                json={
                    "day_order": 1,
                    "readiness": 4,
                    "session_notes": "",
                    "sets": [
                        {
                            "exercise": _exercise_payload("sq", "Squat"),
                            "sets": [{"weight_kg": 100.0, "reps": 8, "rpe": 8.5}],
                        }
                    ],
                },
            )
            assert commit.status_code == 201

            csv_response = api.get("/workouts/sessions/export.csv", headers=headers)
            assert csv_response.status_code == 200
            assert csv_response.headers["content-type"].startswith("text/csv")
            assert "attachment" in csv_response.headers["content-disposition"]
            csv_text = csv_response.text
            assert csv_text.splitlines()[0].split(",")[0] == "session_date"
            assert "Squat" in csv_text
            assert "131.67" in csv_text  # 100 kg x 8 @ RPE 8.5 e1RM
            assert "800.0" in csv_text

            json_response = api.get("/workouts/sessions/export.json", headers=headers)
            assert json_response.status_code == 200
            payload = json_response.json()
            assert payload["schema_version"] == 1
            session = payload["sessions"][0]
            assert session["coach_debrief"]
            assert session["exercises"][0]["exercise_name"] == "Squat"
            assert session["exercises"][0]["sets"][0]["e1rm_kg"] == 131.67
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def test_logout_revokes_token(tmp_path, monkeypatch):
    app, db = _real_jwt_app(tmp_path, monkeypatch)
    try:
        with TestClient(app) as api:
            token = api.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            assert api.get("/dashboard/exercises", headers=headers).status_code == 200
            assert api.post("/auth/logout", headers=headers).status_code == 204
            assert api.get("/dashboard/exercises", headers=headers).status_code == 401
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def test_expired_token_rejected(tmp_path, monkeypatch):
    from svc.auth import create_access_token

    app, db = _real_jwt_app(tmp_path, monkeypatch)
    try:
        with TestClient(app) as api:
            api.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
            stale = create_access_token("alice", expires_hours=-1)
            assert api.get("/dashboard/exercises", headers={"Authorization": f"Bearer {stale}"}).status_code == 401
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def test_login_rate_limit(client):
    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    statuses = [client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code for _ in range(7)]
    assert statuses.count(200) == 5
    assert statuses.count(429) == 2


def test_profile_crud_without_body_identity(client):
    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert client.get("/profile").status_code == 404
    # A body-supplied identity must be ignored: schemas reject it and the JWT subject wins.
    update = client.put("/profile", json={"current_goal": "Strength", "trainee_id": "bob"})
    assert update.status_code in {200, 422}
    profile = client.get("/profile").json()
    assert profile["current_goal"] == ("Strength" if update.status_code == 200 else profile["current_goal"])
    persona = client.put("/profile/persona", json={"coach_tone": "Direct", "custom_instructions": ""})
    assert persona.status_code == 200
    assert client.delete("/profile").status_code == 204
    assert client.get("/profile").status_code == 404


def test_dashboard_empty_ledger(client):
    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    volume = client.get("/dashboard/volume").json()
    assert volume["Quads"] == 0.0
    assert client.get("/dashboard/exercises").json() == []
    history = client.get("/dashboard/exercises/sq/history").json()
    assert history == {"history": [], "caption": None, "records": []}
    assert client.get("/dashboard/personal-records").json() == []


def test_chat_history_and_turn(client, monkeypatch):
    from svc.routers import chat as chat_router

    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})

    def fake_turn(state):
        state["response_content"] = "Keep elbows tucked."
        state["program_updated"] = False
        state["messages"] = list(state["messages"]) + [AIMessage(content="Keep elbows tucked.")]
        yield "Keep elbows tucked."

    monkeypatch.setattr(chat_router, "stream_assistant_turn", fake_turn)
    with client.stream("POST", "/chat/messages", json={"content": "Cue my bench?", "trainee_id": "bob"}) as stream:
        assert stream.status_code in {200, 422}
        frames = [line for line in stream.iter_lines() if line.startswith("data:")]
    import json as _json

    events = [_json.loads(frame[len("data: "):]) for frame in frames]
    assert any(event.get("token") for event in events)
    done = next(event for event in events if event.get("done"))
    assert done["response_content"] == "Keep elbows tucked."
    history = client.get("/chat/history").json()
    roles = [m["role"] for m in history]
    assert "user" in roles
    assert client.delete("/chat/history").status_code == 204
    assert client.get("/chat/history").json() == []


def test_chat_error_frame_never_leaks(client, monkeypatch):
    from svc.routers import chat as chat_router

    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})

    def boom(state):
        raise RuntimeError("internal database secret")
        yield ""

    monkeypatch.setattr(chat_router, "stream_assistant_turn", boom)
    with client.stream("POST", "/chat/messages", json={"content": "Hi?"}) as stream:
        assert stream.status_code == 200
        raw = stream.read().decode()
    assert "event: error" in raw
    assert "secret" not in raw


def test_workouts_require_program(client):
    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert client.get("/dashboard/volume").status_code == 200


def test_lifespan_skip_mode_and_drain_flag(monkeypatch):
    import svc.app as app_module

    # Hermetic even without shell env: skip-mode is the behavior under test.
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    app_module._ready.update({"model": False, "catalog": False, "draining": False})
    app = create_app()
    with TestClient(app):
        assert app_module._ready["catalog"] is True
        assert app_module._ready["model"] is False
    assert app_module._ready["draining"] is True
    app_module._ready.update({"model": False, "catalog": False, "draining": False})


def test_onboarding_state_is_server_side(client, monkeypatch):
    from service import onboarding as onboarding_service

    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    calls = []

    def fake_start(db, trainee_id):
        calls.append(trainee_id)
        return {"messages": [AIMessage(content="Q1?")], "trainee_id": trainee_id, "intake_step": 1, "is_complete": False, "profile_data": None}

    def fake_answer(db, trainee_id, state, user_input):
        calls.append((trainee_id, user_input))
        state["messages"].append(HumanMessage(content=user_input))
        state["messages"].append(AIMessage(content="Q2?"))
        return state

    monkeypatch.setattr(onboarding_service, "start_onboarding", fake_start)
    monkeypatch.setattr(onboarding_service, "answer_intake", fake_answer)
    started = client.post("/onboarding/start").json()
    assert started["messages"] == ["Q1?"]
    step = client.post("/onboarding/step", json={"content": "25"}).json()
    assert step["messages"] == ["Q2?"]
    assert calls[1] == ("alice", "25")


def test_onboarding_answer_keeps_assistant_reply_when_prior_messages_exist(client):
    """Regression: Fly onboarding advanced but returned no assistant replies."""
    assert client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 201
    assert client.post("/onboarding/start").status_code == 200

    for answer, next_step, is_complete in (
        ("1: lower body 2: male, 30 years, 80 kg, 180 cm", 2, False),
        ("3: build muscle 4: stay strong 5: 3 days 6: 2 years", 3, False),
        ("7: full gym 8: no injuries 9: low stress, 8 hours sleep", 3, True),
    ):
        response = client.post("/onboarding/step", json={"content": answer})
        assert response.status_code == 200
        assert response.json()["intake_step"] == next_step
        assert response.json()["is_complete"] is is_complete
        assert response.json()["messages"]


def test_onboarding_state_survives_restart(client, monkeypatch):
    from service import onboarding as onboarding_service

    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    seen_states = []

    def fake_start(db, trainee_id):
        return {"messages": [AIMessage(content="Q1?")], "trainee_id": trainee_id, "intake_step": 1, "is_complete": False, "profile_data": None}

    def fake_answer(db, trainee_id, state, user_input):
        seen_states.append((trainee_id, [m.content for m in state["messages"]], user_input))
        state["messages"].append(HumanMessage(content=user_input))
        state["messages"].append(AIMessage(content="Q2?"))
        return state

    monkeypatch.setattr(onboarding_service, "start_onboarding", fake_start)
    monkeypatch.setattr(onboarding_service, "answer_intake", fake_answer)
    assert client.post("/onboarding/start").json()["messages"] == ["Q1?"]
    assert client.post("/onboarding/step", json={"content": "25"}).json()["messages"] == ["Q2?"]
    # Second step reloads persisted state from the ledger: prior messages present without process memory.
    assert client.post("/onboarding/step", json={"content": "male"}).json()["messages"] == ["Q2?"]
    assert seen_states[1][1] == ["Q1?", "25", "Q2?"]
    assert seen_states[1][2] == "male"


def test_onboarding_start_resumes_persisted_progress(client, monkeypatch):
    """An app restart calls /onboarding/start again: it must resume, not reset."""
    from service import onboarding as onboarding_service

    client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    answered_from = []

    def fake_start(db, trainee_id):
        return {
            "messages": [AIMessage(content="Q1?")],
            "trainee_id": trainee_id,
            "intake_step": 1,
            "is_complete": False,
            "profile_data": None,
        }

    def fake_answer(db, trainee_id, state, user_input):
        answered_from.append([m.content for m in state["messages"]])
        state["messages"].append(HumanMessage(content=user_input))
        state["messages"].append(AIMessage(content="Q2?"))
        return state

    monkeypatch.setattr(onboarding_service, "start_onboarding", fake_start)
    monkeypatch.setattr(onboarding_service, "answer_intake", fake_answer)

    assert client.post("/onboarding/step", json={"content": "25"}).json()["messages"] == ["Q2?"]

    # A fresh /onboarding/start, as after an app restart mid-intake, returns the
    # full assistant conversation instead of discarding saved progress.
    resumed = client.post("/onboarding/start")
    assert resumed.status_code == 200
    assert resumed.json()["messages"] == ["Q1?", "Q2?"]

    # Explicit reset on /onboarding/step still clears saved progress before answering.
    reset = client.post("/onboarding/step", json={"content": "restart", "reset": True}).json()
    assert reset["messages"] == ["Q2?"]
    assert answered_from[-1] == ["Q1?"]
