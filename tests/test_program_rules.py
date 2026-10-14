import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

import pytest
from langchain_core.messages import AIMessage

from agent import program_generator
from agent.program_blueprints import SLOT_SPECS, match_split_keyword
from agent.program_generator import (
    ProgramGenerationRequest,
    _recognized_split_preference,
    has_supported_split_keyword,
)
from agent.ProgramState import DynamicSplitPlan
from agent.program_rules import (
    fetch_filtered_candidates,
    get_default_split,
    resolve_split,
    valid_splits_for,
)
from tests.fakes.chat_model import ScriptedChatModel, StructuredValue
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
        "mayos:4": "compound",  # Machine Hip Thrust (Plate-Loaded): curated Hip Extension, like the barbell one.
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


def test_dynamic_split_uses_bounded_schema_and_output_budget(monkeypatch):
    from agent.ProgramState import (
        MAX_DYNAMIC_DOUBLE_SLOTS_PER_DAY,
        MAX_DYNAMIC_TARGET_SLOTS_PER_DAY,
        MAX_PROGRAM_DAYS,
    )
    from agent.program_prescription import MAX_EXERCISES_PER_DAY

    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
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
    assert model.calls[0]["kwargs"]["method"] == "function_calling"
    schema = model.calls[0]["kwargs"]["structured_schema"].model_json_schema()
    day_schema = schema["$defs"]["CustomDayPlan"]["properties"]
    assert day_schema["target_slots"]["maxItems"] == MAX_DYNAMIC_TARGET_SLOTS_PER_DAY
    assert day_schema["double_slots"]["maxItems"] == MAX_DYNAMIC_DOUBLE_SLOTS_PER_DAY
    assert day_schema["target_slots"]["maxItems"] + day_schema["double_slots"]["maxItems"] <= MAX_EXERCISES_PER_DAY
    assert schema["properties"]["days"]["minItems"] == 1
    assert schema["properties"]["days"]["maxItems"] == MAX_PROGRAM_DAYS


def test_dynamic_split_retries_short_plan_through_inference_call(monkeypatch):
    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    default_plan = get_default_split(3)
    short_plan = default_plan.model_copy(update={"days": default_plan.days[:2]})
    good_plan = default_plan.model_copy(update={"split_name": "Recovered custom plan"})
    model = ScriptedChatModel([short_plan, good_plan])
    monkeypatch.setattr("agent.program_rules.llm", model)
    inference_calls = []

    def injected_inference(invoke, prompt):
        inference_calls.append(prompt)
        return invoke(prompt)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days",
        inference_call=injected_inference,
    )

    assert plan == good_plan
    assert len(inference_calls) == len(model.calls) == 2
    assert model.calls[0]["kwargs"] == model.calls[1]["kwargs"]
    assert model.calls[0]["kwargs"]["max_completion_tokens"] == DYNAMIC_SPLIT_PLAN_MAX_OUTPUT_TOKENS


def test_dynamic_split_falls_back_when_retry_has_empty_slot_days(monkeypatch):
    from agent.program_rules import _sanitize_llm_plan

    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    default_plan = get_default_split(3)
    short_plan = default_plan.model_copy(update={"days": default_plan.days[:2]})
    retry_days = list(default_plan.days)
    retry_days[1] = retry_days[1].model_copy(
        update={"target_slots": [], "target_body_parts": ["chest", "lats", "triceps"]}
    )
    empty_slot_retry = default_plan.model_copy(
        update={"split_name": "Invalid retry", "days": retry_days}
    )
    model = ScriptedChatModel([short_plan, empty_slot_retry])
    monkeypatch.setattr("agent.program_rules.llm", model)
    inference_calls = []

    def injected_inference(invoke, prompt):
        inference_calls.append(prompt)
        return invoke(prompt)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days",
        inference_call=injected_inference,
    )

    assert plan == default_plan
    assert _sanitize_llm_plan(empty_slot_retry, 3, "male") == default_plan
    assert len(inference_calls) == len(model.calls) == 2
    assert plan != empty_slot_retry
    assert all(day.target_slots for day in plan.days)


def test_dynamic_split_truncates_overlong_plan_without_retry(monkeypatch):
    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    overlong_plan = get_default_split(4).model_copy(update={"split_name": "Overlong custom plan"})
    model = ScriptedChatModel([overlong_plan])
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days",
    )

    assert plan.split_name == "Overlong custom plan"
    assert plan.days == overlong_plan.days[:3]
    assert len(model.calls) == 1


def test_dynamic_split_uses_good_first_plan_without_retry(monkeypatch):
    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    good_plan = get_default_split(3)
    model = ScriptedChatModel([good_plan])
    monkeypatch.setattr("agent.program_rules.llm", model)
    inference_calls = []

    def injected_inference(invoke, prompt):
        inference_calls.append(prompt)
        return invoke(prompt)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days",
        inference_call=injected_inference,
    )

    assert plan == good_plan
    assert len(inference_calls) == len(model.calls) == 1


