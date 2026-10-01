"""The roster urgency order (CONTEXT.md "Roster urgency order", ticket #118).

A strict total order over roster rows where each key only breaks ties in the one
before it, with no weights and no model scores. ``roster_urgency_key`` is the
single pure definition: it reads only the row it is given plus the caller's
``today``, so tests inject the date and the Coach Pro prioritisation (#71) can
reuse the same key later.

Keys, in order:

1. ``alerts_new_lapsing``, highest first (only new missed-day and follow-up-due
   alerts count).
2. Other new alerts plus ``pending_requests``, highest first (acknowledged
   alerts are not an input, so they never count).
3. ``current_missed_streak``, longest first.
4. Follow-up: overdue first (earliest ``next_follow_up_on`` first), then due
   today, then everything else (no follow-up due yet, or none scheduled).
5. ``last_workout_on``, oldest first; a player who never trained ranks before
   any date.
6. ``player_username``, ascending.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

__all__ = ["roster_urgency_key"]


def _follow_up_key(next_follow_up_on: Any, today: date) -> tuple[int, str]:
    """The follow-up bucket: overdue (earliest first), due today, then not due."""
    if not next_follow_up_on:
        return 2, ""
    due_on = date.fromisoformat(str(next_follow_up_on))
    if due_on < today:
        return 0, due_on.isoformat()
    if due_on == today:
        return 1, ""
    return 2, ""


def roster_urgency_key(entry: Mapping[str, Any], today: date) -> tuple[int, int, int, int, str, str, str]:
    """The urgency-order sort key for one roster row (pure; no clock, no I/O).

    Sort roster rows with ``sorted(rows, key=lambda row: roster_urgency_key(row, today))``.
    ``today`` is the roster-wide comparison date for follow-up due-ness; the
    caller sources it from the clock. Malformed ``next_follow_up_on`` values
    raise ``ValueError`` rather than silently reordering the roster.
    """
    return (
        -int(entry.get("alerts_new_lapsing") or 0),
        -(
            max(0, int(entry.get("alerts_new") or 0) - int(entry.get("alerts_new_lapsing") or 0))
            + int(entry.get("pending_requests") or 0)
        ),
        -int(entry.get("current_missed_streak") or 0),
        *_follow_up_key(entry.get("next_follow_up_on"), today),
        str(entry.get("last_workout_on") or ""),
        str(entry.get("player_username") or ""),
    )
