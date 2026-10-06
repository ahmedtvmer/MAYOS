"""Swap target resolution: catalog-name-first installs, hallucinated-name refusals, muscle mismatches."""

import re
import shutil
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph
from agent.assistant_graph import exercise_substitution_node
from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager
from tests.fakes.chat_model import ScriptedChatModel
from utils.equipment_access import BODYWEIGHT_ONLY, COMMERCIAL_GYM, HOME_GYM

CHEST_SLOT = "577"  # machine chest press (pectorals | chest)
REVERSE_LAT_SLOT = "673"  # reverse grip machine lat pulldown (lats | back)
REVERSE_LAT_DISPLAY_NAME = "Reverse-Grip Pulldown (Machine)"
CABLE_LAT_SLOT = "150"  # cable bar lateral pulldown (lats | back)
MACHINE_LAT_VARIANT = "2736"  # machine reverse grip lateral pulldown (lats | back)
PULL_THROUGH = "196"  # cable pull through (with rope)
HIP_THRUST = "3562"  # barbell glute bridge row, displayed as Barbell Hip Thrust
PUSH_UP = "662"  # push-up
DECLINE_PUSH_UP = "279"  # decline push-up
STIFF_LEG_DEADLIFT = "432"  # dumbbell stiff leg deadlift
ROMANIAN_DEADLIFT = "85"  # barbell romanian deadlift

HALLUCINATED_TARGET = "Machine Two-Arm Lateral Pulldown"


def _exercise(exercise_id: str) -> dict:
    return {
        "exercise_id": exercise_id,
        "target_sets": 3,
        "target_reps_min": 8,
        "target_reps_max": 12,
        "target_rpe": 8.5,
    }


@pytest.fixture
def sub_db(tmp_path, monkeypatch):
    catalog_path = tmp_path / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog_path)
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="default",
    )
    try:
        db.ledger.save_training_program(
            {
                "program_name": "Resolution Test Split",
                "weekly_frequency": 3,
                "split_type": "Upper/Lower",
                "days": [
                    {
                        "day_name": "Upper 1",
                        "day_order": 1,
                        "exercises": [_exercise(CHEST_SLOT), _exercise(REVERSE_LAT_SLOT), _exercise(CABLE_LAT_SLOT)],
                    }
                ],
            }
        )
        yield db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _state(source: str, target: str) -> dict:
    return {
        "messages": [HumanMessage(content=f"swap {source} for {target}")],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": source, "target_exercise": target},
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }


def _slot_name(db, index: int) -> str:
    program = db.ledger.get_active_program()
    assert program is not None
    return program.days[0].exercises[index].exercise_name.lower()


def _save_program_days(db, day_specs: list[tuple[str, list[str]]]) -> None:
    program = db.ledger.get_active_program().model_dump()
    program.pop("created_at", None)
    program["days"] = [
        {
            "day_name": day_name,
            "day_order": index,
            "exercises": [_exercise(exercise_id) for exercise_id in exercise_ids],
        }
        for index, (day_name, exercise_ids) in enumerate(day_specs, start=1)
    ]
    db.ledger.save_training_program(program)


@pytest.mark.parametrize(
    ("message", "source_id", "replacement_id", "false_day", "source_day"),
    [
        (
            "swap cable pull-through for hip thrust",
            PULL_THROUGH,
            HIP_THRUST,
            "Pull",
            "Posterior 1",
        ),
        ("swap push-ups for decline push-up", PUSH_UP, DECLINE_PUSH_UP, "Push", "Upper 1"),
        (
            "swap stiff legs deadlift for barbell romanian deadlift",
            STIFF_LEG_DEADLIFT,
            ROMANIAN_DEADLIFT,
            "Legs",
            "Posterior 1",
        ),
    ],
)
def test_exercise_words_do_not_select_a_day(
    sub_db, message, source_id, replacement_id, false_day, source_day
):
    _save_program_days(
        sub_db,
        [
            (false_day, [CHEST_SLOT, REVERSE_LAT_SLOT, CABLE_LAT_SLOT]),
            (source_day, [source_id, CHEST_SLOT, REVERSE_LAT_SLOT]),
        ],
    )
    state = _state("", "")
    state["messages"] = [HumanMessage(content=message)]
    state["intent_metadata"].update(
        source_exercise=message.removeprefix("swap ").split(" for ", 1)[0],
        target_exercise=message.split(" for ", 1)[1],
    )

    result = exercise_substitution_node(
        state, {"configurable": {"ledger": sub_db.ledger, "store": sub_db}}
    )

    assert result["program_updated"] is True
    active = sub_db.ledger.get_active_program()
    assert active.version == 3
    by_day = {day.day_name: day for day in active.days}
    assert by_day[source_day].exercises[0].exercise_id == replacement_id
    assert by_day[false_day].exercises[0].exercise_id == CHEST_SLOT


