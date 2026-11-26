"""Issue #867: every Training program rebuild is confirmed first, and loose
wording the classifier understands gets that confirmation instead of advice.

A rebuild replaces the program and clears the chat, so chat shows the new
program and changes nothing until the Player answers yes. "No" or any other
message drops the offer. Questions, negations and hedges never preview. The
classifier stays scripted and program generation is faked; no test calls a model.
"""

from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import agent.assistant_graph as assistant_graph
from agent.assistant_graph import stream_assistant_turn
from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema
from tests.test_808_routing_swaps import (  # noqa: F401 - fixtures used by name
    COACHING_REPLY,
    _exercise_slot,
    _scripted,
    _seed_program,
    _turn,
    program_store,
)

DAY_NAMES = ("Push", "Pull", "Legs", "Upper", "Lower")
EXERCISES = ("Chest Fly", "Incline Dumbbell Press", "Shoulder Press (Dumbbell)")
ARABIC_PPL = {"intent": "program_change", "target_split_type": "ppl", "target_frequency": 3}


@pytest.fixture
def rebuild_store(program_store, monkeypatch):
    """A seeded program, with generation faked: the draft builds the preview
    and the pipeline saves it, the way the real ones do."""
    store = program_store
    _seed_program(store, {"Full Body A": EXERCISES, "Full Body B": EXERCISES, "Full Body C": EXERCISES})
    calls = {"draft": [], "save": []}

    def built(frequency):
        frequency = frequency or 3
        return GeneratedProgramSchema(
            program_name="Rebuilt PPL",
            split_type="PPL",
            weekly_frequency=frequency,
            days=[
                ProgramDaySchema(
                    day_name=DAY_NAMES[index],
                    day_order=index + 1,
                    exercises=[_exercise_slot(store, name) for name in EXERCISES],
                )
                for index in range(frequency)
            ],
        )

    def draft(request, *, ledger, **_kwargs):
        calls["draft"].append((request.user_split_override, request.frequency_override))
        return built(request.frequency_override), "md"

    def pipeline(user_split_override=None, rep_preference_override=None, frequency_override=None, *, ledger, **_kwargs):
        calls["save"].append((user_split_override, frequency_override))
        program = built(frequency_override)
        ledger.save_training_program(program.model_dump())
        return program, "md"

    monkeypatch.setattr(assistant_graph, "generate_program_draft_pipeline", draft)
    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", pipeline)
    store.rebuild_calls = calls
    return store


def _ask(store, monkeypatch, message, turns=()):
    _scripted(monkeypatch, list(turns), default_turn=COACHING_REPLY)
    state = _turn(message)
    reply = "".join(stream_assistant_turn(state, ledger=store.ledger, store=store))
    return state, reply


def _answer(store, monkeypatch, first, offer, answer, turns=()):
    _scripted(monkeypatch, list(turns), default_turn=COACHING_REPLY)
    state = _turn(answer)
    state["messages"] = [HumanMessage(content=first), AIMessage(content=offer), HumanMessage(content=answer)]
    reply = "".join(stream_assistant_turn(state, ledger=store.ledger, store=store))
    return state, reply


def _assert_preview_only(store, before, reply):
    after = store.ledger.get_active_program()
    assert after.version == before.version
    assert after.program_name == before.program_name
    assert store.rebuild_calls["save"] == []
    assert store.ledger.get_pending_program_rebuild() is not None
    assert "Rebuilt PPL" in reply


# --- 1. Every rebuild previews first, then rebuilds on yes --------------------