def test_dynamic_split_caps_overfull_day_for_generated_program(monkeypatch, fresh_store):
    from agent.ProgramState import GeneratedProgramSchema, MAX_DYNAMIC_TARGET_SLOTS_PER_DAY
    from agent.program_prescription import MAX_EXERCISES_PER_DAY

    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    default_plan = get_default_split(3)
    target_slots = list(SLOT_SPECS)[:16]
    days = list(default_plan.days)
    days[0] = days[0].model_copy(
        update={"target_slots": target_slots, "double_slots": target_slots[:4]}
    )
    overfull_plan = default_plan.model_copy(update={"days": days})
    model = ScriptedChatModel([StructuredValue(overfull_plan)])
    monkeypatch.setattr("agent.program_rules.llm", model)
    resolved_plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days",
    )
    request = ProgramGenerationRequest(frequency_override=3)
    generated_days = program_generator._generate_program_days(
        _split_generation_profile(), request, resolved_plan, fresh_store.ledger
    )
    generated = GeneratedProgramSchema(
        program_name=resolved_plan.split_name,
        split_type=resolved_plan.split_name,
        weekly_frequency=len(resolved_plan.days),
        days=generated_days,
    )

    assert len(target_slots) + 4 > MAX_EXERCISES_PER_DAY
    assert len(model.calls) == 1
    assert resolved_plan.days[0].target_slots == target_slots[:MAX_DYNAMIC_TARGET_SLOTS_PER_DAY]
    assert resolved_plan.days[0].double_slots == []
    assert all(len(day.exercises) <= MAX_EXERCISES_PER_DAY for day in generated.days)
    assert GeneratedProgramSchema.model_validate(generated.model_dump()) == generated


def test_dynamic_split_retries_empty_target_slots(monkeypatch):
    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    default_plan = get_default_split(3)
    days = list(default_plan.days)
    days[0] = days[0].model_copy(update={"target_slots": []})
    empty_slot_plan = default_plan.model_copy(update={"days": days})
    model = ScriptedChatModel([empty_slot_plan, default_plan])
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days",
    )

    assert plan == default_plan
    assert len(model.calls) == 2


def test_dynamic_split_retries_overlong_structured_response_before_fallback(monkeypatch):
    from agent.ProgramState import (
        MAX_DYNAMIC_DOUBLE_SLOTS_PER_DAY,
        MAX_DYNAMIC_TARGET_SLOTS_PER_DAY,
    )

    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    default_plan = get_default_split(3)
    overlong_payload = default_plan.model_dump()
    overlong_payload["days"][0]["target_slots"] = list(SLOT_SPECS)[: MAX_DYNAMIC_TARGET_SLOTS_PER_DAY + 1]
    overlong_payload["days"][0]["double_slots"] = list(SLOT_SPECS)[: MAX_DYNAMIC_DOUBLE_SLOTS_PER_DAY + 1]
    model = ScriptedChatModel([overlong_payload, overlong_payload])
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days",
    )

    assert plan == default_plan
    assert len(model.calls) == 2


def test_custom_split_prompt_is_formatted_and_valid_output_survives_sanitization(monkeypatch):
    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    candidate = get_default_split(3)
    model = ScriptedChatModel([candidate])
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Custom split with separate balanced emphasis days",
        gender="female",
    )

    assert plan == candidate
    prompt = model.calls[0]["messages"][0].content
    assert "{frequency}" not in prompt
    normalized_prompt = " ".join(prompt.casefold().split())
    assert "12 slots" in normalized_prompt
    assert "2 double_slots" in normalized_prompt
    assert re.search(r"beginners.{0,100}1-2 rir.{0,100}compound", normalized_prompt)
    assert re.search(r"intermediate and advanced.{0,120}0-1 rir.{0,120}compound", normalized_prompt)
    assert "technical failure" in normalized_prompt
    assert all(
        rest in normalized_prompt
        for rest in ("3-4 minutes", "2-3 minutes", "1.5-2 minutes")
    )


def test_dynamic_split_plan_schema_constrains_warmup_family():
    from agent.program_blueprints import WARMUP_FAMILIES

    schema = DynamicSplitPlan.model_json_schema()
    assert set(schema["$defs"]["CustomDayPlan"]["properties"]["warmup_family"]["enum"]) == set(WARMUP_FAMILIES)


def test_split_plan_with_invented_warmup_family_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "false")
    invalid = get_default_split(3).model_dump()
    invalid["days"][0]["warmup_family"] = "dynamic lower body + banded glute activation"
    model = ScriptedChatModel([invalid, invalid])
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(3, preference="Custom weekly arrangement with separate emphasis days")

    assert plan == get_default_split(3)
    assert len(model.calls) == 2


