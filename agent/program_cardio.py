"""Coach-selected cardio notes for generated Training programs."""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
import re
from typing import Any, Literal

from agent.ProgramState import CustomDayPlan, ProgramDaySchema
from agent.program_blueprints import FAT_LOSS_CARDIO_NOTE, is_fat_loss_goal

CardioType = Literal["none", "steady", "intervals", "custom"]


@dataclass(frozen=True)
class CoachCardioOptions:
    days: int
    minutes: int
    cardio_type: CardioType
    custom_note: str | None = None
    display_language: str = "en"


_LEG_SLOT_KEYS = frozenset(
    {
        "quad_compound",
        "quad_lunge",
        "quad_iso",
        "ham_curl",
        "ham_hinge",
        "glute_thrust",
        "glute_iso",
        "adductors",
    }
)
_LEG_DAY_NAME = re.compile(r"\b(?:legs?|lower|posterior|anterior)\b", re.IGNORECASE)


def select_cardio_day_indices(
    split_days: list[CustomDayPlan], cardio_days: int, cardio_type: CardioType
) -> tuple[int, ...]:
    """Choose evenly spaced training days, preferring non-leg days for Intervals."""
    if cardio_days == 0:
        return ()
    day_count = len(split_days)
    targets = [
        int((index + 0.5) * day_count / cardio_days)
        for index in range(cardio_days)
    ]
    leg_days = tuple(is_leg_day(day) for day in split_days)

    def score(indices: tuple[int, ...]) -> tuple[int, int, int, tuple[int, ...]]:
        leg_count = (
            sum(leg_days[index] for index in indices)
            if cardio_type == "intervals"
            else 0
        )
        distance = sum(abs(index - target) for index, target in zip(indices, targets))
        gaps = [right - left for left, right in zip(indices, indices[1:])]
        spread = max(gaps, default=0) - min(gaps, default=0)
        return leg_count, distance, spread, indices

    return min(combinations(range(day_count), cardio_days), key=score)


def build_cardio_note(options: CoachCardioOptions) -> str | None:
    if options.cardio_type == "none":
        return None
    if options.cardio_type == "custom":
        if options.custom_note is None or not options.custom_note.strip():
            raise ValueError("A custom cardio note is required.")
        return options.custom_note
    if options.display_language == "ar":
        if options.cardio_type == "steady":
            return (
                f"تمارين لياقة مستمرة: {options.minutes} دقيقة بوتيرة مريحة تسمح بالمحادثة."
            )
        return (
            f"تمارين متقطعة: {options.minutes} دقيقة؛ 30 ثانية بشدة عالية / 90 ثانية بوتيرة سهلة."
        )
    if options.cardio_type == "steady":
        return f"Steady cardio: {options.minutes} min at an easy, conversational pace."
    return f"Intervals: {options.minutes} min, 30 s hard / 90 s easy."


def apply_coach_cardio(
    program_days: list[ProgramDaySchema],
    split_days: list[CustomDayPlan],
    options: CoachCardioOptions,
) -> None:
    note = build_cardio_note(options)
    selected = set(
        select_cardio_day_indices(split_days, options.days, options.cardio_type)
    )
    for index, day in enumerate(program_days):
        day.cardio = note if index in selected else None


def apply_program_cardio(
    program_days: list[ProgramDaySchema],
    split_days: list[CustomDayPlan],
    profile: Mapping[str, Any],
    options: CoachCardioOptions | None,
) -> None:
    if is_fat_loss_goal(profile.get("current_goal"), profile.get("long_term_goal")):
        for day in program_days:
            day.cardio = FAT_LOSS_CARDIO_NOTE
    if options is not None:
        apply_coach_cardio(program_days, split_days, options)


def is_leg_day(day: CustomDayPlan) -> bool:
    if _LEG_SLOT_KEYS.intersection(day.target_slots):
        return True
    return bool(_LEG_DAY_NAME.search(day.day_name))
