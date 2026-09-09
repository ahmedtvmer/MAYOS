# tests/test_plate_calculator.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from utils.logger import MyosLogger
from utils.plate_calculator import calculate_barbell_plates

logger = MyosLogger().get_logger(__name__)


def test_standard_loads():
    """Validates standard heavy and intermediate plate distributions."""
    # 1. 100 kg on standard 20 kg bar -> 80 kg total plates -> 40 kg per side = [25, 15] or [20, 20]
    res_100 = calculate_barbell_plates(100.0, bar_weight_kg=20.0)
    assert res_100["effective_weight_kg"] == 100.0
    assert res_100["weight_per_side_kg"] == 40.0
    assert res_100["plates_per_side"] == [25.0, 15.0]
    assert res_100["formatted_display"] == "100 kg = Bar + [25, 15] kg/side"

    # 2. 142.5 kg on standard 20 kg bar -> 122.5 kg total plates -> 61.25 kg per side = [25, 25, 10, 1.25]
    res_142_5 = calculate_barbell_plates(142.5, bar_weight_kg=20.0)
    assert res_142_5["effective_weight_kg"] == 142.5
    assert res_142_5["weight_per_side_kg"] == 61.25
    assert res_142_5["plates_per_side"] == [25.0, 25.0, 10.0, 1.25]

    # 3. 60 kg on standard 20 kg bar -> 20 kg per side = [20]
    res_60 = calculate_barbell_plates(60.0, bar_weight_kg=20.0)
    assert res_60["plates_per_side"] == [20.0]
    assert res_60["formatted_display"] == "60 kg = Bar + [20] kg/side"

    logger.info("✅ Standard load plate calculations verified.")


def test_sub_bar_and_empty_bar():
    """Validates boundary conditions when target is less than or equal to bar weight."""
    # Empty bar exactly
    res_20 = calculate_barbell_plates(20.0, bar_weight_kg=20.0)
    assert res_20["effective_weight_kg"] == 20.0
    assert res_20["plates_per_side"] == []
    assert res_20["formatted_display"] == "20 kg (Empty Bar)"

    # Sub-bar weight request
    res_sub = calculate_barbell_plates(15.0, bar_weight_kg=20.0)
    assert res_sub["effective_weight_kg"] == 20.0
    assert res_sub["plates_per_side"] == []
    assert res_sub["formatted_display"] == "20 kg (Empty Bar)"

    # Zero or negative load
    res_zero = calculate_barbell_plates(0.0, bar_weight_kg=20.0)
    assert res_zero["effective_weight_kg"] == 20.0
    assert res_zero["plates_per_side"] == []

    logger.info("✅ Sub-bar and empty bar boundary guards verified.")


def test_quantization_and_rounding():
    """Validates snapping non-divisible weights to the nearest symmetric 2.5 kg step."""
    # 101.8 kg -> snaps to 102.5 kg
    res_round_up = calculate_barbell_plates(101.8, bar_weight_kg=20.0)
    assert res_round_up["effective_weight_kg"] == 102.5
    assert res_round_up["weight_per_side_kg"] == 41.25
    assert res_round_up["plates_per_side"] == [25.0, 15.0, 1.25]

    # 101.1 kg -> snaps to 100.0 kg
    res_round_down = calculate_barbell_plates(101.1, bar_weight_kg=20.0)
    assert res_round_down["effective_weight_kg"] == 100.0
    assert res_round_down["weight_per_side_kg"] == 40.0
    assert res_round_down["plates_per_side"] == [25.0, 15.0]

    logger.info("✅ Quantization and 2.5kg rounding verified.")


def run_all():
    logger.info("⚡ Running Plate Calculator Test Suite...\n")
    test_standard_loads()
    test_sub_bar_and_empty_bar()
    test_quantization_and_rounding()
    logger.info("\n🎉 All Plate Calculator tests passed successfully.")


if __name__ == "__main__":
    run_all()
