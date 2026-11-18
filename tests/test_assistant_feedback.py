"""Assistant reply feedback contract tests (issue #748).

Exercises the public HTTP surface and the ledger writes behind it:
1. A 👍/👎 is one tap, idempotent on replay, and a re-sent identical vote never
   erases the stored reasons or note.
2. A report requires at least one reason and a bounded note; the reply is
   reported once and client retries are safe.
3. Reports — and 👎 feedback with a reason or a note — reach the owner's
   Discord with the full redacted reply and any redacted comment, split into
   2000-character parts when long; a 👎 without a reason or note is a quiet
   vote. Delivery is saved first, retried hourly, sent at most once per
   feedback row, and cancelled when the vote flips to 👍 before delivery.
   The payload never includes the player's username, preferred name, email,
   or account id.
4. The signed context is account-bound: a forged or foreign context is refused.
5. Feedback is owner-only, joins the clear-history cascade, and dies with the
   account's ledger at deletion.
6. The weekly vote summary fires Monday >=09:00 UTC, is deduplicated per week,
   and exports counts only.
"""

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service.assistant_feedback import (
    _redact_text,
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
    """Inserts one persisted user/assistant exchange with a known reply id.

    The user question's id is derived from the reply id, so one test can seed
    several exchanges without colliding on chat_history's unique ids.
    """
    now = datetime.now(UTC).isoformat()
    with db.open_ledger(ledger_id) as ledger:
        ledger.conn.execute(
            "INSERT INTO chat_history (id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (f"question-{message_id}", "How many sets should I bench?", now),
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


def _capture_discord(monkeypatch) -> list[str]:
    """Patches the Discord seam to capture every sent part; all parts succeed."""
    captured: list[str] = []

    def fake_discord_post(content: str) -> bool:
        captured.append(content)
        return True

    from service import assistant_feedback

    monkeypatch.setattr(assistant_feedback, "_discord_post", fake_discord_post)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")
    return captured


def _strip_part_marker(part: str) -> str:
    return re.sub(r" \(\d+/\d+\)$", "", part)


def test_downvote_with_reason_is_delivered_and_marked(api, monkeypatch):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    captured = _capture_discord(monkeypatch)
    response = _down_vote(client, headers, context, reasons=["unsafe_advice"])
    assert response.status_code == 200, response.text
    assert response.json()["delivery_pending"] is False
    assert len(captured) == 1
    content = captured[0]
    assert content.startswith("MAYOS AI reply 👎 feedback")
    assert "Reason: Unsafe advice" in content
    assert "Language: en" in content and "Route: assistant" in content
    # The rated exchange is sent: the redacted question, then the full reply.
    assert "Question: How many sets should I bench?" in content
    assert "Keep three working sets and leave two reps in reserve." in content
    question_at = content.index("Question: ")
    reply_at = content.index("Reply: ")
    assert question_at < reply_at

    from service import assistant_feedback

    with db.open_ledger(PLAYER_USERNAME) as ledger:
        notified = ledger.conn.execute(
            "SELECT vote_notified_at FROM assistant_reply_feedback WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()[0]
    assert notified is not None
    # Delivered: the hourly retry has nothing pending.
    assert assistant_feedback.retry_pending_reports(db) == 0
    assert len(captured) == 1


def test_bare_downvote_and_upvote_never_send(api, monkeypatch):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    captured = _capture_discord(monkeypatch)
    assert _down_vote(client, headers, context).status_code == 200
    assert client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": "up", "reasons": []}
    ).status_code == 200
    assert captured == []


def test_downvote_edit_is_saved_but_not_resent(api, monkeypatch):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    captured = _capture_discord(monkeypatch)
    first = _down_vote(client, headers, context, reasons=["unsafe_advice"])
    assert first.status_code == 200 and first.json()["delivery_pending"] is False
    assert len(captured) == 1

    # A later edit of the same 👎 is saved but never re-sent: one send per row.
    second = _down_vote(client, headers, context, reasons=["not_helpful"], note="also confusing")
    assert second.status_code == 200 and second.json()["delivery_pending"] is False
    assert len(captured) == 1
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        reasons, note = ledger.conn.execute(
            "SELECT vote_reasons_json, vote_note FROM assistant_reply_feedback "
            "WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()
    assert (reasons, note) == ('["not_helpful"]', "also confusing")


def test_flip_to_up_before_delivery_cancels_the_send(api, monkeypatch):
    from service import assistant_feedback

    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    # Discord is down at vote time: the 👎 stays pending.
    monkeypatch.setattr(assistant_feedback, "_discord_post", lambda content: False)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")
    response = _down_vote(client, headers, context, reasons=["unsafe_advice"])
    assert response.status_code == 200 and response.json()["delivery_pending"] is True
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        notified = ledger.conn.execute(
            "SELECT vote_notified_at FROM assistant_reply_feedback WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()[0]
    assert notified is None

    # Flipping to 👍 before delivery cancels the pending send.
    assert client.post(
        "/chat/feedback/vote", headers=headers, json={"context": context, "vote": "up", "reasons": []}
    ).status_code == 200
    captured: list[str] = []
    monkeypatch.setattr(
        assistant_feedback,
        "_discord_post",
        lambda content: captured.append(content) or True,
    )
    assert assistant_feedback.retry_pending_reports(db) == 0
    assert captured == []

    # A fresh 👎 with a reason after the cancel was never delivered, so it goes.
    again = _down_vote(client, headers, context, reasons=["unsafe_advice"])
    assert again.status_code == 200 and again.json()["delivery_pending"] is False
    assert len(captured) == 1


def test_clear_chat_history_keeps_row_until_both_sides_are_done(api, monkeypatch):
    """One row holds the reply's report and its 👎: nothing is deleted while
    either side is still owed, whichever order they were completed in."""
    from service import assistant_feedback

    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    captured: list[str] = []

    def healthy_post(content: str) -> bool:
        captured.append(content)
        return True

    def failing_post(content: str) -> bool:
        captured.append(content)
        return False

    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")

    # Case A: the report is delivered, then a 👎 with a reason arrives while
    # Discord is down. The row must survive Clear chat.
    monkeypatch.setattr(assistant_feedback, "_discord_post", healthy_post)
    report = client.post(
        "/chat/feedback/report", headers=headers, json={"context": context, "reasons": ["unsafe_advice"]}
    )
    assert report.status_code == 200 and report.json()["delivery_pending"] is False

    monkeypatch.setattr(assistant_feedback, "_discord_post", failing_post)
    vote = _down_vote(client, headers, context, reasons=["not_helpful"])
    assert vote.status_code == 200 and vote.json()["delivery_pending"] is True

    assert client.delete("/chat/history", headers=headers).status_code == 204
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        kept = ledger.conn.execute(
            "SELECT report_delivered_at IS NOT NULL, vote_notified_at IS NULL, "
            "delivery_claimed_at IS NULL, COUNT(*) FROM assistant_reply_feedback"
        ).fetchone()
    assert tuple(kept) == (1, 1, 1, 1)  # report done, 👎 send still owed, claim released

    # The retry delivers the 👎; with the message gone and nothing owed, the
    # row is cleaned up.
    monkeypatch.setattr(assistant_feedback, "_discord_post", healthy_post)
    assert assistant_feedback.retry_pending_reports(db) == 1
    assert len(captured) == 3  # report, failed 👎 send, delivered 👎 send
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM assistant_reply_feedback").fetchone()[0] == 0

    # Case B: the 👎 is delivered first, then a report arrives while Discord
    # is down. The row must survive Clear chat just the same.
    _seed_reply(db, PLAYER_USERNAME, message_id="reply-2")
    context2 = _signed_context(account_id, message_id="reply-2")
    vote2 = _down_vote(client, headers, context2, reasons=["unsafe_advice"])
    assert vote2.status_code == 200 and vote2.json()["delivery_pending"] is False

    monkeypatch.setattr(assistant_feedback, "_discord_post", failing_post)
    report2 = client.post(
        "/chat/feedback/report", headers=headers, json={"context": context2, "reasons": ["offensive"]}
    )
    assert report2.status_code == 200 and report2.json()["delivery_pending"] is True

    assert client.delete("/chat/history", headers=headers).status_code == 204
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        kept2 = ledger.conn.execute(
            "SELECT vote_notified_at IS NOT NULL, reported_at IS NOT NULL, "
            "report_delivered_at IS NULL, COUNT(*) FROM assistant_reply_feedback"
        ).fetchone()
    assert tuple(kept2) == (1, 1, 1, 1)  # 👎 done, report still owed

    monkeypatch.setattr(assistant_feedback, "_discord_post", healthy_post)
    assert assistant_feedback.retry_pending_reports(db) == 1
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM assistant_reply_feedback").fetchone()[0] == 0


def test_undelivered_downvote_survives_clear_chat_on_its_own(api, monkeypatch):
    from service import assistant_feedback

    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    # Discord is down: the 👎 with a reason stays pending.
    monkeypatch.setattr(assistant_feedback, "_discord_post", lambda content: False)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")
    vote = _down_vote(client, headers, context, reasons=["not_helpful"])
    assert vote.status_code == 200 and vote.json()["delivery_pending"] is True

    assert client.delete("/chat/history", headers=headers).status_code == 204
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        kept = ledger.conn.execute(
            "SELECT vote, vote_reasons_json, vote_notified_at IS NULL, COUNT(*) "
            "FROM assistant_reply_feedback"
        ).fetchone()
    assert tuple(kept) == ("down", '["not_helpful"]', 1, 1)

    # The retry delivers the surviving send, then the row goes with its reply.
    captured: list[str] = []

    def healthy_post(content: str) -> bool:
        captured.append(content)
        return True

    monkeypatch.setattr(assistant_feedback, "_discord_post", healthy_post)
    assert assistant_feedback.retry_pending_reports(db) == 1
    assert "Not helpful" in captured[0]
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM assistant_reply_feedback").fetchone()[0] == 0


def test_claim_blocks_concurrent_retry_and_stale_claim_is_taken_over(api, monkeypatch):
    from service import assistant_feedback

    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    # The immediate send fails (Discord down) and releases its claim, so the
    # row stays pickable by the next retry pass.
    monkeypatch.setattr(assistant_feedback, "_discord_post", lambda content: False)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")
    vote = _down_vote(client, headers, context, reasons=["unsafe_advice"])
    assert vote.status_code == 200 and vote.json()["delivery_pending"] is True
    feedback_id = str(vote.json()["feedback_id"])
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        claimed, notified = ledger.conn.execute(
            "SELECT delivery_claimed_at IS NULL, vote_notified_at IS NULL "
            "FROM assistant_reply_feedback WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
    assert (claimed, notified) == (1, 1)  # failed post released the claim

    # A concurrent holder claims the row: the retry pass must not post it.
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        assert ledger.claim_assistant_feedback_vote_delivery(feedback_id) is True
        # A second claim on the same row loses the race.
        assert ledger.claim_assistant_feedback_vote_delivery(feedback_id) is False
    captured: list[str] = []

    def healthy_post(content: str) -> bool:
        captured.append(content)
        return True

    monkeypatch.setattr(assistant_feedback, "_discord_post", healthy_post)
    assert assistant_feedback.retry_pending_reports(db) == 0
    assert captured == []  # nothing was posted under someone else's claim
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        claimed, notified = ledger.conn.execute(
            "SELECT delivery_claimed_at IS NOT NULL, vote_notified_at IS NULL "
            "FROM assistant_reply_feedback WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
    assert (claimed, notified) == (1, 1)  # still pending under the fresh claim

    # An immediate send yields to the claim holder instead of posting again.
    edit = _down_vote(client, headers, context, reasons=["unsafe_advice"], note="again")
    assert edit.status_code == 200 and edit.json()["delivery_pending"] is True
    assert captured == []

    # A stale claim — its holder crashed — is taken over and delivered.
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        stale = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        ledger.conn.execute(
            "UPDATE assistant_reply_feedback SET delivery_claimed_at = ? "
            "WHERE feedback_id = ?",
            (stale, feedback_id),
        )
        ledger._commit_ledger()
    assert assistant_feedback.retry_pending_reports(db) == 1
    assert len(captured) == 1
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        claimed, notified = ledger.conn.execute(
            "SELECT delivery_claimed_at IS NULL, vote_notified_at IS NOT NULL "
            "FROM assistant_reply_feedback WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
    assert (claimed, notified) == (1, 1)  # delivered and unclaimed


def test_v64_migration_never_sends_preexisting_downvotes(api, monkeypatch):
    """Existing 👎 feedback predates 👎 sends (policy 1.13 shared only reports
    with the owner), so the v64 migration stamps old rows as already notified
    and the retry pass sends nothing for them; new 👎 sends still go out."""
    from database.migration_manager import get_ledger_schema_version, set_ledger_schema_version
    from service import assistant_feedback

    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = _signed_context(account_id, message_id="reply-1")

    # Discord is down, so the 👎 lands exactly like a pre-upgrade row: a 👎
    # with a reason and no notified stamp.
    monkeypatch.setattr(assistant_feedback, "_discord_post", lambda content: False)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")
    vote = _down_vote(client, headers, context, reasons=["unsafe_advice"])
    assert vote.status_code == 200 and vote.json()["delivery_pending"] is True
    feedback_id = str(vote.json()["feedback_id"])
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        pending, unclaimed = ledger.conn.execute(
            "SELECT vote_notified_at IS NULL, delivery_claimed_at IS NULL "
            "FROM assistant_reply_feedback WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
    assert (pending, unclaimed) == (1, 1)

    # Demote the ledger to v63 so reopening runs the v64 migration again,
    # exactly as a Player's upgraded ledger would.
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        set_ledger_schema_version(ledger.conn, 63)
        ledger._commit_ledger()

    # After the upgrade the retry pass sends nothing for the old row.
    captured: list[str] = []

    def healthy_post(content: str) -> bool:
        captured.append(content)
        return True

    monkeypatch.setattr(assistant_feedback, "_discord_post", healthy_post)
    assert assistant_feedback.retry_pending_reports(db) == 0
    assert captured == []
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        stamped = ledger.conn.execute(
            "SELECT vote_notified_at IS NOT NULL FROM assistant_reply_feedback "
            "WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()[0]
        assert get_ledger_schema_version(ledger.conn) == 64
    assert stamped == 1

    # A new 👎 after the migration behaves as designed and is sent.
    _seed_reply(db, PLAYER_USERNAME, message_id="reply-post-migration")
    context2 = _signed_context(account_id, message_id="reply-post-migration")
    again = _down_vote(client, headers, context2, reasons=["not_helpful"])
    assert again.status_code == 200 and again.json()["delivery_pending"] is False
    assert len(captured) == 1
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        new_notified = ledger.conn.execute(
            "SELECT vote_notified_at IS NOT NULL FROM assistant_reply_feedback "
            "WHERE message_id = 'reply-post-migration'"
        ).fetchone()[0]
    assert new_notified == 1


def test_downvote_note_reaches_discord_redacted(api, monkeypatch):
    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    _seed_reply(db, PLAYER_USERNAME)
    context = build_feedback_context(
        account_id,
        message_id="reply-1",
        question_text="How many sets should I bench?",
        reply_text="Keep three working sets and leave two reps in reserve.",
        language="en",
        route="assistant",
        model=None,
        prompt_version=None,
        redact_terms=[PLAYER_NAME, PLAYER_USERNAME],
    )

    captured = _capture_discord(monkeypatch)
    response = _down_vote(
        client, headers, context, reasons=["offensive"], note=f"Ask {PLAYER_NAME} to be kinder"
    )
    assert response.status_code == 200, response.text
    assert len(captured) == 1
    content = captured[0]
    assert "Comment: Ask [redacted] to be kinder" in content
    # Question, then reply, then comment.
    assert content.index("Question: ") < content.index("Reply: ") < content.index("Comment: ")
    assert PLAYER_NAME not in content and PLAYER_USERNAME not in content


def test_long_reply_is_split_into_ordered_parts(api, monkeypatch):
    from service import assistant_feedback

    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    long_question = " ".join(
        f"{PLAYER_NAME} asked question part {index} about bench programming" for index in range(150)
    )
    long_reply = " ".join(
        f"sentence {index} about training volume and recovery" for index in range(400)
    )
    context = build_feedback_context(
        account_id,
        message_id="reply-long",
        question_text=long_question,
        reply_text=long_reply,
        language="en",
        route="assistant",
        model=None,
        prompt_version=None,
        redact_terms=[PLAYER_NAME],
    )

    captured = _capture_discord(monkeypatch)
    response = _down_vote(client, headers, context, reasons=["not_helpful"])
    assert response.status_code == 200, response.text
    assert response.json()["delivery_pending"] is False
    assert len(captured) > 1
    for part in captured:
        assert len(part) <= assistant_feedback.DISCORD_MESSAGE_LIMIT
    markers = [re.search(r" \((\d+)/(\d+)\)$", part) for part in captured]
    assert all(marker is not None for marker in markers)
    total = int(markers[0].group(2))
    assert [int(marker.group(1)) for marker in markers] == list(range(1, total + 1))
    # Stripping the markers and joining the parts rebuilds the full message:
    # the redacted question precedes the full redacted reply, and nothing —
    # question, reply, or otherwise — is dropped across the part boundary.
    expected = assistant_feedback._feedback_message_content(
        "MAYOS AI reply 👎 feedback",
        context,
        str(response.json()["feedback_id"]),
        ["not_helpful"],
        None,
    )
    assert "".join(_strip_part_marker(part) for part in captured) == expected
    redacted_question = assistant_feedback._redact_text(long_question, [PLAYER_NAME])
    redacted_reply = assistant_feedback._redact_text(long_reply, [PLAYER_NAME])
    question_at = expected.index("Question: ")
    reply_at = expected.index("Reply: ")
    assert question_at < reply_at
    assert redacted_question in expected
    assert redacted_reply in expected
    sent = "".join(_strip_part_marker(part) for part in captured)
    assert PLAYER_NAME not in sent


def test_partial_discord_failure_stays_pending_and_resends_all_parts(api, monkeypatch):
    from service import assistant_feedback

    client, db = api
    registered = _register(client, PLAYER_USERNAME)
    headers = _authed(registered["access_token"])
    account_id = _account_id(client, headers)
    long_reply = " ".join(
        f"sentence {index} about training volume and recovery" for index in range(200)
    )
    context = build_feedback_context(
        account_id,
        message_id="reply-long",
        question_text="q",
        reply_text=long_reply,
        language="en",
        route="assistant",
        model=None,
        prompt_version=None,
        redact_terms=[],
    )
    # The exchange must exist in chat history, or the delivered row would be
    # cleaned up by the retry pass before its delivery can be asserted.
    _seed_reply(db, PLAYER_USERNAME, message_id="reply-long")
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        ledger.conn.execute(
            "UPDATE chat_history SET content = ? WHERE id = ?",
            (long_reply, "reply-long"),
        )
        ledger._commit_ledger()

    # A partial failure: the first Discord post succeeds, the next one fails,
    # and the send stops there — the whole message is retried later.
    captured: list[str] = []

    def flaky_discord_post(content: str) -> bool:
        captured.append(content)
        return len(captured) != 2

    monkeypatch.setattr(assistant_feedback, "_discord_post", flaky_discord_post)
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "https://discord.invalid/webhook")

    response = _down_vote(client, headers, context, reasons=["unsafe_advice"])
    assert response.status_code == 200 and response.json()["delivery_pending"] is True
    first_attempt = len(captured)
    assert first_attempt == 2  # part 1 sent, part 2 failed, send stopped
    assert all(len(part) <= assistant_feedback.DISCORD_MESSAGE_LIMIT for part in captured)
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        notified = ledger.conn.execute(
            "SELECT vote_notified_at FROM assistant_reply_feedback WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()[0]
    assert notified is None

    # Discord recovers: the retry resends every part, and only then counts.
    monkeypatch.setattr(
        assistant_feedback,
        "_discord_post",
        lambda content: captured.append(content) or True,
    )
    assert assistant_feedback.retry_pending_reports(db) == 1
    resend = captured[first_attempt:]
    assert len(resend) > 1
    total = int(re.search(r" \((\d+)/(\d+)\)$", resend[0]).group(2))
    assert len(resend) == total  # every part of the message went out again
    assert all(len(part) <= assistant_feedback.DISCORD_MESSAGE_LIMIT for part in resend)
    with db.open_ledger(PLAYER_USERNAME) as ledger:
        notified = ledger.conn.execute(
            "SELECT vote_notified_at FROM assistant_reply_feedback WHERE message_id = ?",
            (context["message_id"],),
        ).fetchone()[0]
    assert notified is not None


def test_discord_parts_split_never_drop_text():
    from service.assistant_feedback import DISCORD_MESSAGE_LIMIT, _discord_parts

    multiline = "\n".join(f"line {index} of the reply" for index in range(300))
    parts = _discord_parts(multiline)
    assert len(parts) > 1
    for part in parts:
        assert len(part) <= DISCORD_MESSAGE_LIMIT
    assert "".join(_strip_part_marker(part) for part in parts) == multiline

    # A single unbroken word is hard-cut rather than dropped.
    blob = "a" * 5000
    parts = _discord_parts(blob)
    assert all(len(part) <= DISCORD_MESSAGE_LIMIT for part in parts)
    assert "".join(_strip_part_marker(part) for part in parts) == blob

    # Content that fits is one unmarked part.
    assert _discord_parts("short reply") == ["short reply"]


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

    # The report is posted with the signed context from the done frame: it
    # carries the exact exchange being reported (question and reply). Posting
    # by bare message id would instead re-derive the stored chat exchange,
    # which is correct product behavior but a different fixture here.
    report = client.post(
        "/chat/feedback/report",
        headers=headers,
        json={"context": context, "reasons": ["unsafe_advice"], "note": "told me to skip rest days"},
    )
    assert report.status_code == 200, report.text
    # The post carries the feedback id the owner can look up, not the chat
    # message id, plus the redacted question, the full redacted reply, and the
    # redacted comment.
    feedback_id = str(report.json()["feedback_id"])
    assert len(captured) == 1
    content = captured[0]
    assert feedback_id in content
    assert "Unsafe advice" in content
    assert "Language: en" in content
    # The rated exchange is sent in order: redacted question, full redacted
    # reply, then the redacted comment.
    assert "Question: How do I plan around [redacted]'s exam week?" in content
    assert "Keep three working sets." in content
    assert "[redacted email]" in content
    assert "Comment: told me to skip rest days" in content
    question_at = content.index("Question: ")
    reply_at = content.index("Reply: ")
    comment_at = content.index("Comment: ")
    assert question_at < reply_at < comment_at
    for secret in (PLAYER_NAME, PLAYER_USERNAME, "player@example.com", account_id, "reply-1"):
        assert secret not in content, f"Discord payload leaked {secret!r}"


def test_feedback_webhook_wins_when_both_webhooks_are_set(monkeypatch):
    from service import assistant_feedback

    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", " https://discord.com/api/webhooks/1/fbtoken ")
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/2/alerttoken")

    posted: list[tuple[str, str]] = []

    def fake_post(webhook: str, content: str) -> tuple[int, float]:
        posted.append((webhook, content))
        return 204, 0.0

    import svc.monitoring.tiles.sentry_discord as sentry_discord

    monkeypatch.setattr(sentry_discord, "_post", fake_post)

    assert assistant_feedback._discord_post("MAYOS AI reply report") is True
    # The feedback-specific webhook is used even though the alert webhook is
    # also configured; the stripped URL is what reaches Discord.
    assert posted == [("https://discord.com/api/webhooks/1/fbtoken", "MAYOS AI reply report")]


def test_alert_webhook_is_the_fallback_when_feedback_webhook_is_unset(monkeypatch):
    from service import assistant_feedback

    monkeypatch.delenv("DISCORD_FEEDBACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/2/alerttoken")
    # A whitespace-only feedback URL counts as unset.
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "   ")

    posted: list[tuple[str, str]] = []

    def fake_post(webhook: str, content: str) -> tuple[int, float]:
        posted.append((webhook, content))
        return 200, 0.0

    import svc.monitoring.tiles.sentry_discord as sentry_discord

    monkeypatch.setattr(sentry_discord, "_post", fake_post)

    assert assistant_feedback._feedback_webhook() == "https://discord.com/api/webhooks/2/alerttoken"
    assert assistant_feedback._discord_post("MAYOS assistant feedback") is True
    assert posted == [("https://discord.com/api/webhooks/2/alerttoken", "MAYOS assistant feedback")]


def test_nothing_is_posted_when_neither_webhook_is_set(monkeypatch):
    from service import assistant_feedback

    monkeypatch.delenv("DISCORD_FEEDBACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)

    import svc.monitoring.tiles.sentry_discord as sentry_discord

    def unexpected_post(webhook: str, content: str) -> tuple[int, float]:
        raise AssertionError("Discord delivery ran without a configured webhook")

    monkeypatch.setattr(sentry_discord, "_post", unexpected_post)

    assert assistant_feedback._feedback_webhook() == ""
    assert assistant_feedback._discord_post("MAYOS AI reply report") is False


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
    # The report was made by bare message id: the retry carries the reported
    # reply's own stored question, re-derived from the ledger.
    assert "Question: How many sets should I bench?" in captured[0]
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


def test_redaction_keeps_long_words_and_masks_ids():
    # Ordinary long words pass through unredacted: the owner still reads the
    # reply (issue #748 round 2).
    sentence = "Unfortunately the strengthening recommendations need consistency."
    assert _redact_text(sentence, []) == sentence
    # A 12+ char token that contains a digit is an id and is masked.
    masked = _redact_text("token a1b2c3d4e5f6g7 issued", [])
    assert "a1b2c3d4e5f6g7" not in masked
    assert "[redacted id]" in masked
    # Account/Player names are applied before the generic patterns, so a name
    # is "[redacted]", never swallowed into "[redacted id]".
    named = _redact_text(
        "Tell feedbackcoachee (preferred name FeedbackCoacheePref) to add 2.5kg "
        "when all sets hit the top of the range.",
        ["feedbackcoachee", "FeedbackCoacheePref"],
    )
    assert "feedbackcoachee" not in named.lower()
    assert "FeedbackCoacheePref" not in named
    assert "[redacted]" in named
    assert "[redacted id]" not in named


def test_redaction_matches_names_as_whole_words():
    # A short preferred name redacts standalone uses only: "more" and
    # "moment" keep their letters (issue #748 round 2).
    out = _redact_text("Mo, add a set to more of the moment work.", ["Mo"])
    assert out == "[redacted], add a set to more of the moment work."
    # Whole-word matching is Unicode-aware, so Arabic names redact too.
    arabic = _redact_text("اسأل عمر عن تمرينك، وثق بنفسك.", ["عمر"])
    assert "عمر" not in arabic
    assert arabic == "اسأل [redacted] عن تمرينك، وثق بنفسك."
    # An attached Arabic prefix survives with the name redacted after it
    # (issue #748 round 3): the particles are not part of the name. Stacked
    # particles (e.g. فب) are captured too.
    assert _redact_text("وعمر حاضر.", ["عمر"]) == "و[redacted] حاضر."
    assert _redact_text("لعمر رسالة.", ["عمر"]) == "ل[redacted] رسالة."
    assert _redact_text("بعمر تمرين.", ["عمر"]) == "ب[redacted] تمرين."
    assert _redact_text("فبعمر البرنامج.", ["عمر"]) == "فب[redacted] البرنامج."
    assert _redact_text("والعمر موجود.", ["عمر"]) == "وال[redacted] موجود."
    # An unrelated Arabic word that merely contains the same letters stays:
    # the trailing word char blocks the match.
    assert _redact_text("العمرة قريبة.", ["عمر"]) == "العمرة قريبة."
