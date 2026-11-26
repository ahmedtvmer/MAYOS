"""Player workout-history read tool and model-path history answers (#767)."""

import json
from datetime import date

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph
from agent.player_tools import MAX_TOOL_RESULT_BYTES, build_player_read_tools
from database.shared import _normalize_exercise_name
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn

BENCH_ID = "25"  # Bench Press (Barbell) in the tracked synthetic curation.
SQUAT_ID = "43"  # Back Squat (Barbell).


def _seed_session(ledger, session_id, day, split, sets, readiness=4):
    ledger.log_workout_session(
        session_id, day, split,
        f"{day}T10:00:00+00:00", f"{day}T11:00:00+00:00", readiness_score=readiness,
    )
    for index, (exercise_id, weight_kg, reps, rpe) in enumerate(sets, start=1):
        ledger.log_workout_set(
            f"{session_id}-set-{index}", session_id, exercise_id, index, weight_kg, reps, rpe
        )


def _seed_standard_sessions(ledger):
    _seed_session(ledger, "history-session-a", "2026-11-05", "Upper", [
        (BENCH_ID, 75.0, 8, 7), (BENCH_ID, 75.0, 8, 8), (BENCH_ID, 80.0, 6, 8),
        (SQUAT_ID, 100.0, 8, 7),
    ])
    _seed_session(ledger, "history-session-b", "2026-11-07", "Lower", [
        (BENCH_ID, 80.0, 8, 8), (BENCH_ID, 82.5, 6, None), (SQUAT_ID, 110.0, 6, 7.5),
    ])


@pytest.fixture
def history_store(fresh_store):
    _seed_standard_sessions(fresh_store.ledger)
    return fresh_store


def _history_tool(store, ledger):
    tools, _definitions = build_player_read_tools(ledger, store, "history-player")
    return next(tool for tool in tools if tool.name == "get_workout_history")


def test_last_session_returns_set_detail_with_rir_and_comparison(history_store):
    tool = _history_tool(history_store, history_store.ledger)
    result = json.loads(tool.invoke({}))

    assert result["status"] == "ok"
    session = result["sessions"][0]
    assert session["date"] == "2026-11-07"
    assert session["day"] == "Lower"
    assert session["readiness"] == 4
    bench = next(exercise for exercise in session["exercises"] if exercise["id"] == BENCH_ID)
    assert bench["name"] == "Bench Press (Barbell)"
    assert bench["sets"] == [
        {"set": 1, "kg": 80.0, "reps": 8, "rir": 2, "rpe": 8},
        {"set": 2, "kg": 82.5, "reps": 6},
    ]
    # `_status` (database/ledger/debriefs.py) collects the signs of the
    # load_kg, reps and e1RM deltas (zeros discarded) and returns "mixed" when
    # they disagree. Here load is +2.5 kg and reps are equal (0, discarded),
    # but the previous best set was rated RPE 8 (e1RM = 80×(1+8/30) ≈ 101.33)
    # while the new best set is unrated and scores plain Epley as RPE 10
    # (e1RM = 82.5×(1+6/30) = 99.0, #111), so the e1RM delta is negative and
    # the status is "mixed" — heavier load, lower effort-adjusted estimate.
    assert bench["vs_previous"] == {
        "baseline": "2026-11-05", "delta_kg": 2.5, "delta_reps": 0, "status": "mixed",
    }
    unrated_squat = next(
        exercise for exercise in session["exercises"] if exercise["id"] == SQUAT_ID
    )
    assert {"set": 3, "kg": 110.0, "reps": 6, "rir": 2.5, "rpe": 7.5} in unrated_squat["sets"]


def test_date_scope_returns_that_sessions_day_and_sets(history_store):
    tool = _history_tool(history_store, history_store.ledger)
    result = json.loads(tool.invoke({"scope": "date", "date": "2026-11-05"}))

    assert result["status"] == "ok"
    assert [session["date"] for session in result["sessions"]] == ["2026-11-05"]
    assert result["sessions"][0]["day"] == "Upper"
    assert {exercise["id"] for exercise in result["sessions"][0]["exercises"]} == {BENCH_ID, SQUAT_ID}
    assert result["next_offset"] is None


