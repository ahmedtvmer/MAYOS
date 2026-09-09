import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage
from database.database_manager import DatabaseManager
from agent.assistant_graph import assistant_graph
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

def test_context_test_suite():
    logger.info("⚡ Starting Context Window & State Management Test Suite...\n")
    db = DatabaseManager()
    test_user = "test_context_trainee"
    db.switch_user(test_user)
    db.clear_chat_history()

    dialogue = [
        ("user", "Hello, ready to train."),
        ("assistant", "Noted. Focus on execution."),
        ("user", "What is my rep target for squats?"),
        ("assistant", "Target 6-8 reps with 2 RIR."),
        ("user", "Should I do pauses at the bottom?"),
        ("assistant", "Yes, 1-second pause in the hole."),
        ("user", "How about leg press after?"),
        ("assistant", "3 sets of 10-12 reps."),
        ("user", "Can I swap leg press?"),
        ("assistant", "Specify the replacement movement.")
    ]

    for role, content in dialogue:
        db.add_chat_message(role, content)

    total_stored = db.get_chat_history()
    assert len(total_stored) == 10, f"Failed: Expected 10 messages in DB, found {len(total_stored)}."

    clamped_records = db.get_chat_history(limit=6)
    assert len(clamped_records) == 6, f"Failed: Expected 6 clamped messages, got {len(clamped_records)}."
    assert clamped_records[0]["content"] == dialogue[4][1]
    assert clamped_records[-1]["content"] == dialogue[9][1]

    db.upsert_user_profile({
        "gender": "male", "age": 22, "weight_kg": 82.5, "height_cm": 184.0,
        "proportions": "long_legs", "current_goal": "Hypertrophy", "long_term_goal": "Longevity",
        "weekly_frequency": 4, "training_age_years": 3.0, "equipment_access": "commercial gym",
        "stress_and_sleep": "good", "coach_tone": "Direct, grounded, and pragmatic", "custom_instructions": "No cheerleading."
    })

    session_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    db.log_workout_session(session_id=session_id, session_date=now_iso[:10], split_name="Upper 1", started_at=now_iso, completed_at=now_iso, readiness_score=4, notes="Solid session")
    db.log_workout_set(set_id=str(uuid.uuid4()), session_id=session_id, exercise_id="0001", set_index=1, weight_kg=105.0, reps=8, rpe=9.0, is_warmup=0)
    db.save_session_debrief(session_id, "High mechanical output across pressing variations.")

    compact_pointer = f"📋 **Session Logged:** Upper 1 ({now_iso[:10]}) | Readiness: 4/5 | Top: Barbell Bench Press 105.0kg x 8 | Status: Saved to Ledger."
    db.add_chat_message("assistant", compact_pointer)

    latest_chat = db.get_chat_history(limit=1)[0]
    assert "📋 **Session Logged:**" in latest_chat["content"]
    assert len(latest_chat["content"]) < 200

    telemetry = db.get_compact_telemetry()
    assert "82.5kg @ 184.0cm" in telemetry
    assert "Upper 1" in telemetry
    assert "Readiness: 4/5" in telemetry

    db.clear_chat_history()
    assert len(db.get_chat_history()) == 0

    db.add_chat_message("user", "I want to train less.")
    db.add_chat_message("assistant", "We can reduce weekly frequency.")
    assert len(db.get_chat_history()) == 2

    mutation_state = {
        "messages": [HumanMessage(content="Switch to 3 days a week")],
        "trainee_id": test_user, "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "", "telemetry_context": None, "intent": None,
        "intent_metadata": {}, "program_updated": False, "response_content": None
    }
    out = assistant_graph.invoke(mutation_state)
    assert out.get("program_updated") is True
    assert len(db.get_chat_history()) == 0
    logger.info("🎉 All context management tasks verified successfully.")

if __name__ == "__main__":
    test_context_test_suite()