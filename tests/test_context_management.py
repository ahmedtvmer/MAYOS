import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture
def graph(monkeypatch):
    modules = {}
    for name, attrs in {
        "agent.clinical_guard": ["EMBED_MODEL", "evaluate_clinical_semantic_guard"],
        "agent.program_generator": ["extract_frequency_from_text", "generate_program_pipeline", "get_biomechanical_cue"],
        "database.database_manager": ["DatabaseManager"],
        "utils.model_downloader": ["llm"],
        "utils.logger": ["MyosLogger"],
    }.items():
        module = ModuleType(name)
        for attr in attrs:
            setattr(module, attr, MagicMock())
        modules[name] = module
        monkeypatch.setitem(sys.modules, name, module)
    modules["agent.clinical_guard"].evaluate_clinical_semantic_guard.return_value = (False, 0.0)
    modules["agent.program_generator"].extract_frequency_from_text.return_value = None

    class NullFileHandler(logging.NullHandler):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.baseFilename = "/tmp/opencode/mock.log"

    monkeypatch.setattr(logging, "FileHandler", NullFileHandler)
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: None)
    path = Path(__file__).resolve().parents[1] / "agent" / "assistant_graph.py"
    spec = importlib.util.spec_from_file_location("isolated_assistant_graph", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.llm = SimpleNamespace(n_ctx=2048, max_tokens=200, client=SimpleNamespace(tokenize=lambda data, **kwargs: list(range((len(data) + 3) // 4))), invoke=MagicMock(return_value=AIMessage(content="Use controlled reps.")))
    module.reconcile_telemetry_query = MagicMock(return_value=None)
    module._record_telemetry_event = MagicMock()
    return module


def state(query, prior=()):
    return {"messages": list(prior) + [HumanMessage(content=query)], "telemetry_context": "Recorded sets exist.", "intent_metadata": {}}


@pytest.mark.parametrize("query", ["malak", "sarah", "asdasd", "hey", "hello", "I'm frustrated", "fuck you"])
def test_short_conversation_bypasses_canned_clarification(graph, query):
    request = state(query)
    assert graph.router_node(request) == {"intent": "coaching_qa", "intent_metadata": {}}
    result = graph.generation_node(request)
    assert result["response_content"] == "Use controlled reps."
    graph.llm.invoke.assert_called_once()
    prompt = graph.llm.invoke.call_args.args[0][0].content
    assert "Respond naturally to greetings, introductions and frustration" in prompt
    assert "Short messages are not inherently unclear" in prompt


@pytest.mark.parametrize("query", ["RDLs", "RPE?", "why?", "the second one", "8"])
def test_shorthand_and_followups(graph, query):
    result = graph.generation_node(state(query, [HumanMessage(content="How many squat reps?"), AIMessage(content="Try 8 reps.")]))
    assert result["response_content"] == "Use controlled reps."


@pytest.mark.parametrize("query", ["my name is Malak", "call me Sarah"])
def test_explicit_name_and_recall(graph, query):
    name = query.split()[-1]
    graph.db.get_assistant_memory.return_value = {}
    request = state(query)
    assert "".join(graph.stream_assistant_turn(request)) == f"Nice to meet you, {name}."
    graph.db.set_assistant_memory.assert_called_once_with("preferred_name", name)
    graph.db.get_assistant_memory.return_value = {"preferred_name": name}
    recall = state("what's my name?")
    assert "".join(graph.stream_assistant_turn(recall)) == f"You asked me to call you {name}."
    assert recall["messages"][-1].content == recall["response_content"]
    graph.llm.invoke.assert_not_called()


@pytest.mark.parametrize("query", ["how did I do in my last session?", "how was my perfomance in my last session?", "review my latest workout"])
def test_whole_session_summary(graph, query):
    graph.db.get_latest_session_summary.return_value = {
        "session_date": "2026-09-17", "split_name": "Upper", "readiness_score": 4,
        "sets_count": 3, "total_volume_kg": 900,
        "exercises": [{"name": "Bench Press", "sets": 3, "reps": 30, "volume_kg": 900}],
    }
    request = state(query)
    assert graph.router_node(request)["intent"] == "exercise_history"
    display = "".join(graph.stream_assistant_turn(request))
    assert "3 working sets, 900 kg total volume" in display
    assert "Bench Press: 3 sets, 30 total reps, 900 kg volume" in display
    assert "comparison is needed" in display
    assert display == request["response_content"] == request["messages"][-1].content
    graph.db.find_exercise_by_name.assert_not_called()
    graph.llm.invoke.assert_not_called()


def test_missing_session_is_not_an_exercise_clarification(graph):
    graph.db.get_latest_session_summary.return_value = None
    response = graph.exercise_history_node(state("my last session"))["response_content"]
    assert "don't have a logged session summary" in response
    graph.db.find_exercise_by_name.assert_not_called()


@pytest.mark.parametrize("query", ["what about leg curl", "what about the leg curl", "how about squats"])
def test_history_followup_routes_to_exercise_history(graph, comparison, query):
    request = state(query, [HumanMessage(content="how was my perfomance last session?"), AIMessage(content="Your last logged session: ...")])
    routed = graph.router_node(request)
    assert routed["intent"] == "exercise_history"
    request.update(routed)
    result = graph.assistant_graph.invoke(request)
    assert result["response_content"] == result["messages"][-1].content
    assert "Machine Leg Extension" not in result["response_content"]
    assert "Which exercise" not in result["response_content"]
    graph.llm.invoke.assert_not_called()


@pytest.mark.parametrize("query", ["what about leg curl", "what about leg extension"])
def test_history_followup_matches_catalog_when_absent_from_session(graph, comparison, query):
    graph.db.catalog_conn.cursor.return_value.fetchall.return_value = [("leg-ext", "Machine Leg Extension"), ("leg-curl", "Lying Leg Curl")]
    graph.db.get_last_performance.return_value = [{"set_index": 1, "weight_kg": 50, "reps": 10, "rpe": 8}]
    request = state(query, [HumanMessage(content="how was my perfomance last session?"), AIMessage(content="summary")])
    result = graph.assistant_graph.invoke(request)["response_content"]
    assert "No completed working sets for '" in result
    assert "latest session (2026-09-17)" in result
    assert "does not mean it was never logged" in result
    graph.db.get_last_performance.assert_not_called()


@pytest.mark.parametrize("mode", ["graph", "stream"])
def test_reported_two_turn_session_review(graph, comparison, mode):
    comparison["exercises"][0]["name"] = "Machine Leg Extension"
    comparison["exercises"][1]["name"] = "Lying Leg Curl"
    graph.db.get_compact_telemetry.return_value = "Last Session: Lower (2026-09-17) | Top: Machine Leg Extension 80kg x 3 @ RPE 9.5"

    def turn(request):
        if mode == "graph":
            return graph.assistant_graph.invoke(request)
        display = "".join(graph.stream_assistant_turn(request))
        assert display == request["response_content"]
        return request

    first = turn({**state("how was my perfomance last session?"), "telemetry_context": None})
    assert first["intent"] == "exercise_history"
    assert "Machine Leg Extension" in first["response_content"]
    assert "Lying Leg Curl" in first["response_content"]
    assert "12 working sets" in first["response_content"]
    second = turn(state("what about leg curl", first["messages"]))
    assert second["intent"] == "exercise_history"
    assert "Lying Leg Curl [ex-1]" in second["response_content"]
    assert "Set 1: 90 kg × 8 reps @ RPE 8" in second["response_content"]
    assert "Set 2: 85 kg × 10 reps @ RPE 8" in second["response_content"]
    assert "Baseline: 2026-09-11" in second["response_content"]
    assert "Machine Leg Extension" not in second["response_content"]
    graph.db.get_last_performance.assert_not_called()
    graph.llm.invoke.assert_not_called()


def test_history_followup_inherits_occurrence_scope(graph, comparison):
    graph.db.catalog_conn.cursor.return_value.fetchall.return_value = [("squat", "Squat"), ("leg-press", "Leg Press")]
    graph.db.get_last_performance.return_value = [{"set_index": 1, "weight_kg": 80, "reps": 6, "rpe": 7}]
    request = state("what about leg press", [HumanMessage(content="last logged occurrence of squat"), AIMessage(content="occurrence data")])
    result = graph.assistant_graph.invoke(request)["response_content"]
    assert "Last logged occurrence for Leg Press" in result
    graph.db.get_last_performance.assert_called_once_with("leg-press")


def test_history_followup_not_triggered_without_history_context(graph, comparison):
    graph.llm.with_structured_output = MagicMock()
    graph.llm.with_structured_output.return_value.invoke.return_value = SimpleNamespace(intent="coaching_qa")
    request = state("what about leg curl")
    assert graph.router_node(request)["intent"] == "coaching_qa"


def test_history_followup_chain_resolves_to_earliest_history_question(graph, comparison):
    request = state("what about rows", [
        HumanMessage(content="how was my perfomance last session?"),
        AIMessage(content="summary"),
        HumanMessage(content="what about bench press"),
        AIMessage(content="bench data"),
    ])
    routed = graph.router_node(request)
    assert routed["intent"] == "exercise_history"
    assert "rows" in routed["intent_metadata"]["raw_query"]


@pytest.mark.parametrize("query", ["what about upright rows", "should I swap bench press for incline press? and what about leg curl"])
def test_history_followup_defers_to_intercepts_and_compound(graph, comparison, query):
    request = state(query, [HumanMessage(content="how was my perfomance last session?"), AIMessage(content="summary")])
    intent = graph.router_node(request)["intent"]
    assert intent != "exercise_history" or query.startswith("what about upright")


def test_trainee_connection_bound_on_foreign_thread(graph, comparison, monkeypatch):
    import threading

    calls = []
    graph.db.active_user = "someone-else"

    def record_switch(user):
        calls.append(user)
        graph.db.active_user = user

    graph.db.switch_user = record_switch
    request = {**state("how did I do in my last session?"), "trainee_id": "alice"}
    outcome = {}

    def run():
        outcome["display"] = "".join(graph.stream_assistant_turn(request))

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert "Barbell Bench Press" in outcome["display"]
    assert calls == ["alice"]


def test_trainee_connection_not_reswitched_when_already_bound(graph, comparison):
    graph.db.active_user = "alice"
    graph.db.switch_user = MagicMock()
    request = {**state("how did I do in my last session?"), "trainee_id": "alice"}
    "".join(graph.stream_assistant_turn(request))
    graph.db.switch_user.assert_not_called()


def test_tail_and_nonmutation(graph):
    messages = [HumanMessage(content="old"), AIMessage(content="old answer"), HumanMessage(content="first"), HumanMessage(content="second"), AIMessage(content="a" * 900), HumanMessage(content="latest")]
    payload = graph.build_prompt_payload({"messages": [HumanMessage(content="discarded"), AIMessage(content="discarded answer")] + messages})
    assert [m.content for m in payload[1:]] == ["old", "old answer", "first", "second", "a" * 500, "latest"]
    assert len(messages[4].content) == 900


def test_pointer_filter_before_tail(graph):
    pointer = AIMessage(content="\U0001f4cb **Session Logged:** Upper (2026-09-17) | 3 Sets | Volume: 300.0 kg | Readiness: 4/5 | Saved to Ledger.")
    messages = [HumanMessage(content="session logged is what the UI says"), AIMessage(content="What question?"), pointer, HumanMessage(content="squat reps?")]
    payload = graph.build_prompt_payload({"messages": messages})
    assert [m.content for m in payload[1:]] == [messages[0].content, messages[1].content, messages[3].content]


def test_oversized_latest_is_not_truncated(graph):
    original = state("squat " * 3000)
    with pytest.raises(graph.PromptBudgetError, match="latest message"):
        graph.build_prompt_payload(original)
    assert original["messages"][-1].content == "squat " * 3000


def test_oversized_context_and_reserve(graph):
    payload = graph.build_prompt_payload({**state("squat reps?"), "telemetry_context": "x" * 20000, "custom_instructions": "y" * 20000})
    assert graph._prompt_token_count(payload) + graph.llm.max_tokens <= graph.llm.n_ctx
    assert payload[-1].content == "squat reps?"


def test_conservative_fallback_can_answer_short_request(graph):
    graph.llm.client = None
    payload = graph.build_prompt_payload(state("squat reps?"))
    assert graph._prompt_token_count(payload) + 200 <= 2048


@pytest.mark.parametrize("query,expected", [
    ("I trained 3 days this week", "coaching_qa"),
    ("Can you swap bench press for incline press?", "exercise_substitution"),
    ("Should I swap bench press for incline press?", "coaching_qa"),
    ("Can I switch my program to 3 days if work is busy?", "coaching_qa"),
    ("switch routine to 6 days", "program_mutation"),
    ("new split 4 days a week", "program_mutation"),
    ("how did my squats look", "exercise_history"),
])
def test_routes(graph, query, expected):
    graph.llm.with_structured_output = MagicMock()
    graph.llm.with_structured_output.return_value.invoke.return_value = SimpleNamespace(intent="program_mutation", target_frequency=3)
    assert graph.router_node(state(query))["intent"] == expected
    assert graph._classify_single_clause(query)["intent"] == expected


@pytest.fixture
def comparison(graph):
    def aggregate(weight, reps=8, rpe=8):
        sets = [
            {"set_index": 1, "weight_kg": weight, "reps": reps, "rpe": rpe},
            {"set_index": 2, "weight_kg": weight - 5, "reps": 10, "rpe": rpe},
        ]
        return {"sets": sets, "sets_count": 2, "total_reps": reps + 10, "volume_kg": weight * reps + (weight - 5) * 10, "best_set": sets[0], "e1rm": weight * 1.4 if rpe is not None else None}

    session = {"id": "latest", "session_date": "2026-09-17", "started_at": "2026-09-17T10:00:00", "split_name": "Upper", "readiness_score": 4, "session_notes": "Rested"}
    context = {"best_set_convention": "heaviest weight, then most reps, then earliest set_index", "session": session, "previous_session": {**session, "id": "previous", "session_date": "2026-09-16"}, "exercises": []}
    for index, (name, status) in enumerate([
        ("Barbell Bench Press", "improvement"), ("Cable Row", "unchanged"),
        ("Dumbbell Curl", "mixed"), ("Cable Lateral Raise", "decline"),
        ("Triceps Extension", "insufficient_data"), ("Reverse Fly", "insufficient_data"),
    ]):
        rpe = None if index == 4 else 8
        current = aggregate(100 - index * 10, rpe=rpe)
        previous = aggregate(95 - index * 10, rpe=rpe) if index != 5 else None
        if previous:
            previous["session"] = {**session, "id": f"baseline-{index}", "session_date": f"2026-09-{10 + index}"}
        context["exercises"].append({
            "exercise_id": f"ex-{index}", "name": name, "current": current, "previous": previous,
            "deltas": {"load_kg": 5, "reps": 0, "sets": 0, "volume_kg": 90, "e1rm": 7 if rpe else None} if previous else dict.fromkeys(["load_kg", "reps", "sets", "volume_kg", "e1rm"]),
            "status": status,
        })
    graph.db.get_session_comparison_context.return_value = context
    return context


@pytest.mark.parametrize("query", [
    "how did I do in my last session?", "show all exercises in my last session",
    "compare to previous session", "compare my last session to previous session",
    "review my last session compared with the previous workout",
])
@pytest.mark.parametrize("mode", ["graph", "stream"])
def test_comparison_all_exercises_deterministic(graph, comparison, query, mode):
    request = state(query)
    if mode == "graph":
        result = graph.assistant_graph.invoke(request)
        display = result["response_content"]
        assert result["messages"][-1].content == display
    else:
        display = "".join(graph.stream_assistant_turn(request))
        assert display == request["response_content"] == request["messages"][-1].content
    for exercise in comparison["exercises"]:
        assert exercise["name"] in display
        if exercise["previous"]:
            assert exercise["previous"]["session"]["session_date"] in display
    assert display.count("Set 2:") == 6
    assert "100 kg × 8 reps @ RPE 8" in display
    assert "best load +5 kg" in display
    assert "RPE missing" in display
    assert "Baseline: missing previous occurrence" in display
    assert "12 working sets" in display
    assert "Readiness: 4/5" in display
    graph.llm.invoke.assert_not_called()
    graph.db.get_latest_session_summary.assert_not_called()
    graph.db.get_last_performance.assert_not_called()


@pytest.mark.parametrize("target", ["barbell bench press", "ex-0", "bench press"])
def test_exercise_latest_scope_uses_current_ids_first(graph, comparison, target):
    request = state(f"how did I do on {target} last session?")
    result = graph.assistant_graph.invoke(request)["response_content"]
    assert "Barbell Bench Press [ex-0]" in result
    assert "Set 1: 100 kg × 8 reps @ RPE 8" in result
    assert "Set 2: 95 kg × 10 reps @ RPE 8" in result
    assert "Baseline: 2026-09-10" in result
    assert "best load +5 kg" in result
    assert "Cable Row" not in result
    graph.db.catalog_conn.cursor.assert_not_called()
    graph.db.find_exercise_by_name.assert_not_called()
    graph.db.get_last_performance.assert_not_called()


@pytest.mark.parametrize("target", ["incline barbell bench press", "squat", "bench pres"])
def test_latest_scope_never_substitutes_old_or_wrong_variant(graph, comparison, target):
    graph.db.catalog_conn.cursor.return_value.fetchall.return_value = [("old", "Incline Barbell Bench Press"), ("squat", "Squat")]
    graph.db.get_last_performance.return_value = [{"set_index": 1, "weight_kg": 900, "reps": 10, "rpe": 8}]
    result = graph.exercise_history_node(state(f"how did I do on {target} last session?"))["response_content"]
    assert "No completed working sets" in result
    assert "latest session (2026-09-17)" in result
    assert "900" not in result
    graph.db.get_last_performance.assert_not_called()


@pytest.mark.parametrize("duplicate_name", ["Incline Barbell Bench Press", "Barbell Bench Press"])
def test_ambiguous_current_variants_require_id(graph, comparison, duplicate_name):
    comparison["exercises"].append({**comparison["exercises"][0], "exercise_id": "other", "name": duplicate_name})
    result = graph.exercise_history_node(state("how did I do on bench press last session?"))["response_content"]
    assert "Which exercise variant" in result
    assert "[ex-0]" in result and "[other]" in result
    graph.db.get_last_performance.assert_not_called()


@pytest.mark.parametrize("query", ["compare my last session to last month", "how did I do on bench press yesterday", "compare between 2026-09-01 and 2026-09-10", "how did I do on squat over time"])
def test_unsupported_history_dates_are_truthful(graph, comparison, query):
    result = graph.exercise_history_node(state(query))["response_content"]
    assert "requested time period is unavailable" in result
    graph.db.get_last_performance.assert_not_called()


def test_explicit_older_occurrence_is_labeled(graph, comparison):
    graph.db.catalog_conn.cursor.return_value.fetchall.return_value = [("squat", "Squat")]
    graph.db.get_last_performance.return_value = [{"set_index": 1, "weight_kg": 80, "reps": 6, "rpe": None}]
    result = graph.exercise_history_node(state("last logged occurrence of squat"))["response_content"]
    assert "Last logged occurrence for Squat" in result
    assert "may predate your latest session" in result
    assert "RPE missing" in result
    assert "no progress assessment" in result
    graph.db.get_last_performance.assert_called_once_with("squat")


def test_comparison_hydration_followup_and_budget(graph, comparison):
    request = state("what should I focus on next?", [HumanMessage(content="review my last session"), AIMessage(content="Recorded exercises reviewed.")])
    request.update(graph.hydrate_context_node(request))
    for exercise in comparison["exercises"]:
        assert exercise["name"] in request["telemetry_context"]
    assert "baseline=2026-09-10" in request["telemetry_context"]
    assert "RPE missing" in request["telemetry_context"]
    payload = graph.build_prompt_payload(request)
    assert graph.TAIL_WINDOW_SIZE == 6
    assert graph._prompt_token_count(payload) + graph.llm.max_tokens <= graph.llm.n_ctx
    for exercise in comparison["exercises"]:
        assert exercise["name"] in payload[0].content
    assert payload[-1].content == "what should I focus on next?"


def test_comparison_empty_working_sets(graph, comparison):
    comparison["exercises"] = []
    result = graph.assistant_graph.invoke(state("my last session"))["response_content"]
    assert "0 working sets" in result
    assert "No completed working sets" in result
    assert "no progress assessment" in result


@pytest.mark.parametrize("missing_side", ["current", "previous"])
def test_comparison_missing_rpe_never_asserts_progress(graph, comparison, missing_side):
    exercise = comparison["exercises"][0]
    exercise[missing_side]["sets"][0]["rpe"] = None
    result = graph.exercise_history_node(state("how did I do on bench press last session?"))["response_content"]
    assert "RPE missing" in result
    assert "status: insufficient_data" in result
    assert "Status: improvement" not in result
