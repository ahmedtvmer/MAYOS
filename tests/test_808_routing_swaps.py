"""Issue #808: weekly program-volume routing and swap source resolution.

Three staging failures: a weekly sets/volume question about the program was
answered as exercise history, a partial exercise name («ال crunch») failed to
match Kneeling Crunch, and a source that is not on the program got the generic
which-exercise question. The classifier stays scripted; no test calls a model.
"""

import pytest
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

import agent.assistant_graph as assistant_graph
from agent.assistant_graph import router_node, stream_assistant_turn
from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from tests.fakes.chat_model import ScriptedChatModel

ARABIC_SWAP_CLARIFICATION = "أنهي تمرين عايز تغيّره؟"
COACHING_REPLY = "خد راحة كفاية حسب إحساسك، وخلّي مجهودك مناسب لحالتك."

# Catalog rows inserted with exact display names: the swap fixtures name
# Kneeling Crunch on a leg day, Incline Dumbbell Press and Chest Fly, and no
# plain Bench Press.
FIXTURE_EXERCISES = (
    ("808-kneeling-crunch", "Kneeling Crunch", "waist", "abs", "body weight"),
    ("808-crunch-floor", "Crunch Floor", "waist", "abs", "body weight"),
    ("808-plank", "Plank", "waist", "abs", "body weight"),
    ("808-chest-fly", "Chest Fly", "chest", "pectorals", "cable"),
    ("808-incline-db-press", "Incline Dumbbell Press", "chest", "pectorals", "dumbbell"),
    ("808-dumbbell-press", "Dumbbell Press", "chest", "pectorals", "dumbbell"),
    ("808-shoulder-press", "Shoulder Press (Dumbbell)", "shoulders", "delts", "dumbbell"),
    ("808-incline-press-machine", "Incline Press (Machine)", "chest", "pectorals", "leverage machine"),
    ("808-flat-press-machine", "Flat Press (Machine)", "chest", "pectorals", "leverage machine"),
)
FIXTURE_IDS = {name: exercise_id for exercise_id, name, *_ in FIXTURE_EXERCISES}


@pytest.fixture
def program_store(fresh_store):
    with fresh_store.catalog_locked() as conn:
        for exercise_id, name, body_part, muscle, equipment in FIXTURE_EXERCISES:
            conn.execute(
                "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) "
                "VALUES (?, ?, ?, ?, ?)",
                (exercise_id, name, body_part, muscle, equipment),
            )
            conn.execute(
                "INSERT INTO exercise_display_names (exercise_id, display_name, is_reviewed) "
                "VALUES (?, ?, 1)",
                (exercise_id, name),
            )
        conn.commit()
    return fresh_store


def _exercise_slot(store, name):
    entry = (
        store.get_exercise_library_entry(FIXTURE_IDS[name])
        if name in FIXTURE_IDS else None
    )
    if entry is None:
        matches = store.find_exercises_by_name(name, limit=1)
        assert matches, f"{name} is missing from the catalog"
        entry = store.get_exercise_library_entry(str(matches[0]["id"]))
    assert entry is not None, f"{name} has no library entry"
    return ProgramExerciseSchema(
        exercise_id=str(entry["id"]),
        exercise_name=entry["name"],
        target_reps_min=6,
        target_reps_max=10,
    )


def _seed_program(store, day_exercise_names):
    ledger = store.ledger
    ledger.upsert_player_profile({"weekly_frequency": 3, "equipment_access": "Commercial gym"})
    days = [
        ProgramDaySchema(
            day_name=day_name,
            day_order=day_order,
            exercises=[_exercise_slot(store, name) for name in names],
        )
        for day_order, (day_name, names) in enumerate(day_exercise_names.items(), start=1)
    ]
    program = GeneratedProgramSchema(
        program_name="Issue 808 program",
        split_type="Full Body",
        weekly_frequency=3,
        days=days,
    )
    ledger.save_training_program(program.model_dump())
    return ledger.get_active_program()


def _turn(message):
    return {
        "messages": [HumanMessage(content=message)],
        "trainee_id": "issue-808",
        "player_account_id": None,
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }


def _config(store):
    return {"configurable": {"ledger": store.ledger, "store": store}}


def _scripted(monkeypatch, turns=(), **kwargs):
    model = ScriptedChatModel(turns, **kwargs)
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    return model


# --- 1. Weekly program sets/volume is coaching, not history ------------------


def test_issue_808_weekly_program_volume_pattern():
    assert assistant_graph._is_weekly_program_volume_question(
        "البرنامج بتاعي فيه كام set في الأسبوع؟"
    )
    assert assistant_graph._is_weekly_program_volume_question(
        "كم مجموعة في برنامجي أسبوعيًا؟"
    )
    assert assistant_graph._is_weekly_program_volume_question(
        "how many sets a week is my program?"
    )
    # «خامس» must not read as the «امس» past marker (anchored pattern).
    assert assistant_graph._is_weekly_program_volume_question(
        "اليوم الخامس في البرنامج فيه كام set؟"
    )
    # Past-session phrasing stays out even with a sets word.
    assert not assistant_graph._is_weekly_program_volume_question(
        "آخر مرة عملت كام set في البنش؟"
    )
    assert not assistant_graph._is_weekly_program_volume_question(
        "how many sets did I do on bench last time?"
    )
    assert not assistant_graph._is_weekly_program_volume_question(
        "بدل ال crunch بال plank"
    )


@pytest.mark.parametrize(
    "message",
    [
        "البرنامج بتاعي فيه كام set في الأسبوع؟",
        "كم مجموعة في برنامجي أسبوعيًا؟",
        "how many sets a week is my program?",
    ],
    ids=["egyptian", "msa", "english"],
)
def test_issue_808_weekly_program_sets_question_is_coaching_qa(
    program_store, monkeypatch, message
):
    _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    # The staging failure: the classifier called the message exercise_history.
    _scripted(monkeypatch, [{"intent": "exercise_history"}])
    state = _turn(message)

    route = router_node(state, _config(program_store))

    assert route["intent"] == "coaching_qa"


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        (
            "آخر مرة عملت كام set في البنش؟",
            {"intent": "exercise_history", "history_exercise": "Bench Press"},
        ),
    ],
    ids=["arabic"],
)
def test_issue_808_past_session_sets_question_stays_history(
    program_store, monkeypatch, message, classification
):
    _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    _scripted(monkeypatch, [classification])
    state = _turn(message)

    route = assistant_graph._classify_arabic_intent(message, _config(program_store))

    assert route["intent"] == "exercise_history"
    assert route["intent_metadata"]["arabic_history"] is True


def test_issue_808_arabic_last_session_sets_question_routes_as_history(
    program_store, monkeypatch
):
    _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    _scripted(monkeypatch, [])
    state = _turn("آخر مرة عملت كام set في البنش؟")

    route = router_node(state, _config(program_store))

    assert route["intent"] == "exercise_history"
    assert route["intent_metadata"]["arabic_history"] is True


def test_issue_808_english_last_session_sets_question_routes_as_history(
    program_store, monkeypatch
):
    _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    _scripted(monkeypatch, [])
    state = _turn("how many sets did I do on bench last session?")

    route = router_node(state, _config(program_store))

    assert route["intent"] == "exercise_history"


# --- 2. A partial exercise name matches one program exercise -----------------


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        (
            "بدل ال crunch بال plank",
            {
                "intent": "exercise_substitution",
                "source_exercise": "ال crunch",
                "target_exercise": "Plank",
            },
        ),
        (
            "استبدل الكرنش بالبلانك",
            {
                "intent": "exercise_substitution",
                "source_exercise": "Kneeling Crunch",
                "target_exercise": "Plank",
            },
        ),
        ("swap the crunch for plank", None),
    ],
    ids=["egyptian-partial", "msa", "english-partial"],
)
def test_issue_808_partial_source_name_swaps_the_single_program_match(
    program_store, monkeypatch, message, classification
):
    before = _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    if classification is None:
        # English "swap ... for ..." routes without the classifier.
        _scripted(monkeypatch)
    else:
        _scripted(monkeypatch, [classification], default_turn=COACHING_REPLY)
    state = _turn(message)

    "".join(stream_assistant_turn(state, ledger=program_store.ledger, store=program_store))

    after = program_store.ledger.get_active_program()
    leg_names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Plank" in leg_names
    assert "Kneeling Crunch" not in leg_names