def test_date_scope_resolves_player_local_relative_days(history_store, monkeypatch):
    monkeypatch.setattr(
        "agent.player_tools.player_local_date", lambda _ledger, _ledger_id: date(2026, 11, 8)
    )
    tool = _history_tool(history_store, history_store.ledger)
    yesterday = json.loads(tool.invoke({"scope": "date", "date": "yesterday"}))
    today = json.loads(tool.invoke({"scope": "date", "date": "today"}))

    assert [session["date"] for session in yesterday["sessions"]] == ["2026-11-07"]
    assert today["status"] == "no_sessions"
    assert today["date"] == "2026-11-08"
    assert today["sessions"] == []


def test_date_scope_reports_empty_and_invalid_dates(history_store):
    tool = _history_tool(history_store, history_store.ledger)
    empty = json.loads(tool.invoke({"scope": "date", "date": "2026-11-06"}))
    invalid = json.loads(tool.invoke({"scope": "date", "date": "not-a-date"}))

    assert empty["status"] == "no_sessions"
    assert "No sessions logged on that date." in empty["message"]
    assert empty["date"] == "2026-11-06"
    assert invalid["status"] == "invalid_date"


def test_exercise_scope_resolves_english_nickname_and_exact_name(history_store):
    tool = _history_tool(history_store, history_store.ledger)
    nickname = json.loads(tool.invoke({"scope": "exercise", "exercise": "bench"}))
    exact = json.loads(tool.invoke({"scope": "exercise", "exercise": "Bench Press (Barbell)"}))

    for result in (nickname, exact):
        assert result["status"] == "ok"
        assert [session["date"] for session in result["sessions"]] == ["2026-11-07", "2026-11-05"]
        for session in result["sessions"]:
            assert [exercise["id"] for exercise in session["exercises"]] == [BENCH_ID]
    assert exact["sessions"][0]["exercises"][0]["sets"][0]["kg"] == 80.0


def test_exercise_scope_resolves_arabic_alias(history_store):
    with history_store.catalog_locked() as conn:
        conn.execute(
            "INSERT INTO exercise_aliases (exercise_id, alias, normalized_alias) VALUES (?, ?, ?)",
            (BENCH_ID, "بنش", _normalize_exercise_name("بنش")),
        )
    tool = _history_tool(history_store, history_store.ledger)
    result = json.loads(tool.invoke({"scope": "exercise", "exercise": "بنش"}))

    assert result["status"] == "ok"
    assert [session["date"] for session in result["sessions"]] == ["2026-11-07", "2026-11-05"]
    for session in result["sessions"]:
        assert [exercise["id"] for exercise in session["exercises"]] == [BENCH_ID]


def test_exercise_scope_reports_ambiguous_and_unknown_names(history_store):
    tool = _history_tool(history_store, history_store.ledger)
    ambiguous = json.loads(tool.invoke({"scope": "exercise", "exercise": "barbell"}))
    unknown = json.loads(tool.invoke({"scope": "exercise", "exercise": "ziada"}))

    assert ambiguous["status"] == "ambiguous_exercise"
    assert ambiguous["candidates"] == ["Bench Press (Barbell)", "Back Squat (Barbell)"]
    assert unknown["status"] == "unknown_exercise"
    assert unknown["sessions"] == []


def test_recent_sessions_pages_newest_first(history_store):
    _seed_session(history_store.ledger, "history-session-c", "2026-11-03", "Upper", [
        (BENCH_ID, 70.0, 8, 8),
    ])
    tool = _history_tool(history_store, history_store.ledger)
    first = json.loads(tool.invoke({"scope": "recent_sessions", "limit": 2}))
    second = json.loads(tool.invoke({"scope": "recent_sessions", "limit": 2, "offset": 2}))

    assert [session["date"] for session in first["sessions"]] == ["2026-11-07", "2026-11-05"]
    assert first["next_offset"] == 2
    assert [session["date"] for session in second["sessions"]] == ["2026-11-03"]
    assert second["next_offset"] is None


