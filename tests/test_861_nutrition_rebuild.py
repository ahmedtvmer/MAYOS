"""Issue #861: a Player can rebuild their Nutrition plan from chat.

A rebuild request routes in code, never to the model. Chat shows the
recalculated Nutrition targets (the same formulas as setup) and changes nothing
until the Player answers yes. A Coach who holds Nutrition authority, a positive
health screening and a missing plan each get a fixed reply. Questions about
the plan are never a rebuild. No test calls a model.
"""

import json
from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.assistant_graph import _is_nutrition_rebuild_request, stream_assistant_turn
from database.ledger.nutrition import NutritionPlanVersion
from service import nutrition
from tests.test_808_routing_swaps import (  # noqa: F401 - fixtures used by name
    COACHING_REPLY,
    _scripted,
    _turn,
    program_store,
)

PROFILE = {"age": 30, "height_cm": 180.0, "weight_kg": 90.0, "gender": "male", "weekly_frequency": 3}
SETUP = {
    "sex": "male",
    "daily_activity": "mostly_sitting",
    "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
}


def _set_weight(ledger, weight_kg):
    ledger.upsert_player_profile({**PROFILE, "weight_kg": weight_kg})


@pytest.fixture
def nutrition_store(program_store):
    """A Player with a Nutrition plan set up at 90 kg who now weighs 80 kg."""
    store = program_store
    ledger = store.ledger
    _set_weight(ledger, 90.0)
    assert nutrition.setup(ledger, SETUP)["state"] == "ready"
    _set_weight(ledger, 80.0)
    return store


def _plans(ledger):
    return [dict(row) for row in ledger.conn.execute("SELECT * FROM nutrition_plan_versions ORDER BY id")]


def _calories(plan):
    return json.loads(plan["targets_json"])["calories"]


def _ask(store, monkeypatch, message, player_account_id=None):
    _scripted(monkeypatch, [], default_turn=COACHING_REPLY)
    state = _turn(message)
    state["player_account_id"] = player_account_id
    reply = "".join(stream_assistant_turn(state, ledger=store.ledger, store=store))
    return state, reply


def _answer(store, monkeypatch, first, offer, answer, player_account_id=None):
    _scripted(monkeypatch, [], default_turn=COACHING_REPLY)
    state = _turn(answer)
    state["player_account_id"] = player_account_id
    state["messages"] = [HumanMessage(content=first), AIMessage(content=offer), HumanMessage(content=answer)]
    reply = "".join(stream_assistant_turn(state, ledger=store.ledger, store=store))
    return state, reply


def _coach_assignment(store, ledger, monkeypatch):
    """The assigned Coach publishes the current targets, taking Nutrition authority."""
    active = ledger.get_active_nutrition_plan()
    with ledger.ledger_transaction():
        ledger.save_nutrition_plan(NutritionPlanVersion(
            goal=active["goal"], reason={"code": "coach"}, intensity=active["intensity"],
            daily_activity=active["daily_activity"], targets=json.loads(active["targets_json"]),
            author="Coach", provenance="coach", authority_assignment_id="assignment-1",
        ))
    monkeypatch.setattr(
        store, "get_active_assignment_for_player",
        lambda _player: {"assignment_id": "assignment-1", "coach_account_id": "coach-1"},
        raising=False,
    )


# --- 1. Preview first, then rebuild on yes -----------------------------------


@pytest.mark.parametrize(
    ("request_text", "answer", "language"),
    [
        ("rebuild my nutrition plan", "yes", "en"),
        ("ظبطلي خطة الأكل من جديد", "أيوه", "ar"),
        ("أعد بناء خطة التغذية", "نعم", "ar"),
        ("اعملي خطة أكل جديدة", "ابنيها", "ar"),
    ],
    ids=["english", "egyptian", "msa", "egyptian-new-plan"],
)
def test_rebuild_previews_then_saves_on_yes(nutrition_store, monkeypatch, request_text, answer, language):
    store = nutrition_store
    ledger = store.ledger
    before = _plans(ledger)
    expected = nutrition.rebuild_preview(ledger)
    assert expected["state"] == "ready"
    assert expected["after"]["calories"] < expected["before"]["calories"]

    state, offer = _ask(store, monkeypatch, request_text)

    assert state["intent"] == "nutrition_rebuild"
    assert _plans(ledger) == before
    assert ledger.get_pending_nutrition_rebuild() is not None
    assert state["nutrition_updated"] is False
    assert str(expected["before"]["calories"]) in offer and str(expected["after"]["calories"]) in offer
    assert ("رد بـ «أيوه»" in offer) == (language == "ar")
    assert ("Reply yes" in offer) == (language == "en")

    state, reply = _answer(store, monkeypatch, request_text, offer, answer)

    assert state["intent"] == "nutrition_rebuild"
    plans = _plans(ledger)
    assert len(plans) == len(before) + 1
    saved = plans[-1]
    assert _calories(saved) == expected["after"]["calories"]
    assert (saved["goal"], saved["intensity"], saved["daily_activity"]) == (
        before[-1]["goal"], before[-1]["intensity"], before[-1]["daily_activity"])
    assert saved["author"] == "Player"
    assert state["nutrition_updated"] is True
    assert ledger.get_pending_nutrition_rebuild() is None
    assert ("اتبنت من جديد" in reply) == (language == "ar")
    assert ("Rebuilt your Nutrition plan" in reply) == (language == "en")


