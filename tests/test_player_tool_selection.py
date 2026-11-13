"""Model tool selection and the #718 program-options regression."""

import json
import sqlite3

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import assistant_graph as graph
from agent.ProgramState import PersistedProgramDaySchema, PersistedProgramExerciseSchema, PersistedProgramSchema
from agent.player_action_tools import build_player_chat_tools, run_player_chat_tool_calls
from agent.program_rules import valid_splits_for
from service.chat_program_edit import plan_chat_program_rebuild
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn


@pytest.fixture
def player_program(fresh_store, editable_catalog_rows):
    ledger = fresh_store.ledger
    ledger.upsert_player_profile({"weekly_frequency": 3, "gender": "male", "equipment_access": "Commercial gym"})
    row = editable_catalog_rows[0]
    exercise = PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
        target_sets=3, target_reps_min=8, target_reps_max=12)
    program = PersistedProgramSchema(program_name="Original", split_type="Full Body", weekly_frequency=5,
        days=[PersistedProgramDaySchema(day_name="Full A", day_order=1, exercises=[exercise])])
    ledger.save_training_program(program.model_dump())
    return fresh_store


def _call(name, args=None):
    return {"name": name, "args": args or {}, "id": "requested-tool"}


def _turn(query):
    return {"messages": [HumanMessage(content=query)], "trainee_id": "default", "player_account_id": None}


def _run(state, store, streaming):
    if streaming:
        list(graph.stream_assistant_turn(state, ledger=store.ledger, store=store))
        return state
    return graph.assistant_graph.invoke(state, config={"configurable": {"ledger": store.ledger, "store": store}})


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("query", [
    "What other 5-day programs are there?",
    "What other program types are available for 5 days",
    "إيه أنواع البرامج التانية المتاحة لخمس أيام؟",
])
def test_718_program_options_reach_the_main_model_and_return_five_day_choices(player_program, monkeypatch, streaming, query):
    store = player_program
    before = store.ledger.get_active_program().model_dump()
    names = [name for _key, name in valid_splits_for(5)]
    model = ScriptedChatModel([ToolCallsTurn(calls=[_call("list_program_options", {"days": 5})]),
                               "; ".join(names) + "."])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn(query), store, streaming)

    assert all(name in result["response_content"] for name in names)
    tool_results = [json.loads(message.content) for message in model.calls[-1]["messages"]
                    if isinstance(message, ToolMessage) and message.name == "list_program_options"]
    assert len(tool_results) == 1
    options = tool_results[0]
    assert options["days"] == 5
    assert {row["split_type"] for row in options["options"]} == {
        "full_body", "upper_lower", "anterior_posterior", "arnold_x_ul", "ppl_x_ul",
    }
    assert all(row["suits"] for row in options["options"])
    assert result["selected_tools"] == ["list_program_options"]
    assert store.ledger.get_active_program().model_dump() == before
    assert store.ledger.get_pending_chat_program_edit() is None


def test_program_options_default_to_active_days_without_changing_saved_frequency(player_program):
    store = player_program
    tools, _definitions = build_player_chat_tools(_turn("What other programs can I choose?"),
        {"configurable": {"ledger": store.ledger, "store": store}})
    result = json.loads(next(tool for tool in tools if tool.name == "list_program_options").invoke({}))

    assert result["days"] == 5
    assert len(result["options"]) == 5
    assert store.ledger.get_player_profile()["weekly_frequency"] == 3


@pytest.mark.parametrize(("query", "tool_name", "args"), [
    ("What did I eat yesterday?", "get_player_food_log", {"day": "yesterday"}),
    ("What are my Nutrition targets?", "get_player_nutrition", {}),
    ("How did I do in my last workout?", "get_exercise_history", {}),
    ("What does my fatigue telemetry say?", "get_player_telemetry", {}),
    ("Find exercises for chest", "search_exercises", {"query": "bench press"}),
])
def test_previous_forced_read_paths_are_chosen_by_the_main_model(player_program, monkeypatch, query, tool_name, args):
    model = ScriptedChatModel([ToolCallsTurn(calls=[_call(tool_name, args)]), "Checked the available data."])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn(query), player_program, False)

    assert result["response_content"] == "Checked the available data."
    assert result["selected_tools"] == [tool_name]
    assert any(isinstance(message, ToolMessage) and message.name == tool_name for message in model.calls[-1]["messages"])


@pytest.mark.parametrize(("query", "expected"), [
    ("I have sharp pain in my shoulder; rebuild my program", "clinical_intercept"),
    ("Add upright rows to my program", "banned_movement"),
])
def test_safety_preempts_model_tools_and_leaves_program_unchanged(player_program, monkeypatch, query, expected):
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([AssertionError("Safety must precede the model")]))
    version = player_program.ledger.get_active_program().version

    result = _run(_turn(query), player_program, True)

    assert result["intent"] == expected
    assert result["response_content"] != graph.PIPELINE_ERROR_RESPONSE
    assert not result["program_updated"]
    assert result["selected_tools"] == []
    assert player_program.ledger.get_active_program().version == version


