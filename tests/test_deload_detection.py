import sys
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.progression_engine import evaluate_systemic_fatigue
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def test_normal_recovery_state():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("s1", "2026-09-01", 4), ("s2", "2026-09-03", 5), ("s3", "2026-09-05", 4)],
        [("s1", 8.0), ("s1", 8.5), ("s2", 8.0), ("s3", 8.5)],
    ]
    mock_db.user_conn.cursor.return_value = mock_cursor

    res = evaluate_systemic_fatigue(mock_db)
    assert res["deload_recommended"] is False
    assert res["severity"] == "NORMAL"
    assert res["volume_multiplier"] == 1.0
    logger.info("✅ Normal recovery state verified.")


def test_rolling_readiness_crash():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("s1", "2026-09-01", 2), ("s2", "2026-09-03", 2), ("s3", "2026-09-05", 1)],
        [("s1", 9.0), ("s2", 9.0), ("s3", 9.0)],
    ]
    mock_db.user_conn.cursor.return_value = mock_cursor

    res = evaluate_systemic_fatigue(mock_db)
    assert res["deload_recommended"] is True
    assert res["severity"] == "HIGH"
    assert res["volume_multiplier"] == 0.5
    assert res["intensity_cap_rpe"] == 7.0
    assert "Rolling readiness crash" in res["reason"]
    logger.info("✅ Rolling readiness crash trigger verified.")


def test_acute_readiness_floor():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("s1", "2026-09-05", 1), ("s2", "2026-09-03", 4), ("s3", "2026-09-01", 4)],
        [("s1", 8.5)],
    ]
    mock_db.user_conn.cursor.return_value = mock_cursor

    res = evaluate_systemic_fatigue(mock_db)
    assert res["deload_recommended"] is True
    assert res["severity"] == "HIGH"
    assert "Acute readiness floor" in res["reason"]
    logger.info("✅ Acute readiness floor trigger verified.")


def test_high_exertion_density():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("s1", "2026-09-05", 3), ("s2", "2026-09-03", 3), ("s3", "2026-09-01", 3)],
        [("s1", 10.0), ("s1", 10.0), ("s2", 9.5), ("s2", 10.0), ("s3", 8.0), ("s3", 8.5)],
    ]
    mock_db.user_conn.cursor.return_value = mock_cursor

    res = evaluate_systemic_fatigue(mock_db)
    assert res["deload_recommended"] is True
    assert res["severity"] == "MODERATE"
    assert res["volume_multiplier"] == 0.6
    assert res["intensity_cap_rpe"] == 8.0
    logger.info("✅ High exertion density trigger verified.")


if __name__ == "__main__":
    test_normal_recovery_state()
    test_rolling_readiness_crash()
    test_acute_readiness_floor()
    test_high_exertion_density()
