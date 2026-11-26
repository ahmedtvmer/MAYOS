"""Realistic-message understanding cases: run them through real chat turns and score them in code (#866).

Every case gets its own throwaway Player. Each message goes through
``stream_assistant_turn`` with the same persistence the chat route uses, so a
follow-up case really answers the question the assistant asked. Scoring never
asks a judge model: it compares the Program and the injury records before and
after every turn, and reads the reply only for fixed facts (a question was
asked, an option was named).

Two numbers matter: correct outcomes, and **wrong changes applied** (a Program
or injury write the message did not ask for), which must be 0.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent import assistant_graph
from agent.program_blueprints import SPLIT_DISPLAY_NAMES
from agent.ProgramState import (
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
)
from agent.prompts import DEFAULT_ASSISTANT_STYLE
from service import assignments as assignments_service
from service import chat as chat_service
from service import coach as coach_service
from service import injuries as injuries_service
from utils.text_scrubber import PIPELINE_ERROR_RESPONSES

BASE_DIR = Path(__file__).resolve().parents[2]
DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "understanding_cases.json"
OUTCOMES = ("change", "confirm", "ask", "answer", "refuse")
LANGUAGES = ("en", "egy", "msa", "mixed", "franco")
CHANGE_KINDS = ("swap", "rebuild", "sets", "remove", "add", "clearance")
REVIEW_STATUSES = ("NOT_REQUIRED", "PENDING_OWNER", "OWNER_REVIEWED")
MAX_CASE_ATTEMPTS = 3

#: Replies that claim a change was made. Checked only when nothing changed.
CLAIMED_DONE_RE = re.compile(
    r"\b(?:i(?:'ve| have)?\s+(?:swapped|changed|replaced|updated|rebuilt|removed|added)|rebuilt routine)\b"
    r"|(?:بدلت|بدّلت|غيرت|غيّرت|استبدلت|شلت|ضفت)\s*لك"
    r"|تم\s+(?:ال)?(?:تبديل|تغيير|استبدال)",
    re.IGNORECASE,
)


# --- dataset ---------------------------------------------------------------


def load_dataset(path: Path = DATASET_PATH) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    validate_dataset(dataset)
    return dataset


def validate_dataset(dataset: dict[str, Any]) -> None:
    cases = dataset.get("cases")
    programs = dataset.get("programs")
    if not isinstance(cases, list) or not cases or not isinstance(programs, dict):
        raise ValueError("The understanding dataset needs programs and at least one case.")
    identifiers = [case.get("id") for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Understanding case ids must be unique.")
    for case in cases:
        _validate_case(case, programs)


def _validate_case(case: dict[str, Any], programs: dict[str, Any]) -> None:
    label = f"Understanding case {case.get('id')!r}"
    if not case.get("message") or case.get("language") not in LANGUAGES:
        raise ValueError(f"{label} needs a message and a known language.")
    if case.get("program") not in programs:
        raise ValueError(f"{label} names an unknown program.")
    expected = case.get("expected")
    if not isinstance(expected, list) or not expected or not set(expected) <= set(OUTCOMES):
        raise ValueError(f"{label} has an unknown expected outcome.")
    allowed = case.get("allowed_change")
    if "change" in expected and allowed is None:
        raise ValueError(f"{label} expects a change but does not say which one.")
    if allowed is not None and allowed.get("kind") not in CHANGE_KINDS:
        raise ValueError(f"{label} has an unknown change kind.")
    status = case.get("review_status")
    if status not in REVIEW_STATUSES:
        raise ValueError(f"{label} has an unknown review status.")
    if case["language"] != "en" and status == "NOT_REQUIRED":
        raise ValueError(f"{label} is not English, so the owner must review it.")


def counts_toward_score(case: dict[str, Any]) -> bool:
    return case["review_status"] != "PENDING_OWNER"


# --- Player fixtures -------------------------------------------------------


@contextmanager
def real_library_store(exercises_csv: Path) -> Iterator[Any]:
    """A throwaway store over the real exercise library the cases name."""
    from database.database_manager import DatabaseManager
    from tests.catalog import close_catalog_store, seed_catalog

    with tempfile.TemporaryDirectory(prefix="mayos-understanding-", ignore_cleanup_errors=True) as temp_root:
        root = Path(temp_root)
        store = DatabaseManager(
            catalog_path=root / "catalog.db",
            ledgers_dir=root / "users",
            backups_dir=root / "backups",
        )
        try:
            seed_catalog(store, csv_path=exercises_csv)
            yield store
        finally:
            close_catalog_store(store)


@dataclass(frozen=True)
class CasePlayer:
    account_id: str
    ledger_id: str


def _register(store: Any, username: str) -> CasePlayer:
    account_id = store.create_account(username)
    if not account_id:
        raise ValueError(f"Could not create the case account {username!r}.")
    account = store.get_active_account_by_username(username)
    with store.open_ledger(account["ledger_id"]):
        pass
    return CasePlayer(account_id, account["ledger_id"])


def _assign_coach(store: Any, player: CasePlayer, username: str) -> str:
    """Assigns a fresh Coach to the Player and returns the Coach's account id."""
    coach = _register(store, username)
    invite = coach_service.issue_coach_invite(store, username, actor="cli")
    coach_service.redeem_coach_invite(store, coach.account_id, invite["token"])
    assignment = assignments_service.issue_assignment_invite(store, coach.account_id)
    redeemed = assignments_service.redeem_assignment_invite(
        store, assignment["token"], player.account_id, True
    )
    if "error" in redeemed:
        raise ValueError(f"Could not assign the case Coach: {redeemed['error']}")
    return coach.account_id


