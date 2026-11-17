import pytest
from langchain_core.messages import HumanMessage

from agent import clinical_guard
from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from agent.assistant_graph import router_node, stream_assistant_turn
from tests.fakes.chat_model import ScriptedChatModel

ARABIC_SWAP_CLARIFICATION = "أنهي تمرين عايز تغيّره؟"
ARABIC_ONE_AT_A_TIME_NOTE = "هبدّل التمرين ده الأول، وبعدها قولي تحب أساعدك في إيه كمان؟"
COACHING_REPLY = "خد راحة كفاية حسب إحساسك، وخلّي مجهودك مناسب لحالتك."


def _seed_program(store, *, duplicate_bench=False, exercise_names=None, day_name="Full Body A"):
    names = exercise_names or ["barbell bench press", "barbell squat", "barbell row"]
    if duplicate_bench:
        names.append("dumbbell bench press")
    return _seed_program_days(store, {day_name: names})


def _seed_program_days(store, day_exercise_names):
    ledger = store.ledger
    ledger.upsert_player_profile({"weekly_frequency": 3, "equipment_access": "Commercial gym"})
    days = []
    for day_order, (day_name, names) in enumerate(day_exercise_names.items(), start=1):
        exercises = []
        for name in names:
            matches = store.find_exercises_by_name(name, limit=1)
            assert matches
            entry = store.get_exercise_library_entry(str(matches[0]["id"]))
            exercises.append(
                ProgramExerciseSchema(
                    exercise_id=str(entry["id"]),
                    exercise_name=entry["name"],
                    target_reps_min=6,
                    target_reps_max=10,
                )
            )
        days.append(
            ProgramDaySchema(day_name=day_name, day_order=day_order, exercises=exercises)
        )
    program = GeneratedProgramSchema(
        program_name="Arabic swap day test program",
        split_type="Full Body",
        weekly_frequency=3,
        days=days,
    )
    ledger.save_training_program(program.model_dump())
    return ledger.get_active_program()


def test_issue_738_explicit_arabic_curl_swap_uses_the_substitution_path(fresh_store, monkeypatch):
    before = _seed_program(
        fresh_store,
        exercise_names=["Preacher Curl (Barbell)", "barbell bench press", "barbell row"],
    )
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel([{"intent": "coaching_qa"}]))
    state = _turn("بدل Preacher Curl (Barbell) بـ Incline Curl (Dumbbell)")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Incline Curl (Dumbbell)" in names
    assert "Preacher Curl (Barbell)" not in names
    assert "Program tab" not in response


def test_issue_738_english_curl_swap_uses_the_substitution_path(fresh_store, monkeypatch):
    before = _seed_program(
        fresh_store,
        exercise_names=["Preacher Curl (Barbell)", "barbell bench press", "barbell row"],
    )

    class ClinicalEmbedder:
        def embed_query(self, _text):
            return clinical_guard.CLINICAL_ANCHOR_VECTORS[0]

    monkeypatch.setattr(clinical_guard, "EMBED_MODEL", ClinicalEmbedder())
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel())
    state = _turn("swap Preacher Curl (Barbell) for Incline Curl (Dumbbell)")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Incline Curl (Dumbbell)" in names
    assert "Preacher Curl (Barbell)" not in names
    assert "Program tab" not in response


def test_issue_738_franco_curl_swap_uses_the_substitution_path(fresh_store, monkeypatch):
    before = _seed_program(
        fresh_store,
        exercise_names=["Preacher Curl (Barbell)", "barbell bench press", "barbell row"],
    )
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel())
    state = _turn("3ayez abadel Preacher Curl (Barbell) bel Incline Curl (Dumbbell)")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Incline Curl (Dumbbell)" in names
    assert "Preacher Curl (Barbell)" not in names
    assert "Program tab" not in response


@pytest.mark.parametrize(
    "query",
    [
        "swap Preacher Curl (Barbell) for Incline Curl (Dumbbell) on Pull day",
        "بدل Preacher Curl (Barbell) بـ Incline Curl (Dumbbell) يوم Pull",
    ],
)
def test_issue_738_day_qualified_swap_validates_target_and_updates_program(
    fresh_store, monkeypatch, query
):
    before = _seed_program(
        fresh_store,
        exercise_names=["Preacher Curl (Barbell)", "barbell bench press", "barbell row"],
        day_name="Pull",
    )
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel())
    state = _turn(query)

    response = "".join(
        stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store)
    )

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Incline Curl (Dumbbell)" in names
    assert "Preacher Curl (Barbell)" not in names
    assert "Pull" in response