def test_split_plan_keeps_separate_reasoning_metadata_out_of_parsed_fields(monkeypatch):
    monkeypatch.setenv("PROGRAM_GENERATION_REASONING_ENABLED", "true")
    plan_from_tool_call = get_default_split(3)
    model = ScriptedChatModel(
        [
            AIMessage(
                content="",
                additional_kwargs={
                    "reasoning_content": "<think>private planning text</think>",
                    "scripted_structured_value": plan_from_tool_call,
                },
            )
        ]
    )
    monkeypatch.setattr("agent.program_rules.llm", model)

    resolved_plan = resolve_split(
        3,
        preference="Build three custom sessions with balanced movement emphasis.",
    )

    assert resolved_plan == plan_from_tool_call
    assert "private planning text" not in resolved_plan.model_dump_json()


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
    invalid_response = AIMessage(content=content, response_metadata={"finish_reason": finish_reason})
    model = ScriptedChatModel([invalid_response, invalid_response])
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Create a custom three-day split with varied emphasis",
    )

    assert plan == get_default_split(3)
    assert len(model.calls) == 2


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


@pytest.mark.parametrize(
    ("preference", "expected_name"),
    [
        ("PPL", "PPL × UL"),
        ("PPL × UL", "PPL × UL"),
        ("Arnold × Upper/Lower", "Arnold × Upper/Lower"),
    ],
)
def test_five_day_hybrid_keywords_resolve_to_the_named_split(preference, expected_name):
    plan = resolve_split(5, preference)

    assert plan.split_name == expected_name


def test_issue_232_glute_priority_prose_uses_the_injected_model_path():
    request = (
        "Arrange four weekly sessions by front-side and back-side movement emphasis, "
        "with a glute priority."
    )
    model_plan = get_default_split(4, "female").model_copy(
        update={"split_name": "Model-selected split"}
    )

    def run_model(_invoke, _messages):
        return {"parsed": model_plan}

    plan = resolve_split(4, request, gender="female", inference_call=run_model)

    assert plan.split_name == "Model-selected split"


@pytest.mark.parametrize(
    ("frequency", "gender", "split_type", "expected_name"),
    [
        (4, "male", "upper_lower", "Upper / Lower (Arms & Delts Augmented)"),
        (4, "female", "female_full_body", "Full Body (Glute Priority)"),
        (4, "female", "female_upper_lower", "Lower (Glute Bias) / Upper & Core"),
    ],
)
def test_catalog_split_family_keys_route_deterministically(
    frequency, gender, split_type, expected_name
):
    assert _recognized_split_preference(split_type) == split_type
    plan = resolve_split(frequency, split_type, gender)

    assert plan.split_name == expected_name


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
        ("دفع/سحب/أرجل", "Upper / Lower (Arms & Delts Augmented)"),
        ("p/p/l", "Upper / Lower (Arms & Delts Augmented)"),
        ("PPL", "Upper / Lower (Arms & Delts Augmented)"),
        ("جسم كامل", "Full Body 4-Day"),
        ("f/b", "Full Body 4-Day"),
        ("أرنولد", "Upper / Lower (Arms & Delts Augmented)"),
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


def test_valid_splits_for_matches_the_parent_frequency_table():
    expected = {
        1: [],
        2: [
            ("full_body", "Full Body"),
            ("upper_lower", "Upper/Lower"),
            ("anterior_posterior", "Anterior / Posterior"),
        ],
        3: [
            ("full_body", "Full Body"),
            ("female_full_body", "Full Body (Glute Priority)"),
            ("upper_lower", "Upper/Lower/Upper"),
            ("anterior_posterior", "Anterior / Posterior"),
            ("ppl", "PPL"),
            ("arnold", "Arnold"),
        ],
        4: [
            ("full_body", "Full Body"),
            ("female_full_body", "Full Body (Glute Priority)"),
            ("upper_lower", "Upper/Lower"),
            ("anterior_posterior", "Anterior / Posterior"),
        ],
        5: [
            ("full_body", "Full Body"),
            ("female_full_body", "Full Body (Glute Priority)"),
            ("upper_lower", "Upper/Lower ×2 + Upper"),
            ("anterior_posterior", "Anterior / Posterior"),
            ("arnold_x_ul", "Arnold × Upper/Lower"),
            ("ppl_x_ul", "PPL × UL"),
        ],
    }

    for gender in ("male", "female"):
        for frequency, choices in expected.items():
            assert valid_splits_for(frequency, gender) == choices

    assert [len(get_default_split(frequency, "male").days) for frequency in expected] == [1, 2, 3, 4, 5]
    assert [len(get_default_split(frequency, "female").days) for frequency in expected] == [1, 2, 3, 4, 5]


if __name__ == "__main__":
    test_rules()
