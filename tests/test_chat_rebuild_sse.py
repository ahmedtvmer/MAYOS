"""#718 second staging conversation through the real streaming HTTP router.

Only the hosted model and injected storage faults are replaced. Generation,
offer persistence, per-request ledger handles and SSE encoding remain real.
"""

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from agent import assistant_graph as graph
from agent.program_generator import ProgramGenerationRequest, generate_program_draft_pipeline
from agent.program_rules import valid_splits_for
from database.ledger.handle import TrainingLedger
from svc.app import create_app
from svc.dependencies import get_db
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn


@pytest.fixture
def rebuild_chat(fresh_store, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    from svc.rate_limit import limiter

    limiter._storage.reset()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_store
    with TestClient(app) as client:
        registered = client.post("/auth/register", json={
            "trainee_id": "rebuild-player", "password": "correct-horse-1",
        })
        assert registered.status_code == 201, registered.text
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        with fresh_store.open_ledger("rebuild-player") as ledger:
            ledger.upsert_player_profile({"age": 21, "training_age_years": 4,
                "weekly_frequency": 5, "gender": "male", "equipment_access": "Commercial gym"})
            generated, _markdown = generate_program_draft_pipeline(
                ProgramGenerationRequest(frequency_override=5, split_id_override="ppl_x_ul"), ledger=ledger)
            ledger.save_training_program(generated.model_dump())
        yield client, fresh_store, headers


def _tool(name, args=None):
    return ToolCallsTurn(calls=[{"name": name, "args": args or {}, "id": "model-selected-action"}])


def _post_sse(chat, content):
    client, _store, headers = chat
    with client.stream("POST", "/chat/messages", headers=headers, json={"content": content}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = response.read().decode("utf-8")
    payloads = [json.loads(line.removeprefix("data: "))
                for line in raw.splitlines() if line.startswith("data: ")]
    return raw, payloads


def _done(chat, content):
    raw, payloads = _post_sse(chat, content)
    assert "event: error" not in raw, raw
    assert graph.PIPELINE_ERROR_RESPONSE not in raw
    done = next(payload for payload in payloads if payload.get("done"))
    assert "".join(payload["token"] for payload in payloads if "token" in payload) == done["response_content"]
    return done


def _assert_real_preview(done, language):
    preview = done["program_edit_preview"]
    assert len(preview["days"]) == 5
    for day in preview["days"]:
        assert day["exercises"]
        for exercise in day["exercises"]:
            assert exercise["name"] in done["response_content"]
            assert exercise["sets"] > 0
            prescription = f"{exercise['sets']} " + ("sets" if language == "en" else "مجموعات")
            assert prescription in done["response_content"]
    assert ("Confirm" if language == "en" else "أكد") in done["response_content"]
    assert not done["program_updated"]
    return preview


@pytest.mark.parametrize(("language", "options", "rebuild", "generate", "confirm"), [
    ("en", "what program types are available for me?", "rebuild my program", "generate", "yes"),
    ("ar", "إيه أنواع البرامج المتاحة ليا؟", "عايز أعيد بناء برنامجي", "اعمل المعاينة", "أيوه"),
])
def test_718_rebuild_streams_real_preview_immediately_and_confirmation_writes_once(
    rebuild_chat, monkeypatch, language, options, rebuild, generate, confirm,
):
    client, store, headers = rebuild_chat
    with store.open_ledger("rebuild-player") as ledger:
        original = ledger.get_active_program()
    options_reply = "; ".join(name for _key, name in valid_splits_for(5)) + "."
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([
        _tool("list_program_options"), options_reply,
        _tool("get_active_program"), _tool("preview_program_rebuild"),
        _tool("confirm_program_edit"), _tool("confirm_program_edit"),
        _tool("confirm_program_edit"), "There is no current preview to confirm.",
    ]))
    _done(rebuild_chat, options)
    preview = _assert_real_preview(_done(rebuild_chat, rebuild), language)
    assert len(json.dumps(preview).encode("utf-8")) > 4096
    with store.open_ledger("rebuild-player") as ledger:
        pending = ledger.get_pending_chat_program_edit()
        assert ledger.get_active_program().version == original.version
        assert pending["proposal"]["rebuild_base_program"]["split_type"] == original.split_type
        old_ids = {row.exercise_id for day in original.days for row in day.exercises}
        new_ids = {row["exercise_id"] for day in pending["proposal"]["rebuild_base_program"]["days"]
                   for row in day["exercises"]}
        assert new_ids - old_ids
    repeated = _done(rebuild_chat, generate)
    assert _assert_real_preview(repeated, language)["id"] == preview["id"]
    history = client.get("/chat/history", headers=headers).json()
    assert history[-1]["content"] == repeated["response_content"]
    assert history[-1]["program_edit_preview"] == repeated["program_edit_preview"]
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_pending_chat_program_edit()["offer_text"] == repeated["response_content"]
        assert ledger.get_active_program().version == original.version
    assert _done(rebuild_chat, confirm)["program_updated"]
    assert not _done(rebuild_chat, confirm)["program_updated"]
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_active_program().version == original.version + 1
        assert ledger.get_pending_chat_program_edit() is None


@pytest.mark.parametrize(("language", "answer", "confirm", "old_offer"), [
    ("en", "yes", "confirm", "Want me to generate the full preview with the actual exercises and sets?"),
    ("en", "generate", "confirm", "Want me to generate the full preview with the actual exercises and sets?"),
    ("ar", "أيوه", "أكد", "تمام، تحب أجهز المعاينة الكاملة بالتمارين والمجموعات؟"),
    ("ar", "اعمل المعاينة", "أكد", "تمام، تحب أجهز المعاينة الكاملة بالتمارين والمجموعات؟"),
])
def test_718_answer_to_legacy_generation_offer_previews_before_separate_confirmation(
    rebuild_chat, monkeypatch, language, answer, confirm, old_offer,
):
    # Replay the old hosted-model reply to reproduce staging history with no
    # saved proposal; later requests must recover through fresh ledger handles.
    _client, store, _headers = rebuild_chat
    with store.open_ledger("rebuild-player") as ledger:
        original = ledger.get_active_program().version
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([
        _tool("list_program_options"), "PPL × UL (your current program).",
        old_offer, _tool("preview_program_rebuild"), _tool("confirm_program_edit"),
    ]))
    _done(rebuild_chat, "what program types are available for me?")
    old_reply = _done(rebuild_chat, "rebuild my program" if language == "en" else "أعيد بناء برنامجي")
    assert "program_edit_preview" not in old_reply
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_pending_chat_program_edit() is None
    _assert_real_preview(_done(rebuild_chat, answer), language)
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_active_program().version == original
    assert _done(rebuild_chat, confirm)["program_updated"]
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_active_program().version == original + 1


