"""Program routing contracts at the hosted chat-turn seam (#527, ADR 105).

The real ledger/tool readers feed a network-free model; no router unit seam.
"""

import json
import logging

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from agent import assistant_graph, player_prompt
from agent.ProgramState import (
    PersistedProgramDaySchema, PersistedProgramExerciseSchema, PersistedProgramSchema,
)
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn
from tests.test_player_chat_privacy import (
    _assigned_player, _authed, _done_content, _force_free_form_coaching_intent, _register,
)


def _save_router_program(ledger, publisher=None):
    prescriptions = [
        ("Push A", [("dbp", "Dumbbell Bench Press", 2), ("bc", "Biceps Curl", 3),
                    ("tp", "Triceps Pushdown", 2)]),
        ("Lower A", [("sq", "Squat", 4), ("bc", "Biceps Curl", 2)]),
        ("Tuesday", [("row", "Row", 3), ("tp", "Triceps Pushdown", 3)]),
        ("Lower B", [("lc", "Leg Curl", 3)]),
    ]
    program = PersistedProgramSchema(
        program_name="ROUTER_PRIVATE_PROGRAM", split_type="Upper Lower", weekly_frequency=4,
        days=[PersistedProgramDaySchema(
            day_name=name, day_order=order, exercises=[PersistedProgramExerciseSchema(
                exercise_id=exercise_id, exercise_name=exercise_name, target_sets=sets,
                target_reps_min=8, target_reps_max=12, target_rpe=8,
            ) for exercise_id, exercise_name, sets in exercises],
        ) for order, (name, exercises) in enumerate(prescriptions, start=1)],
    )
    ledger.save_training_program(program.model_dump(), published_by_coach_account_id=publisher)
    ledger.upsert_player_profile({"age": 39, "current_goal": "ROUTER_PRIVATE_GOAL",
                                  "injuries_or_limitations": "ROUTER_PRIVATE_INJURY"})


@pytest.fixture
def router_player(api):
    client, db = api
    username = "router-player"
    headers = _authed(_register(client, username)["access_token"])
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES (?, ?, ?, ?)",
        [("dbp", "Dumbbell Bench Press", "Chest", "Chest"),
         ("bc", "Biceps Curl", "Upper Arms", "Biceps"),
         ("tp", "Triceps Pushdown", "Upper Arms", "Triceps"),
         ("lc", "Leg Curl", "Upper Legs", "Hamstrings"),
         ("ibp", "Incline Bench Press", "Chest", "Chest")],
    )
    db.catalog_conn.executemany(
        "INSERT INTO exercise_aliases (exercise_id, alias, normalized_alias) VALUES (?, ?, ?)",
        [("ibp", "incline press", "incline press"), ("bp", "bench", "bench")],
    )
    db.catalog_conn.commit()
    with db.open_ledger(username) as ledger:
        _save_router_program(ledger)
    return client, db, headers


def _simulated_reads(model):
    messages = model.calls[0]["messages"]
    calls = [call for message in messages for call in getattr(message, "tool_calls", [])]
    results = [message for message in messages if isinstance(message, ToolMessage)]
    assert [message.tool_call_id for message in results] == [call["id"] for call in calls]
    assert all(call["name"] == "get_active_program" for call in calls)
    return calls, [json.loads(message.content) for message in results]