@pytest.mark.parametrize("query", ["yes", "What other 5-day programs are there?"])
def test_confirmation_tool_cannot_save_without_a_current_offer(player_program, query):
    store = player_program
    state = _turn(query)
    tools, definitions = build_player_chat_tools(state, {"configurable": {"ledger": store.ledger, "store": store}})
    version = store.ledger.get_active_program().version

    messages, _metrics = run_player_chat_tool_calls([_call("confirm_program_edit")],
        tools=tools, definitions=definitions, language="en")

    assert json.loads(messages[0].content)["status"] == "no_current_preview"
    assert store.ledger.get_active_program().version == version


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("answer", ["yes", "أيوه"])
def test_rebuild_uses_separate_confirmation_and_saves_one_version(player_program, monkeypatch, streaming, answer):
    store = player_program
    active = store.ledger.get_active_program()
    rebuilt = active.model_copy(update={"program_name": "Reviewed rebuild", "weekly_frequency": 1})
    planned = plan_chat_program_rebuild(store, store.ledger, None, rebuilt)
    offer = "Program rebuild preview. Confirm or cancel."
    store.ledger.set_pending_chat_program_edit(planned["proposal"], offer)
    assert store.ledger.get_active_program().version == active.version
    state = {**_turn(answer), "messages": [AIMessage(content=offer), HumanMessage(content=answer)]}
    model = ScriptedChatModel([AssertionError("An existing offer must resolve without the model")])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(state, store, streaming)

    assert result["program_updated"] is True
    assert model.calls == []
    saved = store.ledger.get_active_program()
    assert saved.version == active.version + 1
    assert saved.program_name == "Reviewed rebuild"
    assert saved.weekly_frequency == 1
    assert store.ledger.get_pending_chat_program_edit() is None


def test_model_rebuild_tool_prepares_a_preview_without_writing_the_program(player_program, monkeypatch):
    store = player_program
    active = store.ledger.get_active_program()
    model = ScriptedChatModel([ToolCallsTurn(content="I can prepare that preview.", calls=[
        _call("preview_program_rebuild", {"days": 5, "split_type": "ppl_x_ul"}),
    ])])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn("Please rebuild my program as PPL × UL for five days"), store, True)

    pending = store.ledger.get_pending_chat_program_edit()
    assert pending is not None
    assert pending["proposal"]["rebuild_frequency"] == 5
    assert len(pending["proposal"]["preview_days"]) == 5
    assert pending["offer_text"] == result["response_content"]
    assert result["program_edit_preview"]["id"] == pending["offer_id"]
    assert result["program_updated"] is False
    assert store.ledger.get_active_program().version == active.version


def test_substitution_tool_keeps_code_authorization_for_questions(player_program):
    store = player_program
    active = store.ledger.get_active_program()
    source = active.days[0].exercises[0].exercise_name
    state = _turn(f"Should I swap {source} for another exercise?")
    tools, definitions = build_player_chat_tools(state, {"configurable": {"ledger": store.ledger, "store": store}})

    run_player_chat_tool_calls([_call("substitute_exercise", {"source_exercise": source, "target_exercise": "bench press"})],
        tools=tools, definitions=definitions, language="en")

    assert state["tool_action_result"]["program_updated"] is False
    assert store.ledger.get_active_program().version == active.version


def test_rebuild_tool_keeps_coach_program_authority_in_code(player_program, monkeypatch):
    store = player_program
    ledger = store.ledger
    ledger.save_training_program(ledger.get_active_program().model_dump(),
                                 published_by_coach_account_id="publishing-coach")
    active = ledger.get_active_program()
    # Registry lookup is an external authorization boundary; Program state is real.
    monkeypatch.setattr(store, "get_active_assignment_for_player", lambda _account_id: {
        "coach_account_id": "publishing-coach", "started_at": "2000-01-01T00:00:00",
    })
    state = {**_turn("Rebuild my program for four days"), "player_account_id": "player-account"}
    tools, definitions = build_player_chat_tools(state, {"configurable": {"ledger": ledger, "store": store}})

    run_player_chat_tool_calls([_call("preview_program_rebuild", {"days": 4, "split_type": "upper_lower"})],
        tools=tools, definitions=definitions, language="en")

    result = state["tool_action_result"]
    assert result["program_updated"] is False
    assert result["request_suggestion"]["desired_weekly_frequency"] == 4
    assert ledger.get_pending_chat_program_edit() is None
    assert ledger.get_active_program().version == active.version


