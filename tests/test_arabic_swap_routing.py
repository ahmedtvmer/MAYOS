import uuid
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import HumanMessage

from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from agent.assistant_graph import router_node, stream_assistant_turn
from tests.fakes.chat_model import ScriptedChatModel

ARABIC_SWAP_CLARIFICATION = "أنهي تمرين عايز تغيّره؟"
ARABIC_ONE_AT_A_TIME_NOTE = "هبدّل التمرين ده الأول، وبعدها قولي تحب أساعدك في إيه كمان؟"
COACHING_REPLY = "خد راحة كفاية حسب إحساسك، وخلّي مجهودك مناسب لحالتك."


def _seed_program(store, *, duplicate_bench=False):
    ledger = store.ledger
    ledger.upsert_player_profile({"weekly_frequency": 3, "equipment_access": "Commercial gym"})
    names = ["barbell bench press", "barbell squat", "barbell row"]
    if duplicate_bench:
        names.append("dumbbell bench press")
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
    program = GeneratedProgramSchema(
        program_name="Arabic swap test program",
        split_type="Full Body",
        weekly_frequency=3,
        days=[ProgramDaySchema(day_name="Full A", day_order=1, exercises=exercises)],
    )
    ledger.save_training_program(program.model_dump())
    return ledger.get_active_program()


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
    # #766: the vocabulary rule routes these lexically — the Arabic classifier
    # is never called (the scripted classification documents the intended target).
    model = ScriptedChatModel([])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["intent"] == "exercise_history"
    assert state["intent_metadata"]["arabic_history"] is True
    assert state["intent_metadata"]["history_exercise_id"] in program_exercise_ids
    assert classification["history_exercise"] in state["intent_metadata"]["history_exercise_name"]
    assert state["program_updated"] is False
    assert model.calls == []


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


# --- #766: deterministic Arabic workout-history routing ----------------------

ARABIC_PROGRAM_AND_TECHNIQUE_QUESTIONS = [
    "ايه تمارين برنامجي",
    "اعمل تمرين ايه النهارده",
    "ازاي اعمل بنش صح",
    "عايز تمرين للصدر",
    "تمارين يوم الرجل كام سيت",
    "برنامجي عامل ازاي؟",
    # The program's last exercise is a program question, not history (#766).
    "اخر تمرين في البرنامج ايه",
    # Today's plan, not today's logged workout.
    "تمرين النهارده ايه",
    "هتمرن ايه النهارده",
    # Lifestyle questions where the workout word is only a time reference
    # («قبل/بعد التمرين/الجيم») — drinks, supplements, sleep, calories. Food
    # questions («كلت ايه بعد الجيم امبارح») live in test_food_log_assistants:
    # the food-log guard routes them without a model call.
    "شربت ايه امبارح قبل التمرين",
    "اخدت مكملات امبارح قبل التمرين",
    "نمت كام ساعه امبارح قبل التمرين",
    "السعرات اللي دخلتها قبل التمرين امبارح",
    "شربت بروتين بعد الجيم امبارح",
]


