import sys
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

import pytest

from agent.program_rules import (
    DYNAMIC_SPLIT_PLAN_MAX_TOKENS,
    fetch_filtered_candidates,
    get_default_split,
    resolve_split,
)
from utils.logger import MyosLogger

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


def test_dynamic_split_plan_uses_its_own_output_budget(monkeypatch):
    model = MagicMock()
    model.with_structured_output.return_value.bind.return_value.invoke.return_value = get_default_split(3)
    monkeypatch.setattr("agent.program_rules.llm", model)

    plan = resolve_split(
        3,
        preference="Custom weekly arrangement with separate emphasis days for chest, back, and arms",
    )

    assert len(plan.days) == 3
    model.with_structured_output.assert_called_once()
    model.with_structured_output.return_value.bind.assert_called_once_with(
        max_tokens=DYNAMIC_SPLIT_PLAN_MAX_TOKENS
    )


def test_dynamic_split_uses_the_generation_metering_scope(monkeypatch):
    model = MagicMock()
    structured = model.with_structured_output.return_value.bind.return_value
    structured.invoke.return_value = get_default_split(3)
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
    structured.invoke.assert_called_once()


def test_blueprint_split_does_not_call_injected_inference():
    run_model = MagicMock(side_effect=AssertionError("deterministic split called the model"))

    plan = resolve_split(3, preference="ppl", inference_call=run_model)

    assert len(plan.days) == 3
    run_model.assert_not_called()


if __name__ == "__main__":
    test_rules()
