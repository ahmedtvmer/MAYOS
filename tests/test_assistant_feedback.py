"""Assistant reply feedback contract tests (issue #748).

Exercises the public HTTP surface and the ledger writes behind it:
1. A 👍/👎 is one tap, idempotent on replay, and a re-sent identical vote never
   erases the stored reasons or note.
2. A report requires at least one reason and a bounded note; the reply is
   reported once and client retries are safe.
3. The Discord payload carries the reason, language, route, and a redacted
   reply excerpt — never the player's username, preferred name, email, or
   account id.
4. The signed context is account-bound: a forged or foreign context is refused.
5. Feedback is owner-only, joins the clear-history cascade, and dies with the
   account's ledger at deletion.
6. The weekly vote summary fires Monday >=09:00 UTC, is deduplicated per week,
   and exports counts only.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service.assistant_feedback import (
    _redact_excerpt,
    build_feedback_context,
    send_weekly_summary,
    validate_feedback_context,
)
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
PLAYER_USERNAME = "feedbackplayer"
PLAYER_NAME = "FeedbackPlayer"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "")
    from svc.rate_limit import limiter

    limiter._storage.reset()
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


def _account_id(client, headers):
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return str(me.json()["account_id"])


def _signed_context(account_id: str, message_id: str = "reply-1") -> dict:
    return build_feedback_context(
        account_id,
        message_id=message_id,
        question_text="How many sets should I bench?",
        reply_text="Keep three working sets and leave two reps in reserve.",
        language="en",
        route="assistant",
        model=None,
        prompt_version=None,
        redact_terms=[PLAYER_NAME],
    )


def _seed_reply(db, ledger_id: str, message_id: str = "reply-1") -> None:
    """Inserts one persisted user/assistant exchange with a known reply id."""
    now = datetime.now(UTC).isoformat()
    with db.open_ledger(ledger_id) as ledger:
        ledger.conn.execute(
            "INSERT INTO chat_history (id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            ("question-1", "How many sets should I bench?", now),
        )
        ledger.conn.execute(
            "INSERT INTO chat_history (id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (message_id, "Keep three working sets and leave two reps in reserve.", now),
        )
        ledger._commit_ledger()


def _down_vote(client, headers, context, reasons=None, note=None):
    return client.post(
        "/chat/feedback/vote",
        headers=headers,
        json={
            "context": context,
            "vote": "down",
            "reasons": reasons or [],
            **({"note": note} if note else {}),
        },
    )


def test_vote_up_down_switch_and_undo_are_idempotent(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    context = _signed_context(account_id)

    first = client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": "up", "reasons": []}
    )
    assert first.status_code == 200, first.text
    assert first.json()["vote"] == "up"
    again = client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": "up", "reasons": []}
    )
    assert again.status_code == 200
    assert again.json()["vote"] == "up"

    switch = _down_vote(client, headers, context, reasons=["unsafe_advice"], note="risky")
    assert switch.status_code == 200
    assert switch.json()["vote"] == "down"
    replay = _down_vote(client, headers, context, reasons=["unsafe_advice"], note="risky")
    assert replay.status_code == 200
    assert replay.json()["vote"] == "down"

    undo = client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": None, "reasons": []}
    )
    assert undo.status_code == 200
    assert undo.json()["vote"] is None
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        rows = ledger.conn.execute(
            "SELECT vote, vote_reasons_json, vote_note FROM assistant_reply_feedback "
            "WHERE message_id = ?",
            (context["message_id"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] is None and rows[0][1] == "[]" and rows[0][2] is None


def test_same_vote_replay_never_erases_reasons(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(
        client.post("/auth/login", json={"trainee_id": PLAYER_USERNAME, "password": "correct-horse-1"}).json()[
            "access_token"
        ]
    )
    account_id = _account_id(client, headers)
    context = _signed_context(account_id)

    assert _down_vote(client, headers, context, reasons=["offensive"], note="rude").status_code == 200
    # A client retry of the exact same vote is a true no-op server-side.
    assert _down_vote(client, headers, context).status_code == 200
    # Switching to 👍 clears the 👎 reasons.
    assert client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": "up", "reasons": []}
    ).status_code == 200
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        vote, reasons, note = ledger.conn.execute(
            "SELECT vote, vote_reasons_json, vote_note FROM assistant_reply_feedback "
            "WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()
    assert (vote, reasons, note) == ("up", "[]", None)

    # Back to 👎 with the same reasons again re-records them.
    assert _down_vote(client, headers, context, reasons=["offensive"], note="rude").status_code == 200
    assert _down_vote(client, headers, context).status_code == 200
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        vote, reasons, note = ledger.conn.execute(
            "SELECT vote, vote_reasons_json, vote_note FROM assistant_reply_feedback "
            "WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()
    assert (vote, reasons, note) == ("down", '["offensive"]', "rude")


def test_vote_up_refuses_reasons_and_note(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    context = _signed_context(account_id)

    # A 👍 (or undo) may not carry reasons or a note: refused at the API edge.
    up_with_reasons = client.post(
        "/chat/feedback/vote",
        headers=headers,
        json={"context": context, "vote": "up", "reasons": ["offensive"]},
    )
    assert up_with_reasons.status_code == 422
    up_with_note = client.post(
        "/chat/feedback/vote",
        headers=headers,
        json={"context": context, "vote": "up", "reasons": [], "note": "why"},
    )
    assert up_with_note.status_code == 422
    undo_with_reasons = client.post(
        "/chat/feedback/vote",
        headers=headers,
        json={"context": context, "vote": None, "reasons": ["not_helpful"]},
    )
    assert undo_with_reasons.status_code == 422

    # Switching 👎 to 👍 clears the stored reasons and note.
    assert _down_vote(client, headers, context, reasons=["offensive"], note="rude").status_code == 200
    assert client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": "up", "reasons": []}
    ).status_code == 200
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        vote, reasons, note = ledger.conn.execute(
            "SELECT vote, vote_reasons_json, vote_note FROM assistant_reply_feedback "
            "WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()
    assert (vote, reasons, note) == ("up", "[]", None)

    # A stale 👍 row (reasons/note somehow present) heals to clean on replay.
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        ledger.conn.execute(
            "UPDATE assistant_reply_feedback SET vote_reasons_json = '[\"offensive\"]', "
            "vote_note = 'stale' WHERE message_id = ?",
            (context["message_id"],),
        )
        ledger._commit_ledger()
    assert client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": "up", "reasons": []}
    ).status_code == 200
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        reasons, note = ledger.conn.execute(
            "SELECT vote_reasons_json, vote_note FROM assistant_reply_feedback "
            "WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()
    assert (reasons, note) == ("[]", None)


def test_report_requires_reason_and_bounds_note(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    context = _signed_context(account_id)

    missing_reason = client.post(
        "/chat/feedback/report", headers=headers, json={"context": context, "reasons": []}
    )
    assert missing_reason.status_code == 422

    long_note = client.post(
        "/chat/feedback/report",
        headers=headers,
        json={"context": context, "reasons": ["offensive"], "note": "x" * 501},
    )
    assert long_note.status_code == 422

    report = client.post(
        "/chat/feedback/report",
        headers=headers,
        json={"context": context, "reasons": ["offensive"], "note": "insulting reply"},
    )
    assert report.status_code == 200, report.text
    assert report.json()["created"] is True
    # A retry of the same report is safe and does not create a second report.
    retry = client.post(
        "/chat/feedback/report",
        headers=headers,
        json={"context": context, "reasons": ["offensive"]},
    )
    assert retry.status_code == 200
    assert retry.json()["created"] is False
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        rows = ledger.conn.execute(
            "SELECT COUNT(*) FROM assistant_reply_feedback WHERE message_id = ? AND reported_at IS NOT NULL",
            (context["message_id"],),
        ).fetchone()
        assert rows[0] == 1


def test_forged_or_foreign_context_is_refused(api):
    client, db = api
    owner = _register(client, PLAYER_USERNAME)
    stranger = _register(client, "feedbackstranger")
    owner_headers = _authed(owner["access_token"])
    stranger_headers = _authed(stranger["access_token"])
    owner_account = _account_id(client, owner_headers)
    context = _signed_context(owner_account)

    forged = dict(context)
    forged["signature"] = "0" * 64
    assert (
        client.post(
            "/chat/feedback/vote", headers=owner_headers, json={"context": forged, "vote": "up", "reasons": []}
        ).status_code
        == 400
    )
    # Another account cannot reuse the owner's signed context.
    assert (
        client.post(
            "/chat/feedback/vote",
            headers=stranger_headers,
            json={"context": context, "vote": "up", "reasons": []},
        ).status_code
        == 400
    )


def test_history_restores_feedback_state(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    before = client.get("/chat/history", headers=headers)
    assert before.status_code == 200
    reply = next(m for m in before.json() if m["role"] == "assistant")
    assert reply["feedback"]["vote"] is None
    assert reply["feedback"]["reported"] is False

    assert _down_vote(client, headers, context, reasons=["not_helpful"]).status_code == 200
    after = client.get("/chat/history", headers=headers)
    reply = next(m for m in after.json() if m["role"] == "assistant")
    assert reply["feedback"]["vote"] == "down"
    assert reply["feedback"]["reported"] is False

    bare_id_vote = client.post(
        "/chat/feedback/vote",
        headers=headers,
        json={"message_id": "reply-1", "vote": "up", "reasons": []},
    )
    assert bare_id_vote.status_code == 200
    assert bare_id_vote.json()["vote"] == "up"
    restored = client.get("/chat/history", headers=headers)
    assert next(m for m in restored.json() if m["role"] == "assistant")["feedback"]["vote"] == "up"


def test_report_delivery_to_discord_carries_no_identifiers(api, monkeypatch):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = build_feedback_context(
        account_id,
        message_id="reply-1",
        question_text=f"How do I plan around {PLAYER_NAME}'s exam week?",
        reply_text="Keep three working sets. Contact me at player@example.com.",
        language="en",
        route="assistant",
        model=None,
        prompt_version=None,
        redact_terms=[PLAYER_NAME, PLAYER_USERNAME],
    )
    assert _down_vote(client, headers, context).status_code == 200

    captured: list[str] = []

    def fake_discord_post(content: str) -> bool:
        captured.append(content)
        return True

    from service import assistant_feedback

    monkeypatch.setattr(assistant_feedback, "_discord_post", fake_discord_post)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")

    report = client.post(
        "/chat/feedback/report",
        headers=headers,
        json={"message_id": "reply-1", "reasons": ["unsafe_advice"], "note": "told me to skip rest days"},
    )
    assert report.status_code == 200, report.text
    # The post carries the feedback id the owner can look up, not the chat
    # message id.
    feedback_id = str(report.json()["feedback_id"])
    assert len(captured) == 1
    content = captured[0]
    assert feedback_id in content
    assert "Unsafe advice" in content
    assert "Language: en" in content
    assert "told me to skip rest days" not in content
    for secret in (PLAYER_NAME, PLAYER_USERNAME, "player@example.com", account_id, "reply-1"):
        assert secret not in content, f"Discord payload leaked {secret!r}"


def test_redaction_failure_does_not_duplicate_the_persisted_reply(api, monkeypatch):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    _account_id(client, headers)

    from svc.routers import chat as chat_router

    def explode(db_: Any, account_id_: str, ledger_: Any) -> list[str]:
        raise RuntimeError("redaction source failed")

    monkeypatch.setattr(chat_router, "report_context_redact_terms", explode)

    response = client.post(
        "/chat/messages",
        headers=headers,
        json={"content": "How many sets should I bench?"},
    )
    assert response.status_code == 200, response.text
    frames = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert any(frame.get("done") for frame in frames)
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        replies = ledger.conn.execute(
            "SELECT content FROM chat_history WHERE role = 'assistant'"
        ).fetchall()
    assert len(replies) == 1


def test_clear_chat_history_cascades_feedback(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")
    assert _down_vote(client, headers, context).status_code == 200

    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert (
            ledger.conn.execute("SELECT COUNT(*) FROM assistant_reply_feedback").fetchone()[0] == 1
        )

    assert client.delete("/chat/history", headers=headers).status_code == 204
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert (
            ledger.conn.execute("SELECT COUNT(*) FROM assistant_reply_feedback").fetchone()[0] == 0
        )
        assert ledger.conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0] == 0


def test_clear_history_keeps_undelivered_report_until_retry_delivers(api, monkeypatch):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)

    from service import assistant_feedback

    # Discord is down: the report is recorded but not delivered.
    monkeypatch.setattr(assistant_feedback, "_discord_post", lambda content: False)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")
    report = client.post(
        "/chat/feedback/report",
        headers=headers,
        json={"message_id": "reply-1", "reasons": ["unsafe_advice"]},
    )
    assert report.status_code == 200, report.text
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert tuple(ledger.conn.execute(
            "SELECT reported_at IS NOT NULL, report_delivered_at IS NULL "
            "FROM assistant_reply_feedback"
        ).fetchone()) == (1, 1)

    # Clearing the history must keep the undelivered report so it still
    # reaches the owner; votes and delivered reports cascade away.
    assert client.delete("/chat/history", headers=headers).status_code == 204
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0] == 0
        kept = [
            tuple(row) for row in ledger.conn.execute(
                "SELECT reported_at IS NOT NULL, report_delivered_at IS NULL "
                "FROM assistant_reply_feedback"
            ).fetchall()
        ]
        assert kept == [(1, 1)]

    # The retry pass delivers the surviving report, then removes the row: its
    # chat message is gone and no player-facing surface remains.
    captured: list[str] = []

    def fake_discord_post(content: str) -> bool:
        captured.append(content)
        return True

    monkeypatch.setattr(assistant_feedback, "_discord_post", fake_discord_post)
    assert assistant_feedback.retry_pending_reports(db) == 1
    assert len(captured) == 1
    assert "Unsafe advice" in captured[0]
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert ledger.conn.execute(
            "SELECT COUNT(*) FROM assistant_reply_feedback"
        ).fetchone()[0] == 0


def test_account_deletion_removes_feedback_with_the_ledger(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")
    assert _down_vote(client, headers, context).status_code == 200
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert (
            ledger.conn.execute("SELECT COUNT(*) FROM assistant_reply_feedback").fetchone()[0] == 1
        )

    from database.account_deletion import AccountDeletionMixin

    assert isinstance(db, AccountDeletionMixin)
    deletion = db.delete_account(account_id, datetime.now(UTC).isoformat(), ledger_id=PLAYER_USERNAME)
    assert deletion["ok"] is True
    assert not db.ledger_exists(PLAYER_USERNAME)


def test_rate_limit_bounds_feedback_submissions(api):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    context = _signed_context(account_id)

    statuses = [
        client.post(
            "/chat/feedback/vote",
            headers=headers,
            json={"context": context, "vote": "up" if index % 2 else "down", "reasons": []},
        ).status_code
        for index in range(30)
    ]
    assert 429 in statuses
    assert statuses[-1] == 429


def _make_coach(client, db, username):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": f"Coach {username}", "bio": "b", "specialization": "s", "capacity": 10},
        ).status_code
        == 200
    )
    return headers


def _assignment_id(client, coach_headers, player_username):
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_username)
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=_authed(player["access_token"]),
        json={"token": token, "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    return str(redeemed.json()["assignment"]["assignment_id"]), player


def test_coach_feedback_stored_on_coach_ledger_and_never_shared(api, monkeypatch):
    client, db = api
    from service import assistant_feedback

    coach_headers = _make_coach(client, db, "feedbackcoach")
    assignment_id, player = _assignment_id(client, coach_headers, "feedbackcoachee")
    player_username = str(player["trainee_id"])

    # The coach reply names the Player twice: by username and by the preferred
    # name in the Player's assistant memory. The done-frame terms must redact
    # both from the owner's Discord excerpt.
    with db.open_ledger(player_username) as player_ledger:
        player_ledger.set_assistant_memory("preferred_name", "FeedbackCoacheePref")
    coach_account = str(db.get_active_account_by_username("feedbackcoach")["account_id"])
    redact_terms = assistant_feedback.coach_feedback_redact_terms(db, coach_account)
    assert player_username in redact_terms
    assert "FeedbackCoacheePref" in redact_terms
    context = build_feedback_context(
        coach_account,
        message_id="coach-reply-1",
        question_text="How should I progress his bench?",
        reply_text=(
            f"Tell {player_username} (preferred name FeedbackCoacheePref) to add "
            "2.5kg when all sets hit the top of the range."
        ),
        language="en",
        route="coach_assistant",
        model=None,
        prompt_version=None,
        redact_terms=redact_terms,
    )

    vote = client.post(
        f"/coach/assignments/{assignment_id}/assistant/feedback/vote",
        headers=coach_headers,
        json={"context": context, "vote": "up", "reasons": []},
    )
    assert vote.status_code == 200, vote.text

    captured: list[str] = []

    def fake_discord_post(content: str) -> bool:
        captured.append(content)
        return True

    monkeypatch.setattr(assistant_feedback, "_discord_post", fake_discord_post)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")

    report = client.post(
        f"/coach/assignments/{assignment_id}/assistant/feedback/report",
        headers=coach_headers,
        json={"context": context, "reasons": ["wrong_information"]},
    )
    assert report.status_code == 200, report.text
    # Neither the Player's username nor the preferred name reaches the owner's
    # Discord payload; the excerpt shows the redaction instead.
    assert player_username not in captured[0]
    assert "FeedbackCoacheePref" not in captured[0]
    assert "[redacted]" in captured[0]
    assert "Wrong information" in captured[0]

    with db.open_ledger("feedbackcoach") as ledger:
        rows = ledger.conn.execute(
            "SELECT vote, reported_at FROM assistant_reply_feedback WHERE message_id = ?",
            ("coach-reply-1",),
        ).fetchone()
        assert rows is not None and rows[0] == "up" and rows[1] is not None
    # The player's own ledger never holds coach feedback.
    with db.open_ledger("feedbackcoachee") as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM assistant_reply_feedback").fetchone()[0] == 0


def _insert_vote(db, ledger_id, account_id, message_id, vote, reasons, at):
    with db.open_ledger(ledger_id) as ledger:
        ledger.conn.execute(
            "INSERT INTO assistant_reply_feedback (feedback_id, account_id, message_id, reply_text, "
            "question_text, reply_language, route, vote, vote_reasons_json, vote_updated_at, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id, account_id, message_id, "reply text", "question text", "en", "assistant",
                vote, json.dumps(reasons), at, at, at,
            ),
        )
        ledger._commit_ledger()


def test_weekly_summary_fires_only_monday_and_deduplicates(api, monkeypatch):
    client, db = api
    monday_9am = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)  # a Monday
    assert monday_9am.weekday() == 0

    captured: list[str] = []

    def fake_discord_post(content: str) -> bool:
        captured.append(content)
        return True

    from service import assistant_feedback

    monkeypatch.setattr(assistant_feedback, "_discord_post", fake_discord_post)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")

    _register(client, PLAYER_USERNAME)
    account_id = str(db.get_active_account_by_username(PLAYER_USERNAME)["account_id"])
    week_start = monday_9am - timedelta(days=7)
    _insert_vote(
        db, PLAYER_USERNAME, account_id, "reply-a", "up", [],
        (week_start + timedelta(hours=2)).isoformat(),
    )
    _insert_vote(
        db, PLAYER_USERNAME, account_id, "reply-b", "down", ["unsafe_advice", "not_helpful"],
        (week_start + timedelta(days=1)).isoformat(),
    )
    _insert_vote(
        db, PLAYER_USERNAME, account_id, "reply-c", "down", ["offensive"],
        (week_start + timedelta(days=2)).isoformat(),
    )

    # Not Monday: no summary.
    assert send_weekly_summary(db, now=datetime(2026, 11, 17, 10, 0, tzinfo=UTC)) is False
    assert not captured
    # Monday but before 09:00: no summary.
    assert send_weekly_summary(db, now=monday_9am.replace(hour=8)) is False
    assert not captured
    # Monday at 09:00: one summary with counts only.
    assert send_weekly_summary(db, now=monday_9am) is True
    assert len(captured) == 1
    content = captured[0]
    assert "👍 1" in content and "👎 2" in content
    assert "Unsafe advice" in content and "Offensive" in content
    # No reply text, message ids, or account identifiers.
    assert PLAYER_USERNAME not in content and "reply text" not in content
    # Deduplicated per week: the same Monday again (or a later hour) is a no-op.
    assert send_weekly_summary(db, now=monday_9am.replace(hour=15)) is False
    assert len(captured) == 1
    with db.catalog_transaction():
        weeks = db.catalog_conn.execute(
            "SELECT week_start FROM assistant_feedback_summary_weeks"
        ).fetchall()
    assert weeks == [(week_start.date().isoformat(),)]


def test_feedback_context_signing_is_account_bound(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    account_a = "account-a"
    context = build_feedback_context(
        account_a,
        message_id="m-1",
        question_text="q",
        reply_text="r",
        language="ar",
        route="assistant",
        model=None,
        prompt_version=None,
        redact_terms=[],
    )
    assert validate_feedback_context(account_a, context) is not None
    with pytest.raises(ValueError):
        validate_feedback_context("account-b", dict(context))


def test_excerpt_redaction_keeps_long_words_and_masks_ids():
    # Ordinary long words pass through unredacted: the owner still reads the
    # reply (issue #748 round 2).
    sentence = "Unfortunately the strengthening recommendations need consistency."
    assert _redact_excerpt(sentence, []) == sentence
    # A 12+ char token that contains a digit is an id and is masked.
    masked = _redact_excerpt("token a1b2c3d4e5f6g7 issued", [])
    assert "a1b2c3d4e5f6g7" not in masked
    assert "[redacted id]" in masked
    # Account/Player names are applied before the generic patterns, so a name
    # is "[redacted]", never swallowed into "[redacted id]".
    named = _redact_excerpt(
        "Tell feedbackcoachee (preferred name FeedbackCoacheePref) to add 2.5kg "
        "when all sets hit the top of the range.",
        ["feedbackcoachee", "FeedbackCoacheePref"],
    )
    assert "feedbackcoachee" not in named.lower()
    assert "FeedbackCoacheePref" not in named
    assert "[redacted]" in named
    assert "[redacted id]" not in named


def test_excerpt_redaction_matches_names_as_whole_words():
    # A short preferred name redacts standalone uses only: "more" and
    # "moment" keep their letters (issue #748 round 2).
    out = _redact_excerpt("Mo, add a set to more of the moment work.", ["Mo"])
    assert out == "[redacted], add a set to more of the moment work."
    # Whole-word matching is Unicode-aware, so Arabic names redact too.
    arabic = _redact_excerpt("اسأل عمر عن تمرينك، وثق بنفسك.", ["عمر"])
    assert "عمر" not in arabic
    assert arabic == "اسأل [redacted] عن تمرينك، وثق بنفسك."
    # An attached Arabic prefix survives with the name redacted after it
    # (issue #748 round 3): the particles are not part of the name. Stacked
    # particles (e.g. فب) are captured too.
    assert _redact_excerpt("وعمر حاضر.", ["عمر"]) == "و[redacted] حاضر."
    assert _redact_excerpt("لعمر رسالة.", ["عمر"]) == "ل[redacted] رسالة."
    assert _redact_excerpt("بعمر تمرين.", ["عمر"]) == "ب[redacted] تمرين."
    assert _redact_excerpt("فبعمر البرنامج.", ["عمر"]) == "فب[redacted] البرنامج."
    assert _redact_excerpt("والعمر موجود.", ["عمر"]) == "وال[redacted] موجود."
    # An unrelated Arabic word that merely contains the same letters stays:
    # the trailing word char blocks the match.
    assert _redact_excerpt("العمرة قريبة.", ["عمر"]) == "العمرة قريبة."