@pytest.fixture
def ppl_ul_player(player_program):
    from agent.program_generator import ProgramGenerationRequest, generate_program_draft_pipeline

    ledger = player_program.ledger
    ledger.upsert_player_profile({**ledger.get_player_profile(), "age": 21,
        "training_age_years": 4, "weekly_frequency": 5})
    program, _markdown = generate_program_draft_pipeline(
        ProgramGenerationRequest(frequency_override=5, split_id_override="ppl_x_ul"), ledger=ledger)
    ledger.save_training_program(program.model_dump())
    return player_program


def _narrated_call(name, args=None):
    return ToolCallsTurn(content="Let me first check your current profile and program details to make sure I have the full picture.",
                         calls=[_call(name, args)])


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("arabic_rebuild", [False, True])
def test_718_staging_four_turn_replay_shows_current_split_and_same_split_preview(
    ppl_ul_player, monkeypatch, streaming, arabic_rebuild,
):
    """Real staging regression: options → rebuild → 'ppl ul' → rebuild again."""
    store = ppl_ul_player
    active = store.ledger.get_active_program()
    history = []
    names = [name for _key, name in valid_splits_for(5)]
    options_reply = "; ".join(
        name + (" (your current program)" if name == "PPL × UL" else "") for name in names) + "."
    final_query = "عايز أعيد بناء برنامجي بنفس تقسيمة PPL UL" if arabic_rebuild else "i want to rebuild my program"
    cases = [
        ("what are availible program types for me?", [
            _narrated_call("list_program_options"), options_reply]),
        ("okay lets rebuild the program", [
            _narrated_call("get_player_profile", {"sections": ["Body", "Training setup"]}),
            _narrated_call("get_active_program"),
            "You're 21, with 4 years of training, on a 5-day PPL × UL with player authority. Which split would you like?"]),
        ("ppl ul", [
            _narrated_call("get_player_profile", {"sections": ["Training setup"]}),
            _narrated_call("get_active_program"),
            _narrated_call("preview_program_rebuild", {"split_type": "ppl ul"}),
            ""]),
        (final_query, [
            _narrated_call("get_active_program"),
            _narrated_call("preview_program_rebuild"), ""]),
    ]
    for index, (query, script) in enumerate(cases):
        model = ScriptedChatModel(script, chunk_size=1)
        monkeypatch.setattr(graph, "llm", model)
        request = {**_turn(query), "messages": [*history, HumanMessage(content=query)]}
        result = _run(request, store, streaming)
        reply = result["response_content"]
        assert graph.EMPTY_RESPONSE_FALLBACK not in reply
        assert graph.PIPELINE_ERROR_RESPONSE not in reply
        assert "Let me first check" not in reply
        assert "picture." not in reply
        assert "authority" not in reply.casefold()
        assert not result["program_updated"]
        assert store.ledger.get_active_program().model_dump() == active.model_dump()
        if index == 0:
            assert all(name in reply for name in names)
            assert "PPL × UL (your current program)" in reply
            payloads = [json.loads(message.content) for message in model.calls[-1]["messages"]
                        if isinstance(message, ToolMessage) and message.name == "list_program_options"]
            assert [row["name"] for row in payloads[-1]["options"] if row["is_current"]] == ["PPL × UL"]
        if index >= 2:
            pending = store.ledger.get_pending_chat_program_edit()
            assert result["program_edit_preview"]["id"] == pending["offer_id"]
            assert pending["offer_text"] == reply
            assert pending["proposal"]["rebuild_base_program"]["split_type"] == active.split_type
            assert len(result["program_edit_preview"]["days"]) == 5
            assert ("أكد أو ألغِ" if arabic_rebuild and index == 3 else "Confirm or cancel") in reply
            old_ids = {row.exercise_id for day in active.days for row in day.exercises}
            new_ids = {row["exercise_id"] for day in pending["proposal"]["rebuild_base_program"]["days"]
                       for row in day["exercises"]}
            assert new_ids - old_ids, "Same-split rebuild should prefer eligible fresh exercises"
        history.extend([HumanMessage(content=query), AIMessage(content=reply)])

    confirmation = "أيوه" if arabic_rebuild else "yes"
    confirmation_model = ScriptedChatModel([AssertionError("Pending confirmation must bypass the model")])
    monkeypatch.setattr(graph, "llm", confirmation_model)
    result = _run({**_turn(confirmation), "messages": [*history, HumanMessage(content=confirmation)]}, store, streaming)
    assert result["program_updated"]
    assert confirmation_model.calls == []
    assert store.ledger.get_active_program().version == active.version + 1
    assert store.ledger.get_pending_chat_program_edit() is None


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(("query", "marker"), [
    ("Rebuild my program", "not available"),
    ("عايز أعيد بناء برنامجي", "مش متاحة"),
])
def test_718_failed_preview_has_specific_localized_reply_even_if_model_would_stop_empty(
    ppl_ul_player, monkeypatch, streaming, query, marker,
):
    store = ppl_ul_player
    before = store.ledger.get_active_program().model_dump()
    model = ScriptedChatModel([
        _narrated_call("preview_program_rebuild", {"split_type": "unsupported imaginary split"}), ""])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn(query), store, streaming)

    assert marker in result["response_content"]
    assert "Let me first check" not in result["response_content"]
    assert graph.EMPTY_RESPONSE_FALLBACK not in result["response_content"]
    assert not result.get("program_edit_preview")
    assert not result["program_updated"]
    assert store.ledger.get_active_program().model_dump() == before
    assert store.ledger.get_pending_chat_program_edit() is None


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(("query", "marker", "unchanged"), [
    ("i want to rebuild my program", "couldn't prepare the program rebuild preview", "Nothing changed"),
    ("عايز أعيد بناء برنامجي", "مقدرتش أجهز معاينة إعادة بناء البرنامج", "مفيش حاجة اتغيرت"),
])
def test_718_empty_final_after_last_read_round_reports_unprepared_rebuild(player_program, monkeypatch, streaming, query, marker, unchanged):
    model = ScriptedChatModel([
        *[_narrated_call("get_player_profile", {"sections": ["Training setup"]})
          for _ in range(graph.MAX_PLAYER_TOOL_ROUNDS)], ""])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn(query), player_program, streaming)

    reply = result["response_content"]
    assert marker in reply
    assert unchanged in reply
    assert "Let me first check" not in reply
    assert graph.EMPTY_RESPONSE_FALLBACK not in reply


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(("query", "answer", "management"), [
    ("Tell me about my current program",
     "You are on Full Body with player authority. The split_type is full_body; get_active_program checked it.",
     "that you manage"),
    ("قولي عن برنامجي الحالي",
     "تمام، برنامجك Full Body مع player authority. قيمة split_type اتراجعت عن طريق get_active_program.",
     "إنت اللي بتديره"),
])
def test_718_last_tool_round_still_gets_a_final_answer(player_program, monkeypatch, streaming, query, answer, management):
    model = ScriptedChatModel([
        *[_narrated_call("get_active_program") for _ in range(graph.MAX_PLAYER_TOOL_ROUNDS)],
        answer])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn(query), player_program, streaming)

    reply = result["response_content"]
    assert "Full Body" in reply
    assert management in reply
    assert all(term not in reply for term in ("authority", "split_type", "get_active_program", "Let me first check"))
    assert graph.EMPTY_RESPONSE_FALLBACK not in reply


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(("query", "marker"), [
    ("Rebuild my program", "couldn't read the requested action details"),
    ("عايز أعيد بناء برنامجي", "مقدرتش أقرأ تفاصيل الطلب"),
])
def test_718_malformed_rebuild_call_discards_narration_and_reports_failure(player_program, monkeypatch, streaming, query, marker):
    model = ScriptedChatModel([AIMessage(
        content="Let me first check your program. I will prepare a fresh preview.",
        invalid_tool_calls=[{"name": "preview_program_rebuild", "args": "not-json", "id": "invalid-call",
                             "error": "Invalid JSON"}],
    )], chunk_size=1)
    monkeypatch.setattr(graph, "llm", model)
    before = player_program.ledger.get_active_program().model_dump()

    result = _run(_turn(query), player_program, streaming)

    reply = result["response_content"]
    assert marker in reply
    assert "Let me first check" not in reply
    assert "I will prepare" not in reply
    assert graph.EMPTY_RESPONSE_FALLBACK not in reply
    assert not result.get("program_edit_preview")
    assert not result["program_updated"]
    assert player_program.ledger.get_active_program().model_dump() == before


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(("query", "marker"), [
    ("Rebuild my program", "couldn't generate the program rebuild preview"),
    ("عايز أعيد بناء برنامجي", "مقدرتش أجهز معاينة إعادة بناء البرنامج"),
])
def test_718_preview_storage_failure_returns_honest_localized_reply(ppl_ul_player, monkeypatch, streaming, query, marker):
    store = ppl_ul_player
    before = store.ledger.get_active_program().model_dump()

    def fail_preview_storage(*_args, **_kwargs):
        raise sqlite3.OperationalError("private storage failure")

    monkeypatch.setattr(store.ledger, "set_pending_chat_program_edit", fail_preview_storage)
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([_narrated_call("preview_program_rebuild"), ""]))

    result = _run(_turn(query), store, streaming)

    reply = result["response_content"]
    assert marker in reply
    assert "private storage" not in reply
    assert "Let me first check" not in reply
    assert graph.EMPTY_RESPONSE_FALLBACK not in reply
    assert not result.get("program_edit_preview")
    assert not result["program_updated"]
    assert store.ledger.get_active_program().model_dump() == before
