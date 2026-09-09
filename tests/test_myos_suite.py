import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from langchain_community.chat_models import ChatLlamaCpp
from langchain_core.messages import HumanMessage

from agent.assistant_graph import (
    clinical_intercept_node,
    router_node,
    stream_assistant_turn,
)
from agent.progression_engine import (
    calculate_e1rm,
    evaluate_systemic_fatigue,
    project_next_load,
)
from core.progression import calculate_epley_e1rm
from core.warmup import calculate_warmup_sets
from database.database_manager import DatabaseManager
from utils.plate_calculator import calculate_barbell_plates
from utils.text_scrubber import scrub_coach_output

# ============================================================================
# 1. BIOMECHANICS, WARMUP & PROGRESSION TESTS
# ============================================================================


def test_e1rm_formulations():
    # Epley baseline: 100kg x 1 rep = 100kg; 100kg x 10 reps = 133.3kg
    assert calculate_epley_e1rm(100.0, 1) == 100.0
    assert calculate_epley_e1rm(100.0, 10) == 133.3

    # RPE-adjusted e1RM: 100kg x 8 reps @ RPE 8.0 -> effective reps = 10 -> 133.33kg
    rpe_e1rm = calculate_e1rm(weight_kg=100.0, reps=8, rpe=8.0)
    assert abs(rpe_e1rm - 133.33) < 0.1


def test_plate_calculator_quantization():
    # Standard load
    res_100 = calculate_barbell_plates(100.0, bar_weight_kg=20.0)
    assert res_100["plates_per_side"] == [25.0, 15.0]

    # Non-divisible load snapping (101.8 kg -> 102.5 kg)
    res_snapped = calculate_barbell_plates(101.8, bar_weight_kg=20.0)
    assert res_snapped["effective_weight_kg"] == 102.5
    assert res_snapped["plates_per_side"] == [25.0, 15.0, 1.25]

    # Sub-bar boundary
    res_sub = calculate_barbell_plates(15.0, bar_weight_kg=20.0)
    assert res_sub["effective_weight_kg"] == 20.0
    assert res_sub["plates_per_side"] == []


def test_warmup_potentiating_ramp():
    warmups = calculate_warmup_sets(100.0, bar_weight_kg=20.0)
    assert len(warmups) == 3
    assert warmups[0]["load_kg"] == 40.0  # 40%
    assert warmups[1]["load_kg"] == 65.0  # 65%
    assert warmups[2]["load_kg"] == 85.0  # 85%


def test_dynamic_progression_logic():
    # Ceiling hit: 8 reps @ RPE 8.5 with target 8 reps -> advance load
    proj_step = project_next_load(
        last_weight=100.0,
        last_reps=8,
        last_rpe=8.5,
        target_reps_min=6,
        target_reps_max=8,
        target_rpe=8.5,
        equipment="barbell",
    )
    assert proj_step["status"] == "PROGRESSION_UP"
    assert proj_step["delta_kg"] == 2.5
    assert proj_step["projected_weight"] == 102.5

    # RPE 10 overshoot -> deload step down
    proj_down = project_next_load(
        last_weight=100.0,
        last_reps=6,
        last_rpe=10.0,
        target_reps_min=8,
        target_reps_max=10,
        target_rpe=8.0,
        equipment="barbell",
    )
    assert proj_down["status"] == "RPE_OVERSHOOT_DELOAD"
    assert proj_down["delta_kg"] == -2.5
    assert proj_down["projected_weight"] == 97.5


# ============================================================================
# 2. SYSTEMIC FATIGUE & DELOAD LOGIC
# ============================================================================


def test_systemic_fatigue_states():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.user_conn.cursor.return_value = mock_cursor

    # Case A: Acute readiness floor (Readiness = 1/5)
    mock_cursor.fetchall.side_effect = [[("s1", "2026-09-08", 1), ("s2", "2026-09-06", 4)], [("s1", 8.5)]]
    res_acute = evaluate_systemic_fatigue(mock_db)
    assert res_acute["deload_recommended"] is True
    assert res_acute["severity"] == "HIGH"
    assert res_acute["intensity_cap_rpe"] == 7.0

    # Case B: High exertion density (>= 50% sets >= RPE 9.5 and avg readiness <= 3.0)
    mock_cursor.fetchall.side_effect = [
        [("s1", "2026-09-08", 3), ("s2", "2026-09-06", 3), ("s3", "2026-09-04", 3)],
        [("s1", 10.0), ("s1", 9.5), ("s2", 10.0), ("s2", 8.0), ("s3", 8.0), ("s3", 8.0)],
    ]
    res_density = evaluate_systemic_fatigue(mock_db)
    assert res_density["deload_recommended"] is True
    assert res_density["severity"] == "MODERATE"
    assert res_density["volume_multiplier"] == 0.6