@pytest.mark.parametrize(("language", "query", "confirm"), [
    ("en", "rebuild my program", "yes"),
    ("ar", "عايز أعيد بناء برنامجي", "أيوه"),
])
def test_718_model_cannot_confirm_a_preview_created_in_the_same_turn(
    rebuild_chat, monkeypatch, language, query, confirm,
):
    _client, store, _headers = rebuild_chat
    with store.open_ledger("rebuild-player") as ledger:
        version = ledger.get_active_program().version
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([
        ToolCallsTurn(calls=[
            {"name": "preview_program_rebuild", "args": {}, "id": "preview"},
            {"name": "confirm_program_edit", "args": {}, "id": "premature-confirm"},
        ]),
        _tool("confirm_program_edit"),
    ]))
    _assert_real_preview(_done(rebuild_chat, query), language)
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_active_program().version == version
    assert _done(rebuild_chat, confirm)["program_updated"]
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_active_program().version == version + 1


@pytest.mark.parametrize("query", ["rebuild my program", "عايز أعيد بناء برنامجي"])
@pytest.mark.parametrize("failure_at", ["preview_storage", "history_read", "offer_binding"])
def test_718_stream_failures_log_traceback_and_request_id_without_private_values(
    rebuild_chat, monkeypatch, caplog, query, failure_at,
):
    _client, store, _headers = rebuild_chat
    with store.open_ledger("rebuild-player") as ledger:
        version = ledger.get_active_program().version
    private_detail = "PRIVATE_PLAYER_CONTENT_718"

    def storage_fault(*_args, **_kwargs):
        raise RuntimeError(private_detail)

    method = {"preview_storage": "set_pending_chat_program_edit", "history_read": "get_chat_history",
              "offer_binding": "update_pending_chat_program_edit_offer"}[failure_at]
    monkeypatch.setattr(TrainingLedger, method, storage_fault)
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([_tool("preview_program_rebuild")]))
    with caplog.at_level(logging.ERROR):
        raw, payloads = _post_sse(rebuild_chat, query)
    assert "event: error" in raw
    assert any(payload.get("message_code") == "chat.failed.v1" for payload in payloads)
    assert not any(payload.get("done") for payload in payloads)
    failures = [record for record in caplog.records if record.exc_info and "request_id=" in record.getMessage()]
    assert failures
    assert all(re.search(r"request_id=[0-9a-f]{32}\b", record.getMessage()) for record in failures)
    assert all(record.exc_info[2] is not None for record in failures)
    assert "exception_type=RuntimeError" in caplog.text
    assert private_detail not in caplog.text + raw
    assert query not in caplog.text
    with store.open_ledger("rebuild-player") as ledger:
        assert ledger.get_active_program().version == version
        if failure_at != "offer_binding":
            assert ledger.get_pending_chat_program_edit() is None
