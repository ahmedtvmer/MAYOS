"""Coach-facing deload and performance-regression alerts (ADR 032, ticket #33).

Existing progression signals are turned into coach-facing alert events at
session commit, without inventing new progression maths:

* ``deload_recommended`` — the systemic fatigue verdict
  (``agent.progression_engine.evaluate_systemic_fatigue``) was true after the
  commit. Subject ``''``.
* ``performance_regression`` — an exercise's existing summary carried
  ``action == 'deload'`` (the OVERSHOOT rule), a projection status of
  ``RPE_OVERSHOOT_DELOAD`` (a top set at RPE 10 even when the load rose), or an
  e1RM fall of at least ``REGRESSION_E1RM_DROP`` of the previous e1RM. Subject is
  the exercise id. Baseline exercises (no previous performance) never fire.

A signal is an *episode*: it opens on the first committing session where it
fires and stays open while later commits keep firing it; it closes on the first
later commit where it does not. For the per-exercise kind, a commit that does not
include the exercise leaves that exercise's episode unchanged.

Episode state is tracked catalog-side in ``alert_signal_state``; the open alert
uses ``dedupe_key = '<subject>:<episode_key>'`` (or just ``episode_key`` when the
subject is empty). The whole evaluation of one commit runs in a single catalog
transaction, and a ``progression_alert_sessions`` marker makes re-processing any
session — even an older one — a no-op.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.deload_choices import DELOAD_CHOICES
from service.coach_notices import notify_coach, player_display_name

logger = logging.getLogger(__name__)

DELOAD_KIND = "deload_recommended"
REGRESSION_KIND = "performance_regression"

#: A per-exercise regression fires when the e1RM drop is at least this fraction
#: of the previous e1RM.
REGRESSION_E1RM_DROP = 0.05

__all__ = [
    "CommitSignal",
    "DELOAD_KIND",
    "REGRESSION_E1RM_DROP",
    "REGRESSION_KIND",
    "evaluate_commit",
    "signals_from_commit",
]


@dataclass(frozen=True)
class CommitSignal:
    """One progression signal that fired for a commit, with its evidence."""

    kind: str
    subject: str
    details: dict[str, Any] = field(default_factory=dict)


def _deload_details(fatigue_post: dict[str, Any], session_id: str, session_date: str) -> dict[str, Any]:
    return {
        "severity": fatigue_post.get("severity"),
        "reason": fatigue_post.get("reason"),
        "recent_readiness_avg": fatigue_post.get("recent_readiness_avg"),
        "volume_multiplier": fatigue_post.get("volume_multiplier"),
        "intensity_cap_rpe": fatigue_post.get("intensity_cap_rpe"),
        "session_id": session_id,
        "session_date": session_date,
    }


def _regression_details(summary: dict[str, Any], session_id: str, session_date: str) -> dict[str, Any]:
    return {
        "exercise_id": str(summary.get("exercise_id")),
        "exercise_name": summary.get("name"),
        "status_badge": summary.get("status_badge"),
        "e1rm_delta": summary.get("e1rm_delta"),
        "current_e1rm": summary.get("current_e1rm"),
        "top_load": summary.get("top_load"),
        "top_reps": summary.get("top_reps"),
        "top_rpe": summary.get("top_rpe"),
        "session_id": session_id,
        "session_date": session_date,
    }


def _is_regression(summary: dict[str, Any]) -> bool:
    """The pre-existing OVERSHOOT/RPE_OVERSHOOT_DELOAD rules, or a >= 5% e1RM drop.

    Exercises without previous performance (``e1rm_delta`` is ``None``) are
    baseline and never trigger, even if their first top set was logged at RPE 10.
    """
    if summary.get("e1rm_delta") is None:
        return False
    if summary.get("action") == "deload":
        return True
    if summary.get("projection_status") == "RPE_OVERSHOOT_DELOAD":
        return True
    delta = summary.get("e1rm_delta")
    if delta is None or delta >= 0:
        return False
    current = summary.get("current_e1rm")
    if current is None:
        return False
    previous = float(current) - float(delta)
    if previous <= 0:
        return False
    return (abs(float(delta)) / previous) >= REGRESSION_E1RM_DROP


def signals_from_commit(
    exercise_summaries: list[dict[str, Any]],
    fatigue_post: dict[str, Any] | None,
    *,
    session_id: str,
    session_date: str,
) -> list[CommitSignal]:
    """The signals that fired for this commit, in a stable order.

    Pure and DB-free: it reads only the per-exercise summaries and the systemic
    fatigue verdict the commit already computed.
    """
    signals: list[CommitSignal] = []
    if fatigue_post and fatigue_post.get("deload_recommended"):
        signals.append(
            CommitSignal(
                kind=DELOAD_KIND,
                subject="",
                details=_deload_details(fatigue_post, session_id, session_date),
            )
        )
    for summary in exercise_summaries:
        exercise_id = summary.get("exercise_id")
        if not exercise_id or not _is_regression(summary):
            continue
        signals.append(
            CommitSignal(
                kind=REGRESSION_KIND,
                subject=str(exercise_id),
                details=_regression_details(summary, session_id, session_date),
            )
        )
    return signals


def note_player_deload_choice(db: Any, player_account_id: str, choice: str) -> bool:
    """Adds the player's one-workout Deload choice to its open Coach alert episode."""
    if choice not in DELOAD_CHOICES:
        return False
    assignment = db.get_active_assignment_for_player(player_account_id)
    if assignment is None:
        return False

    assignment_id = str(assignment["assignment_id"])
    with db.catalog_transaction():
        episode = db.get_alert_signal_state(assignment_id, DELOAD_KIND, "")
        if episode is None or not int(episode["active"]):
            return False
        dedupe_key = str(episode["episode_key"])
        alert = db.get_coach_alert_by_dedupe(assignment_id, DELOAD_KIND, dedupe_key)
        if alert is None:
            return False
        details = dict(alert.get("details") or {})
        details["player_deload_choice"] = {"choice": choice, "scope": "next_workout_only"}
        return bool(db.update_coach_alert_details(alert["alert_id"], details))


