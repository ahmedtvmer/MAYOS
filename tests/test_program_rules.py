import sys
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

import pytest

from agent.program_rules import fetch_filtered_candidates, get_default_split, resolve_split
from tests.fakes.chat_model import ScriptedChatModel
from utils.logger import MyosLogger
from utils.player_output_budgets import DYNAMIC_SPLIT_PLAN_MAX_OUTPUT_TOKENS

logger = MyosLogger().get_logger(__name__)


@pytest.fixture(autouse=True)
def _bind_store(fresh_store):
    """Each test runs against its own catalog/ledger store (ADR 041)."""
    return fresh_store


def test_rules(fresh_store):
    logger.info("--- 1. Testing Default Presets & Frequency Clamping ---")
    # Test 6-day frequency clamp
    plan_6d = resolve_split(6)
    assert len(plan_6d.days) == 5, f"Expected 5 days max, got {len(plan_6d.days)}"
    logger.info(f"6-day clamped to: {len(plan_6d.days)} days ({plan_6d.split_name})")
    for day in plan_6d.days:
        logger.info(f"  Day {day.day_order}: {day.day_name} -> {day.target_body_parts}")

    # Test 2-day preset
    plan_2d = resolve_split(2)
    assert len(plan_2d.days) == 2
    logger.info(f"\n2-day preset: {plan_2d.split_name}")
    for day in plan_2d.days:
        logger.info(f"  Day {day.day_order}: {day.day_name} -> {day.target_body_parts}")

    logger.info("\n--- 2. Testing Dynamic Flexible Split Preference ---")
    # Test user asking for an unusual 3-day split: Upper / Lower / Arms
    custom_pref = "I want Upper, Lower, and an isolated Arms & Shoulders day"
    plan_custom = resolve_split(3, preference=custom_pref)
    logger.info(f"Custom 3-day request resolved to: '{plan_custom.split_name}'")
    for day in plan_custom.days:
        logger.info(f"  Day {day.day_order}: {day.day_name} -> {day.target_body_parts}")
    assert len(plan_custom.days) == 3

    logger.info("\n--- 3. Testing Candidate Retrieval & Contraindication Filters ---")
    candidates = fetch_filtered_candidates(
        body_part="back",
        equipment_access="commercial gym",
        limitations="lower back tightness",
        limit=3,
        ledger=fresh_store.ledger,
    )
    for c in candidates:
        logger.info(f"  [ID {c['id']}] {c['name']} (Target: {c['target_muscle']})")
        assert "deadlift" not in c["name"].lower()
    logger.info("\nAll deterministic and dynamic program rules passed.")


def test_filtered_generation_candidates_omit_hidden_exercises(fresh_store, seed_exercise_curation):
    from agent.program_blueprints import SLOT_STAPLES

    staple_ids = {exercise_id for staple_ids in SLOT_STAPLES.values() for exercise_id in staple_ids}
    candidates = fetch_filtered_candidates(
        muscle_group="chest",
        equipment_access="commercial gym",
        limit=100,
        ledger=fresh_store.ledger,
    )
    hidden_id = next(
        str(candidate["id"])
        for candidate in candidates
        if str(candidate["id"]) not in staple_ids
    )
    seed_exercise_curation(fresh_store, {hidden_id: {"hidden": True}})

    candidates = fetch_filtered_candidates(
        muscle_group="chest",
        equipment_access="commercial gym",
        limit=100,
        ledger=fresh_store.ledger,
    )
    assert hidden_id not in {str(candidate["id"]) for candidate in candidates}


def test_mechanics_for_real_curated_exercises_use_joint_actions(fresh_store):
    from agent.program_generator import MECHANIC_CUES, get_biomechanical_cue
    from agent.program_rules import exercise_mechanic

    expected = {
        "85": "compound",       # Romanian Deadlift (Barbell)
        "116": "compound",      # Stiff-Leg Deadlift (Barbell)
        "3562": "compound",     # Hip Thrust (Barbell)
        "mayos:4": "isolation", # Machine Hip Thrust has no action curation; use its name rule.
        "585": "isolation",     # Leg Extension (Machine)
        "586": "isolation",     # Lying Leg Curl (Machine)
        "1638": "isolation",    # Pulldown-Station Curl (Cable)
        "602": "isolation",     # Reverse Pec Deck (Machine)
        "225": "isolation",     # High Reverse Fly (Cable)
        "305": "isolation",     # Kelso Shrug (Dumbbell)
        "1774": "isolation",    # Side Plank Hip Abduction
        "237": "isolation",     # Rope Straight-Arm Pulldown (Cable)
        "43": "compound",       # Back Squat (Barbell)
        "150": "compound",      # Lat Pulldown (Cable)
        "274": "isolation",     # Crunch
        "472": "isolation",     # Hanging Leg Raise
        "334": "isolation",     # Lateral Raise (Dumbbell)
    }
    entries = {exercise_id: fresh_store.get_exercise_library_entry(exercise_id) for exercise_id in expected}

    assert all(entries.values())
    assert all(fresh_store.is_exercise_library_exercise_visible(exercise_id) for exercise_id in expected)
    assert {exercise_id: exercise_mechanic(entry) for exercise_id, entry in entries.items()} == expected
    assert "pulldown" in entries["1638"]["name"].casefold()
    assert exercise_mechanic("Incline Press") == "compound"
    assert get_biomechanical_cue(entries["237"], "intermediate") == MECHANIC_CUES["isolation_technical_failure"]
    assert get_biomechanical_cue(entries["43"], "intermediate") == MECHANIC_CUES["compound_lower"]


def test_dynamic_split_plan_uses_its_own_output_budget(monkeypatch):
    model = ScriptedChatModel([get_default_split(3)])
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days for chest, back, and arms",
    )

    assert len(plan.days) == 3
    assert len(model.calls) == 1
    assert model.calls[0]["mode"] == "structured"
    assert model.calls[0]["kwargs"]["schema"] == "DynamicSplitPlan"
    assert model.calls[0]["kwargs"]["max_completion_tokens"] == DYNAMIC_SPLIT_PLAN_MAX_OUTPUT_TOKENS


def test_dynamic_split_uses_the_generation_metering_scope(monkeypatch):
    model = ScriptedChatModel([get_default_split(3)])
    monkeypatch.setattr("agent.program_rules.llm", model)
    calls = []

    def injected_inference(function, *args, **kwargs):
        calls.append((function, args))
        return function(*args, **kwargs)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days for chest, back, and arms",
        inference_call=injected_inference,
    )

    assert len(plan.days) == 3
    assert len(calls) == 1
    assert len(model.calls) == 1
    assert model.calls[0]["mode"] == "structured"


def test_blueprint_split_does_not_call_injected_inference():
    run_model = MagicMock(side_effect=AssertionError("deterministic split called the model"))

    plan = resolve_split(3, preference="ppl", inference_call=run_model)

    assert len(plan.days) == 3
    run_model.assert_not_called()


if __name__ == "__main__":
    test_rules()
