import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.program_generator import generate_program_pipeline
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)
db = DatabaseManager()


def run_test():
    logger.info("--- Starting Phase 2 Program Generation ---")

    # 1. Mount isolated test ledger and seed baseline profile
    test_user = "test_generator_trainee"
    db.switch_user(test_user)
    db.upsert_user_profile({
        "gender": "male",
        "proportions": "balanced",
        "age": 22,
        "weight_kg": 80.0,
        "height_cm": 180.0,
        "rep_preference": "balanced",
        "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload",
        "weekly_frequency": 4,
        "training_age_years": 3.0,
        "equipment_access": "commercial gym",
        "injuries_or_limitations": "None",
        "stress_and_sleep": "normal"
    })

    # 2. Execute program synthesis
    program, table_view = generate_program_pipeline()

    # 3. Assertions
    assert program is not None, "Failed: Program generation returned None."
    assert len(program.days) == 4, f"Expected 4 training days, got {len(program.days)}"
    assert db.get_active_program() is not None, "Failed: Program not persisted to SQLite."

    logger.info("\n" + "=" * 50)
    logger.info(table_view)
    logger.info("=" * 50)
    logger.info("\nPhase 2 Program Generation & Database Persistence Verified.")


if __name__ == "__main__":
    run_test()