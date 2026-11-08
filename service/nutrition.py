"""Player Nutrition setup, deterministic target selection, and version storage."""

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from agent.program_blueprints import classify_goal
from core.nutrition_targets import (ACTIVITY_FACTORS, NutritionCalculationInput, NutritionTargets,
                                    calculate_fiber_water_targets, calculate_targets)
from core.cardio_calories import estimate_cardio_calories
from core.cardio_prescriptions import parse_legacy_cardio_prescription
from database.ledger.nutrition import NutritionPlanVersion, NutritionSetup
from database.ledger.nutrition_meals import meals_still_allowed
from service import nutrition_pace_check
from service.nutrition_assistant_meals import meal_context


SCREENING_KEYS = (
    "pregnant_or_breastfeeding",
    "medical_condition",
    "eating_disorder",
)


@dataclass(frozen=True)
class PaceProposalDecision:
    proposal_id: int
    decision: str
    actor_role: str
    assignment_id: str | None
    today: date
MESSAGES = {
    "incomplete": ("Complete your Training profile before setting Nutrition targets.",
                   "أكمل الملف التدريبي قبل إعداد الأهداف الغذائية."),
    "under_18": ("MAYOS does not set automatic Nutrition targets for players under 18.",
                 "لا يحدد ميوس أهدافًا غذائية تلقائية لمن هم دون 18 عامًا."),
    "blocked": ("MAYOS will not set calorie targets. Please speak with a registered dietitian.",
                "لن يحدد ميوس أهداف السعرات. يُرجى التحدث إلى اختصاصي تغذية مسجل."),
}


def _message(state: str, language: str) -> str:
    return MESSAGES[state][1 if language == "ar" else 0]


def resolve_goal(current_goal: str | None, long_term_goal: str | None,
                 weight_kg: float, target_weight_kg: float | None) -> tuple[str, dict[str, Any]]:
    classified = classify_goal(current_goal, long_term_goal)
    target_goal = None
    if target_weight_kg is not None:
        difference = target_weight_kg - weight_kg
        target_goal = "lose" if difference < -1 else "gain" if difference > 1 else "maintain"
    if target_goal is not None and (classified is None or target_goal != classified):
        return target_goal, {"code": "target_weight", "target_weight_kg": target_weight_kg}
    if classified is not None:
        goal_text = current_goal if classify_goal(current_goal) else long_term_goal
        return classified, {"code": "current_goal", "goal_text": goal_text}
    return "maintain", {"code": "default"}


def _target_json(targets: NutritionTargets) -> dict[str, Any]:
    return {
        "calories": targets.calories, "protein_g": targets.protein_g,
        "carbs_g": targets.carbs_g, "fat_g": targets.fat_g,
        "bmr": targets.bmr, "maintenance": targets.maintenance,
        "calorie_floor": targets.calorie_floor, "floor_applied": targets.floor_applied,
        "weekly_rate_pct": targets.weekly_rate_pct,
    }


def _fill_fiber_water_defaults(state: dict[str, Any], weight_kg: float) -> None:
    options = state.get("target_options") or {"daily": state.get("targets") or {}}
    selected = state.get("targets")
    target_options = [(day, target) for day, target in options.items()
                      if isinstance(target, dict)]
    if isinstance(selected, dict) and all(target is not selected for _, target in target_options):
        target_options.append((state.get("target_day_type", "daily"), selected))
    for day_type, target in target_options:
        _fill_target_fiber_water(target, day_type, weight_kg, state)


def _fill_target_fiber_water(target: dict[str, Any], day_type: str, weight_kg: float,
                             state: dict[str, Any]) -> None:
    had_fiber = "fiber_g" in target
    had_water = "water_ml" in target
    defaults = calculate_fiber_water_targets(int(target.get("calories", 0)), weight_kg,
                                              day_type == "training_day")
    target.setdefault("fiber_g", defaults["fiber_g"])
    target.setdefault("water_ml", defaults["water_ml"])
    target.setdefault("fiber_g_source", "coach" if had_fiber and state.get("author") == "Coach" else "default")
    target.setdefault("water_ml_source", "coach" if had_water and state.get("author") == "Coach" else "default")
    if "training_day_water_ml" not in target:
        training_default = calculate_fiber_water_targets(
            int(target.get("calories", 0)), weight_kg, True)["water_ml"]
        target["training_day_water_ml"] = (
            training_default if target["water_ml_source"] == "default" else target["water_ml"])
        target["training_day_water_ml_source"] = target["water_ml_source"]
    if (day_type == "daily" and state.get("target_day_type") == "training_day"
            and target["water_ml_source"] == "default"):
        target["water_ml"] = target["training_day_water_ml"]


def _goal_source(profile: dict[str, Any]) -> dict[str, Any]:
    return {"current_goal": profile.get("current_goal"),
            "long_term_goal": profile.get("long_term_goal"),
            "target_weight_kg": profile.get("target_weight_kg")}


def _offer_key(profile: dict[str, Any]) -> str:
    return json.dumps(_goal_source(profile), sort_keys=True, separators=(",", ":"))