def _program_exercise(store: Any, spec: dict[str, Any]) -> PersistedProgramExerciseSchema:
    entries = [
        store.get_exercise_library_entry(str(match["id"]))
        for match in store.find_exercises_by_name(spec["name"], limit=10)
    ]
    entry = next(
        (item for item in entries if item and spec["name"] in {item.get("display_name"), item.get("name")}), None
    )
    if entry is None:
        raise ValueError(f"The exercise library has no exercise named {spec['name']!r}.")
    return PersistedProgramExerciseSchema(
        exercise_id=str(entry["id"]),
        exercise_name=spec["name"],
        target_sets=spec["sets"],
        target_reps_min=8,
        target_reps_max=12,
    )


def build_program(store: Any, spec: dict[str, Any]) -> dict[str, Any]:
    return PersistedProgramSchema(
        program_name=spec["program_name"],
        split_type=spec["split_type"],
        weekly_frequency=spec["weekly_frequency"],
        days=[
            PersistedProgramDaySchema(
                day_name=day["day_name"],
                day_order=order,
                exercises=[_program_exercise(store, exercise) for exercise in day["exercises"]],
            )
            for order, day in enumerate(spec["days"], start=1)
        ],
    ).model_dump()


def prepare_player(store: Any, case: dict[str, Any], program: dict[str, Any], username: str) -> CasePlayer:
    player = _register(store, username)
    published_by = None
    if case.get("authority") == "coach":
        published_by = _assign_coach(store, player, f"{username}-coach")
    with store.open_ledger(player.ledger_id) as ledger:
        ledger.upsert_player_profile({
            "gender": "male", "age": 28, "weight_kg": 80, "height_cm": 178,
            "training_age_years": 3, "weekly_frequency": program["weekly_frequency"],
        })
        ledger.save_training_program(program, published_by_coach_account_id=published_by)
        injury = case.get("injury")
        if injury:
            injuries_service.create_injury(
                store, ledger, player_account_id=player.account_id,
                body_area=injury["area"], description=injury["description"],
            )
    return player


# --- snapshots -------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """What a message may or may not change, with no ids or timestamps."""

    split: str
    frequency: int
    days: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    injuries: tuple[tuple[str, str], ...]
    clearances: tuple[tuple[str, str], ...]
    preferences: tuple[str, ...]
    restrictions: tuple[str, ...]

    @property
    def program(self) -> tuple[Any, ...]:
        return (self.split, self.frequency, self.days)

    @property
    def records(self) -> tuple[Any, ...]:
        return (self.injuries, self.clearances, self.preferences, self.restrictions)