@pytest.mark.parametrize(
    ("message", "expected_kind", "expected_exercise"),
    [
        # LAST/PAST + WORKOUT (rule a)
        ("اخر تمرين كان عامل ازاي؟", "whole_session", None),
        ("اخر تمرينه كانت عامله ازاي", "whole_session", None),
        ("آخر حصة كانت عاملة إيه؟", "whole_session", None),
        ("التمرين الأخير كان عامل إيه؟", "whole_session", None),
        ("اخر جلسه عملتها", "whole_session", None),
        ("تمريني امبارح كان عامل ازاي", "whole_session", None),
        ("حصتي اللي فاتت؟", "whole_session", None),
        ("اخر جلسه كانت كويس؟", "whole_session", None),
        ("تمرين السبت كان عامل ازاي؟", "whole_session", None),
        ("روحت الجيم امبارح", "whole_session", None),
        ("ورك اوت امبارح كان عامل ازاي؟", "whole_session", None),
        ("الجيم امبارح كان عامل ازاي؟", "whole_session", None),
        ("لخصلي اخر جلسة", "whole_session", None),
        ("راجعلي اخر جلسه", "whole_session", None),
        ("وريني اخر تمرين", "whole_session", None),
        ("اداء اخر تمرين", "whole_session", None),
        ("كيف كان آخر تمرين؟", "whole_session", None),
        ("ملخص آخر جلسة", "whole_session", None),
        ("تقييم اخر جلسه", "whole_session", None),
        ("ايه اخباره اخر جلسه؟", "whole_session", None),
        ("مستوايا اخر تمرين؟", "whole_session", None),
        ("كيف كان ادائي اخر تمرين", "whole_session", None),
        ("ماذا فعلت امبارح", "whole_session", None),
        ("كم رفعت امبارح", "whole_session", None),
        ("شفت اخر جلسه كانت عامله ايه", "whole_session", None),
        # Elongated letters collapse to the same match.
        ("اخر تمرين كان عامل ازااااي؟", "whole_session", None),
        # HOW/PERFORMANCE + LAST/PAST (rule b)
        ("عملت ايه امبارح", "whole_session", None),
        ("اتمرنت امبارح عملت ايه", "whole_session", None),
        ("عملت ايه قبل كده", "whole_session", None),
        ("عملت ايه من يومين", "whole_session", None),
        ("عملت ايه الاسبوع اللي فات", "whole_session", None),
        ("عملت ايه النهارده", "whole_session", None),
        # The last-session request with hamza, ة/ه and MSA spellings.
        ("آخِر جلسة كانت عاملة إيه؟", "whole_session", None),
        ("أداء آخر تمرين", "whole_session", None),
        # Per-exercise history
        ("اخر مرة لعبت بنش عملت كام", "exercise", "Bench Press"),
        ("عملت ايه في السكوات اخر مرة", "exercise", "Squat"),
        ("اخر تمرين بنش كان عامل ازاي", "exercise", "Bench Press"),
        ("عملت كام تكرار في آخر تمرين للقرفصاء؟", "exercise", "Squat"),
        ("رفعت كام في البنش المره الاخيره؟", "exercise", "Bench Press"),
        ("شلت كام في البنش اخر مره؟", "exercise", "Bench Press"),
        ("لعبت كام بنش امبارح؟", "exercise", "Bench Press"),
        ("عملت كام في البنش قبل كده؟", "exercise", "Bench Press"),
        ("عملت ايه في البنش النهارده؟", "exercise", "Bench Press"),
        ("عملت كام بنش امبارح؟", "exercise", "Bench Press"),
        ("ما الوزن الذي سجلته في تمرين squat خلال آخر جلسة؟", "exercise", "Squat"),
        # MSA/relative-clause: «اخر مرة» + past training verb (+ فيها) + exercise
        ("اخر مرة سجلت فيها بنش", "exercise", "Bench Press"),
        ("آخر مرة لعبت فيها بنش", "exercise", "Bench Press"),
        ("اخر مرة قدرت ارفع فيها البنش", "exercise", "Bench Press"),
        # Exercise after a relative clause / purpose phrase on the session noun
        ("آخر حصة عملت فيها بنش", "exercise", "Bench Press"),
        ("اخر تمرين عملته للبنش", "exercise", "Bench Press"),
        ("اخر جلسه عملتها للسكوات", "exercise", "Squat"),
    ],
)
def test_arabic_history_routing_table(
    fresh_store, monkeypatch, message, expected_kind, expected_exercise
):
    _seed_program(fresh_store)
    # No scripted turns: a history hit must route without any model call, so an
    # unexpected classifier call fails the test loudly.
    model = ScriptedChatModel([])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    routed = router_node(
        state, {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}}
    )

    assert routed["intent"] == "exercise_history"
    metadata = routed["intent_metadata"]
    assert metadata["arabic_history"] is True
    assert model.calls == []
    if expected_kind == "whole_session":
        # «اخر تمرين» with no exercise named after it means the last session.
        assert "history_exercise_id" not in metadata
        assert metadata["raw_query"] == "how did I do last session"
    else:
        assert expected_exercise in metadata["history_exercise_name"]


