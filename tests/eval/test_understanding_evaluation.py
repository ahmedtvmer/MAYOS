"""Hermetic tests for the realistic-message understanding cases (#866); no live model."""

import copy
import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent import assistant_graph
from tests.eval import understanding
from tests.fakes.chat_model import ScriptedChatModel
from utils.text_scrubber import PIPELINE_ERROR_RESPONSE

ROOT = Path(__file__).resolve().parents[2]
PRESS, DUMBBELL_PRESS, SQUAT = "Bench Press (Barbell)", "Bench Press (Dumbbell)", "Back Squat (Barbell)"
PROGRAM = {
    "program_name": "Plan", "split_type": "Full Body", "weekly_frequency": 2,
    "days": [
        {"day_name": "Full A", "exercises": [{"name": SQUAT, "sets": 3}, {"name": PRESS, "sets": 3}]},
        {"day_name": "Full B", "exercises": [{"name": PRESS, "sets": 3}]},
    ],
}
SWAP = {"kind": "swap", "from": PRESS, "to": [DUMBBELL_PRESS]}
START = understanding.Snapshot(
    split="Full Body", frequency=2,
    days=(("Full A", ((SQUAT, 3), (PRESS, 3))), ("Full B", ((PRESS, 3),))),
    injuries=(("knee", "reported"),), clearances=(), preferences=(), restrictions=(),
)
SWAPPED = replace(START, days=(("Full A", ((SQUAT, 3), (DUMBBELL_PRESS, 3))), ("Full B", ((DUMBBELL_PRESS, 3),))))
SWAPPED_ON_ONE_DAY = replace(START, days=(("Full A", ((SQUAT, 3), (DUMBBELL_PRESS, 3))), ("Full B", ((PRESS, 3),))))
REBUILT = replace(START, split="PPL", frequency=3, days=(("Push", ((PRESS, 3),)),))


def _case(expected, *, allowed=None, **extra):
    case = {
        "id": "case", "language": "en", "message": "message", "expected": expected,
        "program": "plan", "review_status": "NOT_REQUIRED", **extra,
    }
    if allowed is not None:
        case["allowed_change"] = allowed
    return case


def _turn(snapshot=START, reply="Sure.", *, preview=False, coach_request=False):
    return understanding.TurnResult(
        message="message", reply=reply, intent="", preview=preview,
        coach_request=coach_request, snapshot=snapshot,
    )


# --- dataset -----------------------------------------------------------------


def test_dataset_is_valid_and_names_real_exercises():
    dataset = understanding.load_dataset()
    with (ROOT / "data" / "exercise_curation.csv").open(encoding="utf-8", newline="") as stream:
        library = {
            row["display_name"] or row["source_name"]
            for row in csv.DictReader(stream)
            if row["hidden"] != "true" and not row["duplicate_of"]
        }
    named = {
        item["name"] for program in dataset["programs"].values()
        for day in program["days"] for item in day["exercises"]
    }
    for case in dataset["cases"]:
        change = case.get("allowed_change", {})
        named.update(change.get("to", []))
        named.update(change[key] for key in ("from", "exercise") if key in change)

    assert named - library == set()
    assert len(dataset["cases"]) >= 100


@pytest.mark.parametrize(
    ("field", "value"),
    [("expected", ["maybe"]), ("program", "unknown"), ("review_status", "NOT_REQUIRED"), ("allowed_change", None)],
)
def test_dataset_validation_rejects_bad_cases(field, value):
    dataset = copy.deepcopy(understanding.load_dataset())
    case = next(
        item for item in dataset["cases"] if item["language"] != "en" and "change" in item["expected"]
    )
    case[field] = value

    with pytest.raises(ValueError):
        understanding.validate_dataset(dataset)


# --- scoring -----------------------------------------------------------------


def test_the_asked_swap_on_every_day_passes():
    result = understanding.score_case(_case(["change"], allowed=SWAP), START, [_turn(SWAPPED, "Swapped.")])

    assert (result.passed, result.outcome, result.wrong_changes) == (True, "change", [])


