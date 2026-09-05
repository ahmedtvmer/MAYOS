import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.program_rules import resolve_split, calculate_volume_budget, fetch_filtered_candidates
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)
db = DatabaseManager()

def test_rules():
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

    logger.info("\n--- 3. Testing Recovery Volume Budgeting ---")
    low_recovery_vol = calculate_volume_budget("high stress, 5 hours sleep")
    high_recovery_vol = calculate_volume_budget("good sleep, 8 hours, low stress")
    logger.info(f"Low recovery sets/week: {low_recovery_vol}")
    logger.info(f"High recovery sets/week: {high_recovery_vol}")
    assert low_recovery_vol == 8
    assert high_recovery_vol == 12

    logger.info("\n--- 4. Testing Candidate Retrieval & Contraindication Filters ---")
    candidates = fetch_filtered_candidates(
        body_part="back", 
        equipment_access="commercial gym", 
        limitations="lower back tightness",
        limit=3
    )
    for c in candidates:
        logger.info(f"  [ID {c['id']}] {c['name']} (Target: {c['target_muscle']})")
        assert "deadlift" not in c["name"].lower()

    logger.info("\nAll deterministic and dynamic program rules passed.")

if __name__ == "__main__":
    test_rules()