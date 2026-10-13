import sys
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

import pytest
from langchain_core.messages import AIMessage

from agent import program_generator
from agent.program_blueprints import match_split_keyword
from agent.program_generator import (
    ProgramGenerationRequest,
    _recognized_split_preference,
    has_supported_split_keyword,
)
from agent.program_rules import fetch_filtered_candidates, get_default_split, resolve_split
from tests.fakes.chat_model import ScriptedChatModel
from utils.logger import MyosLogger
from utils.player_output_budgets import DYNAMIC_SPLIT_PLAN_MAX_OUTPUT_TOKENS

logger = MyosLogger().get_logger(__name__)


def _split_generation_profile():
    return {
        "gender": "male",
        "weekly_frequency": 4,
        "equipment_access": "commercial gym",
        "injuries_or_limitations": "None",
        "rep_preference": "balanced",
        "training_age_years": 3.0,
        "stress_and_sleep": "normal",
    }


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


@pytest.mark.parametrize(
    ("content", "finish_reason"),
    [
        pytest.param('{"split_name":"Partial plan","days":[{"day_order":1', "length", id="truncated-json"),
        pytest.param('{"split_name":', "stop", id="unparseable-json"),
        pytest.param(
            get_default_split(3).model_copy(update={"split_name": "Incomplete generated plan"}).model_dump_json(),
            "length",
            id="parsed-object-with-length-finish-reason",
        ),
    ],
)
def test_406_truncated_or_unparseable_dynamic_split_falls_back_to_default(
    monkeypatch, content, finish_reason
):
    model = ScriptedChatModel(
        [AIMessage(content=content, response_metadata={"finish_reason": finish_reason})]
    )
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Create a custom three-day split with varied emphasis",
    )

    assert plan == get_default_split(3)


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


@pytest.mark.parametrize(
    ("preference", "expected_split"),
    [
        ("علوي و سفلي", "upper_lower"),
        ("سفلي علوي", "upper_lower"),
        ("سفلي/علوي", "upper_lower"),
        ("فوق - تحت", "upper_lower"),
        ("علوي يومين وسفلي يومين", "upper_lower"),
        ("تحت وفوق", "upper_lower"),
        ("العلوية والسفلية", "upper_lower"),
        ("الجزء العلوى والسفلى", "upper_lower"),
        ("عُلْوِيّ/سُفْلِيّ", "upper_lower"),
        ("fo2 w ta7t", "upper_lower"),
        ("UL", "upper_lower"),
        ("U/L", "upper_lower"),
        ("u/l", "upper_lower"),
        ("fb", "full_body"),
        ("FB", "full_body"),
        ("دفع/سحب", None),
        ("سحب/دفع", None),
        ("دفع - سحب - رجل", "ppl"),
        ("أرجل - سحب - دفع", "ppl"),
        ("سحب/دفع/رجل", "ppl"),
        ("دفع وسحب وارجل", "ppl"),
        ("بوش بول ليجز", "ppl"),
        ("بوش بول ليغز", "ppl"),
        ("dafa3 w sa7b w arjel", "ppl"),
        ("daf3 w sa7b w regleen", "ppl"),
        ("p/p/l", "ppl"),
        ("جسم كامِل", "full_body"),
        ("الجسم الكامل", "full_body"),
        ("فول بادي", "full_body"),
        ("فول بودي", "full_body"),
        ("فول بدي", "full_body"),
        ("فل بادي", "full_body"),
        ("فل بودي", "full_body"),
        ("f/b", "full_body"),
        ("أرنولد", "arnold"),
        ("أمامي/خلفي", "anterior_posterior"),
        ("خلفي وأمامي", "anterior_posterior"),
        ("amami w khalfi", "anterior_posterior"),
        ("برو سبليت", None),
        ("برو سبلت", None),
        ("جلوتس", None),
        ("ليجز", None),
        ("المؤخرة", None),
        ("الجلوتس", None),
        ("الأرداف", None),
        ("الجسم بالكامل", "full_body"),
        ("كل الجسم", "full_body"),
    ],
)
def test_translated_split_terms_route_through_existing_keyword_matcher(
    preference, expected_split
):
    translated = _recognized_split_preference(preference)

    assert translated is not None
    if expected_split is not None:
        assert match_split_keyword(translated) == expected_split


@pytest.mark.parametrize(
    "preference",
    [
        "عايز تمارين للكتف الخلفي",
        "الكتف الأمامي",
        "الكتف الأمامي والخلفي",
        "الأكتاف الأمامية والخلفية",
        "دفع",
        "الدفع",
        "دفع وأرجل",
        "سحب",
        "السحب",
        "سحب وأرجل",
        "بول",
        "أمامي",
        "خلفي",
    ],
)
def test_body_region_and_single_push_pull_terms_are_not_split_overrides(preference):
    assert not has_supported_split_keyword(preference)


@pytest.mark.parametrize(
    ("preference", "expected_split"),
    [
        ("upper lower but fb on saturday", "upper_lower"),
        ("PPL, ul is boring", "ppl"),
    ],
)
def test_english_preferences_accepted_before_translation_keep_old_routing(
    preference, expected_split
):
    assert _recognized_split_preference(preference) == preference
    assert match_split_keyword(preference) == expected_split


def test_split_translation_keeps_other_player_words():
    assert _recognized_split_preference("علوي يومين وسفلي يومين") == (
        "upper يومين lower يومين"
    )
    assert _recognized_split_preference("سحب يومين ودفع يومين") == (
        "push pull يومين يومين"
    )


@pytest.mark.parametrize(
    ("preference", "expected_split_name"),
    [
        ("علوي و سفلي", "Upper / Lower (Arms & Delts Augmented)"),
        ("u/l", "Upper / Lower (Arms & Delts Augmented)"),
        ("دفع/سحب/أرجل", "Push / Pull / Legs / Push"),
        ("p/p/l", "Push / Pull / Legs / Push"),
        ("PPL", "Push / Pull / Legs / Push"),
        ("جسم كامل", "Full Body 4-Day"),
        ("f/b", "Full Body 4-Day"),
        ("أرنولد", "Arnold x Upper/Lower (4-Day)"),
        ("أمامي/خلفي", "Anterior / Posterior Split"),
        ("الجسم بالكامل", "Full Body 4-Day"),
    ],
)
def test_arabic_and_abbreviated_split_preferences_apply_blueprints(
    fresh_store, preference, expected_split_name
):
    program, _ = program_generator.generate_program_draft_pipeline(
        ProgramGenerationRequest(user_split_override=preference),
        inference_call=lambda *_args, **_kwargs: pytest.fail(
            "recognized split unexpectedly called the model"
        ),
        ledger=fresh_store.ledger,
        profile=_split_generation_profile(),
    )

    assert program.split_type == expected_split_name


@pytest.mark.parametrize(
    ("preference", "translated_request"),
    [("أريد برو سبليت", "اريد bro split"), ("أريد جلوتس", "اريد glute")],
)
def test_dynamic_split_translation_preserves_the_players_request(
    monkeypatch, fresh_store, preference, translated_request
):
    model = ScriptedChatModel([get_default_split(4)])
    monkeypatch.setattr("agent.program_rules.llm", model)

    program, _ = program_generator.generate_program_draft_pipeline(
        ProgramGenerationRequest(user_split_override=preference),
        ledger=fresh_store.ledger,
        profile=_split_generation_profile(),
    )

    assert program.split_type == get_default_split(4).split_name
    assert len(model.calls) == 1
    assert translated_request in model.calls[0]["messages"][1].content


if __name__ == "__main__":
    test_rules()