# Includes the #523 production failure: weekly bi + tri sets without a model tool round.
@pytest.mark.parametrize(("question", "scopes", "exercise_names"), [
    ("How many sets for biceps?", [{"muscle": "biceps"}], {"Biceps Curl"}),
    ("How many sets per week for bi and tri?", [{"muscle": "biceps"}, {"muscle": "triceps"}],
     {"Biceps Curl", "Triceps Pushdown"}),
    ("What are my quads sets?", [{"muscle": "quads"}], {"Squat"}),
    ("What's on Push A?", [{"day_name": "Push A"}],
     {"Dumbbell Bench Press", "Biceps Curl", "Triceps Pushdown"}),
    ("What's on leg day?", [{"day_name": "Lower A"}, {"day_name": "Lower B"}],
     {"Squat", "Biceps Curl", "Leg Curl"}),
    ("What's my bench prescription?", [{"exercise_id": "dbp"}], {"Dumbbell Bench Press"}),
    ("What's my Incline Bench Press prescription?", [{"exercise_id": "ibp"}], set()),
    ("What are my reps for incline press?", [{"exercise_id": "ibp"}], set()),
    ("What's on Tuesday?", [{"day_name": "Tuesday"}], {"Row", "Triceps Pushdown"}),
    ("How's my program?", [{}], set()),
    ("How often do I train?", [{}], set()),
    ("كام سيتات للباي والتراي في الاسبوع؟", [{"muscle": "biceps"}, {"muscle": "triceps"}],
     {"Biceps Curl", "Triceps Pushdown"}),
    ("بتمرن كام مجموعة باي؟", [{"muscle": "biceps"}], {"Biceps Curl"}),
    ("تمارين يوم الرجل ايه؟", [{"day_name": "Lower A"}, {"day_name": "Lower B"}],
     {"Squat", "Biceps Curl", "Leg Curl"}),
    ("البنش كام عدة؟", [{"exercise_id": "dbp"}], {"Dumbbell Bench Press"}),
    ("تمارين التلات ايه؟", [{"day_name": "Tuesday"}], {"Row", "Triceps Pushdown"}),
    ("برنامجي عامل ازاي؟", [{}], set()),
    ("وريني تمارين يوم الجزء العلوي", [{"day_name": "Push A"}, {"day_name": "Tuesday"}],
     {"Dumbbell Bench Press", "Biceps Curl", "Triceps Pushdown", "Row"}),
    ("How many biceps sets on Lower A?", [{"day_name": "Lower A", "muscle": "biceps"}],
     {"Biceps Curl"}),
])
def test_program_questions_arrive_scoped_before_first_model_answer(
    router_player, monkeypatch, question, scopes, exercise_names,
):
    client, _db, headers = router_player
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["Your Program facts are available."])
    monkeypatch.setattr(assistant_graph, "llm", model)

    response = client.post("/chat/messages", headers=headers, json={"content": question})

    assert response.status_code == 200
    assert _done_content(response.text) == "Your Program facts are available."
    assert len(model.calls) == 1  # The ticket's one-model-call latency contract.
    calls, results = _simulated_reads(model)
    assert [call["args"] for call in calls] == scopes
    assert all(len(message.content.encode("utf-8")) <= 4 * 1024
               for message in model.calls[0]["messages"] if isinstance(message, ToolMessage))
    assert {exercise["name"] for result in results for day in result["days"]
            for exercise in day.get("exercises", [])} == exercise_names
    if scopes == [{}]:
        assert results[0]["weekly_sets_by_muscle"]["biceps"] == 5
        assert results[0]["weekly_sets_by_muscle"]["triceps"] == 5
    elif scopes == [{"muscle": "biceps"}, {"muscle": "triceps"}]:
        assert [sum(exercise["sets"] for day in result["days"] for exercise in day["exercises"])
                for result in results] == [5, 5]
    payload = "\n".join(str(message.content) for message in model.calls[0]["messages"])
    assert "ROUTER_PRIVATE_GOAL" not in payload
    assert "ROUTER_PRIVATE_INJURY" not in payload
    assert "get_active_program" in model.calls[0]["tools"]


def test_router_keeps_system_bytes_fixed_and_fallback_tools_bound(router_player, monkeypatch, caplog):
    client, _db, headers = router_player
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel([
        "Five working sets.",
        ToolCallsTurn(calls=[{"name": "get_active_program", "args": {"muscle": "triceps"},
                              "id": "fallback-triceps"}]),
        "Five working sets for triceps too.",
    ])
    monkeypatch.setattr(assistant_graph, "llm", model)
    with caplog.at_level(logging.INFO):
        first = client.post("/chat/messages", headers=headers,
                            json={"content": "How many sets for biceps?"})
        second = client.post("/chat/messages", headers=headers,
                             json={"content": "How many sets for triceps?"})
    assert _done_content(first.text) == "Five working sets."
    assert _done_content(second.text) == "Five working sets for triceps too."
    assert model.calls[0]["messages"][0].content == model.calls[1]["messages"][0].content
    assert model.calls[0]["tools"] == model.calls[1]["tools"]
    assert any(getattr(message, "tool_call_id", "") == "fallback-triceps"
               for message in model.calls[2]["messages"])
    events = [record.getMessage() for record in caplog.records if "Context router topics=" in record.getMessage()]
    assert len(events) == 2
    assert "program_what_how_many" in events[0] and "program.muscle" in events[0]
    assert "model_fetched_more=False" in events[0]
    assert "model_fetched_more=True" in events[1]
    for private in ("biceps", "triceps", "Biceps Curl", "Triceps Pushdown", "router-player", "args", "5"):
        assert private not in "\n".join(events)