@pytest.mark.parametrize("snapshot", [SWAPPED_ON_ONE_DAY, REBUILT])
def test_a_change_that_was_not_asked_for_is_a_wrong_change(snapshot):
    result = understanding.score_case(_case(["change"], allowed=SWAP), START, [_turn(snapshot)])

    assert result.wrong_changes == ["program"]
    assert result.passed is False


def test_a_question_that_swaps_is_a_wrong_change_even_when_the_swap_is_tidy():
    result = understanding.score_case(_case(["answer"]), START, [_turn(SWAPPED)])

    assert (result.passed, result.wrong_changes) == (False, ["program"])


def test_a_wrong_change_undone_by_the_last_turn_still_counts():
    turns = [_turn(REBUILT), _turn(START)]

    assert understanding.score_case(_case(["answer"]), START, turns).wrong_changes == ["program"]


def test_a_question_saved_as_a_clearance_is_a_wrong_change():
    cleared = replace(START, injuries=(("knee", "physician_seen"),), clearances=((SQUAT, "cleared"),))

    assert understanding.score_case(_case(["answer"]), START, [_turn(cleared)]).wrong_changes == [
        "injury or preference records"
    ]


def test_the_reported_clearance_passes_and_its_opposite_is_wrong():
    allowed = {"kind": "clearance", "exercise": SQUAT, "verdict": "not_cleared"}
    case = _case(["change"], allowed=allowed)

    saved = replace(START, clearances=((SQUAT, "not_cleared"),))
    opposite = replace(START, clearances=((SQUAT, "cleared"),))

    assert understanding.score_case(case, START, [_turn(saved)]).passed is True
    assert understanding.score_case(case, START, [_turn(opposite)]).wrong_changes != []


def test_ask_needs_a_question_that_names_an_option():
    case = _case(["ask"], reply_any=["Front Plank"])

    assert understanding.score_case(case, START, [_turn(reply="Front Plank or Side Plank?")]).passed is True
    assert understanding.score_case(case, START, [_turn(reply="Which exercise?")]).passed is False
    assert understanding.score_case(case, START, [_turn(reply="Front Plank.")]).passed is False


def test_a_reply_claiming_a_change_that_did_not_happen_fails():
    result = understanding.score_case(_case(["answer"]), START, [_turn(reply="I've swapped it for you.")])

    assert (result.passed, result.false_claim) == (False, True)


def test_a_forbidden_phrase_in_the_reply_fails():
    case = _case(["answer"], reply_none=["your coach"])

    assert understanding.score_case(case, START, [_turn(reply="Ask Your Coach first.")]).passed is False


def test_a_rebuild_without_confirmation_is_reported_separately_from_wrong_changes():
    case = _case(["confirm"], allowed={"kind": "rebuild", "splits": ["ppl"], "frequency": 3})

    result = understanding.score_case(case, START, [_turn(REBUILT)])

    assert (result.passed, result.wrong_changes, result.unconfirmed_rebuild) == (False, [], True)


def test_a_rebuild_after_a_confirmation_passes():
    case = _case(["change"], allowed={"kind": "rebuild", "splits": ["ppl"], "frequency": 3})

    result = understanding.score_case(case, START, [_turn(reply="Rebuild to PPL?"), _turn(REBUILT)])

    assert (result.passed, result.unconfirmed_rebuild) == (True, False)


def test_an_answered_question_that_was_already_applied_early_fails():
    result = understanding.score_case(
        _case(["change"], allowed=SWAP), START, [_turn(SWAPPED), _turn(SWAPPED)]
    )

    assert result.passed is False


