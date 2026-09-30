"""Coach AI privacy suite (issue #45, ADR 016/025/038/049).

Proves the stated guarantees through the real HTTP surface, capturing the
prompt at the lowest LLM entry (``utils.model_downloader.get_coach_llm``), the
same way ``tests/test_player_chat_privacy.py`` captures the player graph entry:

1. The coach model's input carries only the telemetry block, the coach's own
   question, and the client-held transcript — never the player's username,
   recovery email, coach name/bio, player-assistant chat, check-in note text,
   program-request reason, or any account id.
2. The deterministic figures in the prompt match the service computations
   (volume, attendance/adherence).
3. Nothing about the exchange is persisted: catalog and ledger tables are
   unchanged apart from ``model_usage`` (role ``coach``).
4. Denied access (revoked, other coach, non-coach) and a disabled feature
   never reach the model.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent.ProgramState import ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_ai
from service import dashboard as dashboard_service
from service import workouts as workouts_service
from service.attendance import evaluate_attendance
from service.missed_day_alerts import window_start_for_assignment
from service.schedule import timezone_for_versions
from svc.app import create_app
from svc.dependencies import get_db
from utils import model_downloader
from utils.model_metering import MeteringCallback

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

PLAYER_USERNAME = "zephyrustheplayer"
PLAYER_EMAIL = "zephyrustheplayer@example.com"
COACH_DISPLAY_NAME = "CoachIdentifyName"
COACH_BIO = "IDENTIFY_COACH_BIO_9d2f"
PLAYER_CHAT = "PRIVATE_PLAYER_CHAT_7f3a how should I cue my bench"
ASSISTANT_CHAT = "PRIVATE_ASSISTANT_REPLY_9c1d keep the elbows tucked"
CHECK_IN_NOTE = "IDENTIFY_CHECKIN_NOTE_4b7c call me after the session"
REQUEST_REASON = "IDENTIFY_REQUEST_REASON_5a1d I want more squat volume"

COACH_MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"

#: Every seeded identifier, asserted absent from every message sent to the model.
IDENTIFIERS = (
    PLAYER_USERNAME,
    PLAYER_EMAIL,
    COACH_DISPLAY_NAME,
    COACH_BIO,
    PLAYER_CHAT,
    ASSISTANT_CHAT,
    CHECK_IN_NOTE,
    REQUEST_REASON,
)


class _CapturingCoachLLM(BaseChatModel):
    """Coach-role double: records every payload, emits usage, fires metering."""

    model_id: str = COACH_MODEL_ID
    reply: str = "Volume is steady; keep the current plan."
    input_tokens: int = 120
    output_tokens: int = 30
    payloads: list = []

    @property
    def _llm_type(self) -> str:
        return "capturing-coach"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.payloads.append(list(messages))
        usage = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }
        message = AIMessage(content=self.reply, usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])


def _capturing_coach_llm(monkeypatch) -> _CapturingCoachLLM:
    stub = _CapturingCoachLLM(callbacks=[MeteringCallback(COACH_MODEL_ID)])
    monkeypatch.setattr(model_downloader, "get_coach_llm", lambda *args, **kwargs: stub)
    return stub


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("COACH_AI_ENABLED", raising=False)
    monkeypatch.delenv("COACH_AI_EVAL_REPORT", raising=False)
    from service.model_limits import reset_model_limits
    from svc.rate_limit import limiter

    limiter._storage.reset()
    reset_model_limits()
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
            yield client, db, tmp_path
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


def _account_id(db, username):
    account = db.get_active_account_by_username(username)
    assert account is not None
    return account["account_id"]


def _make_coach(client, db, username="coach", capacity=5):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": "Coach", "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    return headers


def _assigned_player(api):
    client, db, _tmp_path = api
    coach_headers = _make_coach(client, db)
    invite = client.post("/coach/assignments/invites", headers=coach_headers).json()
    player = _register(client, PLAYER_USERNAME)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert (
        client.put(
            "/profile", headers=player_headers, json={"weekly_frequency": 4, "current_goal": "Hypertrophy"}
        ).status_code
        == 200
    )
    return coach_headers, player_headers, redeemed.json()["assignment"]["assignment_id"]


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


def _write_report(tmp_path: Path, mutations: dict | None = None) -> Path:
    """A complete, valid report as the runner would record it (ADR 049)."""
    model_id, backend = coach_ai.coach_model_identity()
    runs = [
        {"case_id": f"case_{index}", "question": "q", "answer": "a", "checks": {}, "passed": True}
        for index in range(6)
    ]
    report = {
        "report_version": coach_ai.REPORT_VERSION,
        "suite": "coach_assistant",
        "mode": "live",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "coach_assistant_cases.json",
        "prompt_hash": coach_ai.prompt_version_hash(),
        "context_version": coach_ai.CONTEXT_VERSION,
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {"pass": True, "suite": "tests/test_coach_ai_privacy.py"},
            "evaluation": {"pass": True, "total": 6, "passed": 6, "threshold": 6},
        },
        "run": {"total": 6, "passed": 6, "expected": 6, "failed_cases": []},
        "reasons": [],
        "runs": runs,
        "pass": True,
    }
    if mutations:
        report.update(mutations)
    path = tmp_path / "coach_ai_eval.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _enable(monkeypatch, tmp_path: Path, mutations: dict | None = None) -> Path:
    path = _write_report(tmp_path, mutations)
    monkeypatch.setenv("COACH_AI_ENABLED", "true")
    monkeypatch.setenv("COACH_AI_EVAL_REPORT", str(path))
    return path


def _seed_identifiers(client, db, coach_headers, player_headers, assignment_id) -> str:
    """Seeds every identifier the model must never see; returns the started_at date."""
    assert client.post("/auth/email", headers=player_headers, json={"email": PLAYER_EMAIL}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=coach_headers,
            json={
                "display_name": COACH_DISPLAY_NAME,
                "bio": COACH_BIO,
                "specialization": "s",
                "capacity": 5,
            },
        ).status_code
        == 200
    )
    # The player's schedule, one committed session today, and its volume.
    assert (
        client.put(
            "/profile/schedule",
            headers=player_headers,
            json={"weekdays": [datetime.now(UTC).isoweekday()], "timezone": "UTC"},
        ).status_code
        == 200
    )
    _seed_session(db, PLAYER_USERNAME, datetime.now(UTC).isoformat())

    today = datetime.now(UTC).date().isoformat()
    assert (
        client.post(
            f"/coach/assignments/{assignment_id}/check-ins",
            headers=coach_headers,
            json={"checked_in_on": today, "channel": "video", "note": CHECK_IN_NOTE},
        ).status_code
        == 200
    )

    # A program-request free-text reason (catalog row; the AI must never see it).
    db.create_program_request(
        "req-identify",
        assignment_id,
        _account_id(db, "coach"),
        _account_id(db, PLAYER_USERNAME),
        "exercise_substitution",
        1,
        "Full A",
        "sq",
        "bp",
        None,
        None,
        REQUEST_REASON,
        datetime.now(UTC).isoformat(),
    )

    # Player-assistant chat in the player's ledger.
    assert db.switch_user(PLAYER_USERNAME)
    db.ledger.add_chat_message("user", PLAYER_CHAT)
    db.ledger.add_chat_message("assistant", ASSISTANT_CHAT)

    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    return next(row["started_at"] for row in roster if row["assignment_id"] == assignment_id)


def _dump_tables(conn) -> dict[str, list[tuple]]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    dump: dict[str, list[tuple]] = {}
    for (name,) in rows:
        # Sorted in Python: some catalog tables are WITHOUT ROWID (#225).
        dump[name] = sorted((tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"')), key=repr)
    return dump


def _changed_tables(before: dict, after: dict) -> set[str]:
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def _seeded_tonnage() -> float:
    """Raw math for the one seeded set: 100 kg x 5 reps (see ``_seed_session``)."""
    return 100.0 * 5


def _expected_attendance(db, started_at: str) -> dict[str, str]:
    """Recomputes the ADR 030 attendance figures independently of the AI gather."""
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        versions = ledger.list_training_schedules(PLAYER_USERNAME)
        pauses = ledger.list_training_pauses(PLAYER_USERNAME)
        performed = ledger.list_performed_dates()
    timezone = timezone_for_versions(versions, "UTC")
    evaluation = evaluate_attendance(
        versions=versions,
        pauses=pauses,
        performed_dates=performed,
        window_start=window_start_for_assignment(started_at, versions, timezone),
        now=datetime.now(UTC),
    )
    expected = len(evaluation.expected_days)
    satisfied = len(evaluation.satisfied_days)
    adherence = round(100.0 * satisfied / expected, 1) if expected else None
    return {
        "expected_days": coach_ai.format_number(expected),
        "satisfied_days": coach_ai.format_number(satisfied),
        "missed_days": coach_ai.format_number(len(evaluation.missed_days)),
        "adherence_pct": coach_ai.format_number(adherence),
        "trailing_missed_streak": coach_ai.format_number(evaluation.trailing_streak_length),
    }


QUESTION = {
    "question": "How has training been going this week?",
    "history": [
        {"role": "coach", "content": "Tell me about the last session."},
        {"role": "assistant", "content": "The last session logged 1 working set."},
    ],
}


# --------------------------------------------------------------------------
# 1 + 2: prompt contents and deterministic figures
# --------------------------------------------------------------------------


def test_prompt_carries_only_necessary_telemetry_and_deterministic_figures(api, monkeypatch):
    client, db, tmp_path = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)
    started_at = _seed_identifiers(client, db, coach_headers, player_headers, assignment_id)
    _enable(monkeypatch, tmp_path)
    stub = _capturing_coach_llm(monkeypatch)

    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=coach_headers, json=QUESTION
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == stub.reply
    assert len(stub.payloads) == 1

    rendered = "\n".join(str(getattr(message, "content", message)) for message in stub.payloads[0])

    # The coach's own text reaches the model: the question and the transcript
    # the client holds in memory for this one player.
    assert QUESTION["question"] in rendered
    assert QUESTION["history"][0]["content"] in rendered
    assert QUESTION["history"][1]["content"] in rendered
    assert "[PLAYER TELEMETRY]" in rendered

    # No identity, no contact details, no free text written by the player or
    # about the player, and no account ids.
    for identifier in IDENTIFIERS:
        assert identifier not in rendered, identifier
    assert _account_id(db, PLAYER_USERNAME) not in rendered
    assert _account_id(db, "coach") not in rendered

    # Deterministic figures are supplied, and match the service computations:
    # one working set of 100 kg x 5 reps is 500 kg in both lookback windows.
    tonnage = _seeded_tonnage()
    volumes = dashboard_service.working_set_volume(db, PLAYER_USERNAME, days_lookback=(7, 28))
    assert volumes[7] == volumes[28] == tonnage
    assert f"volume_last_7_days_kg: {coach_ai.format_number(tonnage)}" in rendered
    assert f"volume_last_28_days_kg: {coach_ai.format_number(tonnage)}" in rendered
    assert f"volume_kg {coach_ai.format_number(tonnage)}" in rendered
    attendance = _expected_attendance(db, started_at)
    for key, value in attendance.items():
        assert f"{key}: {value}" in rendered, key
    # Check-in dates and channels are supplied — but never the note.
    today = datetime.now(UTC).date().isoformat()
    assert f"check_ins (dates and channels only): {today} video" in rendered
    # The program-request reason is excluded; only its state is.
    assert "exercise_substitution" in rendered


# --------------------------------------------------------------------------
# 3: nothing persisted but the metering rows
# --------------------------------------------------------------------------


def test_nothing_is_persisted_beyond_model_usage(api, monkeypatch):
    client, db, tmp_path = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)
    _seed_identifiers(client, db, coach_headers, player_headers, assignment_id)
    _enable(monkeypatch, tmp_path)
    stub = _capturing_coach_llm(monkeypatch)

    catalog_before = _dump_tables(db.catalog_conn)
    with db.open_ledger(PLAYER_USERNAME) as player_ledger:
        ledger_before = _dump_tables(player_ledger.conn)

    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant",
        headers=coach_headers,
        json={"question": "Anything I should change?"},
    )
    assert response.status_code == 200, response.text
    assert stub.payloads

    catalog_after = _dump_tables(db.catalog_conn)
    with db.open_ledger(PLAYER_USERNAME) as player_ledger:
        ledger_after = _dump_tables(player_ledger.conn)

    # Only the ADR 038 metering rows may differ in the catalog; the player's
    # training ledger is untouched (no transcript, no copy of the exchange).
    assert _changed_tables(catalog_before, catalog_after) <= {"model_usage"}
    assert _changed_tables(ledger_before, ledger_after) == set()

    account_id = _account_id(db, "coach")
    usage = [
        row
        for row in db.summarize_model_usage("2000-01-01")
        if row["account_id"] == account_id
    ]
    assert usage, "the coach turn must be metered"
    assert usage[0]["role"] == "coach"
    # The metering row counts tokens only — never the question or the answer.
    payload = json.dumps(dict(usage[0]))
    assert QUESTION["question"] not in payload
    assert "Anything I should change?" not in payload


# --------------------------------------------------------------------------
# 4 + 5: denials never reach the model
# --------------------------------------------------------------------------


def test_revoked_assignment_is_denied_without_a_model_call(api, monkeypatch):
    client, db, tmp_path = api
    coach_headers, _player_headers, assignment_id = _assigned_player(api)
    _enable(monkeypatch, tmp_path)
    stub = _capturing_coach_llm(monkeypatch)

    assert client.post(
        f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers
    ).status_code == 200
    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=coach_headers, json=QUESTION
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "No active assignment."
    assert stub.payloads == []


def test_other_coach_and_non_coach_are_denied_without_a_model_call(api, monkeypatch):
    client, db, tmp_path = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)
    _enable(monkeypatch, tmp_path)
    stub = _capturing_coach_llm(monkeypatch)

    other_headers = _make_coach(client, db, "othercoach")
    other = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=other_headers, json=QUESTION
    )
    assert other.status_code == 403
    assert other.json()["detail"] == "No active assignment."

    as_player = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=player_headers, json=QUESTION
    )
    assert as_player.status_code == 403
    assert "Coach capability required." == as_player.json()["detail"]
    assert stub.payloads == []


def test_flag_off_returns_404_without_a_model_call(api, monkeypatch):
    client, _db, _tmp_path = api
    coach_headers, _player_headers, assignment_id = _assigned_player(api)
    stub = _capturing_coach_llm(monkeypatch)

    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=coach_headers, json=QUESTION
    )
    assert response.status_code == 404
    assert stub.payloads == []
