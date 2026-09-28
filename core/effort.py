"""Effort at the display boundary (#111).

RIR = 10 − RPE. Storage and the progression engine keep RPE; players and
coaches only ever read RIR. This module is the backend's **single** conversion
plus its two display formatters, so no surface can disagree about a value or
its wording:

* :func:`rir_from_rpe` / :func:`rir_label` — a **recorded** effort on a set:
  ``2``, ``5+``, or ``not rated``.
* :func:`min_rir_from_rpe` / :func:`min_rir_label` — a program **target** or
  deload **cap**, stated as the equivalent *minimum* RIR (a maximum RPE is a
  floor on RIR), rounded up to a whole number: ``≥ 2``.

An unrated set reads ``not rated`` on every surface — CONTEXT.md: "a blank
value means the player did not rate the set".
"""

from __future__ import annotations

import math
from typing import Any

#: The one wording for a set nobody rated, on every app and backend surface.
UNRATED = "not rated"


def rir_from_rpe(rpe: Any) -> float | None:
    """RIR for a stored RPE (``10 - RPE``), ``None`` when the set is unrated."""
    if rpe is None:
        return None
    try:
        return round(10.0 - float(rpe), 2)
    except (TypeError, ValueError):
        return None


def min_rir_from_rpe(rpe: Any) -> int | None:
    """The equivalent minimum RIR for a target or cap: ``ceil(10 - RPE)``.

    A cap is the *most* effort allowed, so it reads as the *least* RIR the set
    may leave — rounded up so it is never understated (#111).
    """
    rir = rir_from_rpe(rpe)
    if rir is None:
        return None
    # Round first so a stored 9.0 never ceilings 0.999…9 to 1 extra.
    return int(math.ceil(round(rir, 6)))


def rir_label(rpe: Any) -> str:
    """A recorded effort for players and coaches: ``2``, ``5+``, ``not rated``.

    At most one decimal (legacy RPEs were stored as 8.3, whose raw difference
    is 1.6999999999999993), with the trailing ``.0`` dropped, and RIR 5 — the
    top of the scale — shown as ``5+`` everywhere, not only on the keypad chip.
    """
    rir = rir_from_rpe(rpe)
    if rir is None:
        return UNRATED
    shown = round(rir, 1)
    if shown >= 5.0:
        return "5+"
    return f"{shown:g}"


def min_rir_label(rpe: Any) -> str:
    """A target or cap as its equivalent minimum RIR: ``≥ 2``, or ``not rated``."""
    minimum = min_rir_from_rpe(rpe)
    if minimum is None:
        return UNRATED
    return f"≥ {minimum}"