@pytest.mark.parametrize("message", ARABIC_PROGRAM_AND_TECHNIQUE_QUESTIONS)
def test_arabic_program_and_technique_questions_stay_off_the_history_route(
    fresh_store, monkeypatch, message
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([{"intent": "coaching_qa"}, COACHING_REPLY])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    routed = router_node(
        state, {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}}
    )

    assert routed["intent"] == "coaching_qa"
    assert len(model.calls) == 1  # only the Arabic classifier ran, no history hijack
    assert fresh_store.ledger.get_active_program().version == before.version


def _seed_history_session(store, exercise_name_fragment):
    """Log one saved session with a working set on a seeded program exercise."""
    program = _seed_program(store)
    slot = next(
        exercise
        for day in program.days
        for exercise in day.exercises
        if exercise_name_fragment in exercise.exercise_name.lower()
    )
    session_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    store.ledger.log_workout_session(
        session_id=session_id,
        session_date="2026-11-17",
        split_name="Upper",
        started_at=now,
        completed_at=now,
    )
    store.ledger.log_workout_set(
        set_id=str(uuid.uuid4()),
        session_id=session_id,
        exercise_id=str(slot.exercise_id),
        set_index=1,
        weight_kg=100.0,
        reps=8,
        rpe=8.0,
    )
    return slot


def test_arabic_last_workout_question_answers_from_the_seeded_session(
    fresh_store, monkeypatch
):
    slot = _seed_history_session(fresh_store, "bench")
    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("اخر تمرين كان عامل ازاي؟")

    response = "".join(
        stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store)
    )

    assert state["intent"] == "exercise_history"
    assert state["program_updated"] is False
    # The reply is the lean Egyptian Arabic rendering of the ledger answer —
    # never the English template — naming the exercise with its recorded
    # weight and reps, Western digits, kg.
    assert any("\u0600" <= character <= "\u06ff" for character in response)
    assert "Your last logged session" not in response
    assert slot.exercise_name in response
    assert "100 kg × 8" in response
    assert "أحسن سيت" in response
    assert model.calls == []


def test_arabic_last_bench_session_question_answers_from_the_seeded_session(
    fresh_store, monkeypatch
):
    slot = _seed_history_session(fresh_store, "bench")
    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("اخر مره لعبت بنش عملت كام؟")

    response = "".join(
        stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store)
    )

    assert state["intent"] == "exercise_history"
    assert state["intent_metadata"]["history_exercise_id"] == str(slot.exercise_id)
    assert slot.exercise_name in response
    assert any("\u0600" <= character <= "\u06ff" for character in response)
    assert "100 kg × 8" in response
    assert "تكرار" in response
    assert model.calls == []


def test_arabic_progress_status_reaches_the_player(fresh_store, monkeypatch):
    # Two recorded bench sessions with a heavier, higher-rep best set in the
    # newer one: the lean Arabic reply must carry both best sets and the
    # progress status in words (the ledger scores load + reps + e1RM all up as
    # "improvement"), with no model call.
    _seed_program(fresh_store)
    program = fresh_store.ledger.get_active_program()
    slot = next(
        exercise
        for day in program.days
        for exercise in day.exercises
        if "bench" in exercise.exercise_name.lower()
    )
    now = datetime.now(UTC)
    for index, (weight, reps) in enumerate([(80.0, 5), (100.0, 8)]):
        started = (now - timedelta(days=7 - index * 7)).isoformat()
        session_id = str(uuid.uuid4())
        fresh_store.ledger.log_workout_session(
            session_id=session_id,
            session_date=(now - timedelta(days=7 - index * 7)).date().isoformat(),
            split_name="Upper",
            started_at=started,
            completed_at=started,
        )
        fresh_store.ledger.log_workout_set(
            set_id=str(uuid.uuid4()),
            session_id=session_id,
            exercise_id=str(slot.exercise_id),
            set_index=1,
            weight_kg=weight,
            reps=reps,
            rpe=8.0,
        )
    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("اخر مره لعبت بنش عملت كام؟")

    response = "".join(
        stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store)
    )

    assert state["intent"] == "exercise_history"
    assert "100 kg × 8" in response
    assert "80 kg × 5" in response
    assert "تحسن" in response
    assert "مش اتجاه طويل المدى" in response
    assert model.calls == []