@pytest.mark.parametrize(
    ("change", "after", "allowed"),
    [
        ({"kind": "sets", "exercise": SQUAT, "sets": 4},
         replace(START, days=(("Full A", ((SQUAT, 4), (PRESS, 3))), START.days[1])), True),
        ({"kind": "sets", "exercise": SQUAT, "sets": 4},
         replace(START, days=(("Full A", ((SQUAT, 4), (PRESS, 4))), START.days[1])), False),
        ({"kind": "remove", "exercise": PRESS, "days": ["Full A"]},
         replace(START, days=(("Full A", ((SQUAT, 3),)), START.days[1])), True),
        ({"kind": "remove", "exercise": PRESS, "days": ["Full A"]},
         replace(START, days=(START.days[0], ("Full B", ()))), False),
        ({"kind": "add", "days": ["Full B"]},
         replace(START, days=(START.days[0], ("Full B", ((PRESS, 3), (SQUAT, 3))))), True),
        ({"kind": "add", "days": ["Full B"]},
         replace(START, days=(START.days[0], ("Full B", ((SQUAT, 3),)))), False),
    ],
)
def test_edits_are_compared_exactly(change, after, allowed):
    assert (understanding.wrong_changes(START, after, change) == []) is allowed


# --- real turns over the synthetic catalog -------------------------------------


@pytest.fixture
def no_model(monkeypatch):
    model = ScriptedChatModel([])
    monkeypatch.setattr(assistant_graph, "llm", model)
    return model


def test_a_swap_case_runs_through_the_real_turn(fresh_store, no_model):
    program = understanding.build_program(fresh_store, PROGRAM)
    case = _case(["change"], allowed=SWAP, message=f"swap {PRESS} for {DUMBBELL_PRESS}")

    result = understanding.run_case(fresh_store, case, program)

    assert (result.passed, result.outcome, result.attempts) == (True, "change", 1), result


def test_a_coach_controlled_case_is_refused_and_unchanged(fresh_store, no_model):
    program = understanding.build_program(fresh_store, PROGRAM)
    case = _case(["refuse"], message=f"swap {PRESS} for {DUMBBELL_PRESS}", authority="coach")

    result = understanding.run_case(fresh_store, case, program)

    assert (result.passed, result.outcome) == (True, "refuse"), result


def test_the_injury_fixture_is_recorded_before_the_first_turn(fresh_store):
    program = understanding.build_program(fresh_store, PROGRAM)
    case = _case(["answer"], injury={"area": "knee", "description": "knee pain"})

    player = understanding.prepare_player(fresh_store, case, program, "injured")

    with fresh_store.open_ledger(player.ledger_id) as ledger:
        assert understanding.take_snapshot(ledger).injuries == (("knee", "reported"),)


def test_a_pipeline_failure_is_retried_on_a_fresh_player_and_never_passes(fresh_store, monkeypatch):
    program = understanding.build_program(fresh_store, PROGRAM)
    players = []

    def failing_turn(_store, player, _message):
        players.append(player.account_id)
        return _turn(understanding_start, PIPELINE_ERROR_RESPONSE)

    case = _case(["answer"])
    probe = understanding.prepare_player(fresh_store, case, program, "probe")
    with fresh_store.open_ledger(probe.ledger_id) as ledger:
        understanding_start = understanding.take_snapshot(ledger)
    monkeypatch.setattr(understanding, "run_turn", failing_turn)

    result = understanding.run_case(fresh_store, case, program)

    assert (result.scored, result.passed, result.attempts) == (False, False, 3)
    assert len(set(players)) == 3


# --- report -------------------------------------------------------------------


def test_report_separates_counted_cases_from_pending_review():
    dataset = {"version": 1, "cases": [{}, {}]}
    counted = understanding.score_case(_case(["answer"]), START, [_turn()])
    pending = understanding.score_case(
        _case(["answer"], review_status="PENDING_OWNER"), START, [_turn(SWAPPED)]
    )

    report = understanding.build_report(
        dataset, [counted, pending], model="model-a", real_model_run=True, commit="c"
    )

    assert report["counted"]["correct"] == 1
    assert report["counted"]["wrong_changes_applied"] == 0
    assert report["all_cases"]["wrong_changes_applied"] == 1
    assert report["partial"] is False
    assert json.loads(json.dumps(report)) == report