def coach_read(ledger: Any, today: date, assignment_id: str, days: int = 14) -> dict[str, Any]:
    state = read(ledger, today=today)
    state.update(_coach_water_log(ledger, today, days))
    # Food log data is not available yet; this is the read seam for Spec B1.
    state["fiber_eaten_days"] = None
    state["adherence_days"] = _coach_adherence_days(ledger, today, days)
    state["weight_trend"] = _coach_weight_trend(ledger, today, days)
    state["authority"] = (
        "coach" if state.get("author") == "Coach"
        and state.get("authority_assignment_id") == assignment_id else "player"
    )
    state.pop("authority_assignment_id", None)
    state.pop("screening", None)
    profile = ledger.get_nutrition_profile()
    if profile and _profile_is_complete(profile):
        state["calorie_floor"] = _player_calorie_floor(ledger, profile, state)
        if state.get("state") == "ready":
            state["planned_weekly_rate_pct"] = _coach_planned_rate(ledger, profile, state)
    state["next_pace_check"] = "after_21_days_of_weigh_ins"
    return state


def coach_food_log_day(ledger: Any, entry_date: date, today: date) -> dict[str, Any]:
    from service.food_log import read_day

    day = read_day(ledger, entry_date, today)
    adherence = ledger.list_nutrition_adherence(entry_date.isoformat(), entry_date.isoformat())
    return {
        "date": day["date"], "today": day["today"],
        "entries": day["entries"], "totals": day["totals"], "targets": day["targets"],
        "adherence": ({"value": adherence[0]["value"], "source": adherence[0]["source"]}
                      if adherence else None),
    }


def _coach_water_log(ledger: Any, today: date, days: int) -> dict[str, Any]:
    water_days = ledger.get_water_log_days(today - timedelta(days=days - 1), today)
    return {
        "today_water_glasses": ledger.get_water_glasses(today),
        "water_days": [
            {"date": (today - timedelta(days=offset)).isoformat(),
             "glasses": water_days.get((today - timedelta(days=offset)).isoformat(), 0)}
            for offset in range(days - 1, -1, -1)
        ],
    }


def change_water(ledger: Any, today: date, change: int) -> tuple[int, str]:
    return ledger.change_water_glasses(today, change)


def _coach_planned_rate(ledger: Any, profile: dict[str, Any], state: dict[str, Any]) -> float:
    targets = state.get("targets") or {}
    if state.get("author") != "Coach":
        rate = float(targets.get("weekly_rate_pct", 0))
        direction = -1 if state.get("goal") == "lose" else 1 if state.get("goal") == "gain" else 0
        return direction * rate
    baseline = _coach_target_baseline(
        ledger, profile, state.get("goal", "maintain"),
        state.get("daily_activity") or "mostly_sitting",
    )
    options = state.get("target_options") or {"daily": targets}
    training = options.get("training_day") or options.get("daily") or targets
    rest = options.get("rest_day") or options.get("daily") or targets
    training_days = ledger.get_nutrition_training_days(profile.get("weekly_frequency") or 0)
    average_calories = (
        float(training["calories"]) * training_days
        + float(rest["calories"]) * (7 - training_days)
    ) / 7
    weight = float(profile["weight_kg"])
    return (average_calories - baseline.maintenance) * 7 / (weight * 7700) * 100


def _coach_adherence_days(ledger: Any, today: date, days: int) -> list[dict[str, Any]]:
    start = today - timedelta(days=days - 1)
    entries = {entry["date"]: entry for entry in ledger.list_nutrition_adherence(
        start.isoformat(), today.isoformat())}
    return [
        {"date": (start + timedelta(days=offset)).isoformat(),
         "value": entries.get((start + timedelta(days=offset)).isoformat(), {}).get("value"),
         "source": entries.get((start + timedelta(days=offset)).isoformat(), {}).get("source")}
        for offset in range(days)
    ]


def _coach_weight_trend(ledger: Any, today: date, days: int) -> list[dict[str, Any]]:
    start = today - timedelta(days=days - 1)
    return [{"date": row["entry_date"], "weight_kg": row["weight_kg"]}
            for row in ledger.list_weight_history(start.isoformat(), today.isoformat())]


def _player_calorie_floor(ledger: Any, profile: dict[str, Any], state: dict[str, Any]) -> int:
    baseline = _coach_target_baseline(
        ledger, profile, state.get("goal", "maintain"),
        state.get("daily_activity") or "mostly_sitting",
    )
    return int(baseline.calorie_floor)


def save_coach_targets(
    ledger: Any, body: dict[str, Any], assignment_id: str, today: date | None = None
) -> dict[str, Any]:
    profile = _coach_profile(ledger, body["goal"])
    goal = body["goal"]
    activity = body.get("daily_activity") or profile.get("daily_activity") or "mostly_sitting"
    _require_coach_authority_confirmation(ledger, body, assignment_id)
    targets_by_day = _targets_by_day(body)
    baseline = _coach_target_baseline(ledger, profile, goal, activity)
    targets_by_day = _validate_coach_targets(targets_by_day, profile, baseline)
    selected = targets_by_day.get("targets") or targets_by_day.get("training_day_targets")
    with ledger.ledger_transaction():
        ledger.save_nutrition_plan(NutritionPlanVersion(
            goal=goal, reason={"code": "coach"}, intensity=None, daily_activity=activity,
            targets={"daily": selected, "training_day": targets_by_day.get("training_day_targets"),
                     "rest_day": targets_by_day.get("rest_day_targets")}, author="Coach", provenance="coach",
            authority_assignment_id=assignment_id,
            goal_source_snapshot=_goal_source(profile),
        ))
    return coach_read(ledger, today or date.today(), assignment_id)


