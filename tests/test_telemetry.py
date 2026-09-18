from pathlib import Path

from langchain_core.messages import HumanMessage

from agent.assistant_graph import _record_telemetry_event, stream_assistant_turn
from scripts.check_engine_health import analyze_logs

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "myos.log"


def test_fast_path_telemetry_logging():
    """Verify deterministic fast-path writes structured telemetry to disk."""
    state = {"messages": [HumanMessage(content="I felt a sharp pop in my shoulder")], "trainee_id": "ci_test_user"}

    # Consume generator to trigger routing and logging
    list(stream_assistant_turn(state))

    assert LOG_PATH.exists(), "Telemetry log file was not created"
    log_content = LOG_PATH.read_text(encoding="utf-8")
    assert "[TELEMETRY]" in log_content
    assert "clinical_intercept" in log_content


def test_engine_health_parser_execution():
    """Verify health analysis script parses logged telemetry without exceptions."""
    _record_telemetry_event(
        intent="coaching_qa",
        fast_path_ms=0.015,
        ttft_ms=250.0,
        gen_time_s=2.5,
        tokens=35,
        tps=14.0,
        user_id="ci_test_user",
    )

    # analyze_logs will parse the line just written
    analyze_logs()


import pytest

from agent.telemetry_reconciler import reconcile_telemetry_query


@pytest.mark.parametrize("telemetry", [
    "Progression: Establishing baseline loads across routine.",
    "Last Session: Upper | Top: Bench Press 80kg x 8 @ RPE 8.5",
    "Last Session: No recorded sessions yet in ledger.",
    "",
])
def test_compact_telemetry_never_proves_exercise_absence(telemetry):
    assert reconcile_telemetry_query("how did my squats look", telemetry) is None


@pytest.mark.parametrize("query,telemetry", [
    ("Did I complete all sets for squats in my last session?", "Last Session: Legs | 12 sets logged"),
    ("Did I complete all sets for squats yesterday?", "Last Session: Legs | squats: 3 sets logged"),
    ("Did I complete all sets for incline press in my last session?", "Last Session: Upper | flat press: 3 sets logged"),
    ("Did I complete all sets for squats in my last session?", "Squats: 3 sets logged"),
    ("Did I complete all sets for squats in my last session?", "Last Session: Legs\nSet 1: 80kg\nSet 2: 80kg"),
    ("Did I complete all sets for squats in my last session?", "Last Session: Legs | squats: 3 sets logged | squats: 2 sets logged"),
    ("Did I complete all sets in my last session?", "Last Session: Legs | squats: 3 sets logged"),
    ("Did I complete all sets for squats last week?", "Last Session: Legs | squats: 3 sets logged"),
])
def test_set_counts_require_verified_movement_and_session_scope(query, telemetry):
    assert reconcile_telemetry_query(query, telemetry) is None


@pytest.mark.parametrize("exercise,count", [("squats", 3), ("incline press", 2), ("squats", 0)])
def test_explicit_last_session_movement_counts(exercise, count):
    result = reconcile_telemetry_query(
        f"Did I complete all sets for {exercise} in my last session?",
        f"Last Session: Training | {exercise}: {count} sets logged | 12 sets logged",
    )
    assert result == f"Your session log records exactly {count} completed sets for {exercise} in your last session."


def test_explicit_session_count_is_not_attributed_to_movement():
    result = reconcile_telemetry_query(
        "Did I complete all sets in my last session?", "Last Session: Legs | 12 sets logged"
    )
    assert result == "Your session log records exactly 12 completed sets across your last session."
