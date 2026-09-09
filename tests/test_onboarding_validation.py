import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage
from agent.onboarding_graph import onboarding_graph
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

def test_step_test(label: str, initial_state: dict, user_reply: str, expected_step: int, should_reject: bool):
    state = dict(initial_state)
    state["messages"] = list(state.get("messages", [])) + [HumanMessage(content=user_reply)]
    
    result = onboarding_graph.invoke(state)
    last_msg = result["messages"][-1].content
    actual_step = result["intake_step"]
    
    logger.info(f"\n--- {label} ---")
    logger.info(f"Input: \"{user_reply}\"")
    logger.info(f"Expected Step: {expected_step} | Actual Step: {actual_step}")
    
    if should_reject:
        assert actual_step == expected_step, f"Failed: Step advanced on invalid input! ({actual_step} != {expected_step})"
        assert "⚠️ **Invalid response:**" in last_msg or "⚠️ Could not parse" in last_msg, "Failed: Rejection banner missing!"
        logger.info("✅ Correctly rejected with feedback:")
        logger.info(f"   {last_msg.splitlines()[0]}")
    else:
        assert actual_step == expected_step, f"Failed: Step did not advance as expected! ({actual_step} != {expected_step})"
        logger.info("✅ Correctly accepted. Next prompt primed.")
        
    return result

if __name__ == "__main__":
    logger.info("⚡ Starting Intake Validation Test Suite...")
    
    # 0. Initial Graph Boot
    boot_state = onboarding_graph.invoke({
        "messages": [],
        "trainee_id": "test_validation_user",
        "intake_step": 1,
        "is_complete": False,
        "profile_data": None
    })
    
    # TEST 1: Step 1 - Pure Off-Topic / Chit-chat (Must Reject)
    state_after_t1 = test_step_test(
        label="Test 1: Off-Topic Chat",
        initial_state=boot_state,
        user_reply="Can you write me a python script to scrape gym websites?",
        expected_step=1,
        should_reject=True
    )

    # TEST 2: Step 1 - Missing Key Biometrics (Must Reject)
    state_after_t2 = test_step_test(
        label="Test 2: Incomplete Biometrics",
        initial_state=state_after_t1,
        user_reply="male, 21 years old, long legs",  # Missing weight and height
        expected_step=1,
        should_reject=True
    )

    # TEST 3: Step 1 - Physically Impossible Biometrics (Must Reject)
    state_after_t3 = test_step_test(
        label="Test 3: Impossible Biometrics",
        initial_state=state_after_t2,
        user_reply="balanced, male, 5 years old, 400kg, 320cm",
        expected_step=1,
        should_reject=True
    )

    # TEST 4: Step 1 - Valid Biometrics (Must Accept & Advance to Step 2)
    state_after_t4 = test_step_test(
        label="Test 4: Valid Step 1 Submission",
        initial_state=state_after_t3,
        user_reply="1lower body is longer, 2male, 21, 80kg, 183cm",
        expected_step=2,
        should_reject=False
    )

    # TEST 5: Step 2 - Out-of-Bounds Frequency (Must Reject)
    state_after_t5 = test_step_test(
        label="Test 5: Frequency > 5 Days",
        initial_state=state_after_t4,
        user_reply="3strength 4longevity 5seven days a week 63years",
        expected_step=2,
        should_reject=True
    )

    # TEST 6: Step 2 - Valid Goals & Capacity (Must Accept & Advance to Step 3)
    state_after_t6 = test_step_test(
        label="Test 6: Valid Step 2 Submission",
        initial_state=state_after_t5,
        user_reply="3hypertrophy 4health and longevity 54 days per week 63 years lifting",
        expected_step=3,
        should_reject=False
    )

    # TEST 7: Step 3 - Valid Logistics & Final Completion (Must Complete Intake)
    state_after_t7 = test_step_test(
        label="Test 7: Valid Step 3 Submission",
        initial_state=state_after_t6,
        user_reply="7commercial gym 8no injuries 9medium stress, 8 hours sleep",
        expected_step=3,
        should_reject=False
    )

    assert state_after_t7["is_complete"] is True, "Failed: Intake failed to flag is_complete=True on Step 3!"
    logger.info("\n🎉 All 7 validation edge cases passed successfully.")