@pytest.mark.parametrize(
    ("message", "reply_prefix"),
    [
        ("بدل ال crunch بال plank", "هل تقصد **Kneeling Crunch** أو **Crunch Floor**؟"),
        ("swap the crunch for plank", "Did you mean **Kneeling Crunch** or **Crunch Floor**?"),
    ],
    ids=["arabic", "english"],
)
def test_issue_808_partial_source_with_two_program_matches_asks_with_the_list(
    program_store, monkeypatch, message, reply_prefix
):
    before = _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "Crunch Floor", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    _scripted(
        monkeypatch,
        (
            []
            if message.startswith("swap")
            else [{
                "intent": "exercise_substitution",
                "source_exercise": "ال crunch",
                "target_exercise": "Plank",
            }]
        ),
        default_turn=COACHING_REPLY,
    )
    state = _turn(message)

    response = "".join(
        stream_assistant_turn(state, ledger=program_store.ledger, store=program_store)
    )

    assert response == reply_prefix
    assert state["program_updated"] is False
    after = program_store.ledger.get_active_program()
    assert after.version == before.version


def test_issue_808_whole_word_rule_ignores_four_or_more_matches():
    def exercise(exercise_id, name):
        return SimpleNamespace(exercise_id=exercise_id, exercise_name=name)

    days = [
        SimpleNamespace(exercises=[exercise(f"crunch-{index}", f"Crunch Variant {index}")])
        for index in range(4)
    ]

    resolved = assistant_graph._resolve_source_by_whole_words(days, "crunch")

    assert resolved.source is None
    assert resolved.candidates == ()


# --- 3. A source that is not on the program gets a specific answer -----------


@pytest.mark.parametrize(
    "message",
    [
        "تمام بس بدل Bench Press بـ Dumbbell Bench Press",
        "استبدل Bench Press بـ Dumbbell Bench Press",
    ],
    ids=["egyptian", "msa"],
)
def test_issue_808_source_not_in_program_names_the_closest_exercises(
    program_store, monkeypatch, message
):
    before = _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "seated leg curl"],
            "Chest Day": ["Chest Fly", "Pec Deck (Machine)", "barbell row"],
        },
    )
    _scripted(monkeypatch)
    state = _turn(message)

    response = "".join(
        stream_assistant_turn(state, ledger=program_store.ledger, store=program_store)
    )

    assert state["intent"] == "arabic_swap_clarification"
    assert state["intent_metadata"]["clarification_kind"] == "source_not_in_program"
    assert state["intent_metadata"]["requested_source"] == "Bench Press"
    closest = state["intent_metadata"]["closest_exercises"]
    assert 1 <= len(closest) <= 3
    assert "Chest Fly" in closest
    assert response.startswith("Bench Press مش موجود في برنامجك. الأقرب: ")
    assert response.endswith("تقصد أنهي واحد؟")
    assert "Chest Fly" in response
    assert state["program_updated"] is False
    after = program_store.ledger.get_active_program()
    assert after.version == before.version


def test_issue_808_english_source_not_in_program_keeps_the_routine_reply(
    program_store, monkeypatch
):
    before = _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "seated leg curl"],
            "Chest Day": ["Chest Fly", "Pec Deck (Machine)", "barbell row"],
        },
    )
    _scripted(monkeypatch)
    state = _turn("swap Bench Press for Dumbbell Bench Press")

    response = "".join(
        stream_assistant_turn(state, ledger=program_store.ledger, store=program_store)
    )

    assert state["intent"] == "exercise_substitution"
    assert "Could not identify" in response
    assert "bench press" in response.lower()
    assert state["program_updated"] is False
    after = program_store.ledger.get_active_program()
    assert after.version == before.version


