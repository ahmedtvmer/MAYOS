import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage

from agent.onboarding_graph import onboarding_graph
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def _assert_step_transition(
    label: str,
    initial_state: dict,
    user_reply: str,
    expected_step: int,
    should_reject: bool,
) -> dict:
    """Helper assertion function (hidden from Pytest discovery via leading underscore)."""
    state = dict(initial_state)
    state["messages"] = list(state.get("messages", [])) + [HumanMessage(content=user_reply)]

    result = onboarding_graph.invoke(state)
    last_msg = result["messages"][-1].content
    actual_step = result["intake_step"]

    logger.info(f"\n--- {label} ---")
    logger.info(f'Input: "{user_reply}"')
    logger.info(f"Expected Step: {expected_step} | Actual Step: {actual_step}")

    if should_reject:
        assert actual_step == expected_step, (
            f"Failed: Step advanced on invalid input! ({actual_step} != {expected_step})"
        )
        assert "⚠️ **Invalid response:**" in last_msg or "⚠️ Could not parse" in last_msg, (
            "Failed: Rejection banner missing!"
        )
        logger.info("✅ Correctly rejected with feedback:")
        logger.info(f"   {last_msg.splitlines()[0]}")
    else:
        assert actual_step == expected_step, (
            f"Failed: Step did not advance as expected! ({actual_step} != {expected_step})"
        )
        logger.info("✅ Correctly accepted. Next prompt primed.")

    return result


def test_onboarding_validation_workflow():
    """Validates the multi-step conversational intake state machine end-to-end."""
    logger.info("⚡ Starting Intake Validation Test Suite...")

    # 0. Initial Graph Boot
    boot_state = onboarding_graph.invoke(
        {
            "messages": [],
            "trainee_id": "test_validation_user",
            "intake_step": 1,
            "is_complete": False,
            "profile_data": None,
        }
    )

    # TEST 1: Step 1 - Pure Off-Topic / Chit-chat (Must Reject)
    state_after_t1 = _assert_step_transition(
        label="Test 1: Off-Topic Chat",
        initial_state=boot_state,
        user_reply="Can you write me a python script to scrape gym websites?",
        expected_step=1,
        should_reject=True,
    )

    # TEST 2: Step 1 - Missing Key Biometrics (Must Reject)
    state_after_t2 = _assert_step_transition(
        label="Test 2: Incomplete Biometrics",
        initial_state=state_after_t1,
        user_reply="male, 21 years old, long legs",
        expected_step=1,
        should_reject=True,
    )

    # TEST 3: Step 1 - Physically Impossible Biometrics (Must Reject)
    state_after_t3 = _assert_step_transition(
        label="Test 3: Impossible Biometrics",
        initial_state=state_after_t2,
        user_reply="balanced, male, 5 years old, 400kg, 320cm",
        expected_step=1,
        should_reject=True,
    )

    # TEST 4: Step 1 - Valid Biometrics (Must Accept & Advance to Step 2)
    state_after_t4 = _assert_step_transition(
        label="Test 4: Valid Step 1 Submission",
        initial_state=state_after_t3,
        user_reply="1lower body is longer, 2male, 21, 80kg, 183cm",
        expected_step=2,
        should_reject=False,
    )

    # TEST 5: Step 2 - Out-of-Bounds Frequency (Must Reject)
    state_after_t5 = _assert_step_transition(
        label="Test 5: Frequency > 5 Days",
        initial_state=state_after_t4,
        user_reply="3strength 4longevity 5seven days a week 63years",
        expected_step=2,
        should_reject=True,
    )

    # TEST 6: Step 2 - Valid Goals & Capacity (Must Accept & Advance to Step 3)
    state_after_t6 = _assert_step_transition(
        label="Test 6: Valid Step 2 Submission",
        initial_state=state_after_t5,
        user_reply="3hypertrophy 4health and longevity 54 days per week 63 years lifting",
        expected_step=3,
        should_reject=False,
    )

    # TEST 7: Step 3 - Valid Logistics & Final Completion (Must Complete Intake)
    state_after_t7 = _assert_step_transition(
        label="Test 7: Valid Step 3 Submission",
        initial_state=state_after_t6,
        user_reply="7commercial gym 8no injuries 9medium stress, 8 hours sleep",
        expected_step=3,
        should_reject=False,
    )

    assert state_after_t7["is_complete"] is True, "Failed: Intake failed to flag is_complete=True on Step 3!"
    logger.info("\n🎉 All 7 validation edge cases passed successfully.")


import pytest
from unittest.mock import MagicMock

from agent import onboarding_graph as onboarding


@pytest.mark.parametrize("frequency", ["0", "6", "7", "12", "zero", "six", "seven", "twenty-one", "one hundred", "-1"])
@pytest.mark.parametrize("numbered", [True, False])
def test_invalid_frequency_never_advances_or_writes(monkeypatch, frequency, numbered):
    database = MagicMock()
    extractor = MagicMock()
    monkeypatch.setattr(onboarding, "db", database)
    monkeypatch.setattr(onboarding, "step2_extractor", extractor)
    query = (
        f"3strength 4longevity 5: {frequency} days a week 63years"
        if numbered else f"My goal is strength, long term longevity, {frequency} days a week, lifting for 3 years"
    )
    profile = {"gender": "male", "weekly_frequency": 4}
    result = onboarding.intake_node({
        "messages": [HumanMessage(content=query)], "intake_step": 2, "profile_data": profile,
    })
    assert result["intake_step"] == 2
    assert result["is_complete"] is False
    assert result["profile_data"] == profile
    assert "1 to 5" in result["messages"][-1].content
    assert database.mock_calls == []
    extractor.invoke.assert_not_called()