def take_snapshot(ledger: Any) -> Snapshot:
    program = ledger.get_active_program()
    injuries = injuries_service.list_injuries(ledger)
    profile = ledger.get_player_profile() or {}
    return Snapshot(
        split=str(program.split_type),
        frequency=int(program.weekly_frequency),
        days=tuple(
            (str(day.day_name), tuple((str(item.exercise_name), int(item.target_sets)) for item in day.exercises))
            for day in program.days
        ),
        injuries=tuple(sorted((str(row.get("body_area")), str(row.get("status"))) for row in injuries)),
        clearances=tuple(sorted(
            (str(item.get("exercise_name")), str(item.get("verdict")))
            for row in injuries for item in row["clearances"]
        )),
        preferences=tuple(sorted(str(row["text"]) for row in ledger.list_assistant_preferences())),
        restrictions=tuple(sorted(json.dumps(item) for item in profile.get("movement_restrictions") or [])),
    )


# --- is this change the one the message asked for? --------------------------


def _with_days(before: Snapshot, transform: Callable[[str, tuple], tuple]) -> tuple[Any, ...]:
    return (before.split, before.frequency, tuple((name, transform(name, items)) for name, items in before.days))


def _is_swap(before: Snapshot, after: Snapshot, change: dict[str, Any]) -> bool:
    """The exercise is replaced on every day that has it (owner decision, #863)."""
    return any(
        after.program == _with_days(
            before,
            lambda _name, items, target=target: tuple(
                (target if name == change["from"] else name, count) for name, count in items
            ),
        )
        for target in change["to"]
    )


def _is_set_change(before: Snapshot, after: Snapshot, change: dict[str, Any]) -> bool:
    return after.program == _with_days(
        before,
        lambda _name, items: tuple(
            (name, change["sets"] if name == change["exercise"] else count) for name, count in items
        ),
    )


def _is_removal(before: Snapshot, after: Snapshot, change: dict[str, Any]) -> bool:
    """Removed from the named days, or from a subset of them when the wording fits either."""
    if (after.split, after.frequency, len(after.days)) != (before.split, before.frequency, len(before.days)):
        return False
    removed_days = 0
    for (day_name, old), (new_name, new) in zip(before.days, after.days, strict=True):
        if day_name != new_name:
            return False
        if new == old:
            continue
        without = tuple(item for item in old if item[0] != change["exercise"])
        if new != without or (change["days"] and day_name not in change["days"]):
            return False
        removed_days += 1
    return removed_days > 0


def _is_addition(before: Snapshot, after: Snapshot, change: dict[str, Any]) -> bool:
    """Exercises are appended to the named days; nothing already there moves."""
    if (after.split, after.frequency, len(after.days)) != (before.split, before.frequency, len(before.days)):
        return False
    for (day_name, old), (new_name, new) in zip(before.days, after.days, strict=True):
        if day_name != new_name:
            return False
        if new != old and (day_name not in change["days"] or new[: len(old)] != old):
            return False
    return after.days != before.days


def _is_rebuild(after: Snapshot, change: dict[str, Any]) -> bool:
    names = {name.casefold() for key in change["splits"] for name in (key, SPLIT_DISPLAY_NAMES.get(key, key))}
    return after.split.casefold() in names and after.frequency == change["frequency"]


def _is_allowed_program_change(before: Snapshot, after: Snapshot, change: dict[str, Any] | None) -> bool:
    if change is None:
        return False
    checks: dict[str, Callable[[], bool]] = {
        "swap": lambda: _is_swap(before, after, change),
        "sets": lambda: _is_set_change(before, after, change),
        "remove": lambda: _is_removal(before, after, change),
        "add": lambda: _is_addition(before, after, change),
        "rebuild": lambda: _is_rebuild(after, change),
    }
    check = checks.get(change["kind"])
    return check is not None and check()


def _is_allowed_record_change(before: Snapshot, after: Snapshot, change: dict[str, Any] | None) -> bool:
    """Only the named clearance is added; the injury status is not checked against it."""
    if change is None or change["kind"] != "clearance":
        return False
    added = tuple(sorted((*before.clearances, (change["exercise"], change["verdict"]))))
    same_rest = (before.preferences, before.restrictions) == (after.preferences, after.restrictions)
    return after.clearances == added and same_rest and len(before.injuries) == len(after.injuries)