def test_day_named_for_muscles_includes_its_other_exercises(router_player, monkeypatch):
    client, db, headers = router_player
    with db.open_ledger("router-player") as ledger:
        program = ledger.get_active_program()
        program.days[0].day_name = "Chest & Back"
        ledger.save_training_program(program.model_dump())
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["The day also includes arms."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    response = client.post("/chat/messages", headers=headers, json={"content": "What's on Chest & Back?"})
    assert _done_content(response.text) == "The day also includes arms."
    calls, results = _simulated_reads(model)
    assert [call["args"] for call in calls] == [{"day_name": "Chest & Back"}]
    assert {exercise["name"] for exercise in results[0]["days"][0]["exercises"]} == {
        "Dumbbell Bench Press", "Biceps Curl", "Triceps Pushdown",
    }


def test_weekday_without_program_label_does_not_invent_schedule_mapping(router_player, monkeypatch):
    client, db, headers = router_player
    with db.open_ledger("router-player") as ledger:
        ledger.append_training_schedule(ledger.ledger_id, [1, 2, 4, 6], "UTC",
                                        "2026-01-01", "2026-01-01T00:00:00+00:00")
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["Your Program has no day named Monday."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    response = client.post("/chat/messages", headers=headers, json={"content": "What's on Monday?"})
    assert _done_content(response.text) == "Your Program has no day named Monday."
    _calls, results = _simulated_reads(model)
    assert results == [{"status": "not_found", "day_names": ["Push A", "Lower A", "Tuesday", "Lower B"]}]


def test_no_program_is_reported_before_model_answers(api, monkeypatch):
    client, _db = api
    headers = _authed(_register(client, "router-no-program")["access_token"])
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["You have no active Program."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    response = client.post("/chat/messages", headers=headers, json={"content": "How's my program?"})
    assert _done_content(response.text) == "You have no active Program."
    _calls, results = _simulated_reads(model)
    assert results == [{"status": "not_set", "active_program": "not set", "program_authority": "player"}]


def test_coach_program_router_retains_authority(router_player, monkeypatch):
    client, db, _headers = router_player
    _coach_headers, headers, _assignment = _assigned_player((client, db), "router-coached")
    coach_id = db.get_active_account_by_username("coach")["account_id"]
    with db.open_ledger("router-coached") as ledger:
        _save_router_program(ledger, coach_id)
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["Your Coach holds Program authority."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    response = client.post("/chat/messages", headers=headers, json={"content": "What's on Push A?"})
    assert _done_content(response.text) == "Your Coach holds Program authority."
    _calls, results = _simulated_reads(model)
    assert results[0]["program_authority"] == "coach"
    assert results[0]["coach"]


@pytest.mark.parametrize("question", [
    "My knee has sharp pain on squats, how many sets for quads?",
    "ركبتي بتوجعني وانا بعمل سكوات، كام مجموعة للكواد؟",
    "remember that I prefer 3 sets for biceps",
    "change squat to 3 sets on leg days",
])
def test_safety_and_deterministic_writes_never_enter_context_router(router_player, monkeypatch, caplog, question):
    client, db, headers = router_player
    model = ScriptedChatModel(default_turn="UNEXPECTED HOSTED CALL")
    monkeypatch.setattr(assistant_graph, "llm", model)
    with caplog.at_level(logging.INFO):
        response = client.post("/chat/messages", headers=headers, json={"content": question})
    assert response.status_code == 200
    assert _done_content(response.text) != "UNEXPECTED HOSTED CALL"
    assert not model.calls
    assert not any("Context router topics=" in record.getMessage() for record in caplog.records)
    if question.startswith("remember"):
        with db.open_ledger("router-player") as ledger:
            assert ledger.list_assistant_preferences()[0]["text"] == "I prefer 3 sets for biceps"
    elif question.startswith("change"):
        assert '"program_edit_preview"' in response.text
        with db.open_ledger("router-player") as ledger:
            assert ledger.get_pending_chat_program_edit() is not None
    else:
        expected = (assistant_graph.CLINICAL_SAFEGUARD_RESPONSE if question.startswith("My")
                    else assistant_graph.ARABIC_CLINICAL_SAFEGUARD_RESPONSE)
        assert _done_content(response.text).startswith(expected)


def test_router_drops_pieces_that_do_not_fit_prompt_reserve(router_player, monkeypatch, caplog):
    client, db, headers = router_player
    _force_free_form_coaching_intent(monkeypatch)
    with db.open_ledger("router-player") as ledger:
        for _ in range(9):
            ledger.add_chat_message("assistant", "Earlier answer. " + "x" * 2_900)
    model = ScriptedChatModel(["Please narrow the question."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    with caplog.at_level(logging.INFO):
        response = client.post("/chat/messages", headers=headers,
                               json={"content": "What are my sets for bi and tri on leg days?"})
    assert _done_content(response.text) == "Please narrow the question."
    messages = model.calls[0]["messages"]
    calls, _results = _simulated_reads(model)
    # Smaller empty scopes may fit even when the requested prescriptions do not.
    assert len(calls) < 4
    call_bytes = sum(len(json.dumps(call, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                     for call in calls)
    assert sum(len(str(message.content).encode("utf-8")) for message in messages) + call_bytes <= (
        player_prompt.HOSTED_PROMPT_MAX_BYTES - player_prompt.HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES
    )
    assert any("topics=program_what_how_many" in record.getMessage() for record in caplog.records)


def test_buffered_generation_also_receives_scoped_program_before_model(router_player, monkeypatch):
    _client, db, _headers = router_player
    model = ScriptedChatModel(["Five working sets."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    with db.open_ledger("router-player") as ledger:
        response = assistant_graph.generation_node(
            {"messages": [HumanMessage(content="How many sets for bi?")]},
            {"configurable": {"ledger": ledger, "store": db}},
        )
    assert response["response_content"] == "Five working sets."
    calls, results = _simulated_reads(model)
    assert calls[0]["args"] == {"muscle": "biceps"}
    assert sum(exercise["sets"] for day in results[0]["days"] for exercise in day["exercises"]) == 5


@pytest.mark.parametrize("intent", ["exercise_history", "exercise_history_fallback"])
def test_buffered_history_intents_do_not_receive_program_prescriptions(router_player, monkeypatch, intent):
    _client, db, _headers = router_player
    model = ScriptedChatModel(["That history is unavailable."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    with db.open_ledger("router-player") as ledger:
        response = assistant_graph.generation_node(
            {"intent": intent, "messages": [HumanMessage(content="How much did I lift for Squat?")]},
            {"configurable": {"ledger": ledger, "store": db}},
        )
    assert response["response_content"] == "That history is unavailable."
    assert not any(isinstance(message, ToolMessage) for message in model.calls[0]["messages"])
    assert "get_active_program" in model.calls[0]["tools"]


def test_multiple_large_unicode_day_pieces_respect_total_budget(router_player, monkeypatch):
    client, db, headers = router_player
    with db.open_ledger("router-player") as ledger:
        program = ledger.get_active_program()
        for index, day in enumerate(program.days):
            day.exercises = [day.exercises[0]]
            exercise = day.exercises[0]
            db.catalog_conn.execute(
                "INSERT INTO exercise_display_names (exercise_id, display_name, is_reviewed) VALUES (?, ?, 1) "
                "ON CONFLICT(exercise_id) DO UPDATE SET display_name = excluded.display_name, is_reviewed = 1",
                (exercise.exercise_id, "تمرين" * 220 + str(index)),
            )
        db.catalog_conn.commit()
        ledger.save_training_program(program.model_dump())
        assert all(len(day.exercises[0].exercise_name.encode("utf-8")) > 2_000
                   for day in ledger.get_active_program().days)
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["The remaining days are available on request."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    response = client.post("/chat/messages", headers=headers, json={
        "content": "What are my exercises on Push A, Lower A, Tuesday and Lower B?",
    })
    assert _done_content(response.text) == "The remaining days are available on request."
    calls, results = _simulated_reads(model)
    assert 0 < len(calls) < 4
    assert all(result["status"] == "ok" for result in results)
    tool_bytes = [len(message.content.encode("utf-8")) for message in model.calls[0]["messages"]
                  if isinstance(message, ToolMessage)]
    assert max(tool_bytes) <= 4 * 1024
    call_bytes = sum(len(json.dumps(call, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                     for call in calls)
    assert sum(tool_bytes) + call_bytes <= 8 * 1024
    assert "get_active_program" in model.calls[0]["tools"]