def _dedupe_key(subject: str, episode_key: str) -> str:
    return f"{subject}:{episode_key}" if subject else episode_key


def _noop_result() -> dict[str, Any]:
    return {"evaluated": False, "alerts_created": 0, "alerts_resolved": 0, "signals": 0}


def _open_alert(
    db: Any,
    assignment: dict[str, Any],
    signal: CommitSignal,
    session_id: str,
    now_iso: str,
) -> dict[str, Any]:
    """Insert-or-ignore the alert that opens an episode."""
    return db.insert_coach_alert(
        uuid.uuid4().hex,
        assignment["assignment_id"],
        assignment["coach_account_id"],
        assignment["player_account_id"],
        signal.kind,
        _dedupe_key(signal.subject, session_id),
        signal.details,
        now_iso,
    )


def _open_or_extend(
    db: Any,
    assignment: dict[str, Any],
    signal: CommitSignal,
    session_id: str,
    session_date: str,
    now_iso: str,
) -> bool:
    """Opens a new episode or extends the active one; returns whether an alert was created."""
    assignment_id = assignment["assignment_id"]
    state = db.get_alert_signal_state(assignment_id, signal.kind, signal.subject)

    if state is None or not int(state["active"]):
        inserted = _open_alert(db, assignment, signal, session_id, now_iso)
        db.upsert_alert_signal_state(assignment_id, signal.kind, signal.subject, 1, session_id, now_iso)
        return bool(inserted["created"])

    episode_key = str(state["episode_key"])
    alert = db.get_coach_alert_by_dedupe(
        assignment_id, signal.kind, _dedupe_key(signal.subject, episode_key)
    )
    if alert is not None:
        latest = {
            key: value
            for key, value in signal.details.items()
            if key not in ("session_id", "session_date")
        }
        details = {
            **alert.get("details", {}),
            **latest,
            "latest_session_id": session_id,
            "latest_session_date": session_date,
        }
        db.update_coach_alert_details(alert["alert_id"], details)
    db.upsert_alert_signal_state(assignment_id, signal.kind, signal.subject, 1, episode_key, now_iso)
    return False


def _close_episode(db: Any, assignment_id: str, kind: str, subject: str, now_iso: str) -> int:
    state = db.get_alert_signal_state(assignment_id, kind, subject)
    if state is None or not int(state["active"]):
        return 0
    episode_key = str(state["episode_key"])
    resolved = db.resolve_open_coach_alerts_for_dedupe(
        assignment_id, kind, _dedupe_key(subject, episode_key), now_iso
    )
    db.upsert_alert_signal_state(assignment_id, kind, subject, 0, episode_key, now_iso)
    return resolved


def _notify(db: Any, assignment: dict[str, Any], signal: CommitSignal, now_iso: str) -> None:
    """Best-effort coach in-app notice; names the signal and the exercise only."""
    if signal.kind == DELOAD_KIND:
        message = f"{player_display_name(db, assignment)} has a deload recommended. Review the alert in your roster."
    else:
        exercise = signal.details.get("exercise_name") or "an exercise"
        message = (
            f"{player_display_name(db, assignment)} regressed on {exercise}."
            " Review the alert in your roster."
        )
    notify_coach(db, assignment, signal.kind, message, now_iso)


def evaluate_commit(
    db: Any,
    account_id: str,
    session_id: str,
    session_date: str,
    exercise_summaries: list[dict[str, Any]],
    fatigue_post: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The single transition point for the deload/regression alert kinds.

    Catalog-only and atomic: the whole evaluation for one commit runs in a single
    catalog transaction, and the ``(assignment, session)`` marker written in that
    transaction makes re-processing any session — including an older one after
    later sessions — a no-op. Coach notices are sent only after the commit.
    """
    now = now or datetime.now(UTC)
    now_iso = now.isoformat()
    if not account_id:
        return _noop_result()

    assignment = db.get_active_assignment_for_player(account_id)
    if assignment is None:
        return _noop_result()

    assignment_id = assignment["assignment_id"]
    notices: list[CommitSignal] = []
    result = _noop_result()
    with db.catalog_transaction():
        if db.is_progression_session_processed(assignment_id, session_id):
            return _noop_result()

        signals = signals_from_commit(
            exercise_summaries, fatigue_post, session_id=session_id, session_date=session_date
        )
        fired = {(signal.kind, signal.subject) for signal in signals}
        created = 0
        for signal in signals:
            if _open_or_extend(db, assignment, signal, session_id, session_date, now_iso):
                created += 1
                notices.append(signal)

        resolved = 0
        if (DELOAD_KIND, "") not in fired:
            resolved += _close_episode(db, assignment_id, DELOAD_KIND, "", now_iso)
        for summary in exercise_summaries:
            exercise_id = summary.get("exercise_id")
            if not exercise_id:
                continue
            subject = str(exercise_id)
            if (REGRESSION_KIND, subject) not in fired:
                resolved += _close_episode(db, assignment_id, REGRESSION_KIND, subject, now_iso)

        db.mark_progression_session_processed(assignment_id, session_id, now_iso)
        result = {
            "evaluated": True,
            "alerts_created": created,
            "alerts_resolved": resolved,
            "signals": len(signals),
        }

    for signal in notices:
        _notify(db, assignment, signal, now_iso)
    return result