def _coach_profile(ledger: Any, goal: str) -> dict[str, Any]:
    profile = ledger.get_nutrition_profile()
    if profile is None or not _profile_is_complete(profile):
        raise ValueError("Complete the Player's Training profile before setting Nutrition targets.")
    screening = ledger.get_nutrition_screening()
    if screening and any(json.loads(screening[0]).values()):
        raise ValueError(_message("blocked", "en"))
    if int(profile["age"]) < 18 and goal == "lose":
        raise ValueError("Players under 18 may only have Maintain or Gain targets.")
    return profile


def _require_coach_authority_confirmation(ledger: Any, body: dict[str, Any], assignment_id: str) -> None:
    plan = ledger.get_active_nutrition_plan()
    holds_authority = (
        plan is not None and plan["author"] == "Coach"
        and plan["authority_assignment_id"] == assignment_id
    )
    if not holds_authority and not body.get("confirm_takeover"):
        raise ValueError("Confirm that you are taking over Nutrition authority.")


def _targets_by_day(body: dict[str, Any]) -> dict[str, Any]:
    targets = {key: body[key] for key in ("targets", "training_day_targets", "rest_day_targets")
               if body.get(key)}
    if not targets:
        raise ValueError("Set Nutrition targets.")
    return targets


def _coach_target_baseline(ledger: Any, profile: dict[str, Any], goal: str,
                           activity: str) -> NutritionTargets:
    age = int(profile["age"])
    training_days = ledger.get_nutrition_training_days(profile.get("weekly_frequency") or 0)
    inputs = NutritionCalculationInput(
        sex=profile.get("gender", "male"), age=age,
        height_cm=float(profile["height_cm"]), weight_kg=float(profile["weight_kg"]),
        daily_activity=activity, training_days=training_days, goal=goal, intensity="moderate",
    )
    if age >= 18:
        return calculate_targets(inputs)
    # Coach validation needs a floor for permitted Maintain/Gain plans; minors get no generated plan.
    bmr = 10 * inputs.weight_kg + 6.25 * inputs.height_cm - 5 * age + (5 if inputs.sex == "male" else -161)
    maintenance = bmr * (ACTIVITY_FACTORS[activity] + 0.0625 * training_days)
    floor = max(bmr, 1200 if inputs.sex == "female" else 1500)
    return NutritionTargets(0, 0, 0, 0, round(bmr, 1), round(maintenance, 1), floor, False, 0)


def _validate_coach_targets(targets_by_day: dict[str, Any], profile: dict[str, Any],
                            baseline: NutritionTargets) -> dict[str, dict[str, int]]:
    return {
        day_type: _validate_coach_target(day_type, target, profile, baseline)
        for day_type, target in targets_by_day.items()
    }


def _validate_coach_target(day_type: str, target: Any, profile: dict[str, Any],
                           baseline: NutritionTargets) -> dict[str, int]:
    if not isinstance(target, dict):
        raise ValueError(f"Targets for {day_type} must include calories and Macros.")
    calories = _coach_target_amount(target, "calories", day_type, minimum=1)
    macros = [_coach_target_amount(target, field, day_type, minimum=0)
              for field in ("protein_g", "carbs_g", "fat_g")]
    if calories < baseline.calorie_floor:
        raise ValueError(f"Calories must meet the Calorie floor of {int(baseline.calorie_floor)} kcal for {day_type}.")
    macro_calories = 4 * macros[0] + 4 * macros[1] + 9 * macros[2]
    if abs(macro_calories - calories) / calories > .05:
        raise ValueError(f"Macros must be within 5% of the {calories} kcal target for {day_type}.")
    calorie_change = calories - baseline.maintenance
    weekly_rate = abs(calorie_change) * 7 / (float(profile["weight_kg"]) * 7700) * 100
    cap = .5 if calorie_change > 0 else 1.0 if calorie_change < 0 else 0
    if weekly_rate > cap:
        raise ValueError(f"Implied weekly rate must not exceed {cap:g}% per week.")
    normalized = {"calories": calories, "protein_g": macros[0], "carbs_g": macros[1], "fat_g": macros[2]}
    normalized.update(_coach_fiber_water_targets(target, day_type, calories, profile))
    return normalized


def _coach_fiber_water_targets(target: dict[str, Any], day_type: str, calories: int,
                               profile: dict[str, Any]) -> dict[str, Any]:
    day_label = ("training_day" if day_type == "training_day_targets" else
                 "rest_day" if day_type == "rest_day_targets" else "daily")
    defaults = calculate_fiber_water_targets(calories, float(profile["weight_kg"]),
                                              day_label == "training_day")
    normalized = {}
    for field in ("fiber_g", "water_ml"):
        normalized[field], source = _coach_fiber_water_amount(
            field, target, day_type, defaults[field])
        normalized[f"{field}_source"] = source
    training_default = calculate_fiber_water_targets(calories, float(profile["weight_kg"]), True)["water_ml"]
    if normalized["water_ml_source"] == "coach":
        normalized["training_day_water_ml"] = normalized["water_ml"]
        normalized["training_day_water_ml_source"] = "coach"
    else:
        normalized["training_day_water_ml"] = training_default
        normalized["training_day_water_ml_source"] = "default"
    return normalized


