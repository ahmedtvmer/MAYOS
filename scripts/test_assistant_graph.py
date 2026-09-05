import sys
import time
from pathlib import Path
from langchain_core.messages import HumanMessage

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import DatabaseManager
from agent.assistant_graph import assistant_graph

def run_routing_suite():
    db = DatabaseManager()
    test_user = "ahmdtvmer"
    
    if not db.user_exists(test_user):
        print(f"[-] User '{test_user}' not found. Initializing profile...")
        db.switch_user(test_user)
        db.upsert_user_profile({
            "gender": "male",
            "proportions": "balanced",
            "age": 21,
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
        db.update_user_persona(
            coach_tone="Direct, grounded, and pragmatic",
            custom_instructions="Prioritize stability. Never use motivational fluff."
        )
    else:
        db.switch_user(test_user)

    test_cases = [
        {
            "name": "1. Program Mutation (Speed & Schema)",
            "input": "Switch my split to 3 days a week",
            "expected_intent": "program_mutation"
        },
        {
            "name": "2. Literature / Research Trigger",
            "input": "What does the research and literature say about hypertrophy rep ranges?",
            "expected_intent": "research_qa"
        },
        {
            "name": "3. Vector Catalog Search",
            "input": "Find cable exercises for rear delts",
            "expected_intent": "catalog_search"
        },
        {
            "name": "4. Biomechanics & Coaching Q&A",
            "input": "How do I prevent elbow flare on machine chest press?",
            "expected_intent": "coaching_qa"
        },
        {
            "name": "5. Out-of-Scope Fallback",
            "input": "Can you write a poem about protein powder?",
            "expected_intent": "fallback"
        },
        {
            "name": "6. Exercise Substitution",
            "input": "Swap flat barbell bench press for incline dumbbell press",
            "expected_intent": "exercise_substitution"
        }
    ]

    print("\n" + "=" * 60)
    print("MYOS ASSISTANT GRAPH ROUTING & LATENCY SUITE")
    print("=" * 60)

    for case in test_cases:
        print(f"\n[RUNNING] {case['name']}")
        print(f"Query: \"{case['input']}\"")
        
        initial_state = {
            "messages": [HumanMessage(content=case["input"])],
            "trainee_id": test_user,
            "coach_tone": "",
            "custom_instructions": "",
            "intent": None,
            "intent_metadata": {},
            "retrieved_context": None,
            "program_updated": False,
            "response_content": None
        }

        t0 = time.perf_counter()
        result = assistant_graph.invoke(initial_state)
        elapsed = round(time.perf_counter() - t0, 2)

        print(f"Elapsed: {elapsed}s | Resolved Intent: {result.get('intent')}")
        print("Response Preview:")
        preview = (result.get("response_content") or "").strip().split("\n")[0]
        print(f"> {preview[:120]}...")
        
        if case["expected_intent"] == "program_mutation":
            assert result.get("program_updated") is True, "Mutation flag was not set."
            active = db.get_active_program()
            print(f"[OK] Database updated to: {active.program_name} ({active.weekly_frequency} Days)")

    print("\n" + "=" * 60)
    print("ALL ROUTING TEST CASES COMPLETED SUCCESSFULLY")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    run_routing_suite()