@pytest.mark.parametrize(
    ("request_text", "turns", "answer", "language"),
    [
        ("rebuild my program 3 days", (), "yes", "en"),
        ("rebuild my program 3 days", (), "ok, go ahead", "en"),
        ("غيّر برنامجي لـ PPL 3 أيام", (ARABIC_PPL,), "أيوه", "ar"),
        ("ظبطلي البرنامج PPL تلات أيام", (ARABIC_PPL,), "تمام", "ar"),
        ("غيّر برنامجي لـ PPL 3 أيام", (ARABIC_PPL,), "aywa", "ar"),
    ],
    ids=["english", "english-loose-yes", "egyptian", "egyptian-zabat", "franco-yes"],
)
def test_rebuild_previews_then_rebuilds_on_yes(rebuild_store, monkeypatch, request_text, turns, answer, language):
    store = rebuild_store
    before = store.ledger.get_active_program()

    state, offer = _ask(store, monkeypatch, request_text, turns)

    assert state["intent"] == "program_mutation"
    assert state["program_updated"] is False
    _assert_preview_only(store, before, offer)
    assert ("رد بـ «أيوه»" in offer) == (language == "ar")
    assert ("Reply yes" in offer) == (language == "en")

    state, reply = _answer(store, monkeypatch, request_text, offer, answer)

    assert state["intent"] == "program_mutation"
    assert state["program_updated"] is True
    assert state["program_change"] == "regenerated"
    assert store.ledger.get_active_program().program_name == "Rebuilt PPL"
    assert len(store.rebuild_calls["save"]) == 1
    assert store.rebuild_calls["save"][0][1] == 3
    assert store.ledger.get_pending_program_rebuild() is None
    assert ("ظبطتلك البرنامج" in reply) == (language == "ar")


# --- 2. "No" and unrelated messages cancel ------------------------------------


@pytest.mark.parametrize("answer", ["no", "cancel", "لا", "لأ شكرا", "بلاش", "la2"])
def test_no_cancels_the_rebuild(rebuild_store, monkeypatch, answer):
    store = rebuild_store
    before = store.ledger.get_active_program()
    _, offer = _ask(store, monkeypatch, "rebuild my program 3 days")

    _, reply = _answer(store, monkeypatch, "rebuild my program 3 days", offer, answer)

    after = store.ledger.get_active_program()
    assert after.version == before.version
    assert store.rebuild_calls["save"] == []
    assert store.ledger.get_pending_program_rebuild() is None
    assert "Nothing changed" in reply or "مفيش حاجة اتغيرت" in reply


@pytest.mark.parametrize(
    "answer",
    ["how many sets should I do for chest?", "yes but keep my legs day", "ايوه بس مش دلوقتي؟"],
)
def test_unrelated_message_drops_the_rebuild(rebuild_store, monkeypatch, answer):
    store = rebuild_store
    before = store.ledger.get_active_program()
    _, offer = _ask(store, monkeypatch, "rebuild my program 3 days")

    _answer(store, monkeypatch, "rebuild my program 3 days", offer, answer)

    assert store.ledger.get_active_program().version == before.version
    assert store.rebuild_calls["save"] == []
    assert store.ledger.get_pending_program_rebuild() is None


def test_yes_after_the_offer_was_dropped_changes_nothing(rebuild_store, monkeypatch):
    store = rebuild_store
    before = store.ledger.get_active_program()
    _, offer = _ask(store, monkeypatch, "rebuild my program 3 days")
    _answer(store, monkeypatch, "rebuild my program 3 days", offer, "how many sets should I do for chest?")

    state, _ = _answer(store, monkeypatch, "rebuild my program 3 days", offer, "yes")

    assert state["program_updated"] is False
    assert store.ledger.get_active_program().version == before.version
    assert store.rebuild_calls["save"] == []


def test_yes_to_an_older_offer_changes_nothing(rebuild_store, monkeypatch):
    store = rebuild_store
    _, offer = _ask(store, monkeypatch, "rebuild my program 3 days")

    state, _ = _answer(store, monkeypatch, "rebuild my program 3 days", "Something else chat said.", "yes")

    assert state["program_updated"] is False
    assert store.rebuild_calls["save"] == []
    assert store.ledger.get_pending_program_rebuild() is None


def test_expired_offer_changes_nothing(rebuild_store, monkeypatch):
    store = rebuild_store
    _, offer = _ask(store, monkeypatch, "rebuild my program 3 days")
    old = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    store.ledger.conn.execute("UPDATE assistant_goal_weak_point_pending SET created_at = ?", (old,))

    state, _ = _answer(store, monkeypatch, "rebuild my program 3 days", offer, "yes")

    assert state["program_updated"] is False
    assert store.rebuild_calls["save"] == []