# ============================================================================
# 3. ROUTER & CLINICAL INTERCEPT FAST PATH (<1ms)
# ============================================================================


@pytest.mark.parametrize(
    "query,expected_intent",
    [
        ("I felt a sharp pop in my shoulder", "clinical_intercept"),
        ("Shooting pain down my leg on squats", "clinical_intercept"),
        ("My pec is swollen and tore on bench", "clinical_intercept"),
        ("swap barbell bench press for dumbbell press", "exercise_substitution"),
        ("alternatives for leg curl", "exercise_substitution"),
        ("switch routine to 3 days a week", "program_mutation"),
        ("rebuild split", "program_mutation"),
        ("search seated cable row", "catalog_search"),
        ("How do I bias the lengthened position on RDLs?", "coaching_qa"),
    ],
)
def test_deterministic_router_fast_paths(query, expected_intent):
    state = {"messages": [HumanMessage(content=query)]}
    result = router_node(state)
    assert result["intent"] == expected_intent


def test_clinical_intercept_response():
    state = {"messages": [HumanMessage(content="sharp pain in elbow")]}
    res = clinical_intercept_node(state)
    assert "⚠️ **Movement Discontinued & Clinical Safeguard Triggered**" in res["response_content"]
    assert res["program_updated"] is False


def test_output_scrubber():
    raw_output = "Sure thing! As an AI, here is the breakdown: Drive through mid-foot. Keep crushing it!"
    scrubbed = scrub_coach_output(raw_output)
    assert scrubbed == "Drive through mid-foot."


# ============================================================================
# 4. DATABASE INTEGRITY, TRANSACTIONS & MULTI-TENANCY
# ============================================================================


def test_database_manager_operations(tmp_path):
    catalog_path = tmp_path / "catalog.db"
    users_dir = tmp_path / "users"

    db = DatabaseManager(catalog_path=catalog_path, users_dir=users_dir, active_user="test_trainee")
    db.create_catalog_schema()
    db.create_user_schema()

    # Verify active WAL mode on user ledger
    mode = db.user_conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"

    # User profile persistence
    db.upsert_user_profile(
        {
            "gender": "male",
            "proportions": "long_femurs",
            "age": 22,
            "weight_kg": 85.0,
            "height_cm": 182.0,
            "weekly_frequency": 4,
            "training_age_years": 3.0,
            "equipment_access": "Commercial Gym",
            "stress_and_sleep": "Normal",
        }
    )
    saved_profile = db.get_user_profile()
    assert saved_profile["weight_kg"] == 85.0
    assert saved_profile["weekly_frequency"] == 4

    # Cascading deletes test
    session_id = str(uuid.uuid4())
    set_id = str(uuid.uuid4())
    now_iso = datetime.now(UTC).isoformat()

    db.log_workout_session(session_id, now_iso[:10], "Lower 1", now_iso, now_iso, 4)
    db.log_workout_set(set_id, session_id, "ex_dummy", 1, 100.0, 8, 8.5)

    # Delete workout session -> workout_sets must cascade
    db.user_conn.execute("DELETE FROM workout_sessions WHERE id = ?", (session_id,))
    db.user_conn.commit()

    count = db.user_conn.execute("SELECT COUNT(*) FROM workout_sets WHERE id = ?", (set_id,)).fetchone()[0]
    assert count == 0


# ============================================================================
# 5. STREAMING TURN RUNTIME (MOCKING ChatLlamaCpp)
# ============================================================================


def test_stream_assistant_turn_mocked_llm():
    mock_chunks = [
        MagicMock(content="Maintain "),
        MagicMock(content="scapular retraction "),
        MagicMock(content="throughout the movement."),
    ]

    state = {
        "messages": [HumanMessage(content="Cue machine chest press")],
        "trainee_id": "test_trainee",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": "None",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }

    # Patch ChatLlamaCpp.stream rather than ChatOllama
    with patch.object(ChatLlamaCpp, "stream", return_value=iter(mock_chunks)):
        tokens = list(stream_assistant_turn(state))
        assert "".join(tokens) == "Maintain scapular retraction throughout the movement."
        assert state["intent"] == "coaching_qa"
        assert state["program_updated"] is False
