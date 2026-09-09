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