def test_empty_ledger_reports_no_sessions_for_every_scope(fresh_store):
    ledger = fresh_store.ledger
    tool = _history_tool(fresh_store, ledger)
    for arguments in (
        {},
        {"scope": "recent_sessions", "limit": 2},
        {"scope": "date", "date": "2026-11-07"},
        {"scope": "exercise", "exercise": "bench"},
    ):
        result = json.loads(tool.invoke(arguments))
        assert result["status"] == "no_sessions"
        assert "No sessions logged." in result["message"]
        assert result["sessions"] == []


def test_oversized_session_is_compacted_under_the_result_cap(fresh_store):
    ledger = fresh_store.ledger
    _seed_session(
        ledger, "history-session-big", "2026-11-07", "Upper",
        [(BENCH_ID, 80.0 + index, 8, 8) for index in range(150)],
    )
    tool = _history_tool(fresh_store, ledger)
    payload = tool.invoke({"scope": "last_session"})

    assert len(payload.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES
    result = json.loads(payload)
    assert result["status"] == "ok"
    assert result["sessions"][0]["detail_truncated"] is True
    assert result["sessions"][0]["exercises"][0]["sets"][0] == {"kg": 80.0, "reps": 8}


def test_multi_session_results_page_before_exceeding_the_result_cap(fresh_store):
    ledger = fresh_store.ledger
    # Each ~45-set session renders to ~2.3 KB: one fits per 4 KB page with
    # margin on both sides of the cap, so the split is deterministic.
    for index, day in enumerate(("2026-11-01", "2026-11-03", "2026-11-05")):
        _seed_session(ledger, f"history-session-{index}", day, "Upper", [
            (BENCH_ID, 80.0 + set_index, 8, 8) for set_index in range(45)
        ])
    tool = _history_tool(fresh_store, ledger)
    first = json.loads(tool.invoke({"scope": "recent_sessions", "limit": 10}))
    second = json.loads(
        tool.invoke({"scope": "recent_sessions", "limit": 10, "offset": first["next_offset"]})
    )
    third = json.loads(
        tool.invoke({"scope": "recent_sessions", "limit": 10, "offset": second["next_offset"]})
    )

    assert [session["date"] for session in first["sessions"]] == ["2026-11-05"]
    assert first["next_offset"] == 1
    assert [session["date"] for session in second["sessions"]] == ["2026-11-03"]
    assert second["next_offset"] == 2
    assert [session["date"] for session in third["sessions"]] == ["2026-11-01"]
    assert third["next_offset"] is None


def test_history_reads_are_scoped_to_one_account_and_read_only(fresh_store):
    with fresh_store.open_ledger("history-player-a") as ledger_a:
        _seed_standard_sessions(ledger_a)
        tool_a = _history_tool(fresh_store, ledger_a)
        before = list(ledger_a.conn.iterdump())
        own = tool_a.invoke({})
        assert list(ledger_a.conn.iterdump()) == before
    with fresh_store.open_ledger("history-player-b") as ledger_b:
        tool_b = _history_tool(fresh_store, ledger_b)
        other = tool_b.invoke({})

    own_result = json.loads(own)
    assert own_result["status"] == "ok"
    assert own_result["sessions"][0]["date"] == "2026-11-07"
    assert "Bench Press (Barbell)" in own
    other_result = json.loads(other)
    assert other_result["status"] == "no_sessions"
    assert "No sessions logged." in other_result["message"]
    for secret in ("Bench Press", "2026-11-07", "Lower", "82.5"):
        assert secret not in other


def _force_coaching_qa_intent(monkeypatch):
    monkeypatch.setattr(
        assistant_graph,
        "_classify_intent_with_llm",
        lambda _query, *_context: assistant_graph.IntentClassification(intent="coaching_qa"),
    )
    monkeypatch.setattr(
        assistant_graph,
        "_classify_arabic_intent",
        lambda _query, _config, *_context: {"intent": "coaching_qa", "intent_metadata": {}},
    )


def _run_model_turn(fresh_store, monkeypatch, mode, query, language, model):
    monkeypatch.setattr(assistant_graph, "llm", model)
    state = {"messages": [HumanMessage(content=query)], "display_language": language}
    if mode == "stream":
        output = "".join(assistant_graph.stream_assistant_turn(
            state, ledger=fresh_store.ledger, store=fresh_store
        ))
    else:
        state = assistant_graph.assistant_graph.invoke(
            state, config={"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}}
        )
        output = state["response_content"]
    return state, output


@pytest.mark.parametrize("mode", ["stream", "graph"])
@pytest.mark.parametrize(("query", "language", "answer"), [
    ("was I strong today?", "en", "Your last session says yes."),
    ("كنت تقيل في الضغط المرة دي؟", "ar", "آخر سيت كان 82.5 كجم."),
])
def test_model_path_answers_history_questions_through_the_tool(
    history_store, monkeypatch, mode, query, language, answer
):
    _force_coaching_qa_intent(monkeypatch)
    model = ScriptedChatModel([
        ToolCallsTurn(calls=[{
            "name": "get_workout_history", "args": {"scope": "last_session"}, "id": "history-read",
        }]),
        answer,
    ])
    state, output = _run_model_turn(history_store, monkeypatch, mode, query, language, model)

    assert state["intent"] == "coaching_qa"
    assert output == state["response_content"] == answer
    assert "get_workout_history" in model.calls[0]["tools"]
    tool_reply = next(
        message for message in model.calls[-1]["messages"] if message.type == "tool"
    )
    result = json.loads(tool_reply.content)
    assert result["status"] == "ok"
    assert result["sessions"][0]["date"] == "2026-11-07"
    assert result["sessions"][0]["day"] == "Lower"
    bench = next(
        exercise for exercise in result["sessions"][0]["exercises"] if exercise["id"] == BENCH_ID
    )
    assert {"set": 2, "kg": 82.5, "reps": 6} in bench["sets"]


def test_plain_franco_history_question_gets_the_input_refusal_not_the_injury_path():
    # #343 Stage A: every detected Franco-Arabic message gets the fixed
    # "write in Arabic or English" refusal. The injury guard itself is a
    # clinical negative for this plain history question (see
    # test_franco_clinical_guard.py); the interception is the input gate.
    query = "a5er mara kan 3amel ezay"
    assert assistant_graph.is_franco_arabic(query) is True
    state = {"messages": [HumanMessage(content=query)], "telemetry_context": "", "intent_metadata": {}}
    route = assistant_graph.router_node(state)

    assert route["intent"] == "clinical_intercept"
    assert route["intent_metadata"]["franco"] is True


@pytest.mark.parametrize("mode", ["stream", "graph"])
def test_model_path_answers_honestly_when_no_sessions_are_logged(
    fresh_store, monkeypatch, mode
):
    _force_coaching_qa_intent(monkeypatch)
    answer = "You have no sessions logged yet."
    model = ScriptedChatModel([
        ToolCallsTurn(calls=[{"name": "get_workout_history", "args": {}, "id": "history-read"}]),
        answer,
    ])
    state, output = _run_model_turn(
        fresh_store, monkeypatch, mode, "was I strong today?", "en", model
    )

    assert state["intent"] == "coaching_qa"
    assert output == state["response_content"] == answer
    tool_reply = next(
        message for message in model.calls[-1]["messages"] if message.type == "tool"
    )
    result = json.loads(tool_reply.content)
    assert result["status"] == "no_sessions"
    assert "No sessions logged." in result["message"]
