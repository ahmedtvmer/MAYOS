"""#865: a question or an ordinary message is never a physician's clearance.

"Is it okay to squat?" was parsed as "cleared": it saved the question as a
physician's clearance and moved a reported injury to "physician seen".
"""

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph
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
    "مسموح ألعب سكوات",
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
    ("I'm not allowed to squat", "not_cleared"),
    ("I am no longer allowed to squat", "not_cleared"),
    ("my doctor said no squats", "not_cleared"),
    ("my doctor said light weight only on squats", "cleared_with_limits"),
    ("squats aren't allowed", "not_cleared"),
    # A negated permission must never read as a permission.
    ("my doctor hasn't cleared me to squat", "not_cleared"),
    ("the doctor never cleared squats", "not_cleared"),
    ("الدكتور قال السكوات غير مسموح", "not_cleared"),
    ("السكوات مش مسموح", "not_cleared"),
    ("الدكتور قالي بلاش ليج اكستنشن", "not_cleared"),
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


@pytest.mark.parametrize(("message", "verdict"), [
    ("cleared", "cleared"),
    ("he said it's cleared", "cleared"),
    ("not allowed", "not_cleared"),
    ("light weight only", "cleared_with_limits"),
    ("مسموح", "cleared"),
    ("غير مسموح", "not_cleared"),
    ("ممنوع", "not_cleared"),
])
def test_a_short_answer_to_the_follow_up_is_saved_for_the_asked_exercise(message, verdict):
    assert injuries_service.parse_clearance_statement(message, "Back Squat (Barbell)") == {
        "exercise_name": "Back Squat (Barbell)", "verdict": verdict, "note": "",
    }


ORDINARY = [
    "no",
    "No, leave it as it is",
    "nope",
    "modify my program",
    "modify the push day",
    "I want light weight today",
    "light weight and more reps on curls",
    "I can do 10 pull ups now",
    "limited time today, only 30 minutes",
    "only if it fits my week",
    "ok to start with legs",
    "I'm not sure I'm cleared to squat",
    "عايز أوزان خفيفة النهاردة",
    "لا",
    "مش متأكد لو مسموح ألعب سكوات",
]


@pytest.mark.parametrize("message", ORDINARY)
def test_an_ordinary_message_is_not_a_clearance_statement(message):
    assert injuries_service.parse_clearance_statement(message) is None
    assert injuries_service.parse_clearance_statement(message, "Back Squat (Barbell)") is None


@pytest.mark.parametrize(("message", "exercise"), [
    ("I'm not allowed to squat", "squat"),
    ("my doctor hasn't cleared me to squat", "squat"),
    ("squats aren't allowed", "squats"),
    ("I'm not allowed to do overhead pressing", "overhead pressing"),
    ("cleared for bench with limits", "bench"),
    ("الدكتور قال السكوات غير مسموح", "السكوات"),
    ("الدكتور قالي بلاش ليج اكستنشن", "ليج اكستنشن"),
])
def test_the_saved_exercise_is_only_the_exercise(message, exercise):
    assert injuries_service.parse_clearance_statement(message)["exercise_name"] == exercise


@pytest.mark.parametrize(("name", "known"), [
    ("squats", True), ("bench press", True), ("squatting", True), ("overhead pressing", True),
    ("eat sugar", False), ("skip days", False), ("dumbbells", False), ("leg day", False), ("my schedule", False),
])
def test_ordinary_wording_needs_a_real_exercise(fresh_store, name, known):
    assert injuries_service.names_library_exercise(fresh_store, name) is known


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


@pytest.mark.parametrize("message", [
    *QUESTIONS, "no", "no wait", "no dumbbells", "modify my program", "avoid leg day", "I cleared my schedule",
    "the last set was not ok", "I'm not allowed to eat sugar",
])
def test_a_message_without_advice_changes_nothing_on_an_active_injury(fresh_store, monkeypatch, message):
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

    "".join(stream_assistant_turn(state, ledger=ledger, store=fresh_store))

    assert state["intent"] not in {
        "exercise_clearance_update", "exercise_clearance_disambiguation", "injury_status_update",
    }
    assert ledger.list_exercise_clearances(injury["id"]) == []
    assert ledger.get_injury_record(injury["id"])["status"] == "reported"


def test_a_restriction_is_saved_without_naming_the_doctor(fresh_store, monkeypatch):
    ledger = fresh_store.ledger
    injury, _created = ledger.create_injury_record("knee", "Pain during squats")
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel([]))
    monkeypatch.setattr(
        injuries_service, "resolve_exercise_matches", lambda _store, _name: [{"id": "sq", "name": "Back Squat"}]
    )
    state = {
        "messages": [HumanMessage(content="I'm not allowed to squat")],
        "trainee_id": "issue-865", "player_account_id": None, "coach_tone": "Direct",
        "custom_instructions": "", "telemetry_context": "", "intent": None,
        "intent_metadata": {}, "program_updated": False, "response_content": None,
    }

    "".join(stream_assistant_turn(state, ledger=ledger, store=fresh_store))

    saved = ledger.list_exercise_clearances(injury["id"])
    assert [(row["exercise_name"], row["verdict"]) for row in saved] == [("Back Squat", "not_cleared")]


def test_a_plain_answer_counts_only_right_after_the_question():
    from langchain_core.messages import AIMessage

    asks = assistant_graph._previous_assistant_message_asks_for_physician_advice
    question = AIMessage(content="Okay.\n\nWhat did your physician say about Back Squat?")
    answer = HumanMessage(content="cleared")

    assert asks([question, answer]) is True
    assert asks([question, HumanMessage(content="hi"), AIMessage(content="Hello!"), answer]) is False
