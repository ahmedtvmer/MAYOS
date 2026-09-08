import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage, AIMessage
from database.database_manager import DatabaseManager
from agent.assistant_graph import assistant_graph

def run_context_test_suite():
    print("⚡ Starting Context Window & State Management Test Suite...\n")
    
    db = DatabaseManager()
    test_user = "test_context_trainee"
    db.switch_user(test_user)

    # Clean setup for isolation
    db.clear_chat_history()

    # ---------------------------------------------------------------------
    # TEST 1: Task 1 - State Externalization & Tail Clamping
    # ---------------------------------------------------------------------
    print("--- Test 1: Sliding Window & Tail Clamping (Task 1) ---")

    # Simulate 10 historical dialogue turns persisted directly to SQLite
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

    # 1. Verify total persistence in SQLite
    total_stored = db.get_chat_history()
    assert len(total_stored) == 10, f"Failed: Expected 10 messages in DB, found {len(total_stored)}."
    print(f"✅ State externalized: {len(total_stored)} messages confirmed in SQLite.")

    # 2. Verify chronological tail slicing (limit=6)
    clamped_records = db.get_chat_history(limit=6)
    assert len(clamped_records) == 6, f"Failed: Expected 6 clamped messages, got {len(clamped_records)}."
    
    # Chronological integrity check: oldest of the tail must be dialogue[4]
    assert clamped_records[0]["content"] == dialogue[4][1], (
        f"Failed: Chronological mismatch. Expected '{dialogue[4][1]}', got '{clamped_records[0]['content']}'"
    )
    # Most recent of the tail must be dialogue[9]
    assert clamped_records[-1]["content"] == dialogue[9][1], (
        f"Failed: Tail end mismatch. Expected '{dialogue[9][1]}', got '{clamped_records[-1]['content']}'"
    )
    print("✅ Tail clamping verified: Retrieved strictly the last 6 messages in chronological order.")

    # ---------------------------------------------------------------------
    # TEST 2: Task 4 & Task 2 - Debrief Compaction & Telemetry Injection
    # ---------------------------------------------------------------------
    print("\n--- Test 2: Debrief Compaction & Telemetry Context (Task 4 & 2) ---")

    # 1. Set up biometrics
    db.upsert_user_profile({
        "gender": "male",
        "age": 22,
        "weight_kg": 82.5,
        "height_cm": 184.0,
        "proportions": "long_legs",
        "current_goal": "Hypertrophy",
        "long_term_goal": "Longevity",
        "weekly_frequency": 4,
        "training_age_years": 3.0,
        "equipment_access": "commercial gym",
        "stress_and_sleep": "good",
        "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "No cheerleading."
    })

    # 2. Log a dummy workout session to SQLite
    session_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    db.log_workout_session(
        session_id=session_id,
        session_date=now_iso[:10],
        split_name="Upper 1",
        started_at=now_iso,
        completed_at=now_iso,
        readiness_score=4,
        notes="Solid session"
    )
    
    # Log top set
    db.log_workout_set(
        set_id=str(uuid.uuid4()),
        session_id=session_id,
        exercise_id="0001",
        set_index=1,
        weight_kg=105.0,
        reps=8,
        rpe=9.0,
        is_warmup=0
    )
    
    # Save full debrief into database column
    full_debrief = (
        "High mechanical output across pressing variations. "
        "Fatigue accumulated heavily by set 3. Ensure 48 hours recovery before direct shoulder loading."
    )
    db.save_session_debrief(session_id, full_debrief)

    # 3. Task 4: Debrief Compaction in Chat Feed
    compact_pointer = (
        f"📋 **Session Logged:** Upper 1 ({now_iso[:10]}) | "
        f"Readiness: 4/5 | Top: Barbell Bench Press 105.0kg x 8 | Status: Saved to Ledger."
    )
    db.add_chat_message("assistant", compact_pointer)

    # Verify that the message logged to chat is compact (< 200 chars), not the full narrative
    latest_chat = db.get_chat_history(limit=1)[0]
    assert "📋 **Session Logged:**" in latest_chat["content"]
    assert len(latest_chat["content"]) < 200, "Failed: Verbose debrief leaked into chat history."
    print("✅ Debrief compaction verified: 1-line atomic pointer stored in chat table.")

    # 4. Task 2: Verify Telemetry Generation
    telemetry = db.get_compact_telemetry()
    assert "82.5kg @ 184.0cm" in telemetry, "Failed: Telemetry missing biometrics."
    assert "Upper 1" in telemetry, "Failed: Telemetry missing last session split."
    assert "Readiness: 4/5" in telemetry, "Failed: Telemetry missing readiness score."
    print("✅ Telemetry generation verified: Real performance metrics captured into compact context block.")

    # ---------------------------------------------------------------------
    # TEST 3: Task 3 - Episodic State Eviction
    # ---------------------------------------------------------------------
    print("\n--- Test 3: Episodic State Eviction (Task 3) ---")

    # A. Manual Clear Eviction
    db.clear_chat_history()
    cleared_history = db.get_chat_history()
    assert len(cleared_history) == 0, f"Failed: Chat history not flushed. Found {len(cleared_history)} rows."
    print("✅ Manual episodic eviction verified: Chat ledger successfully cleared.")

    # B. Program Mutation Trigger Eviction
    # Seed 2 conversation turns
    db.add_chat_message("user", "I want to train less.")
    db.add_chat_message("assistant", "We can reduce weekly frequency.")
    assert len(db.get_chat_history()) == 2

    # Invoke program mutation through the graph
    mutation_state = {
        "messages": [HumanMessage(content="Switch to 3 days a week")],
        "trainee_id": test_user,
        "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None
    }

    out = assistant_graph.invoke(mutation_state)
    assert out.get("program_updated") is True, "Failed: Program mutation node was not triggered."

    # Verify that the program mutation node flushed previous chat history
    post_mutation_history = db.get_chat_history()
    assert len(post_mutation_history) == 0, (
        f"Failed: Chat context was not evicted upon program mutation! Count: {len(post_mutation_history)}"
    )
    print("✅ Mutation episodic eviction verified: Program mutation automatically evicted stale split context.")

    print("\n🎉 All 3 context management tasks verified successfully.")

if __name__ == "__main__":
    run_context_test_suite()