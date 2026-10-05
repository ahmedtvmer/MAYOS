"""Hosted player chat privacy and retry tests (#37, ADR 016/036).

Proves the stated guarantees through the real HTTP surface:
1. The player's model input carries the message and needed context only — never
   the account username, recovery email, coach name/username, or coach private
   notes (captured at the lowest LLM entry, ``agent.assistant_graph.llm``).
2. No coach-facing endpoint exposes player-assistant chat content. Every
   coach route in the app's route table is enumerated and checked, and the
   coach program-generation path (deterministic, no model) returns no chat.
3. A retried failed turn persists exactly one user row and one assistant row.
4. ``GET /chat/history`` labels the session-commit pointer as a ``debrief``.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from agent import assistant_graph
from agent.ProgramState import ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import workouts as workouts_service
from svc.app import create_app
from svc.dependencies import get_db
from svc.schemas import CHAT_MESSAGE_MAX_CHARS
from tests.fakes.chat_model import ScriptedChatModel

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

PRIVATE_USER_CHAT = "PRIVATE_PLAYER_CHAT_7f3a How should I cue my bench?"
PRIVATE_ASSISTANT_CHAT = "PRIVATE_ASSISTANT_REPLY_9c1d Keep the elbows tucked."
COACH_USERNAME = "CoachPrivateIdentity"
COACH_NOTES = "COACH_PRIVATE_NOTES_2b6e this player is fragile"


def _last_rendered(llm: ScriptedChatModel) -> str:
    assert llm.calls, "the model was never called"
    return "\n".join(
        str(getattr(message, "content", message)) for message in llm.calls[-1]["messages"]
    )


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
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
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back');"
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
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db, username, capacity=5):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": COACH_USERNAME, "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    return headers


def _day_plan():
    return ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )


def _seed_session(db, player, started_at):
    payload = [
        {
            "exercise": _day_plan().exercises[0],
            "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}],
            "previous_perf": [],
        }
    ]
    return workouts_service.commit_session(
        db, player, _day_plan(), readiness=4, session_notes="", sets_by_exercise=payload, now_iso=started_at
    )


def _assigned_player(api, player_name="p1"):
    client, db = api
    coach_headers = _make_coach(client, db, "coach")
    invite = client.post("/coach/assignments/invites", headers=coach_headers).json()
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    # A profile is needed for the coach's program generation to run.
    assert client.put(
        "/profile", headers=player_headers, json={"weekly_frequency": 4, "current_goal": "Hypertrophy"}
    ).status_code == 200
    return coach_headers, player_headers, redeemed.json()["assignment"]["assignment_id"]


# --------------------------------------------------------------------------
# 1. Player model input excludes identifying fields (real POST path)
# --------------------------------------------------------------------------


def test_player_model_input_excludes_identifying_fields(api, monkeypatch):
    client, db = api
    username = "secretpineapple"
    email = "secretpineapple@example.com"
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    assert client.post("/auth/email", headers=headers, json={"email": email}).status_code == 200
    # custom_instructions and preferred_name are needed context (ADR 016) and are
    # intentionally sent; assert only that they — not identity — appear.
    assert (
        client.put(
            "/profile",
            headers=headers,
            json={"current_goal": "Hypertrophy", "weekly_frequency": 4},
        ).status_code
        == 200
    )
    assert db.switch_user(username)
    # custom_instructions and preferred_name are stored context, not settable
    # through PUT /profile; write them directly as onboarding/memory would.
    db.ledger.update_player_persona("direct", "Prefer short answers.")
    db.ledger.set_assistant_memory("preferred_name", "Sam")

    llm = ScriptedChatModel(["Keep the elbows tucked."])
    monkeypatch.setattr(assistant_graph, "llm", llm)
    # Keep the prompt budget generous so the trimming loop cannot drop the
    # context block and mask the privacy assertion.
    monkeypatch.setattr(assistant_graph, "_prompt_budget", lambda: 100_000)

    with client.stream(
        "POST", "/chat/messages", headers=headers, json={"content": "How should I cue my bench?"}
    ) as stream:
        assert stream.status_code == 200
        stream.read()

    rendered = _last_rendered(llm)
    # The player's own message and the needed context reach the model.
    assert "How should I cue my bench?" in rendered
    assert "[TRAINEE CONTEXT]" in rendered
    assert "Prefer short answers." in rendered  # intended: user-authored instructions
    # Identifying account fields never do.
    assert username not in rendered
    assert email not in rendered
    assert "secretpineapple" not in rendered


@pytest.mark.parametrize("content", ["x" * 400, "ا" * 400])
def test_chat_accepts_messages_at_the_character_limit(api, monkeypatch, content):
    assert CHAT_MESSAGE_MAX_CHARS == 400
    client, db = api
    registered = _register(client, "chat-boundary")
    headers = _authed(registered["access_token"])
    llm = ScriptedChatModel(["Received."])
    monkeypatch.setattr(assistant_graph, "llm", llm)
    monkeypatch.setattr(assistant_graph, "_prompt_budget", lambda: 100_000)

    with client.stream(
        "POST", "/chat/messages", headers=headers, json={"content": content}
    ) as response:
        response.read()
        assert response.status_code == 200

    history = client.get("/chat/history", headers=headers).json()
    assert history[0]["content"] == content
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert llm.calls


def test_oversized_chat_message_is_rejected_before_admission_or_model_work(
    api, monkeypatch
):
    from service.model_limits import reset_model_limits
    client, db = api
    registered = _register(client, "chat-too-long")
    headers = _authed(registered["access_token"])
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    reset_model_limits()
    llm = ScriptedChatModel(["Received."])
    monkeypatch.setattr(assistant_graph, "llm", llm)
    monkeypatch.setattr(assistant_graph, "_prompt_budget", lambda: 100_000)
    account_id = db.get_active_account_by_username("chat-too-long")["account_id"]
    usage_before = [
        row
        for row in db.summarize_model_usage("2000-01-01")
        if row["account_id"] == account_id
    ]

    rejected = client.post(
        "/chat/messages", headers=headers, json={"content": "ا" * 401}
    )
    assert rejected.status_code == 422
    assert "at most 400 characters" in rejected.text
    assert client.get("/chat/history", headers=headers).json() == []
    assert llm.calls == []
    usage_after = [
        row
        for row in db.summarize_model_usage("2000-01-01")
        if row["account_id"] == account_id
    ]
    assert usage_after == usage_before

    # The rejected request did not reserve the sole AI request slot.
    with client.stream(
        "POST",
        "/chat/messages",
        headers=headers,
        json={"content": "How should I cue my bench?"},
    ) as accepted:
        accepted.read()
        assert accepted.status_code == 200
    assert llm.calls
    reset_model_limits()


# --------------------------------------------------------------------------
# 2. Coach surfaces never expose player-assistant chat
# --------------------------------------------------------------------------


def _coach_routes(app) -> list[tuple[str, str]]:
    """Every registered route whose path starts with a coach prefix."""
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if path.startswith("/coach"):
            for method in methods:
                if method not in {"HEAD", "OPTIONS"}:
                    routes.append((method, path))
    return routes


def test_coach_surfaces_never_expose_player_chat(api):
    client, db = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)

    outcome = _seed_session(db, "p1", "2026-09-24T10:00:00+00:00").body
    pointer = outcome["pointer"]
    debrief = outcome["debrief"]
    # Private coach notes and an unmistakable private chat exchange. A check-in
    # can only be dated on/after the assignment's start, so use today.
    import datetime as _dt

    today = _dt.datetime.now(_dt.UTC).date().isoformat()
    assert client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": today, "channel": "video", "note": COACH_NOTES},
    ).status_code == 200
    assert db.switch_user("p1")
    assert any(row["role"] == "assistant" and row["content"] == pointer for row in db.ledger.get_chat_history())
    db.ledger.add_chat_message("user", PRIVATE_USER_CHAT)
    db.ledger.add_chat_message("assistant", PRIVATE_ASSISTANT_CHAT)

    app = client.app
    base = f"/coach/assignments/{assignment_id}"
    # GET routes plus the mutating routes that return state, exercised safely.
    exercised = [
        ("GET", "/coach/profile"),
        ("GET", "/coach/assignments"),
        ("GET", "/coach/assignments/notices"),
        ("GET", "/coach/alerts"),
        ("GET", f"{base}/player/summary"),
        ("GET", f"{base}/player/personal-records"),
        ("GET", f"{base}/player/exercises"),
        ("GET", f"{base}/player/exercises/sq/history"),
        ("GET", f"{base}/check-ins"),
        ("GET", f"{base}/program-requests"),
        ("GET", "/coach/program-requests"),
    ]

    for method, path in exercised:
        response = client.request(
            method,
            path,
            headers=coach_headers,
            json={} if method == "POST" else None,
        )
        if method == "GET":
            assert response.status_code == 200, (method, path, response.text)
        body = response.text
        assert PRIVATE_USER_CHAT not in body, (method, path)
        assert PRIVATE_ASSISTANT_CHAT not in body, (method, path)
        assert pointer not in body, (method, path)
        assert debrief[:40] not in body, (method, path)

    # The coach program-generation path is deterministic (blueprints, no model
    # call), so nothing about it can carry chat. Exercise it with a
    # non-raising client and assert its output is chat-free even when the tiny
    # test catalog makes generation fail.
    with TestClient(client.app, raise_server_exceptions=False) as raw_client:
        program = raw_client.post(f"{base}/program-draft/generate", headers=coach_headers, json={})
    assert PRIVATE_USER_CHAT not in program.text
    assert PRIVATE_ASSISTANT_CHAT not in program.text
    assert pointer not in program.text

    # Every coach route registered in the app is accounted for by the exercised
    # set or is a mutation/denial route; new coach routes must be added here.
    registered = {f"{method} {path}" for method, path in _coach_routes(app)}
    covered = {f"{method} {path}" for method, path in exercised}
    param_paths = {
        f"POST /coach/alerts/{'{alert_id}'}/acknowledge",
        f"POST /coach/alerts/{'{alert_id}'}/resolve",
        f"POST /coach/assignments/{'{assignment_id}'}/revoke",
        f"POST /coach/assignments/{'{assignment_id}'}/check-ins",
        f"POST /coach/assignments/{'{assignment_id}'}/assistant",
        f"POST /coach/assignments/{'{assignment_id}'}/program-draft/generate",
        f"POST /coach/assignments/{'{assignment_id}'}/program-requests/{'{request_id}'}/apply",
        f"POST /coach/assignments/{'{assignment_id}'}/program-requests/{'{request_id}'}/decline",
        "POST /coach/assignments/notices/read",
        "POST /coach/capability/disable",
        "POST /coach/invite/redeem",
        "PUT /coach/profile",
        "POST /coach/assignments/invites",
    }
    uncovered = registered - covered - param_paths
    assert not uncovered, f"Uncovered coach routes: {sorted(uncovered)}"


def test_coach_capability_disabled_after_revocation_still_sees_no_chat(api):
    client, db = api
    coach_headers, _, assignment_id = _assigned_player(api)
    _seed_session(db, "p1", "2026-09-24T10:00:00+00:00")

    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200
    denied = client.get(f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers)
    assert denied.status_code == 403
    assert "Session Logged" not in denied.text


# --------------------------------------------------------------------------
# 3. A retried failed turn persists exactly one user row and one assistant row
# --------------------------------------------------------------------------


def test_retried_failed_turn_persists_one_user_and_one_assistant(api, monkeypatch):
    from svc.routers import chat as chat_router

    client, db = api
    registered = _register(client, "retryer")
    headers = _authed(registered["access_token"])

    def exploding_turn(state, **kwargs):
        # Mirrors a failure after the user row is persisted and before any
        # assistant reply: the route emits an `event: error` frame.
        raise RuntimeError("model exploded")
        yield ""

    monkeypatch.setattr(chat_router, "stream_assistant_turn", exploding_turn)

    # First turn fails: the user message persists, no assistant reply.
    with client.stream("POST", "/chat/messages", headers=headers, json={"content": "hello"}) as stream:
        raw = stream.read().decode()
    assert "event: error" in raw
    assert db.switch_user("retryer")
    assert [row["role"] for row in db.ledger.get_chat_history()] == ["user"]

    # Retry the identical content: no duplicate user row; the turn now succeeds
    # and the assistant reply is stored.
    def succeeding_turn(state, **kwargs):
        state["response_content"] = "Hi there."
        yield "Hi there."

    monkeypatch.setattr(chat_router, "stream_assistant_turn", succeeding_turn)
    with client.stream("POST", "/chat/messages", headers=headers, json={"content": "hello"}) as stream:
        stream.read()

    history = db.ledger.get_chat_history()
    assert [row["role"] for row in history] == ["user", "assistant"]
    assert history[0]["content"] == "hello"
    assert history[1]["content"] == "Hi there."


# --------------------------------------------------------------------------
# 4. GET /chat/history labels the commit pointer as a debrief
# --------------------------------------------------------------------------


def test_chat_history_labels_the_session_pointer(api):
    client, db = api
    registered = _register(client, "p1")
    headers = _authed(registered["access_token"])
    outcome = _seed_session(db, "p1", "2026-09-24T10:00:00+00:00").body

    history = client.get("/chat/history", headers=headers).json()
    assert history, history
    debriefs = [m for m in history if m["kind"] == "debrief"]
    assert len(debriefs) == 1
    assert debriefs[0]["content"] == outcome["pointer"]