def test_issue_808_bench_press_source_still_resolves_to_the_program_press_slot(
    program_store, monkeypatch
):
    # The unchanged similarity rule: the press slot is the clear best match for
    # "Bench Press", so the staging swap still applies when the program has one.
    before = _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    _scripted(monkeypatch)
    state = _turn("تمام بس بدل Bench Press بـ Dumbbell Bench Press")

    "".join(stream_assistant_turn(state, ledger=program_store.ledger, store=program_store))

    after = program_store.ledger.get_active_program()
    chest_names = [exercise.exercise_name for exercise in after.days[1].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in chest_names
    assert "Incline Dumbbell Press" not in chest_names


@pytest.mark.parametrize(
    "message",
    [
        "تمام بس بدل Bench Press بـ Dumbbell Bench Press",
        "استبدل Bench Press بـ Dumbbell Bench Press",
    ],
    ids=["egyptian", "msa"],
)
def test_issue_808_tied_press_sources_name_the_closest_exercises(
    program_store, monkeypatch, message
):
    # Staging reproduction: two press exercises tie at the top similarity for
    # "Bench Press" (both stems reduce to "press"), no plain Bench Press exists,
    # and no program name contains every requested word, so the player gets the
    # source_not_in_program reply naming the tied presses first.
    before = _seed_program(
        program_store,
        {
            "Chest Day": [
                "Incline Dumbbell Press",
                "Dumbbell Press",
                "Shoulder Press (Dumbbell)",
                "Chest Fly",
            ],
        },
    )
    _scripted(monkeypatch)
    state = _turn(message)

    response = "".join(
        stream_assistant_turn(state, ledger=program_store.ledger, store=program_store)
    )

    assert state["intent"] == "arabic_swap_clarification"
    assert state["intent_metadata"]["clarification_kind"] == "source_not_in_program"
    assert state["intent_metadata"]["requested_source"] == "Bench Press"
    closest = state["intent_metadata"]["closest_exercises"]
    assert "Incline Dumbbell Press" in closest
    assert "Shoulder Press (Dumbbell)" in closest
    assert len(closest) <= 3
    assert response.startswith("Bench Press مش موجود في برنامجك. الأقرب: ")
    assert response.endswith("تقصد أنهي واحد؟")
    assert state["program_updated"] is False
    after = program_store.ledger.get_active_program()
    assert after.version == before.version


def test_issue_808_four_tied_press_sources_keep_the_generic_question(
    program_store, monkeypatch
):
    before = _seed_program(
        program_store,
        {
            "Chest Day": [
                "Incline Dumbbell Press",
                "Dumbbell Press",
                "Incline Press (Machine)",
                "Flat Press (Machine)",
                "Chest Fly",
            ],
        },
    )
    _scripted(monkeypatch)
    state = _turn("تمام بس بدل Bench Press بـ Dumbbell Bench Press")

    response = "".join(
        stream_assistant_turn(state, ledger=program_store.ledger, store=program_store)
    )

    assert state["intent"] == "arabic_swap_clarification"
    assert response == ARABIC_SWAP_CLARIFICATION
    assert state["program_updated"] is False
    after = program_store.ledger.get_active_program()
    assert after.version == before.version


def test_issue_808_swap_without_a_named_source_keeps_the_generic_question(
    program_store, monkeypatch
):
    before = _seed_program(
        program_store,
        {
            "Leg Day": ["Kneeling Crunch", "barbell squat", "leg press"],
            "Chest Day": ["Incline Dumbbell Press", "Chest Fly", "barbell row"],
        },
    )
    _scripted(
        monkeypatch, [{"intent": "exercise_substitution"}], default_turn=COACHING_REPLY
    )
    state = _turn("عايز أبدّل تمرين")

    response = "".join(
        stream_assistant_turn(state, ledger=program_store.ledger, store=program_store)
    )

    assert state["intent"] == "arabic_swap_clarification"
    assert response == ARABIC_SWAP_CLARIFICATION
    assert state["program_updated"] is False
    after = program_store.ledger.get_active_program()
    assert after.version == before.version
