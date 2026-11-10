"""One-time rebuild copy drawn from the recorded Focus day decision."""

from collections.abc import Callable
from typing import Any

from agent.program_rationale import FOCUS_MUSCLE_LABELS, focus_extra_tag


def cross_day_focus_explanation(ledger: Any, program: Any) -> dict[str, str] | None:
    return _claimed_focus_explanation(ledger, program, _cross_day_copy)


def cross_day_focus_chat_explanation(ledger: Any, program: Any) -> dict[str, str] | None:
    return _claimed_focus_explanation(ledger, program, _cross_day_chat_copy)


def _claimed_focus_explanation(
    ledger: Any, program: Any, copy_builder: Callable[[Any, dict], dict[str, str]],
) -> dict[str, str] | None:
    if program is None:
        return None
    explanations = _cross_day_explanations(program, copy_builder)
    if not explanations or not ledger.claim_focus_cross_day_explanation():
        return None
    return {language: " ".join(copy[language] for copy in explanations.values())
            for language in ("en", "ar")}


def _cross_day_explanations(
    program: Any, copy_builder: Callable[[Any, dict], dict[str, str]],
) -> dict[str, dict[str, str]]:
    active = {(day.week_order, day.day_order, ex.exercise_id): ex
              for day in program.days for ex in day.exercises}
    explanations = {}
    for day in (program.program_rationale or {}).get("days", []):
        for entry in day.get("exercises", []):
            rationale = entry.get("rationale", {})
            tag = focus_extra_tag(rationale)
            exercise = active.get((day.get("week_order", 1), day["day_order"], entry["exercise_id"]))
            if tag and tag["cross_day"] and exercise is not None:
                explanations.setdefault(tag["muscle"], copy_builder(exercise, rationale))
    return explanations


def _cross_day_copy(exercise: Any, rationale: dict) -> dict[str, str]:
    params = rationale["day_choice"]["params"]
    english, arabic = FOCUS_MUSCLE_LABELS[params["muscle"]]
    count = params.get("weekly_exposures", params["exposures_after"])
    day = params["day_name"]
    return {"en": f"{english} now trains {count}× a week, including {exercise.exercise_name} on {day}, "
            "to give your weak point more frequency.",
            "ar": f"تتدرب عضلة {arabic} الآن {count} مرات في الأسبوع، بما في ذلك {exercise.exercise_name} "
            f"في {day}، لزيادة تكرار تدريب نقطة ضعفك."}


def _cross_day_chat_copy(exercise: Any, rationale: dict) -> dict[str, str]:
    copy = _cross_day_copy(exercise, rationale)
    params = rationale["day_choice"]["params"]
    _, arabic = FOCUS_MUSCLE_LABELS[params["muscle"]]
    count = params.get("weekly_exposures", params["exposures_after"])
    day = params["day_name"]
    copy["ar"] = (f"عضلة {arabic} دلوقتي بتتمرن {count} مرات في الأسبوع، ومنها {exercise.exercise_name} "
                  f"في {day}، علشان نزود مرات تدريب نقطة ضعفك.")
    return copy