@pytest.mark.parametrize("frequency", [1, 5])
def test_valid_frequency_boundaries_advance_without_writes(monkeypatch, frequency):
    database = MagicMock()
    monkeypatch.setattr(onboarding, "db", database)
    result = onboarding.intake_node({
        "messages": [HumanMessage(content=f"3strength 4longevity 5: {frequency} days a week 63years")],
        "intake_step": 2, "profile_data": {},
    })
    assert result["intake_step"] == 3
    assert result["profile_data"]["weekly_frequency"] == frequency
    assert database.mock_calls == []


@pytest.mark.parametrize("frequency", [0, 6, 7, 99, -1])
def test_invalid_extracted_frequency_rejected(monkeypatch, frequency):
    database = MagicMock()
    extractor = MagicMock()
    extractor.invoke.return_value = onboarding.Step2Extraction.model_construct(
        current_goal="strength", long_term_goal="health", weekly_frequency=frequency,
        training_age_years=3, rep_preference="balanced", is_off_topic=False,
    )
    monkeypatch.setattr(onboarding, "db", database)
    monkeypatch.setattr(onboarding, "step2_extractor", extractor)
    result = onboarding.intake_node({
        "messages": [HumanMessage(content="My goal is strength and long term health")],
        "intake_step": 2, "profile_data": {},
    })
    assert result["intake_step"] == 2
    assert result["profile_data"] == {}
    assert database.mock_calls == []


@pytest.mark.parametrize("frequency", [0, 6, 7, 99, None])
def test_completion_revalidates_frequency_before_database_access(monkeypatch, frequency):
    database = MagicMock()
    monkeypatch.setattr(onboarding, "db", database)
    result = onboarding.intake_node({
        "messages": [HumanMessage(content="7commercial gym 8no injuries 9medium stress, 8 hours sleep")],
        "intake_step": 3, "profile_data": {"weekly_frequency": frequency},
    })
    assert result["intake_step"] == 2
    assert result["is_complete"] is False
    assert database.mock_calls == []


UNSTATED_REP_INPUT = (
    "Current focus is building a wider back taper and beefing up forearms. "
    "Long term is hitting a 200kg squat safely without injury. "
    "I can commit to 3 days weekly. Lifting for 4.5 years."
)


def _step2_result(monkeypatch, user_input, extracted_rep):
    database = MagicMock()
    extractor = MagicMock()
    extractor.invoke.return_value = onboarding.Step2Extraction.model_construct(
        current_goal="build a wider back taper",
        long_term_goal="200kg squat safely",
        weekly_frequency=3,
        training_age_years=4.5,
        rep_preference=extracted_rep,
        is_off_topic=False,
    )
    monkeypatch.setattr(onboarding, "db", database)
    monkeypatch.setattr(onboarding, "step2_extractor", extractor)
    result = onboarding.intake_node({
        "messages": [HumanMessage(content=user_input)],
        "intake_step": 2,
        "profile_data": {},
    })
    return result, extractor


def test_unstated_rep_preference_never_becomes_low(monkeypatch):
    """gen_onboard_03: a strength goal/200kg target must not imply a low-rep pref."""
    result, extractor = _step2_result(monkeypatch, UNSTATED_REP_INPUT, "low")
    extractor.invoke.assert_called_once()
    assert result["intake_step"] == 3
    assert result["profile_data"]["rep_preference"] == "balanced"


@pytest.mark.parametrize(
    "user_input,extracted,expected",
    [
        (
            "Current goal is pure lat width. Long term is adding lean tissue. "
            "I can train 4 days a week, lifting for 6 years, prefer low rep heavy compounds.",
            "low",
            "low",
        ),
        (
            "Current goal is arm size. Long term is health. "
            "I train 4 days a week, lifting for 3 years. I prefer high reps.",
            "high",
            "high",
        ),
        (
            "Current goal is arm size. Long term is health. "
            "I train 4 days a week, lifting for 3 years. I prefer moderate reps.",
            "low",  # a hallucinated low must not survive an explicit moderate statement
            "balanced",
        ),
    ],
)
def test_explicit_rep_preference_is_respected(monkeypatch, user_input, extracted, expected):
    result, extractor = _step2_result(monkeypatch, user_input, extracted)
    extractor.invoke.assert_called_once()
    assert result["intake_step"] == 3
    assert result["profile_data"]["rep_preference"] == expected


@pytest.mark.parametrize(
    "user_input,extracted",
    [
        (
            "Current goal is strength. Long term is health. "
            "I train 4 days a week, lifting for 3 years. I prefer heavy compounds.",
            "low",
        ),
        (
            "Current goal is arm size. Long term is health. "
            "I train 4 days a week, lifting for 3 years. I need a rep range.",
            "high",
        ),
    ],
)
def test_generic_rep_wording_does_not_authorize_low_or_high(monkeypatch, user_input, extracted):
    """Generic "heavy compounds"/"rep range" wording states no preference; stay balanced."""
    result, extractor = _step2_result(monkeypatch, user_input, extracted)
    extractor.invoke.assert_called_once()
    assert result["intake_step"] == 3
    assert result["profile_data"]["rep_preference"] == "balanced"


def test_numbered_step2_still_defaults_rep_preference(monkeypatch):
    database = MagicMock()
    extractor = MagicMock()
    monkeypatch.setattr(onboarding, "db", database)
    monkeypatch.setattr(onboarding, "step2_extractor", extractor)
    result = onboarding.intake_node({
        "messages": [HumanMessage(content="3strength 4longevity 54 days per week 63 years lifting")],
        "intake_step": 2,
        "profile_data": {},
    })
    assert result["intake_step"] == 3
    assert result["profile_data"]["rep_preference"] == "balanced"
    extractor.invoke.assert_not_called()


if __name__ == "__main__":
    test_onboarding_validation_workflow()