def test_program_changed_after_the_offer_changes_nothing(rebuild_store, monkeypatch):
    store = rebuild_store
    _, offer = _ask(store, monkeypatch, "rebuild my program 3 days")
    _seed_program(store, {"Other A": EXERCISES, "Other B": EXERCISES, "Other C": EXERCISES})
    changed = store.ledger.get_active_program()

    state, _ = _answer(store, monkeypatch, "rebuild my program 3 days", offer, "yes")

    assert state["program_updated"] is False
    assert store.ledger.get_active_program().version == changed.version
    assert store.rebuild_calls["save"] == []


def test_coach_controlled_program_refuses_the_confirmed_rebuild(rebuild_store, monkeypatch):
    store = rebuild_store
    before = store.ledger.get_active_program()
    _, offer = _ask(store, monkeypatch, "rebuild my program 3 days")
    monkeypatch.setattr(assistant_graph.programs_service, "player_controls_program", lambda *args, **kwargs: False)

    state, _ = _answer(store, monkeypatch, "rebuild my program 3 days", offer, "yes")

    assert state["intent"] == "coach_controlled"
    assert state["program_updated"] is False
    assert store.ledger.get_active_program().version == before.version
    assert store.rebuild_calls["save"] == []


# --- 3. Loose wording the classifier understands gets a preview ----------------


@pytest.mark.parametrize(
    ("request_text", "turns"),
    [
        ("نفسي أجرب PPL 3 أيام في الأسبوع", (ARABIC_PPL,)),
        ("أريد برنامج دفع وسحب وأرجل ثلاثة أيام", (ARABIC_PPL,)),
        ("make my routine a ppl split", ()),
        ("i want a ppl split", ()),
    ],
    ids=["egyptian-loose", "msa-loose", "english-make", "english-want"],
)
def test_loose_request_gets_a_preview(rebuild_store, monkeypatch, request_text, turns):
    store = rebuild_store
    before = store.ledger.get_active_program()

    state, offer = _ask(store, monkeypatch, request_text, turns)

    assert state["intent"] == "program_mutation"
    _assert_preview_only(store, before, offer)


# --- 4. Questions, negations and hedges never change or preview ----------------


@pytest.mark.parametrize(
    ("request_text", "turns"),
    [
        ("should I change my split to ppl?", ()),
        ("don't rebuild my program", ()),
        ("ينفع أغير البرنامج لـ PPL؟", (ARABIC_PPL,)),
        ("مش عايز أغير البرنامج لـ PPL", (ARABIC_PPL,)),
        ("كنت عايز أغير البرنامج لـ PPL", (ARABIC_PPL,)),
        ("مش متأكد أغير البرنامج لـ PPL", (ARABIC_PPL,)),
    ],
    ids=["english-question", "english-negation", "arabic-question", "arabic-negation", "arabic-hedge", "arabic-unsure"],
)
def test_questions_negations_and_hedges_never_preview(rebuild_store, monkeypatch, request_text, turns):
    store = rebuild_store
    before = store.ledger.get_active_program()

    state, _ = _ask(store, monkeypatch, request_text, turns)

    assert state["intent"] != "program_mutation"
    assert state["program_updated"] is False
    assert store.ledger.get_active_program().version == before.version
    assert store.rebuild_calls["draft"] == []
    assert store.ledger.get_pending_program_rebuild() is None


# --- 5. The yes/no answer is matched in code ----------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("yes", "yes"), ("Yes please", "yes"), ("go ahead!", "yes"), ("أيوه", "yes"),
        ("ايوه يا كوتش", "yes"), ("تمام", "yes"), ("aywa", "yes"), ("ماشي", "yes"),
        ("no", "no"), ("لا", "no"), ("مش عايز", "no"), ("cancel", "no"), ("la2", "no"),
        ("yes?", None), ("yes but only 3 days", None), ("rebuild my program", None),
        ("ايوه بس غير الرجل", None), ("", None),
    ],
)
def test_rebuild_answer_in_code(answer, expected):
    assert assistant_graph._program_rebuild_answer(answer) == expected
