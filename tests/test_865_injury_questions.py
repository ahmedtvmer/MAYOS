"""#865: a question is never a physician's clearance.

"Is it okay to squat?" was parsed as "cleared": it saved the question as a
physician's clearance and moved a reported injury to "physician seen".
"""

import pytest
from langchain_core.messages import HumanMessage

from agent.assistant_graph import stream_assistant_turn
from service import injuries as injuries_service
from tests.fakes.chat_model import ScriptedChatModel

QUESTIONS = [
    "Is it okay to squat?",
    "is it ok to squat",
    "Am I allowed to bench?",
    "Is squat safe to do?",
    "can I do squats or are they not allowed",
    "So is it safe to deadlift",
    "okay to squat?",
    "Should I avoid squats?",
    "هل مسموح لي بالسكوات؟",
    "مسموح ألعب سكوات؟",
    "هو السكوات ممنوع عليا؟",
]

STATEMENTS = [
    ("My doctor cleared me to squat", "cleared"),
    ("cleared for bench with limits", "cleared_with_limits"),
    ("squat is not cleared", "not_cleared"),
    ("الدكتور قال مسموح السكوات", "cleared"),
    # A reported restriction must survive a question in the same message.
    ("my doctor said avoid squats, what should I do instead?", "not_cleared"),
    ("الدكتور قال السكوات ممنوع، ألعب إيه بداله؟", "not_cleared"),
    ("My doctor cleared squat. How heavy should I go?", "cleared"),
    ("squat is not cleared, what can I do instead?", "not_cleared"),
    ("Is leg press fine? The doctor said avoid squats", "not_cleared"),
    ("should avoid squats", "not_cleared"),
    ("am not allowed to squat", "not_cleared"),
]


@pytest.mark.parametrize("message", QUESTIONS)
def test_a_question_is_not_a_clearance_statement(message):
    assert injuries_service.parse_clearance_statement(message) is None
    # Not even while chat is waiting to hear about one exercise.
    assert injuries_service.parse_clearance_statement(message, "Back Squat (Barbell)") is None


@pytest.mark.parametrize(("message", "verdict"), STATEMENTS)
def test_a_reported_clearance_is_still_parsed(message, verdict):
    parsed = injuries_service.parse_clearance_statement(message)
    assert parsed is not None
    assert parsed["verdict"] == verdict


@pytest.mark.parametrize("message", ["cleared", "not allowed", "مسموح", "ممنوع"])
def test_a_short_answer_to_the_follow_up_is_still_parsed(message):
    parsed = injuries_service.parse_clearance_statement(message, "Back Squat (Barbell)")
    assert parsed is not None


@pytest.mark.parametrize("message", [
    "Should I have seen a doctor by now?",
    "Has the doctor fully cleared me?",
])
def test_a_question_does_not_report_a_doctor_visit(fresh_store, message):
    fresh_store.ledger.create_injury_record("knee", "Pain during squats")
    assert not injuries_service.has_matching_status_update(fresh_store.ledger, message)
    assert not injuries_service.full_physician_clearance(message)


@pytest.mark.parametrize("message", ["I saw a doctor", "I saw a doctor, can I train today?"])
def test_a_reported_doctor_visit_is_still_recognized(fresh_store, message):
    fresh_store.ledger.create_injury_record("knee", "Pain during squats")
    assert injuries_service.has_matching_status_update(fresh_store.ledger, message)


@pytest.mark.parametrize("message", QUESTIONS)
def test_a_question_changes_nothing_on_an_active_injury(fresh_store, monkeypatch, message):
    ledger = fresh_store.ledger
    injury, _created = ledger.create_injury_record("knee", "Pain during squats")
    assert injury["status"] == "reported"
    monkeypatch.setattr(
        "agent.assistant_graph.llm",
        ScriptedChatModel([{"intent": "coaching_qa"}], default_turn="Ask your physician first."),
    )
    state = {
        "messages": [HumanMessage(content=message)],
        "trainee_id": "issue-865",
        "player_account_id": None,
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }

    response = "".join(stream_assistant_turn(state, ledger=ledger, store=fresh_store))

    print("ROUTE", state["intent"], "| REPLY", response[:120])
    print("SAVED", [dict(row) for row in ledger.list_exercise_clearances(injury["id"])])
    print("STATUS", ledger.get_injury_record(injury["id"])["status"])
    assert state["intent"] not in {
        "exercise_clearance_update", "exercise_clearance_disambiguation", "injury_status_update",
    }
    assert ledger.list_exercise_clearances(injury["id"]) == []
    assert ledger.get_injury_record(injury["id"])["status"] == "reported"