def wrong_changes(before: Snapshot, after: Snapshot, change: dict[str, Any] | None) -> list[str]:
    """Every write that is not the change the case allows."""
    wrong = []
    if after.program != before.program and not _is_allowed_program_change(before, after, change):
        wrong.append("program")
    if after.records != before.records and not _is_allowed_record_change(before, after, change):
        wrong.append("injury or preference records")
    return wrong


# --- turns -----------------------------------------------------------------


@dataclass
class TurnResult:
    message: str
    reply: str
    intent: str
    preview: bool
    coach_request: bool
    snapshot: Snapshot


def run_turn(store: Any, player: CasePlayer, message: str) -> TurnResult:
    """One chat turn with the persistence of ``svc.routers.chat._run_turn``."""
    with store.open_ledger(player.ledger_id) as ledger:
        profile = ledger.get_player_profile() or {}
        history = chat_service.prepare_user_turn(store, message, ledger)
        state = chat_service.build_turn_state(
            player.ledger_id,
            chat_service.build_tail_messages(history),
            coach_tone=profile.get("coach_tone", DEFAULT_ASSISTANT_STYLE),
            custom_instructions=profile.get("custom_instructions", ""),
            player_account_id=player.account_id,
        )
        for _piece in assistant_graph.stream_assistant_turn(state, ledger=ledger, store=store):
            pass
        reply = str(state.get("response_content") or "")
        chat_service.persist_assistant_message(ledger, reply)
        return TurnResult(
            message=message,
            reply=reply,
            intent=str(state.get("intent") or ""),
            # #867: a full rebuild also previews first and waits for yes.
            preview=state.get("program_edit_preview") is not None
            or ledger.get_pending_program_rebuild() is not None,
            coach_request=state.get("request_suggestion") is not None,
            snapshot=take_snapshot(ledger),
        )


# --- scoring ---------------------------------------------------------------


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    scored: bool
    counted: bool
    outcome: str
    expected: list[str]
    wrong_changes: list[str] = field(default_factory=list)
    unconfirmed_rebuild: bool = False
    false_claim: bool = False
    problems: list[str] = field(default_factory=list)
    turns: list[dict[str, str]] = field(default_factory=list)
    attempts: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "scored": self.scored,
            "counted": self.counted,
            "outcome": self.outcome,
            "expected": self.expected,
            "wrong_changes": self.wrong_changes,
            "unconfirmed_rebuild": self.unconfirmed_rebuild,
            "false_claim": self.false_claim,
            "problems": self.problems,
            "turns": self.turns,
            "attempts": self.attempts,
        }


def _names_any(reply: str, options: list[str] | None) -> bool:
    return not options or any(option.casefold() in reply.casefold() for option in options)


def _matching_outcome(case: dict[str, Any], turn: TurnResult, changed: bool) -> str | None:
    """The expected outcome this turn fits, or None."""
    asks = "?" in turn.reply or "؟" in turn.reply
    quiet = not changed and not turn.preview and not turn.coach_request
    names_option = _names_any(turn.reply, case.get("reply_any"))
    fits = {
        "change": changed,
        "confirm": not changed and not turn.coach_request and (turn.preview or (asks and names_option)),
        "ask": quiet and asks and names_option,
        "answer": quiet and bool(turn.reply.strip()) and names_option,
        "refuse": not changed and turn.coach_request,
    }
    return next((outcome for outcome in case["expected"] if fits[outcome]), None)


def _observed_outcome(turn: TurnResult, changed: bool) -> str:
    if changed:
        return "change"
    if turn.coach_request:
        return "refuse"
    if turn.preview:
        return "confirm"
    return "ask" if "?" in turn.reply or "؟" in turn.reply else "answer"