def _coach_fiber_water_amount(field: str, target: dict[str, Any], day_type: str,
                              default: int) -> tuple[int, str]:
    minimum, maximum = (10, 80) if field == "fiber_g" else (1000, 6000)
    value = target.get(field)
    if value in (None, ""):
        return default, "default"
    amount = _coach_target_amount(target, field, day_type, minimum=minimum)
    if amount > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    if field == "water_ml" and amount % 250:
        raise ValueError("water_ml must be in 250 ml steps between 1,000 and 6,000.")
    return amount, "coach"


def _coach_target_amount(target: dict[str, Any], field: str, day_type: str, *, minimum: int) -> int:
    raw_amount = target.get(field)
    if isinstance(raw_amount, bool):
        raise ValueError(f"{day_type} {field} must be a whole number of at least {minimum}.")
    try:
        number = float(raw_amount)
    except (TypeError, ValueError):
        raise ValueError(f"{day_type} targets need a valid {field} value.") from None
    if not math.isfinite(number) or not number.is_integer() or number < minimum:
        raise ValueError(f"{day_type} {field} must be a whole number of at least {minimum}.")
    return int(number)


def setup(ledger: Any, body: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    with ledger.ledger_transaction():
        return _save_setup(ledger, body, today or date.today())


def _save_setup(ledger: Any, body: dict[str, Any], today: date) -> dict[str, Any]:
    training_profile = ledger.get_nutrition_profile()
    if not _profile_is_complete(training_profile):
        return {"state": "incomplete", "targets": None,
                "message": _message("incomplete", body.get("language", "en"))}
    sex = body["sex"]
    activity = body["daily_activity"]
    answers = {key: bool(body["screening"][key]) for key in SCREENING_KEYS}
    if any(answers.values()):
        ledger.save_nutrition_setup(NutritionSetup(
            sex=sex, daily_activity=activity, screening=answers, plan=None,
        ))
        return {"state": "blocked", "targets": None,
                "message": _message("blocked", body.get("language", "en"))}
    if int(training_profile["age"]) < 18:
        return {"state": "under_18", "targets": None,
                "message": _message("under_18", body.get("language", "en"))}
    return _save_first_plan(ledger, training_profile,
                            NutritionSetup(sex, activity, answers, plan=None), today)


def _profile_is_complete(training_profile: dict[str, Any] | None) -> bool:
    return training_profile is not None and all(
        training_profile.get(field) is not None for field in ("age", "height_cm", "weight_kg")
    )


def _save_first_plan(ledger: Any, training_profile: dict[str, Any], setup_request: NutritionSetup,
                     today: date) -> dict[str, Any]:
    weight = training_profile["weight_kg"]
    goal, reason = resolve_goal(training_profile.get("current_goal"), training_profile.get("long_term_goal"),
                                float(weight), training_profile.get("target_weight_kg"))
    targets = _calculate_for(ledger, training_profile, setup_request.sex,
                             setup_request.daily_activity, goal, "moderate")
    intensity = None if goal == "maintain" else "moderate"
    plan = NutritionPlanVersion(goal, reason, intensity, setup_request.daily_activity, targets,
                                goal_source_snapshot=_goal_source(training_profile))
    ledger.save_nutrition_setup(NutritionSetup(setup_request.sex, setup_request.daily_activity,
                                               setup_request.screening, plan))
    return read(ledger, today=today)


def read(
    ledger: Any, language: str = "en", *, today: date
) -> dict[str, Any]:
    screening = ledger.get_nutrition_screening()
    answers = json.loads(screening[0]) if screening else None
    if answers and any(answers.values()):
        blocked_state = {"state": "blocked", "targets": None, "screening": answers,
                         "message": _message("blocked", language)}
        blocked_state.update(_adherence_state(ledger, today))
        return blocked_state
    active_plan = ledger.get_active_nutrition_plan()
    if active_plan is None:
        nutrition_state = _read_without_plan(ledger, answers, language)
    else:
        training_day = _is_training_day(ledger, today)
        nutrition_state = _read_active_plan(active_plan, answers, training_day)
        profile = ledger.get_nutrition_profile()
        if profile and _profile_is_complete(profile):
            _fill_fiber_water_defaults(nutrition_state, float(profile["weight_kg"]))
        if profile and _profile_is_complete(profile):
            resolved, reason = resolve_goal(profile.get("current_goal"), profile.get("long_term_goal"),
                                            float(profile["weight_kg"]), profile.get("target_weight_kg"))
            saved_snapshot = ledger.get_nutrition_goal_offer_snapshot(active_plan["id"])
            saved_source = json.loads(saved_snapshot[0]) if saved_snapshot is not None else None
            changed = saved_source is not None and saved_source != _goal_source(profile)
            dismissal = ledger.get_nutrition_goal_offer_dismissal()
            dismissed = dismissal is not None and dismissal[0] == _offer_key(profile)
            if changed and resolved != active_plan["goal"] and not dismissed:
                nutrition_state["pending_goal"] = resolved
                nutrition_state["pending_goal_reason"] = reason
    nutrition_state.update(_adherence_state(ledger, today))
    if nutrition_state.get("meals") and not meals_still_allowed(ledger, nutrition_state["meals"]):
        nutrition_state["meals"] = []
    if nutrition_state.get("state") == "ready":
        _apply_cardio_day_adjustment(ledger, nutrition_state, today)
    proposal = ledger.get_nutrition_pace_proposal()
    if proposal is not None:
        active = ledger.get_active_nutrition_plan()
        proposal["stale"] = active is None or int(active["id"]) != int(proposal["plan_version_id"])
        nutrition_state["pace_proposal"] = proposal
    else:
        nutrition_state["pace_proposal"] = None
    return nutrition_state


def _apply_cardio_day_adjustment(ledger: Any, state: dict[str, Any], today: date) -> None:
    """Apply today's extra Cardio as a read-time carbs adjustment."""
    sessions, logged = _cardio_day_records(ledger, today)
    profile = ledger.get_nutrition_profile() or {}
    weight_history = ledger.list_weight_history("0001-01-01", today.isoformat())
    weight = (float(weight_history[-1]["weight_kg"]) if weight_history
              else float(profile["weight_kg"]) if profile.get("weight_kg") else None)
    prescribed = _prescribed_cardio_calories(ledger, sessions, weight)
    extra = max(0, logged - prescribed)
    adjustment = extra // 2
    state["cardio_burned_kcal"] = logged
    state["cardio_adjustment_kcal"] = adjustment
    if adjustment:
        targets = dict(state["targets"])
        floor = math.ceil(float(targets.get("calorie_floor", 0)))
        targets["calories"] = max(int(targets["calories"]), floor) + adjustment
        targets["carbs_g"] = int(targets.get("carbs_g", 0)) + int(round(adjustment / 4))
        state["targets"] = targets


def _cardio_day_records(ledger: Any, today: date) -> tuple[list[Any], int]:
    return ledger.get_cardio_day_records(today.isoformat())


def _prescribed_cardio_calories(ledger: Any, sessions: list[Any], weight: float | None) -> int:
    prescribed = 0
    program_cache: dict[int, Any] = {}
    prescribed_days: set[tuple[int, int, int]] = set()
    for session in sessions:
        version = session["program_version"]
        day_order = session["program_day_order"]
        if version is None or day_order is None:
            continue
        version = int(version)
        day_key = (version, int(session["program_week_order"] or 1), int(day_order))
        if day_key in prescribed_days:
            continue
        prescribed_days.add(day_key)
        if version not in program_cache:
            program_cache[version] = ledger.get_program_by_version(version)
        program = program_cache[version]
        prescribed += _prescription_calories(program, session, weight)
    return prescribed


def _prescription_calories(program: Any, session: Any, weight: float | None) -> int:
    if program is None:
        return 0
    week_order = int(session["program_week_order"] or 1)
    day_order = int(session["program_day_order"])
    day = next((item for item in program.days
                if item.week_order == week_order and item.day_order == day_order), None)
    cardio = day.cardio if day is not None else None
    if isinstance(cardio, str):
        cardio = parse_legacy_cardio_prescription(cardio)
    elif cardio is not None:
        cardio = cardio.model_dump(exclude_none=True)
    if not isinstance(cardio, dict) or not cardio.get("minutes"):
        return 0
    if cardio.get("minutes_max") is not None:
        cardio["minutes"] = (int(cardio["minutes"]) + int(cardio["minutes_max"])) / 2
    return estimate_cardio_calories(cardio, weight)["kcal"]

def evaluate_pace_check(ledger: Any, today: date) -> dict[str, Any] | None:
    return nutrition_pace_check.evaluate(ledger, today)


def decide_pace_proposal(ledger: Any, command: PaceProposalDecision) -> dict[str, Any]:
    if command.decision not in ("accepted", "kept"):
        raise ValueError("Decision must be accepted or kept.")
    proposal = ledger.get_nutrition_pace_proposal()
    if (proposal is None or int(proposal["id"]) != command.proposal_id
            or proposal["status"] not in ("pending", "stale")
            or (proposal["status"] == "stale" and command.decision != "kept")):
        raise ValueError("Pace proposal is no longer pending.")
    with ledger.ledger_transaction():
        if command.decision == "accepted":
            _accept_pace_proposal(ledger, proposal, command)
        if not ledger.decide_nutrition_pace_proposal(
            command.proposal_id, command.decision, command.actor_role,
            datetime.now(UTC).isoformat()
        ):
            raise ValueError("Pace proposal is no longer pending.")
    return read(ledger, today=command.today)


def _accept_pace_proposal(ledger: Any, proposal: dict[str, Any],
                          command: PaceProposalDecision) -> None:
    from service.nutrition_pace_check import (PaceCheckContext, _capped_calories,
                                              _recompute_macros, _with_rate_metadata)
    active = ledger.get_active_nutrition_plan()
    if active is None or int(active["id"]) != int(proposal["plan_version_id"]):
        raise ValueError("This pace proposal is stale because the Nutrition plan changed.")
    payload = proposal["payload"]
    profile = ledger.get_nutrition_profile() or {}
    baseline = _calculate_for(ledger, profile, profile.get("gender") or "male",
                              active["daily_activity"], "maintain", "moderate")
    floor = math.ceil(baseline["calorie_floor"])
    targets = payload.get("target_options") or {"daily": payload["targets"]}
    weight = float(profile["weight_kg"])
    context = PaceCheckContext({**dict(active), "goal": payload["goal"]}, profile, {}, weight, 0,
                               calorie_floor=float(baseline["calorie_floor"]),
                               maintenance=float(baseline["maintenance"]))
    if payload.get("target_options"):
        source = json.loads(active["targets_json"])
        source_options = {key: source[key] for key in ("training_day", "rest_day")}
        training_days = ledger.get_nutrition_training_days(profile.get("weekly_frequency") or 0)
        average = (int(source_options["training_day"]["calories"]) * training_days
                   + int(source_options["rest_day"]["calories"]) * (7 - training_days)) / 7
        average_target = int(round(average))
        common_delta = _capped_calories(context, average_target + int(payload["calorie_change"])) - average_target
        common_delta = max(common_delta, max(floor - int(item["calories"])
                                             for item in source_options.values()))
        for key, day_targets in source_options.items():
            calories = int(day_targets["calories"]) + common_delta
            updated = _recompute_macros(day_targets, calories, weight)
            targets[key] = _with_rate_metadata(updated, context, calories)
    else:
        for key, day_targets in list(targets.items()):
            calories = int(day_targets["calories"])
            if calories < floor:
                raise ValueError(f"Pace proposal is below the current Calorie floor of {floor} kcal.")
            calories = _capped_calories(context, calories)
            updated = _recompute_macros(day_targets, calories, weight)
            updated = _with_rate_metadata(updated, context, calories)
            targets[key] = updated
    for day_targets in targets.values():
        calories = int(day_targets["calories"])
        if calories < floor:
            raise ValueError(f"Pace proposal is below the current Calorie floor of {floor} kcal.")
        macro_calories = int(day_targets["protein_g"]) * 4 + int(day_targets["carbs_g"]) * 4 + int(day_targets["fat_g"]) * 9
        if abs(macro_calories - calories) > calories * 0.05:
            raise ValueError("Pace proposal Macros do not match the calorie target within 5%.")
    coach_authored = command.actor_role == "coach"
    ledger.save_nutrition_plan(NutritionPlanVersion(
        goal=payload["goal"], reason={"code": "pace_check", "proposal_id": command.proposal_id},
        intensity=payload["intensity"], daily_activity=active["daily_activity"],
        targets=targets, goal_source_snapshot=_goal_source(profile),
        author="Coach" if coach_authored else "Player",
        provenance="coach_consented" if coach_authored else "player_consented",
        authority_assignment_id=command.assignment_id if coach_authored else None,
    ))


def assistant_projection(ledger: Any, today: date) -> dict[str, Any]:
    """Returns only assistant-safe Nutrition facts, respecting target blocks."""
    nutrition_state = read(ledger, today=today)
    if nutrition_state["state"] != "ready":
        status = nutrition_state["state"] if nutrition_state["state"] in ("blocked", "under_18") else "not_set"
        return {"status": status, "targets": None}

    start = today - timedelta(days=13)
    adherence = ledger.list_nutrition_adherence(start.isoformat(), today.isoformat())
    return {
        "status": "ok",
        "targets": nutrition_state["targets"],
        "author": nutrition_state["author"],
        "goal": nutrition_state["goal"],
        "pace": nutrition_state["intensity"],
        "adherence": _adherence_counts(adherence),
        "cardio_burned_kcal": nutrition_state.get("cardio_burned_kcal", 0),
        "cardio_adjustment_kcal": nutrition_state.get("cardio_adjustment_kcal", 0),
        **meal_context(nutrition_state),
    }


def _adherence_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {value: 0 for value in ("on_target", "roughly", "off")}
    for entry in entries:
        if entry["value"] in counts:
            counts[entry["value"]] += 1
    return counts


def _adherence_state(ledger: Any, today: date) -> dict[str, Any]:
    start = today - timedelta(days=6)
    entries = {entry["date"]: entry for entry in ledger.list_nutrition_adherence(
        start.isoformat(), today.isoformat())}
    profile = ledger.get_nutrition_profile()
    weights = ledger.list_weight_history("0001-01-01", "9999-12-31")
    return {
        "today_adherence": entries.get(today.isoformat(), {}).get("value"),
        "today_adherence_source": entries.get(today.isoformat(), {}).get("source"),
        "adherence_days": [
            {"date": (start + timedelta(days=offset)).isoformat(),
             "value": entries.get((start + timedelta(days=offset)).isoformat(), {}).get("value"),
             "source": entries.get((start + timedelta(days=offset)).isoformat(), {}).get("source")}
            for offset in range(7)
        ],
        "latest_weight": weights[-1]["weight_kg"] if weights else profile.get("weight_kg") if profile else None,
        "target_weight": profile.get("target_weight_kg") if profile else None,
    }


def log_adherence(ledger: Any, value: str, today: date,
                  entry_date: date | None = None) -> tuple[dict[str, Any], str]:
    entry_date = entry_date or today
    if entry_date not in (today, today - timedelta(days=1)):
        raise ValueError("Nutrition adherence can only be answered for today and yesterday.")
    screening = ledger.get_nutrition_screening()
    if screening is not None and any(json.loads(screening[0]).values()):
        raise ValueError("Nutrition adherence is unavailable while health screening blocks targets.")
    if ledger.get_active_nutrition_plan() is None:
        raise ValueError("An active Nutrition plan is required before recording adherence.")
    updated_at = ledger.upsert_nutrition_adherence(entry_date.isoformat(), value)
    return read(ledger, today=today), updated_at


def preview(ledger: Any, goal: str, intensity: str, today: date) -> dict[str, Any]:
    profile = ledger.get_nutrition_profile()
    if not _profile_is_complete(profile):
        return {"state": "incomplete", "targets": None, "reach_target_date": None}
    if int(profile["age"]) < 18:
        return {"state": "under_18", "targets": None, "reach_target_date": None}
    screening = ledger.get_nutrition_screening()
    if not profile.get("sex_confirmed") or screening is None:
        return {"state": "setup_required", "targets": None, "reach_target_date": None}
    if any(json.loads(screening[0]).values()):
        return {"state": "blocked", "targets": None, "reach_target_date": None}
    sex = profile.get("gender") or "male"
    activity = profile.get("daily_activity") or "mostly_sitting"
    targets = _calculate_for(ledger, profile, sex, activity, goal, intensity)
    target_weight = profile.get("target_weight_kg")
    reach_date = None
    rate = float(targets["weekly_rate_pct"])
    if goal != "maintain" and target_weight is not None and rate > 0:
        distance = abs(float(target_weight) - float(profile["weight_kg"]))
        direction_matches = (goal == "lose" and target_weight < profile["weight_kg"]) or (goal == "gain" and target_weight > profile["weight_kg"])
        if direction_matches:
            weeks = distance / (float(profile["weight_kg"]) * rate / 100)
            reach_date = (today + timedelta(days=round(weeks * 7))).isoformat()
    weekly_change = float(profile["weight_kg"]) * rate / 100
    if goal == "lose":
        weekly_change *= -1
    return {"state": "ready", "goal": goal, "intensity": intensity, "targets": targets,
            "reach_target_date": reach_date,
            "weekly_change_kg": weekly_change,
            "gain_target_warning": goal == "gain" and target_weight is not None and target_weight < profile["weight_kg"]}


def save_goal(ledger: Any, goal: str, intensity: str, today: date,
              screening: dict[str, bool] | None = None) -> dict[str, Any]:
    active = ledger.get_active_nutrition_plan()
    if active is None:
        raise ValueError("Set up Nutrition targets first.")
    screening_row = ledger.get_nutrition_screening()
    requires_screening = goal == "lose" and active["goal"] != "lose"
    if requires_screening and screening is None:
        raise ValueError("Health screening is required before choosing Lose.")
    if requires_screening and any(screening.values()):
        profile = ledger.get_nutrition_profile()
        with ledger.ledger_transaction():
            ledger.save_nutrition_setup(NutritionSetup(profile.get("gender") or "male",
                profile.get("daily_activity") or active["daily_activity"], screening, None))
        return read(ledger, today=today)
    if not requires_screening and screening_row is None:
        raise ValueError("Complete the health screening before changing Nutrition targets.")
    expected_intensity = None if goal == "maintain" else intensity
    if active["goal"] == goal and active["intensity"] == expected_intensity:
        return read(ledger, today=today)
    result = preview(ledger, goal, intensity, today)
    if result["state"] != "ready":
        return result
    profile = ledger.get_nutrition_profile()
    source = _goal_source(profile)
    plan = NutritionPlanVersion(goal, {"code": "player_choice"},
                                None if goal == "maintain" else intensity,
                                active["daily_activity"], result["targets"],
                                goal_source_snapshot=source)
    with ledger.ledger_transaction():
        if requires_screening and screening is not None:
            profile = ledger.get_nutrition_profile()
            ledger.save_nutrition_setup(NutritionSetup(profile.get("gender") or "male",
                profile.get("daily_activity") or active["daily_activity"], screening, None))
        ledger.save_nutrition_plan(plan)
    return read(ledger, today=today)


def dismiss_goal_offer(ledger: Any, today: date) -> dict[str, Any]:
    profile = ledger.get_nutrition_profile()
    if profile is not None:
        ledger.dismiss_nutrition_goal_offer(_offer_key(profile))
    return read(ledger, today=today)


def _calculate_for(ledger: Any, profile: dict[str, Any], sex: str, activity: str,
                   goal: str, intensity: str) -> dict[str, Any]:
    targets = calculate_targets(NutritionCalculationInput(
        sex=sex, age=int(profile["age"]), height_cm=float(profile["height_cm"]),
        weight_kg=float(profile["weight_kg"]), daily_activity=activity,
        training_days=ledger.get_nutrition_training_days(profile.get("weekly_frequency") or 0),
        goal=goal, intensity=intensity))
    result = _target_json(targets)
    result.update(calculate_fiber_water_targets(result["calories"], float(profile["weight_kg"])))
    result["fiber_g_source"] = "default"
    result["water_ml_source"] = "default"
    result["training_day_water_ml"] = calculate_fiber_water_targets(
        result["calories"], float(profile["weight_kg"]), True)["water_ml"]
    result["training_day_water_ml_source"] = "default"
    return result


def _read_without_plan(ledger: Any, answers: dict[str, bool] | None,
                       language: str) -> dict[str, Any]:
    training_profile = ledger.get_nutrition_profile()
    state = "not_started"
    if training_profile is None:
        state = "incomplete"
    elif int(training_profile.get("age") or 0) < 18:
        state = "under_18"
    message = _message(state, language) if state in MESSAGES else None
    return {"state": state, "targets": None, "screening": answers,
            "sex": training_profile.get("gender") if training_profile else None,
            "daily_activity": training_profile.get("daily_activity") if training_profile else None,
            "message": message}


def targets_for_day(ledger: Any, entry_date: date) -> dict[str, Any] | None:
    state = state_for_day(ledger, entry_date)
    return state["targets"] if state else None


def state_for_day(ledger: Any, entry_date: date) -> dict[str, Any] | None:
    screening = ledger.get_nutrition_screening()
    if screening and any(json.loads(screening[0]).values()):
        return None
    plan = ledger.get_nutrition_plan_before(_nutrition_day_end(ledger, entry_date))
    if plan is None:
        return None
    state = _read_active_plan(plan, None, _is_training_day(ledger, entry_date))
    _apply_cardio_day_adjustment(ledger, state, entry_date)
    return state


def _nutrition_day_end(ledger: Any, entry_date: date) -> datetime:
    schedule = ledger.get_schedule_effective_on(ledger.ledger_id, entry_date.isoformat())
    timezone = schedule["timezone"] if schedule else "UTC"
    # A version created exactly at the next midnight belongs to the next day.
    return datetime.combine(entry_date + timedelta(days=1), time.min,
                            tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def _read_active_plan(active_plan: Any, answers: dict[str, bool] | None,
                      training_day: bool = False) -> dict[str, Any]:
    reason = json.loads(active_plan["goal_reason_data_json"])
    reason.pop("resolved_from", None)
    targets = json.loads(active_plan["targets_json"])
    day_type = "training_day" if training_day else "rest_day"
    is_day_target_map = any(key in targets for key in ("daily", "training_day", "rest_day"))
    selected_targets = (
        targets.get(day_type) or targets.get("daily") or targets.get("training_day") or targets.get("rest_day")
        if is_day_target_map else targets
    )
    target_options = targets if is_day_target_map else {"daily": targets}
    meal_payload = json.loads(active_plan["meals_json"]) if active_plan["meals_json"] else {}
    meal_variant = meal_payload.get("variants", {}).get(day_type, {})
    return {"state": "ready", "goal": active_plan["goal"],
            "meals": meal_variant.get("meals", []),
            "meals_enabled": meal_payload.get("enabled", False),
            "meals_targets_changed": meal_payload.get("targets_changed", False),
            "goal_reason": reason,
            "intensity": active_plan["intensity"], "daily_activity": active_plan["daily_activity"],
            "targets": selected_targets, "target_options": target_options, "target_day_type": day_type,
            "author": active_plan["author"], "authority_assignment_id": active_plan["authority_assignment_id"],
            "provenance": active_plan["provenance"], "screening": answers}


def _is_training_day(ledger: Any, today: date) -> bool:
    schedule = ledger.get_schedule_effective_on(ledger.ledger_id, today.isoformat())
    return bool(schedule and today.isoweekday() in schedule["weekdays"])


def update_activity(ledger: Any, activity: str, today: date | None = None) -> dict[str, Any]:
    training_profile = ledger.get_nutrition_profile()
    active_plan = ledger.get_active_nutrition_plan()
    screening = ledger.get_nutrition_screening()
    if screening and any(json.loads(screening[0]).values()):
        return read(ledger, today=today)
    if not _profile_is_complete(training_profile) or active_plan is None:
        return read(ledger, today=today)
    if int(training_profile["age"]) < 18:
        return read(ledger, today=today)
    targets = _recalculate_activity_targets(ledger, training_profile, active_plan, activity)
    source_snapshot = ledger.get_nutrition_goal_offer_snapshot(active_plan["id"])
    with ledger.ledger_transaction():
        ledger.update_nutrition_activity(activity)
        ledger.save_nutrition_plan(NutritionPlanVersion(
            active_plan["goal"], json.loads(active_plan["goal_reason_data_json"]),
            active_plan["intensity"], activity, targets,
            goal_source_snapshot=json.loads(source_snapshot[0]) if source_snapshot else None,
        ))
    return read(ledger, today=today)


def _recalculate_activity_targets(ledger: Any, training_profile: dict[str, Any],
                                  active_plan: Any, activity: str) -> dict[str, Any]:
    goal = active_plan["goal"]
    return _calculate_for(ledger, training_profile, training_profile.get("gender", "male"),
                          activity, goal, active_plan["intensity"] or "moderate")
