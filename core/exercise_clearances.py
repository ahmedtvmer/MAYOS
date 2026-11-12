"""Deterministic recommendation eligibility; never a workout logging gate."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from core.injuries import injury_body_parts


def _latest_verdicts_by_injury(
    clearances: Iterable[Mapping[str, Any]], exercise_id: Any
) -> dict[str, Mapping[str, Any]]:
    if exercise_id is None:
        return {}
    latest: dict[str, Mapping[str, Any]] = {}
    ordered = sorted(
        clearances,
        key=lambda row: (str(row.get("recorded_at") or ""), str(row.get("id") or "")),
        reverse=True,
    )
    for record in ordered:
        matched = (
            record.get("exercise_id") is not None
            and str(record["exercise_id"]) == str(exercise_id)
        )
        if matched:
            latest.setdefault(str(record["injury_id"]), record)
    return latest


def _injury_assessment(
    injury: Mapping[str, Any],
    verdict: Mapping[str, Any] | None,
    body_part: str,
) -> tuple[str | None, str | None, bool]:
    if injury.get("status") == "resolved":
        return None, None, False
    if verdict is None:
        excluded = (
            "unverified"
            if body_part in injury_body_parts(injury.get("body_area")) else None
        )
        return excluded, None, False
    if verdict["verdict"] == "not_cleared":
        return "not_cleared", None, False
    if verdict["verdict"] == "cleared_with_limits":
        note = str(verdict["note"]) if verdict.get("note") else None
        return None, note, True
    return None, None, False


def _clearance_status(exclusions: list[str], has_limits: bool) -> str:
    if "not_cleared" in exclusions:
        return "not_cleared"
    if exclusions:
        return "unverified"
    return "cleared_with_limits" if has_limits else "allowed"


def _assess_injuries(
    injuries: Iterable[Mapping[str, Any]],
    latest: Mapping[str, Mapping[str, Any]],
    body_part: str,
) -> tuple[list[str], list[str], bool]:
    exclusions = []
    notes = []
    has_limits = False
    for injury in injuries:
        exclusion, note, limited = _injury_assessment(
            injury, latest.get(str(injury["id"])), body_part
        )
        if exclusion:
            exclusions.append(exclusion)
        if note:
            notes.append(note)
        has_limits = has_limits or limited
    return exclusions, notes, has_limits


def exercise_clearance(
    clearances: Iterable[Mapping[str, Any]],
    injuries: Iterable[Mapping[str, Any]],
    exercise: Mapping[str, Any],
) -> dict[str, Any]:
    """Assess an exercise against each active injury and its latest verdict."""
    exercise_id = exercise.get("id") or exercise.get("exercise_id")
    latest = _latest_verdicts_by_injury(clearances, exercise_id)
    body_part = str(exercise.get("body_part") or "").strip().casefold()
    exclusions, notes, has_limits = _assess_injuries(injuries, latest, body_part)
    return {
        "status": _clearance_status(exclusions, has_limits),
        "excluded": bool(exclusions),
        "limit_notes": list(dict.fromkeys(notes)),
    }