def test_explicit_on_day_reference_selects_that_day(sub_db):
    _save_program_days(
        sub_db,
        [
            ("Upper 1", [PULL_THROUGH, CHEST_SLOT, REVERSE_LAT_SLOT]),
            ("Pull", [PULL_THROUGH, CHEST_SLOT, REVERSE_LAT_SLOT]),
        ],
    )
    state = _state("cable pull-through", "hip thrust")
    state["messages"] = [HumanMessage(content="swap cable pull-through on Pull day for hip thrust")]

    result = exercise_substitution_node(
        state, {"configurable": {"ledger": sub_db.ledger, "store": sub_db}}
    )

    assert result["program_updated"] is True
    active = sub_db.ledger.get_active_program()
    assert active.days[0].exercises[0].exercise_id == PULL_THROUGH
    assert active.days[1].exercises[0].exercise_id == HIP_THRUST
    assert "Pull" in result["response_content"]


def test_swap_request_without_replacement_resolves_on_day_reference(sub_db, monkeypatch):
    _save_program_days(
        sub_db,
        [
            ("Upper 1", [PULL_THROUGH, CHEST_SLOT, REVERSE_LAT_SLOT]),
            ("Pull", [PULL_THROUGH, CHEST_SLOT, REVERSE_LAT_SLOT]),
        ],
    )
    candidate = sub_db.get_exercise_library_entry(HIP_THRUST)
    monkeypatch.setattr(
        assistant_graph,
        "EMBED_MODEL",
        SimpleNamespace(embed_query=lambda _query: [], embed_documents=lambda _documents: []),
    )
    monkeypatch.setattr(sub_db, "search_similar_exercises", lambda *_args, **_kwargs: [candidate])
    state = _state("cable pull-through", "")
    state["messages"] = [HumanMessage(content="swap cable pull-through on Pull day")]

    result = exercise_substitution_node(
        state, {"configurable": {"ledger": sub_db.ledger, "store": sub_db}}
    )

    assert result["program_updated"] is False
    assert "(`glutes` | `pull`)" in result["response_content"].lower()
    assert sub_db.ledger.get_active_program().version == 2


def test_day_without_source_falls_back_to_the_source_day(sub_db):
    _save_program_days(
        sub_db,
        [
            ("Pull", [CHEST_SLOT, REVERSE_LAT_SLOT, CABLE_LAT_SLOT]),
            ("Posterior 1", [PULL_THROUGH, CHEST_SLOT, REVERSE_LAT_SLOT]),
        ],
    )
    state = _state("cable pull-through", "hip thrust")
    state["messages"] = [HumanMessage(content="swap cable pull-through on Pull day for hip thrust")]

    result = exercise_substitution_node(
        state, {"configurable": {"ledger": sub_db.ledger, "store": sub_db}}
    )

    assert result["program_updated"] is True
    active = sub_db.ledger.get_active_program()
    assert active.days[0].exercises[0].exercise_id == CHEST_SLOT
    assert active.days[1].exercises[0].exercise_id == HIP_THRUST


