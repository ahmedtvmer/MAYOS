# scripts/test_progression_engine.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.progression_engine import calculate_e1rm, project_next_load
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def run_tests():
    logger.info("⚡ Starting Dynamic RPE Progression Engine Tests...\n")

    # 1. Test e1RM Formulation
    e1rm = calculate_e1rm(weight_kg=100.0, reps=8, rpe=8.0)
    # Effective reps = 8 + (10 - 8) = 10 -> 100 * (1 + 10/30) = 133.33 kg
    assert abs(e1rm - 133.33) < 0.1, f"e1RM mismatch: {e1rm}"
    logger.info(f"✅ e1RM Calculated: 100kg x 8 @ RPE 8.0 -> {e1rm:.2f}kg e1RM")

    # 2. Test Dynamic Projection Upward (Achieved top of bracket with low RPE)
    # Target was 8 reps @ RPE 8.5. User did 8 reps @ RPE 7.0 (reserve velocity left)
    proj_up = project_next_load(
        last_weight=100.0, last_reps=8, last_rpe=7.0, target_reps=8, target_rpe=8.5, equipment="barbell"
    )
    assert proj_up["delta_kg"] > 0, "Failed to project weight increase on low RPE."
    assert proj_up["projected_weight"] % 2.5 == 0, "Failed to snap to 2.5kg barbell increment."
    logger.info(
        f"✅ Dynamic Upscale: 100kg @ RPE 7.0 -> Next Target: {proj_up['projected_weight']}kg (+{proj_up['delta_kg']}kg)"
    )

    # 3. Test RPE Overshoot Deload / Step-Down
    # User was supposed to hit RPE 8.0 but hit RPE 10.0 (absolute failure)
    proj_down = project_next_load(
        last_weight=100.0, last_reps=6, last_rpe=10.0, target_reps=8, target_rpe=8.0, equipment="barbell"
    )
    assert proj_down["delta_kg"] <= 0, "Failed to protect trainee on RPE 10 overshoot."
    logger.info(
        f"✅ Overshoot Protection: 100kg @ RPE 10.0 -> Next Target: {proj_down['projected_weight']}kg ({proj_down['delta_kg']}kg)"
    )

    logger.info("\n🎉 Dynamic RPE Progression calculations verified successfully.")


if __name__ == "__main__":
    run_tests()