def test_rebuild_reuses_the_setup_formulas(nutrition_store):
    ledger = nutrition_store.ledger
    profile = ledger.get_nutrition_profile()
    active = ledger.get_active_nutrition_plan()
    direct = nutrition._calculate_for(ledger, profile, profile["gender"], active["daily_activity"],
                                      active["goal"], active["intensity"] or "moderate")
    preview = nutrition.rebuild_preview(ledger)
    assert preview["after"] == {field: direct[field] for field in nutrition.REBUILD_TARGET_FIELDS}


# --- 2. No, anything else, an older offer and a changed plan -----------------


@pytest.mark.parametrize(("answer", "cancel_text"), [
    ("no", "cancelled the Nutrition plan rebuild"),
    ("لا", "ألغيت إعادة بناء خطة الأكل"),
])
def test_no_cancels_the_rebuild(nutrition_store, monkeypatch, answer, cancel_text):
    store = nutrition_store
    request_text = "rebuild my nutrition plan" if answer == "no" else "ظبطلي خطة الأكل من جديد"
    _state, offer = _ask(store, monkeypatch, request_text)
    before = _plans(store.ledger)

    state, reply = _answer(store, monkeypatch, request_text, offer, answer)

    assert state["intent"] == "telemetry_intercept"
    assert cancel_text in reply
    assert _plans(store.ledger) == before
    assert store.ledger.get_pending_nutrition_rebuild() is None


def test_unrelated_message_drops_the_offer(nutrition_store, monkeypatch):
    store = nutrition_store
    _state, offer = _ask(store, monkeypatch, "rebuild my nutrition plan")
    before = _plans(store.ledger)

    state, _reply = _answer(store, monkeypatch, "rebuild my nutrition plan", offer, "how much protein is in eggs")

    assert state["intent"] != "nutrition_rebuild"
    assert _plans(store.ledger) == before
    assert store.ledger.get_pending_nutrition_rebuild() is None


def test_yes_to_an_older_offer_changes_nothing(nutrition_store, monkeypatch):
    store = nutrition_store
    _state, offer = _ask(store, monkeypatch, "rebuild my nutrition plan")
    before = _plans(store.ledger)
    _scripted(monkeypatch, [], default_turn=COACHING_REPLY)
    state = _turn("yes")
    state["messages"] = [
        HumanMessage(content="rebuild my nutrition plan"), AIMessage(content=offer),
        HumanMessage(content="thanks"), AIMessage(content="Anytime."), HumanMessage(content="yes"),
    ]
    "".join(stream_assistant_turn(state, ledger=store.ledger, store=store))

    assert state["intent"] != "nutrition_rebuild"
    assert _plans(store.ledger) == before


def test_yes_after_the_plan_changed_is_stale(nutrition_store, monkeypatch):
    store = nutrition_store
    ledger = store.ledger
    _state, offer = _ask(store, monkeypatch, "rebuild my nutrition plan")
    nutrition.update_activity(ledger, "on_feet", date.today())
    before = _plans(ledger)

    state, reply = _answer(store, monkeypatch, "rebuild my nutrition plan", offer, "yes")

    assert state["intent"] == "nutrition_rebuild"
    assert "changed after I showed that rebuild" in reply
    assert _plans(ledger) == before


# --- 3. Fixed replies: unchanged, Coach authority, screening, no plan -------


def test_unchanged_targets_say_nothing_changed(nutrition_store, monkeypatch):
    store = nutrition_store
    _set_weight(store.ledger, 90.0)
    before = _plans(store.ledger)

    state, reply = _ask(store, monkeypatch, "rebuild my nutrition plan")

    assert state["intent"] == "nutrition_rebuild"
    assert "already match your current profile" in reply
    assert _plans(store.ledger) == before
    assert store.ledger.get_pending_nutrition_rebuild() is None