def test_ambiguous_source_asks_which_day_without_publishing(sub_db):
    _save_program_days(
        sub_db,
        [
            ("Upper 1", [REVERSE_LAT_SLOT, CHEST_SLOT, CABLE_LAT_SLOT]),
            ("Pull", [REVERSE_LAT_SLOT, CHEST_SLOT, CABLE_LAT_SLOT]),
        ],
    )
    before = sub_db.ledger.get_active_program()
    result = exercise_substitution_node(
        _state(REVERSE_LAT_DISPLAY_NAME, "Front Pulldown (Machine)"),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert result["program_updated"] is False
    assert "Upper 1" in result["response_content"]
    assert "Pull" in result["response_content"]
    after = sub_db.ledger.get_active_program()
    assert after.version == before.version
    assert [day.exercises[0].exercise_id for day in after.days] == [REVERSE_LAT_SLOT, REVERSE_LAT_SLOT]


def test_catalog_name_resolution_tiers(sub_db):
    db = sub_db
    assert db.find_exercises_by_name("machine chest press")[0]["id"] == "577"
    # Punctuation-insensitive exact: "push up" ≡ "push-up".
    assert db.find_exercises_by_name("push up")[0]["name"] == "Push-Up"
    # Substring: partial name resolves to the full catalog name.
    assert db.find_exercises_by_name("romanian deadlift")[0]["name"] == "Romanian Deadlift (Barbell)"
    # Token-AND: scrambled tokens still resolve.
    assert db.find_exercises_by_name("press chest machine")[0]["name"] == "Chest Press (Machine)"
    # The hallucinated transcript target matches nothing.
    assert db.find_exercises_by_name(HALLUCINATED_TARGET) == []


def test_chat_substitution_resolves_display_alias(sub_db):
    sub_db.initialize_and_seed()
    result = exercise_substitution_node(
        _state(REVERSE_LAT_DISPLAY_NAME, "standing cable pulldown"),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert result["program_updated"] is True, result
    active = sub_db.ledger.get_active_program()
    assert active.days[0].exercises[1].exercise_id == "2330"
    assert active.days[0].exercises[1].exercise_name == "Standing Cable Pulldown (Cable)"
    assert active.days[0].exercises[2].exercise_id == CABLE_LAT_SLOT
    assert "standing cable pulldown (cable)" in result["response_content"].lower()


def test_chat_substitution_resolves_a_target_named_by_its_source_name(sub_db):
    sub_db.initialize_and_seed()
    result = exercise_substitution_node(
        _state(REVERSE_LAT_DISPLAY_NAME, "cable lat pulldown full range of motion"),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert result["program_updated"] is True, result
    active = sub_db.ledger.get_active_program()
    assert active.days[0].exercises[1].exercise_id == "2330"
    assert active.days[0].exercises[1].exercise_name == "Standing Cable Pulldown (Cable)"


def test_chat_library_search_returns_alias_matches_with_display_names(sub_db):
    sub_db.initialize_and_seed()
    state = _state("", "")
    state["intent_metadata"] = {"search_query": "frontal lat pulldown"}

    result = assistant_graph.catalog_search_node(
        state, {"configurable": {"ledger": sub_db.ledger, "store": sub_db}}
    )

    assert "**Lat Pulldown (Cable)**" in result["response_content"]


def test_catalog_lookup_model_context_includes_curated_exercise_facts(
    sub_db, seed_exercise_curation, monkeypatch
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(
        sub_db,
        {
            CHEST_SLOT: {
                "display_name": "Machine Chest Press",
                "primary_action": "Shoulder Horizontal Adduction",
                "secondary_actions": ["Elbow Extension"],
                "primary_muscle": "Chest",
                "load_type": "selectorized",
            }
        },
    )
    model = ScriptedChatModel(["The machine chest press is a chest exercise."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    query = "machine chest press"
    lookup_state = _state("", "")
    lookup_state["messages"] = [HumanMessage(content=query)]
    lookup_state["intent_metadata"] = {
        "raw_query": query,
        "sub_intents": [
            {"intent": "catalog_search", "query": query, "intent_metadata": {"search_query": query}},
            {"intent": "coaching_qa", "query": "What are these movements?"},
        ],
    }
    result = assistant_graph.composite_intent_node(
        lookup_state,
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )
    assert "Primary action:" not in result["response_content"]

    model_context = "\n".join(message.content for message in model.calls[0]["messages"])
    for field in (
        "Machine Chest Press",
        "Primary action: Shoulder Horizontal Adduction",
        "Secondary actions: Elbow Extension",
        "Primary muscle: Chest",
        "Load type: Pin-loaded",
        "Equipment category: Machine",
    ):
        assert field in model_context


def test_uncurated_catalog_lookup_has_only_name_in_player_reply(
    sub_db, seed_exercise_curation
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(sub_db, {CHEST_SLOT: {}})

    lookup_state = _state("", "")
    lookup_state["intent_metadata"] = {"search_query": "machine chest press"}
    result = assistant_graph.catalog_search_node(
        lookup_state,
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert "Machine Chest Press" in result["response_content"]
    assert "Equipment category:" not in result["response_content"]
    assert "Primary action:" not in result["response_content"]
    assert "Secondary actions:" not in result["response_content"]
    assert "Primary muscle:" not in result["response_content"]
    assert "Load type:" not in result["response_content"]
    assert "None" not in result["response_content"]
    assert "null" not in result["response_content"]
    assert "Machine Chest Press — Equipment category: Machine" in result["model_context_content"]
    assert "Primary action:" not in result["model_context_content"]


def test_uncurated_no_staple_substitution_keeps_similarity_and_names(
    sub_db, seed_exercise_curation, monkeypatch
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(sub_db, {CHEST_SLOT: {}})
    _save_program_days(sub_db, [("Upper 1", [CHEST_SLOT])])
    sub_db.ledger.upsert_player_profile(
        {
            "gender": "male", "proportions": "balanced", "age": 30,
            "weight_kg": 80, "height_cm": 180, "rep_preference": "balanced",
            "current_goal": "hypertrophy", "long_term_goal": "strength",
            "weekly_frequency": 3, "training_age_years": 3,
            "equipment_access": BODYWEIGHT_ONLY,
            "injuries_or_limitations": "None", "stress_and_sleep": "normal",
        }
    )
    candidate = sub_db.get_exercise_library_entry(PUSH_UP)
    monkeypatch.setattr(
        assistant_graph,
        "EMBED_MODEL",
        SimpleNamespace(embed_query=lambda _query: [], embed_documents=lambda _documents: []),
    )
    monkeypatch.setattr(sub_db, "search_similar_exercises", lambda *_args, **_kwargs: [candidate])

    result = exercise_substitution_node(
        _state("machine chest press", ""),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert "Machine Chest Press" in result["response_content"]
    assert "Push-Up" in result["response_content"]
    assert "Equipment category:" not in result["response_content"]
    assert "Primary action:" not in result["response_content"]
    assert "Primary muscle:" not in result["response_content"]
    assert "Load type:" not in result["response_content"]
    assert "None" not in result["response_content"]
    assert "Machine Chest Press — Equipment category: Machine" in result["model_context_content"]


def test_active_program_sent_to_coreference_model_includes_curated_exercise_facts(
    sub_db, seed_exercise_curation, monkeypatch
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(
        sub_db,
        {
            REVERSE_LAT_SLOT: {
                "primary_action": "Shoulder Extension",
                "secondary_actions": ["Elbow Flexion"],
                "primary_muscle": "Lats",
                "load_type": "selectorized",
            }
        },
    )
    model = ScriptedChatModel(
        [{"source_exercise": REVERSE_LAT_DISPLAY_NAME, "target_exercise": ""}]
    )
    monkeypatch.setattr(assistant_graph, "llm", model)
    state = _state("it", "")
    state["messages"] = [HumanMessage(content="swap it for something else")]

    exercise_substitution_node(
        state,
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    model_context = model.calls[0]["messages"][0].content
    for field in (
        "Primary action: Shoulder Extension",
        "Secondary actions: Elbow Flexion",
        "Primary muscle: Lats",
        "Load type: Pin-loaded",
        "Equipment category: Machine",
    ):
        assert field in model_context


def test_exercise_history_reply_keeps_display_name_and_model_context_has_curated_facts(
    sub_db, seed_exercise_curation, monkeypatch
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(
        sub_db,
        {
            CHEST_SLOT: {
                "display_name": "Machine Chest Press",
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
                "load_type": "plate_loaded",
            }
        },
    )
    model = ScriptedChatModel(["The last logged movement was a chest press."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    query = f"last logged occurrence of {CHEST_SLOT}"
    request = _state("", "")
    request["messages"] = [HumanMessage(content=query)]
    request["intent_metadata"] = {
        "raw_query": query,
        "sub_intents": [
            {
                "intent": "exercise_history",
                "query": query,
                "intent_metadata": {"raw_query": query},
            },
            {"intent": "coaching_qa", "query": "What movement did I ask about?"},
        ],
    }
    result = assistant_graph.composite_intent_node(
        request,
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )
    model_context = "\n".join(message.content for message in model.calls[0]["messages"])

    assert "machine chest press" in result["response_content"].lower()
    assert "Primary action:" not in result["response_content"]
    assert "Equipment category:" not in result["response_content"]
    assert "Primary action: Shoulder Horizontal Adduction" in model_context
    assert "Load type: Plate-loaded" in model_context
    assert "Equipment category: Machine" in model_context


def test_substitution_model_context_includes_curated_source_and_candidates(
    sub_db, seed_exercise_curation, monkeypatch
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(
        sub_db,
        {
            REVERSE_LAT_SLOT: {
                "primary_action": "Shoulder Extension",
                "secondary_actions": ["Elbow Flexion"],
                "primary_muscle": "Lats",
                "load_type": "selectorized",
            },
            "2330": {
                "display_name": "Wide-Grip Lat Pulldown",
                "primary_action": "Shoulder Extension",
                "secondary_actions": ["Elbow Extension"],
                "primary_muscle": "Lats",
            },
        },
    )
    model = ScriptedChatModel(["The first option keeps the same main movement."])
    monkeypatch.setattr(assistant_graph, "llm", model)
    query = f"show me alternatives for {REVERSE_LAT_DISPLAY_NAME}"
    state = _state("", "")
    state["messages"] = [HumanMessage(content=query)]
    state["intent_metadata"] = {
        "raw_query": query,
        "sub_intents": [
            {
                "intent": "exercise_substitution",
                "query": query,
                "intent_metadata": {
                    "source_exercise": REVERSE_LAT_DISPLAY_NAME,
                    "target_exercise": "",
                },
            },
            {"intent": "coaching_qa", "query": "Which option has the same action?"},
        ],
    }

    result = assistant_graph.composite_intent_node(
        state,
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    model_context = "\n".join(
        message.content for message in model.calls[0]["messages"]
    )
    for field in (
        "Primary action: Shoulder Extension",
        "Secondary actions: Elbow Flexion",
        "Primary muscle: Lats",
        "Load type: Pin-loaded",
        "Equipment category: Machine",
        "Wide-Grip Lat Pulldown",
        "Secondary actions: Elbow Extension",
        "Equipment category: Cable",
    ):
        assert field in model_context
    assert "Primary action:" not in result["response_content"]
    assert "Secondary actions:" not in result["response_content"]
    assert "Equipment category:" not in result["response_content"]


@pytest.mark.parametrize("access", [COMMERCIAL_GYM, HOME_GYM, BODYWEIGHT_ONLY])
def test_no_staple_suggestions_follow_replace_ranking_and_access(
    sub_db, seed_exercise_curation, access
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(
        sub_db,
        {
            REVERSE_LAT_SLOT: {
                "primary_action": "Shoulder Extension",
                "primary_muscle": "Lats",
                "secondary_actions": ["Elbow Flexion"],
                "load_type": "selectorized",
            },
            "2330": {
                "display_name": "Wide-Grip Lat Pulldown",
                "primary_action": "Shoulder Extension",
                "primary_muscle": "Lats",
                "secondary_actions": ["Elbow Extension"],
            },
            "818": {"primary_action": "Shoulder Horizontal Adduction", "primary_muscle": "Upper Back"},
            PULL_THROUGH: {"primary_action": "Knee Flexion", "primary_muscle": "Glutes"},
            HIP_THRUST: {"primary_action": "Hip Extension", "primary_muscle": "Glutes"},
            MACHINE_LAT_VARIANT: {
                "primary_action": "Shoulder Extension",
                "primary_muscle": "Lats",
                "hidden": True,
            },
            "1013": {"primary_action": "Elbow Flexion", "primary_muscle": "Biceps"},
            "1429": {"primary_action": "Shoulder Flexion", "primary_muscle": "Chest"},
        },
    )
    sub_db.ledger.upsert_player_profile(
        {
            "gender": "male", "proportions": "balanced", "age": 30,
            "weight_kg": 80, "height_cm": 180, "rep_preference": "balanced",
            "current_goal": "hypertrophy", "long_term_goal": "strength",
            "weekly_frequency": 3, "training_age_years": 3,
            "equipment_access": access, "injuries_or_limitations": "None",
            "stress_and_sleep": "normal",
        }
    )
    program = sub_db.ledger.get_active_program()
    source = next(
        exercise
        for day in program.days
        for exercise in day.exercises
        if exercise.exercise_id == REVERSE_LAT_SLOT
    )
    assert not source.suggested_substitutes
    expected_names_by_access = {
        COMMERCIAL_GYM: [
            "Wide-Grip Lat Pulldown",
            "Machine One Arm Lateral Wide Pulldown",
            "Machine Pullover",
        ],
        HOME_GYM: [],
        BODYWEIGHT_ONLY: [],
    }

    result = exercise_substitution_node(
        _state(REVERSE_LAT_DISPLAY_NAME, ""),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    numbered_lines = [
        line for line in result["response_content"].splitlines()
        if re.match(r"^\d+\. \*\*", line)
    ]
    shown_names = [line.split("**", 2)[1].split(" — ", 1)[0] for line in numbered_lines]
    assert shown_names == expected_names_by_access[access]
    assert len(shown_names) <= 3
    hidden_name = sub_db.get_exercise_library_entry(MACHINE_LAT_VARIANT)["name"]
    assert hidden_name not in result["response_content"]
    if access == COMMERCIAL_GYM:
        assert "Band Underhand Pulldown" not in result["response_content"]
        assert "Wide-Grip Pull-Up" not in result["response_content"]


def test_assistant_substitution_suggestions_skip_hidden_rows(sub_db, seed_exercise_curation):
    sub_db.initialize_and_seed()
    program = sub_db.ledger.get_active_program().model_dump()
    program.pop("created_at", None)
    source = next(
        exercise
        for exercise in program["days"][0]["exercises"]
        if exercise["exercise_id"] == REVERSE_LAT_SLOT
    )
    suggested = sub_db.get_exercise_library_entry(MACHINE_LAT_VARIANT)
    assert suggested is not None
    source["suggested_substitutes"] = [
        {"exercise_id": MACHINE_LAT_VARIANT, "exercise_name": suggested["name"]}
    ]
    sub_db.ledger.save_training_program(program)
    seed_exercise_curation(sub_db, {MACHINE_LAT_VARIANT: {"hidden": True}})

    result = exercise_substitution_node(
        _state(REVERSE_LAT_DISPLAY_NAME, ""),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert result["program_updated"] is False
    assert suggested["name"] not in result["response_content"]


def test_assistant_near_miss_refusal_does_not_name_hidden_exercises(
    sub_db, seed_exercise_curation
):
    sub_db.initialize_and_seed()
    seed_exercise_curation(sub_db, {"744": {"hidden": True}})

    result = exercise_substitution_node(
        _state(REVERSE_LAT_DISPLAY_NAME, "pendulum squat"),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert result["program_updated"] is False
    assert "pendulum squat" in result["response_content"].lower()
    assert "sled lying squat" not in result["response_content"].lower()


@pytest.mark.parametrize(
    ("target", "target_id", "source_id"),
    [
        ("pendulum squat", "744", "3562"),
        ("kelso shrug", "329", None),
        ("bayesian curl", "190", "318"),
    ],
)
def test_near_miss_substitution_refuses_semantic_sibling(
    sub_db, monkeypatch, target, target_id, source_id
):
    sub_db.initialize_and_seed()
    if source_id is None:
        source_id = sub_db.catalog_conn.execute(
            "SELECT id FROM exercises WHERE target_muscle = 'traps' AND id != ? LIMIT 1",
            (target_id,),
        ).fetchone()[0]
    source_name = sub_db.get_exercise_library_entry(source_id)["name"]
    _save_program_days(sub_db, [("Upper 1", [source_id, CHEST_SLOT, REVERSE_LAT_SLOT])])
    semantic_neighbor = sub_db.get_exercise_library_entry(target_id)
    semantic_neighbor["distance"] = 0.1
    semantic_calls = []

    def search_semantic_neighbors(*args, **kwargs):
        semantic_calls.append((args, kwargs))
        return [semantic_neighbor]

    monkeypatch.setattr(
        assistant_graph,
        "EMBED_MODEL",
        SimpleNamespace(embed_query=lambda _query: [], embed_documents=lambda _documents: []),
    )
    monkeypatch.setattr(sub_db, "search_similar_exercises", search_semantic_neighbors)

    result = exercise_substitution_node(
        _state(source_name, target),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    assert result["program_updated"] is False
    assert semantic_calls == []
    active = sub_db.ledger.get_active_program()
    assert active.days[0].exercises[0].exercise_id == source_id
    assert all(exercise.exercise_id != target_id for exercise in active.days[0].exercises)


def test_hallucinated_target_refuses_instead_of_installing_sibling(sub_db):
    db = sub_db
    res = exercise_substitution_node(_state(REVERSE_LAT_DISPLAY_NAME, HALLUCINATED_TARGET), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert res["program_updated"] is False
    assert "could not find a biomechanically suitable match" in res["response_content"].lower()
    assert _slot_name(db, 1) == REVERSE_LAT_DISPLAY_NAME.lower()


def test_named_catalog_target_installs_without_semantic_search(sub_db, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("EMBED_MODEL must not be used for a named catalog match")

    monkeypatch.setattr(assistant_graph, "EMBED_MODEL", SimpleNamespace(embed_query=_boom, embed_documents=_boom))
    res = exercise_substitution_node(_state(REVERSE_LAT_DISPLAY_NAME, "Front Pulldown (Machine)"), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert res["program_updated"] is True
    assert "Front Pulldown (Machine)" in res["response_content"]
    assert _slot_name(sub_db, 1) == "front pulldown (machine)"


def test_punctuation_normalized_target_installs(sub_db):
    res = exercise_substitution_node(_state("machine chest press", "push up"), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert res["program_updated"] is True
    assert "push-up" in res["response_content"].lower()
    assert _slot_name(sub_db, 0) == "push-up"


def test_transcript_replay_second_commit_refuses(sub_db):
    db = sub_db
    first = exercise_substitution_node(_state(REVERSE_LAT_DISPLAY_NAME, "Front Pulldown (Machine)"), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert first["program_updated"] is True

    second = exercise_substitution_node(_state("Front Pulldown (Machine)", HALLUCINATED_TARGET), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert second["program_updated"] is False
    assert _slot_name(db, 1) == "front pulldown (machine)"


def test_muscle_incompatible_named_target_refuses(sub_db):
    db = sub_db
    res = exercise_substitution_node(_state(REVERSE_LAT_DISPLAY_NAME, "barbell bench press"), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert res["program_updated"] is False
    assert "is in the exercise database" in res["response_content"]
    assert "pectorals" in res["response_content"].lower()
    assert _slot_name(db, 1) == REVERSE_LAT_DISPLAY_NAME.lower()


def test_self_swap_refuses(sub_db):
    db = sub_db
    res = exercise_substitution_node(_state(REVERSE_LAT_DISPLAY_NAME, REVERSE_LAT_DISPLAY_NAME), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert res["program_updated"] is False
    assert _slot_name(db, 1) == REVERSE_LAT_DISPLAY_NAME.lower()


@pytest.mark.parametrize("target", ["it", "choice", "one", "two", "three", "first"])
def test_unspecific_target_refuses_without_junk_match(sub_db, target):
    db = sub_db
    res = exercise_substitution_node(_state(REVERSE_LAT_DISPLAY_NAME, target), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert res["program_updated"] is False
    assert "could not find a biomechanically suitable match" in res["response_content"].lower()
    assert _slot_name(db, 1) == REVERSE_LAT_DISPLAY_NAME.lower()


def test_followup_hint_uses_real_catalog_name(sub_db, monkeypatch):
    monkeypatch.setattr(DatabaseManager, "find_exercises_by_name", lambda self, query, limit=5: [])
    variants = [
        {
            "id": MACHINE_LAT_VARIANT,
            "name": "Reverse-Grip Pulldown (Plate-Loaded)",
            "source_name": "lever reverse grip lateral pulldown",
            "target_muscle": "lats",
            "body_part": "back",
            "equipment": "leverage machine",
            "distance": 0.10,
        },
        {
            "id": "7",
            "name": "Single-Arm Lat Pulldown (Cable)",
            "source_name": "alternate lateral pulldown",
            "target_muscle": "lats",
            "body_part": "back",
            "equipment": "cable",
            "distance": 0.11,
        },
    ]
    monkeypatch.setattr(DatabaseManager, "search_similar_exercises", lambda self, vec, limit=5: variants)

    res = exercise_substitution_node(_state(REVERSE_LAT_DISPLAY_NAME, "something easier on my elbows"), {"configurable": {"ledger": sub_db.ledger, "store": sub_db}})
    assert res["program_updated"] is True
    assert f"swap {REVERSE_LAT_DISPLAY_NAME} for Single-Arm Lat Pulldown (Cable)" in res["response_content"]
    assert "swap for cable machine" not in res["response_content"]
    assert _slot_name(sub_db, 1) == "reverse-grip pulldown (plate-loaded)"
    active = sub_db.ledger.get_active_program()
    assert active.version == 2
    assert active.published_by_coach_account_id is None


@pytest.mark.parametrize(
    "access,expected_names",
    [
        (COMMERCIAL_GYM, {"Standing Cable Pulldown (Cable)", "Parallel-Grip Lat Pulldown (Cable)"}),
        (HOME_GYM, {"Band Underhand Pulldown", "Wide-Grip Pull-Up"}),
        (BODYWEIGHT_ONLY, {"Wide-Grip Pull-Up"}),
    ],
)
def test_unspecified_chat_substitutes_follow_equipment_access(sub_db, monkeypatch, access, expected_names):
    sub_db.ledger.upsert_player_profile({
        "gender": "male", "proportions": "balanced", "age": 30,
        "weight_kg": 80, "height_cm": 180, "rep_preference": "balanced",
        "current_goal": "hypertrophy", "long_term_goal": "strength",
        "weekly_frequency": 3, "training_age_years": 3,
        "equipment_access": access, "injuries_or_limitations": "None",
        "stress_and_sleep": "normal",
    })
    program = sub_db.ledger.get_active_program().model_dump()
    program["days"][0]["exercises"][1]["suggested_substitutes"] = [
        {"exercise_id": "2330", "exercise_name": "Standing Cable Pulldown (Cable)"},
        {"exercise_id": "818", "exercise_name": "Parallel-Grip Lat Pulldown (Cable)"},
        {"exercise_id": "1013", "exercise_name": "Band Underhand Pulldown"},
        {"exercise_id": "1429", "exercise_name": "Wide-Grip Pull-Up"},
    ]
    sub_db.ledger.save_training_program(program)
    monkeypatch.setattr(
        sub_db, "search_similar_exercises",
        lambda *_args, **_kwargs: pytest.fail("unspecified chat replacement must use suggested Staples"),
    )

    result = exercise_substitution_node(
        _state(REVERSE_LAT_DISPLAY_NAME, None),
        {"configurable": {"ledger": sub_db.ledger, "store": sub_db}},
    )

    shown = {
        name for name in (
            "Standing Cable Pulldown (Cable)", "Parallel-Grip Lat Pulldown (Cable)",
            "Band Underhand Pulldown", "Wide-Grip Pull-Up",
        ) if name in result["response_content"]
    }
    assert shown == expected_names