def test_issue_738_arabic_day_swap_does_not_find_source_on_another_day(
    fresh_store, monkeypatch
):
    before = _seed_program_days(
        fresh_store,
        {
            "Pull": ["barbell bench press", "barbell row", "barbell squat"],
            "Push": ["Preacher Curl (Barbell)", "barbell squat", "barbell row"],
        },
    )
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel())
    state = _turn(
        "\u0628\u062f\u0644 Preacher Curl (Barbell) \u0628\u0640 Incline Curl (Dumbbell) \u064a\u0648\u0645 Pull"
    )

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "arabic_swap_clarification"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert any(ex.exercise_name == "Preacher Curl (Barbell)" for ex in after.days[1].exercises)
    assert "Incline Curl (Dumbbell)" not in {
        ex.exercise_name for day in after.days for ex in day.exercises
    }


def test_issue_738_arabic_day_swap_selects_the_named_pull_day(
    fresh_store, monkeypatch
):
    before = _seed_program_days(
        fresh_store,
        {
            "Pull A": [
                "Preacher Curl (Barbell)",
                "Incline Curl (Dumbbell)",
                "barbell row",
            ],
            "Pull B": [
                "Preacher Curl (Barbell)",
                "barbell bench press",
                "barbell squat",
            ],
        },
    )
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel())
    state = _turn(
        "\u0628\u062f\u0644 Preacher Curl (Barbell) \u0628\u0640 Incline Curl (Dumbbell) \u064a\u0648\u0645 Pull B"
    )

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    pull_a_names = {ex.exercise_name for ex in after.days[0].exercises}
    pull_b_names = {ex.exercise_name for ex in after.days[1].exercises}
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Preacher Curl (Barbell)" in pull_a_names
    assert "Incline Curl (Dumbbell)" in pull_a_names
    assert "Preacher Curl (Barbell)" not in pull_b_names
    assert "Incline Curl (Dumbbell)" in pull_b_names


def test_issue_738_day_name_does_not_hide_following_injury_prose(
    fresh_store, monkeypatch
):
    _seed_program(
        fresh_store,
        exercise_names=["Preacher Curl (Barbell)", "barbell bench press", "barbell row"],
        day_name="Pull",
    )

    class ClinicalEmbedder:
        def embed_query(self, _text):
            return clinical_guard.CLINICAL_ANCHOR_VECTORS[0]

    monkeypatch.setattr(clinical_guard, "EMBED_MODEL", ClinicalEmbedder())
    result = router_node(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "\u0628\u062f\u0644 Preacher Curl (Barbell) "
                        "\u0628\u0640 Incline Curl (Dumbbell) \u064a\u0648\u0645 Pull "
                        "because my knee is killing me"
                    )
                )
            ],
            "telemetry_context": "",
        },
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == "clinical_intercept"


def _turn(message):
    return {
        "messages": [HumanMessage(content=message)],
        "trainee_id": "arabic_swap_test",
        "player_account_id": None,
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }


def test_standard_arabic_swap_resolves_classifier_natural_names(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Barbell Bench Press",
                "target_exercise": "Dumbbell Bench Press",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("استبدل تمرين Barbell Bench Press بتمرين Dumbbell Bench Press.")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in names
    assert "Bench Press (Barbell)" not in names
    classifier_prompt = model.calls[0]["messages"][0].content
    assert "Current Training program exercise names:" in classifier_prompt
    assert "Bench Press (Barbell)" in classifier_prompt
    assert "arabic_swap_test" not in classifier_prompt


def test_egyptian_bench_request_resolves_single_program_match(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Bench Press",
                "target_exercise": "Dumbbell Bench Press",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش بالدامبل.")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in names
    assert "Bench Press (Barbell)" not in names


def test_egyptian_incline_request_resolves_library_style_target(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Bench Press (Barbell)",
                "target_exercise": "Incline Bench Press (Barbell)",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("عايز أبدّل البنش بضغط مائل بالبار.")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Incline Bench Press (Barbell)" in names
    assert "Bench Press (Barbell)" not in names


def test_leg_press_target_matches_the_english_named_target_path(fresh_store, monkeypatch):
    from agent.assistant_graph import exercise_substitution_node

    before = _seed_program(fresh_store)
    original_names = {
        exercise.exercise_name
        for day in before.days
        for exercise in day.exercises
    }
    english_state = _turn("swap Back Squat (Barbell) for Leg Press")
    english_state["intent"] = "exercise_substitution"
    english_state["intent_metadata"] = {
        "mode": "direct_swap",
        "source_exercise": "Back Squat (Barbell)",
        "target_exercise": "Leg Press",
    }
    exercise_substitution_node(
        english_state,
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )
    english_program = fresh_store.ledger.get_active_program()
    english_target = next(
        exercise.exercise_name
        for exercise in english_program.days[0].exercises
        if exercise.exercise_name not in original_names
    )

    before = _seed_program(fresh_store)
    original_names = {
        exercise.exercise_name
        for day in before.days
        for exercise in day.exercises
    }
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Back Squat (Barbell)",
                "target_exercise": "Leg Press",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    arabic_state = _turn("بدّل السكوات بالليج برس.")
    list(stream_assistant_turn(arabic_state, ledger=fresh_store.ledger, store=fresh_store))
    arabic_program = fresh_store.ledger.get_active_program()
    arabic_target = next(
        exercise.exercise_name
        for exercise in arabic_program.days[0].exercises
        if exercise.exercise_name not in original_names
    )

    assert english_target == arabic_target
    assert english_target == "45° Leg Press (Plate-Loaded)"
    assert arabic_state["program_updated"] is True


def test_arabic_target_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Bench Press (Barbell)",
                "target_exercise": "دامبل",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش بالدامبل.")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "arabic_swap_clarification"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert "Bench Press (Barbell)" in names
    assert response == ARABIC_SWAP_CLARIFICATION


def test_ar_mixed_03_suggestion_never_executes_scripted_swap(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Back Squat (Barbell)",
                "target_exercise": "Goblet Squat",
                "has_swap": True,
            },
            COACHING_REPLY,
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("الـ squat مش مريح، can you suggest a safer alternative?")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "coaching_qa"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert names == [
        exercise.exercise_name for exercise in before.days[0].exercises
    ]
    assert "45° Leg Press (Plate-Loaded)" not in names
    assert response == COACHING_REPLY


def test_ar_mixed_03_mismatched_name_hit_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    leg_press = fresh_store.find_exercises_by_name("Leg Press", limit=1)[0]
    original_search = fresh_store.find_exercises_by_name

    def name_search(name, *args, **kwargs):
        if name == "Goblet Squat":
            return [leg_press]
        return original_search(name, *args, **kwargs)

    monkeypatch.setattr(fresh_store, "find_unique_exercise_id_by_exact_name", lambda _name: None)
    monkeypatch.setattr(fresh_store, "find_exercises_by_name", name_search)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Back Squat (Barbell)",
                "target_exercise": "Goblet Squat",
                "has_swap": True,
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل السكوات ب Goblet Squat.")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "arabic_swap_clarification"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert "45° Leg Press (Plate-Loaded)" not in {exercise.exercise_name for exercise in after.days[0].exercises}
    assert response == ARABIC_SWAP_CLARIFICATION


def test_arabic_composite_swap_and_weight_progression_question_stays_composite(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "composite_intent",
                "source_exercise": "Bench Press (Barbell)",
                "target_exercise": "Dumbbell Bench Press",
                "has_swap": True,
                "has_additional_request": True,
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش بالدامبل. وقولّي أزوّد الوزن إمتى؟")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "composite_intent"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert names.count("Bench Press (Dumbbell)") == 1
    assert "Bench Press (Barbell)" not in names


def test_preferred_name_request_stays_deterministic_before_arabic_classification(
    fresh_store, monkeypatch
):
    _seed_program(fresh_store)
    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("ناديني سلمى")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["intent"] == "telemetry_intercept"
    assert fresh_store.ledger.get_assistant_memory()["preferred_name"] == "سلمى"
    assert response == "تمام، هناديك سلمى."


def test_ambiguous_source_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store, duplicate_bench=True)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Bench Press",
                "target_exercise": "Incline Bench Press",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "arabic_swap_clarification"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert response == ARABIC_SWAP_CLARIFICATION


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        ("أريح قد إيه بين المجموعات؟", {"intent": "coaching_qa"}),
        ("أتمرن النهارده ولا أريح؟ رجلي مرهقة من تمرين امبارح.", {"intent": "coaching_qa"}),
        ("سؤال تاني عن النادي.", {"intent": "other"}),
    ],
)
def test_arabic_coaching_questions_get_normal_coaching_answer(
    fresh_store, monkeypatch, message, classification
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([classification, COACHING_REPLY])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "coaching_qa"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert response == COACHING_REPLY


def test_composite_swap_executes_once_and_handles_the_other_request_later(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "composite_intent",
                "has_swap": True,
                "source_exercise": "Barbell Bench Press",
                "target_exercise": "Dumbbell Bench Press",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل البنش بالدامبل وقولّي عملت إيه في السكوات")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "composite_intent"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in names
    assert "Back Squat (Barbell)" in names
    assert ARABIC_ONE_AT_A_TIME_NOTE in response


def test_unresolved_swap_target_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Barbell Bench Press",
                "target_exercise": "Imaginary Press",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("عايز أبدّل البنش بتمرين تاني")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "arabic_swap_clarification"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert response == ARABIC_SWAP_CLARIFICATION


def test_english_swap_with_arabic_politeness_keeps_the_english_route(monkeypatch):
    from agent.assistant_graph import router_node

    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    routed = router_node(
        {"messages": [HumanMessage(content="swap bench press for dumbbell press يا كابتن")]}
    )

    assert routed["intent"] == "exercise_substitution"
    assert "arabic_data_validated" not in routed["intent_metadata"]


@pytest.mark.parametrize(
    ("message", "expected_franco"),
    [
        ("ركبتي بتوجعني جامد وأنا بعمل القرفصاء.", False),
        ("3ayez a3raf eh a7san setup lel bench press w el sets ad eh?", True),
    ],
)
def test_arabic_clinical_and_franco_messages_are_intercepted_before_swap_routing(
    fresh_store, monkeypatch, message, expected_franco
):
    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["intent"] == "clinical_intercept"
    assert state["intent_metadata"].get("franco", False) is expected_franco
    assert response


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        (
            "عملت كام تكرار في آخر تمرين للقرفصاء؟",
            {"intent": "exercise_history", "history_exercise": "Back Squat (Barbell)"},
        ),
        (
            "آخر مرة لعبت ضغط صدر بالبار، رفعت كام؟",
            {"intent": "exercise_history", "history_exercise": "Bench Press (Barbell)"},
        ),
        (
            "ما الوزن الذي سجلته في تمرين squat خلال آخر جلسة؟",
            {"intent": "exercise_history", "history_exercise": "Squat"},
        ),
    ],
)
def test_live_arabic_history_targets_remain_history_routes(
    fresh_store, monkeypatch, message, classification
):
    program = _seed_program(fresh_store)
    program_exercise_ids = {
        str(exercise.exercise_id)
        for day in program.days
        for exercise in day.exercises
    }
    model = ScriptedChatModel([classification, "البيانات المسجلة للتمرين موجودة في السياق."])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["intent"] == "exercise_history"
    assert state["intent_metadata"]["arabic_history"] is True
    assert state["intent_metadata"]["history_exercise_id"] in program_exercise_ids
    assert state["intent_metadata"]["history_exercise_name"]
    assert state["program_updated"] is False
    assert response == "البيانات المسجلة للتمرين موجودة في السياق."


def test_arabic_train_or_rest_advice_overrides_misclassified_history(
    fresh_store, monkeypatch
):
    _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {"intent": "exercise_history", "history_whole_session": True},
            COACHING_REPLY,
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("أتمرن النهارده ولا أريح؟ رجلي مرهقة من تمرين امبارح.")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["intent"] == "coaching_qa"
    assert state["program_updated"] is False
    assert response == COACHING_REPLY