def score_case(case: dict[str, Any], start: Snapshot, turns: list[TurnResult]) -> CaseResult:
    allowed = case.get("allowed_change")
    final = turns[-1]
    before_final = turns[-2].snapshot if len(turns) > 1 else start
    wrong = sorted({label for turn in turns for label in wrong_changes(start, turn.snapshot, allowed)})
    changed = (final.snapshot.program, final.snapshot.records) != (before_final.program, before_final.records)
    matched = _matching_outcome(case, final, changed)
    problems = []
    if matched is None:
        problems.append("outcome is not one of the expected ones")
    if any(turn.snapshot.program != start.program for turn in turns[:-1]):
        problems.append("the program changed before the last message")
    if any(turn.snapshot.records != start.records for turn in turns[:-1]):
        problems.append("records changed before the last message")
    named = [text for text in case.get("reply_none", []) if text.casefold() in final.reply.casefold()]
    if named:
        problems.append(f"reply contains {', '.join(named)}")
    false_claim = not changed and CLAIMED_DONE_RE.search(final.reply) is not None
    if false_claim:
        problems.append("reply claims a change that did not happen")
    return CaseResult(
        case_id=case["id"],
        passed=not wrong and not problems,
        scored=True,
        counted=counts_toward_score(case),
        outcome=matched or _observed_outcome(final, changed),
        expected=case["expected"],
        wrong_changes=wrong,
        unconfirmed_rebuild=_rebuilt_without_confirming(start, turns),
        false_claim=false_claim,
        problems=problems,
    )


def _rebuilt_without_confirming(start: Snapshot, turns: list[TurnResult]) -> bool:
    """A rebuild on the first message cannot have been confirmed (owner decision, #867)."""
    first = turns[0].snapshot
    return (first.split, first.frequency) != (start.split, start.frequency)


def _play(store: Any, case: dict[str, Any], player: CasePlayer) -> tuple[Snapshot, list[TurnResult]]:
    with store.open_ledger(player.ledger_id) as ledger:
        start = take_snapshot(ledger)
    turns: list[TurnResult] = []
    for message in [*case.get("before", []), case["message"]]:
        turns.append(run_turn(store, player, message))
        if turns[-1].reply.strip() in PIPELINE_ERROR_RESPONSES:
            break
    return start, turns


def run_case(store: Any, case: dict[str, Any], program: dict[str, Any], *, max_attempts: int = MAX_CASE_ATTEMPTS) -> CaseResult:
    """Scores one case. A pipeline failure is retried on a fresh Player and is never a pass.

    Wrong changes written by a failed attempt still count.
    """
    written_wrong: set[str] = set()
    for attempt in range(1, max_attempts + 1):
        player = prepare_player(store, case, program, f"{case['id']}-{attempt}")
        start, turns = _play(store, case, player)
        failed = turns[-1].reply.strip() in PIPELINE_ERROR_RESPONSES
        if not failed:
            result = score_case(case, start, turns)
            result.wrong_changes = sorted({*result.wrong_changes, *written_wrong})
            result.passed = result.passed and not result.wrong_changes
        else:
            for turn in turns:
                written_wrong.update(wrong_changes(start, turn.snapshot, case.get("allowed_change")))
            result = CaseResult(
                case_id=case["id"], passed=False, scored=False, counted=counts_toward_score(case),
                outcome="error", expected=case["expected"], wrong_changes=sorted(written_wrong),
                problems=["the turn failed with the pipeline error reply"],
            )
        result.attempts = attempt
        result.turns = [
            {"message": turn.message, "reply": turn.reply, "intent": turn.intent} for turn in turns
        ]
        if not failed:
            return result
    return result


# --- report ----------------------------------------------------------------


def _totals(results: list[CaseResult]) -> dict[str, int]:
    scored = [result for result in results if result.scored]
    return {
        "cases": len(results),
        "scored": len(scored),
        "correct": sum(result.passed for result in scored),
        "wrong_changes_applied": sum(bool(result.wrong_changes) for result in results),
        "unconfirmed_rebuilds": sum(result.unconfirmed_rebuild for result in results),
        "false_claims": sum(result.false_claim for result in results),
    }


def build_report(
    dataset: dict[str, Any], results: list[CaseResult], *, model: str, real_model_run: bool, commit: str
) -> dict[str, Any]:
    counted = [result for result in results if result.counted]
    return {
        "kind": "understanding",
        "real_model_run": real_model_run,
        "player_model": model,
        "commit": commit,
        "dataset_version": dataset.get("version"),
        "partial": len(results) != len(dataset["cases"]),
        "counted": _totals(counted),
        "all_cases": _totals(results),
        "pending_owner_review": sorted(result.case_id for result in results if not result.counted),
        "cases": [result.as_dict() for result in results],
    }