@pytest.mark.parametrize(("request_text", "coach_text"), [
    ("rebuild my nutrition plan", "Your Coach controls your Nutrition plan"),
    ("ظبطلي خطة الأكل من جديد", "الكوتش بتاعك هو اللي ماسك خطة الأكل"),
])
def test_coach_authority_gets_the_fixed_reply(nutrition_store, monkeypatch, request_text, coach_text):
    store = nutrition_store
    _coach_assignment(store, store.ledger, monkeypatch)
    before = _plans(store.ledger)

    state, reply = _ask(store, monkeypatch, request_text, player_account_id="player-1")

    assert state["intent"] == "nutrition_rebuild"
    assert coach_text in reply
    assert _plans(store.ledger) == before
    assert store.ledger.get_pending_nutrition_rebuild() is None


def test_coach_taking_authority_before_yes_blocks_the_rebuild(nutrition_store, monkeypatch):
    store = nutrition_store
    _state, offer = _ask(store, monkeypatch, "rebuild my nutrition plan", player_account_id="player-1")
    _coach_assignment(store, store.ledger, monkeypatch)
    before = _plans(store.ledger)

    _state, reply = _answer(store, monkeypatch, "rebuild my nutrition plan", offer, "yes",
                            player_account_id="player-1")

    assert "Your Coach controls your Nutrition plan" in reply
    assert _plans(store.ledger) == before


def test_ended_assignment_returns_authority_to_the_player(nutrition_store, monkeypatch):
    store = nutrition_store
    _coach_assignment(store, store.ledger, monkeypatch)
    monkeypatch.setattr(store, "get_active_assignment_for_player", lambda _player: None, raising=False)

    state, offer = _ask(store, monkeypatch, "rebuild my nutrition plan", player_account_id="player-1")

    assert "Reply yes" in offer
    assert store.ledger.get_pending_nutrition_rebuild() is not None


def test_positive_screening_gets_the_fixed_reply(nutrition_store, monkeypatch):
    store = nutrition_store
    ledger = store.ledger
    with ledger.ledger_transaction():
        ledger.save_nutrition_setup(nutrition.NutritionSetup(
            "male", "mostly_sitting",
            {"pregnant_or_breastfeeding": False, "medical_condition": True, "eating_disorder": False}, None,
        ))
    before = _plans(ledger)

    _state, english = _ask(store, monkeypatch, "rebuild my nutrition plan")
    _state, arabic = _ask(store, monkeypatch, "أعد بناء خطة التغذية")

    assert english == nutrition.MESSAGES["blocked"][0]
    assert arabic == nutrition.MESSAGES["blocked"][1]
    assert _plans(ledger) == before
    assert ledger.get_pending_nutrition_rebuild() is None


def test_no_plan_points_to_nutrition_setup(program_store, monkeypatch):
    store = program_store
    _set_weight(store.ledger, 80.0)

    state, reply = _ask(store, monkeypatch, "rebuild my nutrition plan")

    assert state["intent"] == "nutrition_rebuild"
    assert "don't have a Nutrition plan yet" in reply
    assert _plans(store.ledger) == []


# --- 4. Questions and negations are never a rebuild ---------------------------


@pytest.mark.parametrize("text", [
    "is my nutrition plan good?",
    "how do I rebuild my nutrition plan?",
    "don't rebuild my nutrition plan",
    "خطة الأكل بتاعتي كويسة؟",
    "ممكن أعيد بناء خطة الأكل؟",
    "مش عايز أغير خطة الأكل",
    "هل أعيد حساب خطة التغذية؟",
])
def test_questions_and_negations_change_nothing(nutrition_store, monkeypatch, text):
    store = nutrition_store
    before = _plans(store.ledger)

    state, _reply = _ask(store, monkeypatch, text)

    assert state["intent"] != "nutrition_rebuild"
    assert _plans(store.ledger) == before
    assert store.ledger.get_pending_nutrition_rebuild() is None


@pytest.mark.parametrize(("text", "expected"), [
    ("rebuild my nutrition plan", True),
    ("Rebuild my diet plan please", True),
    ("can you rebuild my nutrition plan?", True),
    ("recalculate my macros", True),
    ("make me a new nutrition plan", True),
    ("please update my nutrition targets", True),
    ("ظبطلي خطة الأكل من جديد", True),
    ("أعد بناء خطة التغذية", True),
    ("اعملي خطة أكل جديدة", True),
    ("جددلي خطة الأكل", True),
    ("ممكن تعيد حساب خطة الأكل؟", True),
    ("عيد بناء النظام الغذائي بتاعي", True),
    ("is my nutrition plan good?", False),
    ("should I recalculate my macros?", False),
    ("rebuild my program", False),
    ("rebuild my split", False),
    ("update my meal log", False),
    ("ظبطلي خطة الأكل", False),
    ("ظبطلي البرنامج من جديد", False),
    ("ليه خطة الأكل كدا؟", False),
    ("متعملش خطة أكل جديدة", False),
    ("اكلت فراخ النهارده", False),
])
def test_rebuild_request_matcher(text, expected):
    assert _is_nutrition_rebuild_request(text) is expected

