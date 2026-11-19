"""Read-only, turn-scoped tools for the player assistant."""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from database.ledger.profile import PLAYER_PROFILE_STORAGE_DEFAULTS
from database.ledger.chat import MAX_CHAT_HISTORY_SEARCH_RESULTS
from core.effort import rir_from_rpe
from core.muscle_volume import (
    MAIN_MUSCLE_GROUPS,
    default_muscle_credits,
    normalize_main_muscle,
)
from service.injuries import render_public_injury_record
from service.nutrition import assistant_projection, targets_for_day as nutrition_targets_for_day
from service.nutrition_assistant_meals import meal_page
from service.food_log import NUTRIENT_KEYS
from service.food_log_context import nutrient_totals
from service.player_weight_context import render_player_weight_context
from service.training_status import saturday_week_start
from service.weight_history import WeightTrendQuery, get_weight_trend, player_local_date
from agent.player_prompt import (
    HOSTED_PROMPT_MAX_BYTES,
    HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES,
    player_prompt_history_settings,
)

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_BYTES = 4 * 1024
#: Headroom per page so the page's own envelope and a follow-up key always fit.
TOOL_RESULT_PAGE_MARGIN_BYTES = 128
MAX_PLAYER_TOOL_ROUNDS = 3
CHAT_SEARCH_MATCH_MAX_CHARS = 300
TOOL_TIMEOUT_SECONDS = 5.0
CARDIO_HISTORY_FIELDS = (
    "machine", "minutes", "speed_kmh", "incline_pct", "level", "watts", "distance_m",
    "calories_kcal", "calories_are_estimate",
)
_TRUNCATED_PROMPT_RESULT = '{"status":"truncated"}'
_INJURY_CLEARANCE_TOOL_FIELDS = (
    "exercise_name",
    "original_wording",
    "verdict",
    "note",
    "recorded_at",
    "source",
)


class EmptyToolArgs(BaseModel):
    """Schema for a read tool that takes no arguments."""


ProfileSection = Literal["Body", "Goals", "Training setup", "Limitations", "Focus", "Recovery"]


class ProfileArgs(BaseModel):
    sections: list[ProfileSection]

    @model_validator(mode="before")
    @classmethod
    def missing_sections_list_available_sections(cls, arguments: Any) -> Any:
        # Advertise a required scope, but keep legacy unscoped calls value-free.
        if isinstance(arguments, dict) and "sections" not in arguments:
            return {**arguments, "sections": []}
        return arguments


class FoodLogArgs(BaseModel):
    """One recent Player-local day, paginated within the hosted result cap."""

    day: str | None = None
    offset: int = Field(default=0, ge=0)


class PlayerNutritionArgs(BaseModel):
    """Read the active plan, or only saved targets for a recent day/window."""

    offset: int = Field(default=0, ge=0)
    day: str | None = None
    days: int | None = Field(default=None, ge=1, le=14)

    @model_validator(mode="after")
    def require_one_period(self):
        if self.day is not None and self.days is not None:
            raise ValueError("Choose day or days, not both")
        return self


class NutritionTrendArgs(BaseModel):
    """A short recent Player-local daily Food log and target trend."""

    days: int = Field(default=14, ge=1, le=14)


class CardioArgs(BaseModel):
    """Continue recent logged Cardio sessions within the hosted result cap."""

    offset: int = Field(default=0, ge=0)
    days: int = Field(default=14, ge=1, le=14)
    day: str | None = Field(default=None, description="today, yesterday or YYYY-MM-DD; overrides days")


class ChatHistorySearchArgs(BaseModel):
    """Keyword search and optional UTC date bounds for older chat messages."""

    query: str = Field(min_length=1, max_length=300)
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(
        default=MAX_CHAT_HISTORY_SEARCH_RESULTS,
        ge=1,
        le=MAX_CHAT_HISTORY_SEARCH_RESULTS,
    )


WorkoutHistoryScope = Literal["last_session", "date", "exercise", "recent_sessions"]


class WorkoutHistoryArgs(BaseModel):
    """Scope for the current player's committed workout history."""

    scope: WorkoutHistoryScope = "last_session"
    date: str | None = None
    exercise: str | None = None
    limit: int = Field(default=3, ge=1, le=10)
    offset: int = Field(default=0, ge=0)


class ProgramRationaleArgs(BaseModel):
    """Optional scope for the active program's recorded rationale."""

    day_name: str | None = None
    day_order: int | None = None
    exercise_name: str | None = None
    exercise_id: str | None = None
    week_order: int | None = None
    page: int = 0


class ActiveProgramArgs(BaseModel):
    """Optional Program week, day, Exercise or muscle scope."""

    day_name: str | None = None
    exercise_name: str | None = None
    exercise_id: str | None = None
    week_order: int | None = None
    muscle: str | None = None
    offset: int = Field(default=0, ge=0)


@dataclass(frozen=True)
class PlayerReadTool:
    """A reusable entry in the player read-tool registry."""

    name: str
    description: str
    args_schema: type[BaseModel]
    reader: Callable[..., dict[str, Any]]
    status_en: str
    status_ar: str
    args_reader: Callable[[Any, BaseModel], dict[str, Any]] | None = None
    timeout_seconds: float = TOOL_TIMEOUT_SECONDS


def _not_set(profile_value: Any) -> Any:
    if profile_value is None:
        return "not set"
    if isinstance(profile_value, str):
        cleaned = profile_value.strip()
        if not cleaned:
            return "not set"
        return cleaned
    if isinstance(profile_value, float) and not math.isfinite(profile_value):
        return "not set"
    return profile_value


_PROFILE_SECTION_FIELDS = {
    "Body": ("gender", "age", "height_cm", "weight_kg", "target_weight_kg"),
    "Goals": ("current_goal", "long_term_goal"),
    "Training setup": (
        "weekly_frequency", "equipment_access", "rep_preference", "training_age_years",
    ),
    "Limitations": ("injuries_or_limitations", "movement_restrictions"),
    "Focus": ("weak_points",),
    "Recovery": ("stress_and_sleep",),
}
_PROFILE_SECTION_DESCRIPTIONS = {
    "Body": "Gender, age, height, weight and target weight.",
    "Goals": "Current and long-term goals.",
    "Training setup": "Weekly frequency, equipment access, rep preference and training age.",
    "Limitations": "Injury text, injury records with Exercise clearances and confirmed Movement restrictions.",
    "Focus": "Weak points.",
    "Recovery": "Stress and sleep.",
}


def _is_storage_default(key: str, stored_value: Any) -> bool:
    default = PLAYER_PROFILE_STORAGE_DEFAULTS.get(key)
    if default is None:
        return False
    if isinstance(stored_value, str) and isinstance(default, str):
        return stored_value.strip().casefold() == default.casefold()
    try:
        return float(stored_value) == float(default)
    except (TypeError, ValueError):
        return stored_value == default


def _profile_has_completion_evidence(ledger: Any) -> bool:
    intake_state = ledger.get_intake_state()
    if intake_state is not None and intake_state.get("status") == "confirmed":
        return True
    completion_getter = getattr(ledger, "get_onboarding_analytics_completed_at", None)
    if callable(completion_getter) and completion_getter():
        return True
    return ledger.get_active_program() is not None


def _player_profile(ledger: Any) -> dict[str, Any]:
    getter = getattr(ledger, "get_player_profile", None)
    return (getter() or {}) if callable(getter) else {}


def _profile_field_value(
    key: str, profile: dict[str, Any], answers: dict[str, Any], completed: bool,
) -> Any:
    if key in answers:
        answer = answers[key]
        stored_value = answer.get("value")
        if answer.get("prefilled") and not completed and _is_storage_default(key, stored_value):
            stored_value = None
    else:
        stored_value = profile.get(key)
        if not completed and _is_storage_default(key, stored_value):
            stored_value = None
    return _not_set(stored_value)


def _read_profile(ledger: Any, args: ProfileArgs) -> dict[str, Any]:
    if not args.sections:
        return {"status": "ok", "sections": dict(_PROFILE_SECTION_DESCRIPTIONS)}
    profile = _player_profile(ledger)
    answers = ledger.load_intake_answers()
    completed = _profile_has_completion_evidence(ledger)
    profile_fields = {
        key: _profile_field_value(key, profile, answers, completed)
        for section in args.sections for key in _PROFILE_SECTION_FIELDS[section]
    }
    return {
        "status": "ok", "profile": profile_fields,
        **({"injuries": _read_injury_records(ledger)} if "Limitations" in args.sections else {}),
    }


def _read_weight_trend(ledger: Any) -> dict[str, Any]:
    ledger_id = ledger.ledger_id
    as_of = player_local_date(ledger, ledger_id)
    trend = get_weight_trend(
        None,
        WeightTrendQuery(ledger_id=ledger_id, weeks=8, as_of=as_of),
        ledger=ledger,
    )
    profile = _player_profile(ledger)
    return {
        "status": "ok",
        "weight_context": render_player_weight_context(
            trend, profile.get("target_weight_kg"), as_of=as_of
        ),
    }


def _read_injury_records(ledger: Any) -> list[dict[str, Any]]:
    records = []
    for record in ledger.list_injury_records():
        rendered = render_public_injury_record(record)
        rendered.pop("id", None)
        rendered["clearances"] = [
            {
                key: clearance[key]
                for key in _INJURY_CLEARANCE_TOOL_FIELDS
                if key in clearance
            }
            for clearance in ledger.list_exercise_clearances(str(record["id"]))
        ]
        records.append(rendered)
    return records


def _read_assistant_preferences(ledger: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "preferences": [
            preference["text"] for preference in ledger.list_assistant_preferences()
        ],
    }


def _chat_search_match(message: dict[str, Any]) -> dict[str, Any]:
    content = message["content"]
    match: dict[str, Any] = {
        "role": message["role"],
        "date": message["created_at"][:10],
        "content": content[:CHAT_SEARCH_MATCH_MAX_CHARS],
    }
    if len(content) > CHAT_SEARCH_MATCH_MAX_CHARS:
        match["content_truncated"] = True
    return match


def _chat_history_search_result(matches: list[dict[str, Any]]) -> dict[str, Any]:
    response: dict[str, Any] = {"status": "ok", "matches": [], "has_more": False}
    for message in matches:
        response["matches"].append(_chat_search_match(message))
        rendered = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        if len(rendered.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
            response["matches"].pop()
            response["has_more"] = True
            break
    if len(response["matches"]) < len(matches):
        response["has_more"] = True
    return response


def _read_chat_history_search(
    ledger: Any,
    args: ChatHistorySearchArgs,
    *,
    recent_window_size: int | None = None,
) -> dict[str, Any]:
    if args.start_date is not None and args.end_date is not None and args.start_date > args.end_date:
        return {"status": "invalid_date_range", "matches": [], "has_more": False}
    matches = ledger.search_chat_history(
        args.query,
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit,
        recent_window_size=recent_window_size,
    )
    if not matches:
        return {"status": "no_matches", "matches": [], "has_more": False}
    return _chat_history_search_result(matches)


def _read_player_nutrition(ledger: Any, args: PlayerNutritionArgs) -> dict[str, Any]:
    """An explicit period returns only saved daily targets; unscoped reads use the active plan."""
    today = player_local_date(ledger, ledger.ledger_id)
    if args.day is not None or args.days is not None:
        return _read_saved_nutrition_targets(ledger, args, today)
    return meal_page(assistant_projection(ledger, today), args.offset, MAX_TOOL_RESULT_BYTES)


def _recent_player_day(requested: str, today: date) -> date:
    # Inclusive recent window: oldest allowed day, today; reject older/future/invalid dates.
    day = {"today": today, "yesterday": today - timedelta(days=1)}.get(requested)
    if day is None:
        day = date.fromisoformat(requested)
    if not today - timedelta(days=13) <= day <= today:
        raise ValueError("Outside the recent Player-local window")
    return day


def _invalid_recent_date(today: date) -> dict[str, Any]:
    return {"status": "invalid_date", "earliest_date": (today - timedelta(days=13)).isoformat(),
            "today": today.isoformat()}


def _read_saved_nutrition_targets(ledger: Any, args: PlayerNutritionArgs, today: date) -> dict[str, Any]:
    try:
        end = _recent_player_day(args.day, today) if args.day is not None else today
    except ValueError:
        return _invalid_recent_date(today)
    start = end - timedelta(days=(args.days or 1) - 1)
    days = [{"date": (start + timedelta(days=offset)).isoformat(),
             "targets": _nutrition_target_values(nutrition_targets_for_day(
                 ledger, start + timedelta(days=offset)))}
            for offset in range((end - start).days + 1)]
    return {"status": "ok" if any(day["targets"] is not None for day in days) else "no_data",
            "start_date": start.isoformat(), "end_date": end.isoformat(), "days": days}


def _nutrition_target_values(targets: dict[str, Any] | None) -> dict[str, Any] | None:
    if not targets:
        return None
    return {key: targets.get(key) for key in ("calories", "protein_g", "carbs_g", "fat_g")}


def _nutrition_trend_day(ledger: Any, day: date) -> dict[str, Any]:
    nutrients = ledger.list_food_log_nutrients(day)
    targets = _nutrition_target_values(nutrition_targets_for_day(ledger, day))
    return {
        "date": day.isoformat(),
        "totals": nutrient_totals(nutrients, NUTRIENT_KEYS) if nutrients else None,
        "targets": targets,
    }


def _read_player_nutrition_trend(ledger: Any, args: NutritionTrendArgs) -> dict[str, Any]:
    today = player_local_date(ledger, ledger.ledger_id)
    start = today - timedelta(days=args.days - 1)
    days = [_nutrition_trend_day(ledger, today - timedelta(days=offset))
            for offset in range(args.days - 1, -1, -1)]
    response = {
        "status": "ok" if any(day["totals"] is not None for day in days) else "no_data",
        "start_date": start.isoformat(), "end_date": today.isoformat(), "days": days,
    }
    encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return response if len(encoded) <= MAX_TOOL_RESULT_BYTES else {
        "status": "truncated", "start_date": start.isoformat(), "end_date": today.isoformat(),
    }


def _recent_cardio_sessions(ledger: Any, today: date, days: int) -> list[dict[str, Any]]:
    sessions = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_sessions, _logged_calories = ledger.get_cardio_day_records(day.isoformat())
        for session in sorted(day_sessions, key=lambda row: str(row["id"])):
            entries = [_cardio_history_entry(entry)
                       for entry in ledger.get_session_cardio(str(session["id"])) or []]
            if entries:
                sessions.append(_cardio_session_record(day, entries))
    sessions.sort(key=lambda session: session["date"], reverse=True)
    return sessions


def _cardio_session_record(day: date, entries: list[dict[str, Any]]) -> dict[str, Any]:
    calories = [entry.get("calories_kcal") for entry in entries]
    complete_total = all(kcal is not None for kcal in calories)
    return {
        "date": day.isoformat(), "entries": entries,
        "calories_kcal": sum(calories) if complete_total else None,
        "calories_are_estimate": (
            any(entry.get("calories_are_estimate", False) for entry in entries)
            if complete_total else None
        ),
    }


def _cardio_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Keep the recorded Cardio details and saved calorie estimate."""
    history = {field: entry[field] for field in CARDIO_HISTORY_FIELDS
               if field in entry and entry[field] is not None}
    if "calories_are_estimate" in history:
        history["calories_are_estimate"] = bool(history["calories_are_estimate"])
    return history


def _cardio_session_minutes(session: dict[str, Any]) -> int:
    return sum(int(entry.get("minutes") or 0) for entry in session["entries"])


def _cardio_period_totals(
    sessions: list[dict[str, Any]], start: date, end: date,
) -> dict[str, int]:
    selected = [session for session in sessions
                if start <= date.fromisoformat(session["date"]) <= end]
    return {"minutes": sum(_cardio_session_minutes(session) for session in selected),
            "sessions": len(selected)}


def _cardio_summary(today: date, sessions: list[dict[str, Any]], days: int) -> dict[str, Any]:
    start = today - timedelta(days=days - 1)
    periods = {
        "this_week": saturday_week_start(today),
        "last_7_days": today - timedelta(days=6),
        "last_14_days": today - timedelta(days=13),
    }
    return {
        "status": "ok" if sessions else "no_data", "today": today.isoformat(),
        "window": {"start_date": start.isoformat(), "end_date": today.isoformat(),
                   **_cardio_period_totals(sessions, start, today)},
        **{name: {"start_date": period_start.isoformat(),
                  **_cardio_period_totals(sessions, period_start, today)}
           for name, period_start in periods.items() if period_start >= start},
        "session_count": len(sessions),
    }


def _cardio_session_page(
    sessions: list[dict[str, Any]], summary: dict[str, Any], offset: int,
) -> dict[str, Any]:
    # Empty/one/many/oversized sessions: every continuation must advance.
    response = {**summary, "sessions": []}
    for index in range(offset, len(sessions)):
        response["sessions"].append(sessions[index])
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_TOOL_RESULT_BYTES - 128:
            response["sessions"].pop()
            if index == offset:
                return {**response, "status": "truncated", "next_offset": None,
                        "truncation_reason": "cardio_session_exceeds_result_limit"}
            response["next_offset"] = index
            return response
    response["next_offset"] = None
    return response


def _read_player_cardio(ledger: Any, args: CardioArgs) -> dict[str, Any]:
    today = player_local_date(ledger, ledger.ledger_id)
    try:
        end = _recent_player_day(args.day, today) if args.day is not None else today
    except ValueError:
        return {**_invalid_recent_date(today), "next_offset": None}
    days = 1 if args.day is not None else args.days
    sessions = _recent_cardio_sessions(ledger, end, days)
    summary = _cardio_summary(end, sessions, days)
    summary["today"] = today.isoformat()
    if args.day is not None:
        summary.pop("this_week", None)
    return _cardio_session_page(sessions, summary, args.offset)


def _food_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    quick_add = entry["kind"] == "quick_add"
    name = "Quick add" if quick_add else entry["name"]
    arabic_name = None if quick_add else entry.get("arabic_name")
    return {
        "name": name[:200],
        **({"name_truncated": True} if len(name) > 200 else {}),
        **({"arabic_name": arabic_name[:200]} if arabic_name else {}),
        **({"arabic_name_truncated": True} if arabic_name and len(arabic_name) > 200 else {}),
        "time": entry["logged_time"], "meal": entry["meal_label"],
        **({"grams": entry["grams"]} if not quick_add else {}),
        "nutrients": {key: entry["nutrients"].get(key) for key in NUTRIENT_KEYS},
    }


def _food_log_page(entries, summary, offset):
    # Empty / one / many / multibyte names: every page must fit and make progress.
    response = {**summary, "entries": []}
    for index in range(offset, len(entries)):
        response["entries"].append(_food_log_entry(entries[index]))
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_TOOL_RESULT_BYTES - TOOL_RESULT_PAGE_MARGIN_BYTES:
            response["entries"].pop()
            response["next_offset"] = index
            return response
    response["next_offset"] = None
    return response


def _read_player_food_log(ledger: Any, args: FoodLogArgs) -> dict[str, Any]:
    today = player_local_date(ledger, ledger.ledger_id)
    try:
        day = _recent_player_day(args.day or "today", today)
    except ValueError:
        return _invalid_recent_date(today)
    entries = ledger.list_food_log_entries(day)
    targets = _nutrition_target_values(nutrition_targets_for_day(ledger, day))
    response = {
        "status": "ok", "date": day.isoformat(), "today": today.isoformat(),
        "totals": nutrient_totals([entry["nutrients"] for entry in entries], NUTRIENT_KEYS),
        "targets": targets,
        "entry_count": len(entries),
    }
    return _food_log_page(entries, response, args.offset)


def _history_set_entry(row: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "set": row["set_index"], "kg": row["weight_kg"], "reps": row["reps"],
    }
    rir = rir_from_rpe(row.get("rpe"))
    if rir is not None:
        entry["rir"] = rir
        entry["rpe"] = row["rpe"]
    return entry


def _group_history_sessions(
    rows: Sequence[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """(session_id, session) pairs, newest first, sets in logged order.

    ``get_session_log`` returns one row per set, oldest session first; warm-ups
    stay excluded like every other committed-history read.
    """
    grouped: list[tuple[str, dict[str, Any]]] = []
    by_id: dict[str, dict[str, Any]] = {}
    exercises_by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row["is_warmup"]:
            continue
        session = by_id.get(row["session_id"])
        if session is None:
            session = {
                "date": str(row["session_date"]),
                "day": str(row["split_name"] or "not set"),
                "exercises": [],
            }
            by_id[row["session_id"]] = session
            exercises_by_id[row["session_id"]] = {}
            grouped.append((str(row["session_id"]), session))
        exercise = exercises_by_id[row["session_id"]].get(row["exercise_id"])
        if exercise is None:
            exercise = {
                "id": str(row["exercise_id"]),
                "name": str(row["exercise_name"] or "not set"),
                "sets": [],
            }
            exercises_by_id[row["session_id"]][row["exercise_id"]] = exercise
            session["exercises"].append(exercise)
        exercise["sets"].append(_history_set_entry(row))
    for session_id, _session in grouped:
        for exercise in exercises_by_id[session_id].values():
            exercise["sets"].sort(key=lambda entry: entry["set"])
    return list(reversed(grouped))


def _history_exercise_entries(sessions: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    for session in sessions:
        for exercise in session["exercises"]:
            entries.setdefault(
                exercise["id"], {"exercise_id": exercise["id"], "name": exercise["name"]}
            )
    return list(entries.values())


def _resolve_history_exercise(
    store: Any, sessions: Sequence[dict[str, Any]], name: str
) -> tuple[str | None, list[str] | None]:
    """Resolves an exercise with the same matchers the history keyword path uses."""
    from agent.assistant_graph import _history_exercise_matches

    matches = _history_exercise_matches(name, _history_exercise_entries(sessions))
    if len(matches) == 1:
        return str(matches[0]["exercise_id"]), None
    if store is not None:
        resolver = getattr(store, "find_unique_exercise_id_by_exact_name", None)
        if callable(resolver):
            resolved = resolver(name)
            if resolved:
                return str(resolved), None
    return None, [entry["name"] for entry in matches] if matches else None


def _history_comparison_by_id(ledger: Any, session_id: str) -> dict[str, dict[str, Any]]:
    """Compact previous-session deltas from the debrief comparison read."""
    getter = getattr(ledger, "get_session_comparison_context", None)
    context = getter() if callable(getter) else None
    if not isinstance(context, dict) or (context.get("session") or {}).get("id") != session_id:
        return {}
    comparison = {}
    for exercise in context.get("exercises") or []:
        previous = exercise.get("previous")
        if previous is None:
            continue
        deltas = exercise.get("deltas") or {}
        comparison[str(exercise["exercise_id"])] = {
            "baseline": (previous.get("session") or {}).get("session_date", "not set"),
            "delta_kg": deltas.get("load_kg"),
            "delta_reps": deltas.get("reps"),
            "status": exercise.get("status", "insufficient_data"),
        }
    return comparison


def _history_summary_extras(summary: Any, session_id: str) -> dict[str, Any]:
    """Session-level facts only ``get_latest_session_summary`` knows."""
    if not isinstance(summary, dict) or summary.get("session_id") != session_id:
        return {}
    extras: dict[str, Any] = {}
    if summary.get("readiness_score") is not None:
        extras["readiness"] = summary["readiness_score"]
    minutes = sum(
        int(item.get("minutes", 0) or 0) for item in (summary.get("cardio") or [])
    )
    if minutes:
        extras["cardio_minutes"] = minutes
    return extras


def _compact_history_session(session: dict[str, Any]) -> dict[str, Any]:
    exercises = [
        {
            "id": exercise["id"],
            "name": exercise["name"],
            "sets": [
                {key: set_entry[key] for key in ("kg", "reps") if key in set_entry}
                for set_entry in exercise["sets"]
            ],
        }
        for exercise in session.get("exercises", ())
    ]
    return {
        "date": session["date"], "day": session["day"],
        "exercises": exercises, "detail_truncated": True,
    }


def _history_page(
    base: dict[str, Any], selected: list[dict[str, Any]], args: WorkoutHistoryArgs
) -> dict[str, Any]:
    """Adds up to ``limit`` sessions until the result cap, paging by session index."""
    response = {**base, "status": "ok", "sessions": [], "next_offset": None}
    end = min(args.offset + args.limit, len(selected))
    for index in range(args.offset, end):
        response["sessions"].append(selected[index])
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_TOOL_RESULT_BYTES - TOOL_RESULT_PAGE_MARGIN_BYTES:
            response["sessions"].pop()
            if response["sessions"]:
                response["next_offset"] = index
                return response
            compact = _compact_history_session(selected[index])
            session = {**base, "status": "ok", "sessions": [compact], "next_offset": None}
            encoded = json.dumps(session, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES - TOOL_RESULT_PAGE_MARGIN_BYTES:
                session["next_offset"] = index + 1 if index + 1 < len(selected) else None
                return session
            oversized = selected[index]
            return {
                **base, "status": "truncated",
                "message": "This session's detail exceeds the result cap; ask about one exercise.",
                "date": oversized["date"], "day": oversized["day"],
            }
    if end < len(selected):
        response["next_offset"] = end
    return response


def _history_date_scope(
    base: dict[str, Any], args: WorkoutHistoryArgs, grouped: list[tuple[str, dict[str, Any]]]
) -> dict[str, Any]:
    today = date.fromisoformat(base["today"])
    requested = (args.date or "").strip().lower()
    day = {"today": today, "yesterday": today - timedelta(days=1)}.get(requested)
    if day is None:
        try:
            day = date.fromisoformat(requested)
        except ValueError:
            return {
                **base, "status": "invalid_date",
                "message": "Use today, yesterday or YYYY-MM-DD.",
            }
    selected = [
        session for _session_id, session in grouped if session["date"] == day.isoformat()
    ]
    if not selected:
        return {
            **base, "status": "no_sessions", "date": day.isoformat(),
            "message": "No sessions logged on that date.", "sessions": [], "next_offset": None,
        }
    return _history_page(base, selected, args)


def _history_exercise_scope(
    base: dict[str, Any],
    store: Any,
    args: WorkoutHistoryArgs,
    grouped: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    name = (args.exercise or "").strip()
    sessions = [session for _session_id, session in grouped]
    if not name:
        return {
            **base, "status": "unknown_exercise",
            "message": "Pass the exercise name for scope=exercise.", "sessions": [],
        }
    resolved, ambiguous = _resolve_history_exercise(store, sessions, name)
    if ambiguous:
        return {
            **base, "status": "ambiguous_exercise", "candidates": ambiguous[:8],
            "message": "Which exercise variant do you mean?", "sessions": [],
        }
    if resolved is None:
        return {
            **base, "status": "unknown_exercise",
            "message": "No Exercise library or logged-session match for that name.",
            "sessions": [],
        }
    selected = []
    for _session_id, session in grouped:
        exercises = [
            exercise for exercise in session["exercises"] if exercise["id"] == resolved
        ]
        if exercises:
            selected.append({**session, "exercises": exercises})
    if not selected:
        return {
            **base, "status": "not_logged",
            "message": "No sessions logged for that exercise.", "sessions": [],
        }
    return _history_page(base, selected, args)


def _history_date_of(value: Any) -> date | None:
    """ISO session dates parse to dates; anything unparseable never outranks one."""
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _history_last_session(
    base: dict[str, Any], ledger: Any, args: WorkoutHistoryArgs,
    grouped: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    summary_getter = getattr(ledger, "get_latest_session_summary", None)
    latest = summary_getter() if callable(summary_getter) else None
    newest_id, newest = grouped[0]
    summary_date = (
        _history_date_of(latest.get("session_date")) if isinstance(latest, dict) else None
    )
    newest_date = _history_date_of(newest["date"])
    if (
        isinstance(latest, dict)
        and latest.get("session_id") != newest_id
        and summary_date is not None
        and newest_date is not None
        and summary_date >= newest_date
    ):
        # The newest committed session has no working sets; report it honestly.
        session = {
            "date": str(latest.get("session_date", newest["date"])),
            "day": str(latest.get("split_name") or "not set"),
            "exercises": [], "no_working_sets": True,
            **_history_summary_extras(latest, str(latest.get("session_id"))),
        }
        return {**base, "status": "ok", "sessions": [session], "next_offset": None}
    session = dict(newest)
    comparison = _history_comparison_by_id(ledger, newest_id)
    session["exercises"] = [
        {
            **exercise,
            **({"vs_previous": comparison[exercise["id"]]} if exercise["id"] in comparison else {}),
        }
        for exercise in session["exercises"]
    ]
    session.update(_history_summary_extras(latest, newest_id))
    paged = _history_page(base, [session], args.model_copy(update={"offset": 0}))
    return paged


def _read_workout_history(
    ledger: Any, args: WorkoutHistoryArgs | None = None, store: Any = None
) -> dict[str, Any]:
    args = args or WorkoutHistoryArgs()
    today = player_local_date(ledger, ledger.ledger_id)
    base = {"today": today.isoformat(), "scope": args.scope}
    grouped = _group_history_sessions(ledger.get_session_log())
    if not grouped:
        return {
            **base, "status": "no_sessions",
            "message": "No sessions logged.", "sessions": [], "next_offset": None,
        }
    if args.scope == "exercise":
        return _history_exercise_scope(base, store, args, grouped)
    if args.scope == "date":
        return _history_date_scope(base, args, grouped)
    if args.scope == "last_session":
        return _history_last_session(base, ledger, args, grouped)
    return _history_page(
        base, [session for _session_id, session in grouped], args
    )


def _program_muscle_groups(muscle: str | None) -> list[str]:
    group = normalize_main_muscle(muscle)
    return [group] if group else []


def _program_exercise_credits(
    ledger: Any, exercise_ids: list[str], targets, metadata
):
    reader = getattr(ledger, "volume_review_exercise_credits", None)
    if callable(reader):
        return reader(exercise_ids)
    return {
        exercise_id: {
            group: {"credit": credit, "is_primary": credit == 1.0, "source": "default"}
            for group, credit in default_muscle_credits(
                targets.get(exercise_id),
                metadata.get(exercise_id, {}).get("secondary_muscles", ()),
                exercise_name=metadata.get(exercise_id, {}).get("exercise_name"),
            ).items()
        }
        for exercise_id in exercise_ids
    }


def _program_exercise_matches(exercise: Any, muscles: Sequence[str], args: ActiveProgramArgs) -> bool:
    if args.exercise_name and exercise.exercise_name.casefold() != args.exercise_name.strip().casefold():
        return False
    if args.exercise_id and str(exercise.exercise_id) != args.exercise_id:
        return False
    if args.muscle:
        selected = args.muscle.strip().casefold()
        if selected == "back":
            return False
        selected_group = normalize_main_muscle(selected)
        return any(
            (selected_group is None and selected == str(muscle or "").strip().casefold())
            or bool(selected_group and selected_group in _program_muscle_groups(muscle))
            for muscle in muscles
        )
    return True


def _program_exercise_secondary_groups(metadata: dict[str, Any]) -> list[str]:
    return sorted(
        {
            group
            for helper_muscle in (metadata.get("secondary_muscles") or ())
            if (group := normalize_main_muscle(helper_muscle))
        }
    )


def _program_exercise_prescription(
    exercise: Any, muscle: str | None, metadata: dict[str, Any]
) -> dict[str, Any]:
    from agent.ProgramState import program_exercise_working_sets

    sets = program_exercise_working_sets(exercise)
    rir = 10 - float(exercise.target_rpe)
    secondary_groups = _program_exercise_secondary_groups(metadata)
    row = {
        "name": exercise.exercise_name, "sets": sets,
        "reps_min": exercise.target_reps_min, "reps_max": exercise.target_reps_max,
        "rir": rir,
        "muscle": _program_exercise_muscle_label(muscle),
        "rest_seconds": exercise.rest_seconds if exercise.rest_seconds is not None else "not set",
        "secondary_muscles": secondary_groups,
        "movement_pattern": metadata.get("movement_pattern"),
    }
    set_group_details = _program_exercise_set_group_details(exercise, sets, rir)
    if set_group_details is not None:
        row["set_groups"] = set_group_details
    return row


def _program_exercise_muscle_label(muscle: str | None) -> str:
    source_label = str(muscle or "").strip()
    group = normalize_main_muscle(source_label)
    if not group:
        return "not set"
    return source_label if source_label.casefold() == group else group


def _program_exercise_set_group_details(
    exercise: Any, sets: int, rir: float
) -> list[dict[str, Any]] | None:
    set_groups = exercise.set_groups or ()
    flat_prescription = (
        sets, exercise.target_reps_min, exercise.target_reps_max, rir,
        getattr(exercise, "load", None), False,
    )
    if not set_groups or not any(
        (
            group.sets, group.reps_min, group.reps_max, group.target_rir,
            group.load, group.amrap_last_set,
        ) != flat_prescription
        for group in set_groups
    ):
        return None
    return [
        {
            "sets": group.sets, "reps_min": group.reps_min,
            "reps_max": group.reps_max, "rir": group.target_rir,
            **({"load": group.load.model_dump()} if group.load else {}),
            **({"amrap_last_set": True} if group.amrap_last_set else {}),
        }
        for group in set_groups
    ]


def _program_restriction_skips(program: Any, days: Sequence[Any]) -> dict[str, list[str]]:
    # Repeated skips across days/weeks must not crowd the overview out of the cap.
    selected_days = {(getattr(day, "week_order", 1), day.day_order) for day in days}
    slots_by_restriction: dict[str, list[str]] = {}
    for day in (program.program_rationale or {}).get("days", []):
        if (day.get("week_order", 1), day.get("day_order")) not in selected_days:
            continue
        for skipped in day.get("skipped", []):
            slots = slots_by_restriction.setdefault(skipped["restriction"], [])
            if skipped["slot"] not in slots:
                slots.append(skipped["slot"])
    return slots_by_restriction


def _program_volume_context(ledger: Any) -> dict[str, Any]:
    from service.dashboard import volume_attribution

    return {
        "logged_volume_7d": volume_attribution(None, ledger.ledger_id, 7, ledger),
        "how_mayos_counts": {
            "en": "Working sets use 12 main muscle groups. Lats means latissimus dorsi; traps includes upper, mid and lower trapezius plus rhomboids and upper/mid back. Each exercise has per-muscle credits: default 1 for its primary group and 0.5 for each distinct helper group; reviewed credits replace those defaults. A generic source label of back is ambiguous and uncounted unless a specific target resolves it. Warm-ups and unlisted muscles are excluded.",
            "ar": "تُحسب المجموعات العاملة ضمن 12 مجموعة عضلية رئيسية. اللاتس (الظهر العريض) هي العضلة الظهرية العريضة، والترابيس تشمل ألياف الترابيس العلوية والوسطى والسفلية والعضلات المعينية ومنتصف وأعلى الظهر. لكل تمرين رصيد: 1 للعضلة الأساسية و0.5 لكل عضلة مساعدة مختلفة؛ وتحل الأرصدة المراجعة محل الافتراضات. وصف المصدر العام «ظهر» غير محدد ولا يُحسب إلا إذا أوضحت العضلة المستهدفة ذلك. لا تُحسب مجموعات الإحماء أو العضلات غير المدرجة.",
        },
    }


def _weekly_program_volume(direct: dict[str, float], indirect: dict[str, float]) -> dict[str, Any]:
    return {
        muscle: {
            "direct": round(direct.get(muscle, 0), 2),
            "indirect": round(indirect.get(muscle, 0), 2),
            "total": round(direct.get(muscle, 0) + indirect.get(muscle, 0), 2),
        }
        for muscle in MAIN_MUSCLE_GROUPS
    }


def _program_prescription_page(response: dict[str, Any], offset: int) -> dict[str, Any]:
    # Empty / exact fit / multi-page / oversized single row: never split a prescription.
    rows = [(day, exercise) for day in response["days"] for exercise in day["exercises"]]
    page = {**response, "days": [], "next_offset": None}
    for index in range(offset, len(rows)):
        day, exercise = rows[index]
        if not page["days"] or page["days"][-1]["day"] != day["day"]:
            page["days"].append({**day, "exercises": []})
        page["days"][-1]["exercises"].append(exercise)
        page["next_offset"] = index + 1 if index + 1 < len(rows) else None
        encoded = json.dumps(page, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
            page["days"][-1]["exercises"].pop()
            if not page["days"][-1]["exercises"]:
                page["days"].pop()
            if not page["days"]:
                return {"status": "truncated", "message": "Prescription exceeds result cap.",
                        "message_ar": "تفاصيل التمرين تتجاوز حد النتيجة."}
            page["next_offset"] = index
            return page
    return page


def _read_active_program(ledger: Any, args: ActiveProgramArgs | None = None, store: Any = None, player_account_id: str | None = None) -> dict[str, Any]:
    program = ledger.get_active_program()
    volume_context = _program_volume_context(ledger)
    if program is None:
        return {"status": "not_set", "active_program": "not set", "program_authority": "player", **volume_context}
    authority = "player"
    coach_name = None
    if store is not None and player_account_id:
        assignment = store.get_active_assignment_for_player(player_account_id)
        from service.programs import coach_controls_program
        if coach_controls_program(assignment, program):
            authority = "coach"
            coach = store.get_account(assignment["coach_account_id"])
            if coach:
                from service.assignments import coach_identity

                coach_name = coach_identity(
                    store, assignment["coach_account_id"], coach
                )["display_name"]
    from agent.ProgramState import program_exercise_working_sets

    all_days = list(getattr(program, "days", ()) or ())
    args = args or ActiveProgramArgs()
    selected_week = args.week_order
    if selected_week is None:
        position_getter = getattr(ledger, "get_program_position", None)
        if callable(position_getter):
            position = position_getter(program)
            selected_week = int(getattr(position, "current_week", 1))
        else:
            selected_week = 1
    all_days = sorted(
        (day for day in all_days if int(getattr(day, "week_order", 1)) == selected_week),
        key=lambda day: day.day_order,
    )
    selected_name = args.day_name.strip().casefold() if args.day_name else None
    if selected_name:
        matching = [day for day in all_days if str(getattr(day, "day_name", "")).casefold() == selected_name]
        if not matching:
            return {"status": "not_found", "day_names": [str(getattr(day, "day_name", "not set")) for day in all_days]}
        all_days = matching
    detailed_scope = bool(selected_name or args.exercise_name or args.exercise_id or args.muscle)
    exercise_ids = sorted({
        str(getattr(exercise, "exercise_id", ""))
        for day in all_days for exercise in (getattr(day, "exercises", ()) or ())
        if getattr(exercise, "exercise_id", None)
    })
    targets = ledger.volume_review_exercise_targets(exercise_ids)
    metadata = ledger.program_exercise_metadata(exercise_ids)
    exercise_names = {
        str(exercise.exercise_id): str(exercise.exercise_name)
        for day in all_days for exercise in (getattr(day, "exercises", ()) or ())
        if getattr(exercise, "exercise_id", None)
    }
    metadata = {
        exercise_id: {
            **metadata.get(exercise_id, {}),
            "exercise_name": exercise_names.get(exercise_id),
        }
        for exercise_id in exercise_ids
    }
    summary: dict[str, float] = {muscle: 0.0 for muscle in MAIN_MUSCLE_GROUPS}
    indirect: dict[str, float] = {}
    credits_by_exercise = _program_exercise_credits(
        ledger, exercise_ids, targets, metadata
    )
    days = []
    for day in all_days:
        exercises = []
        day_muscles = []
        for exercise in getattr(day, "exercises", ()) or ():
            sets = program_exercise_working_sets(exercise)
            muscle = targets.get(str(getattr(exercise, "exercise_id", "")))
            exercise_metadata = metadata.get(str(exercise.exercise_id), {"secondary_muscles": [], "movement_pattern": None})
            secondaries = exercise_metadata["secondary_muscles"]
            exercise_credits = credits_by_exercise.get(str(exercise.exercise_id), {})
            credited_groups = [
                group for group, item in exercise_credits.items()
                if float(item["credit"]) > 0
            ]
            if not _program_exercise_matches(
                exercise, [muscle or "", *secondaries, *credited_groups], args
            ):
                continue
            matching_groups = sorted(
                credited_groups
            )
            for group, item in exercise_credits.items():
                credit = float(item["credit"])
                if credit <= 0:
                    continue
                if item["is_primary"]:
                    summary[group] += sets * credit
                else:
                    indirect[group] = indirect.get(group, 0.0) + sets * credit
            if detailed_scope:
                exercises.append(_program_exercise_prescription(exercise, muscle, exercise_metadata))
            for group in matching_groups:
                if group not in day_muscles:
                    day_muscles.append(group)
        if detailed_scope and not exercises:
            continue
        day_name = str(getattr(day, "day_name", "not set"))
        days.append(
            {"day": day_name, "week_order": selected_week, "exercises": exercises}
            if detailed_scope else {
                "day": day_name, "muscles": day_muscles,
            }
        )
    response = {
        "status": "ok", "f": getattr(program, "weekly_frequency", "not set"),
        "split": _not_set(getattr(program, "split_type", None)),
        "week_order": selected_week, "days": days,
        "movement_restrictions": _player_profile(ledger).get("movement_restrictions", []),
        "skipped_restricted_slots": _program_restriction_skips(program, all_days),
        "program_authority": authority,
        **volume_context,
        **({"coach": coach_name} if coach_name else {}),
        **({} if detailed_scope else {
            "weekly_sets_by_muscle": {muscle: round(sets, 2) for muscle, sets in summary.items()},
            "weekly_volume_by_muscle": _weekly_program_volume(summary, indirect),
            "message": "weekly_sets_by_muscle gives direct sets; weekly_volume_by_muscle gives weighted direct, indirect and total sets. Sub-regions map to one main group. Scope by day_name, exercise_name/exercise_id or muscle for prescriptions.",
        }),
    }
    return _program_prescription_page(response, args.offset) if detailed_scope else response


def _read_program_rationale(ledger: Any, args: ProgramRationaleArgs) -> dict[str, Any]:
    program = ledger.get_active_program()
    if program is None:
        return {"status": "not_set", "reason_available": False, "source": "none"}
    from agent.program_rationale_reader import read_program_rationale
    return read_program_rationale(program, args)


PLAYER_READ_TOOL_REGISTRY: tuple[PlayerReadTool, ...] = (
    PlayerReadTool(
        name="get_player_profile",
        description=(
            "Read only requested Profile sections. No sections: names only. "
            "Limitations includes injuries, Exercise clearances and Movement restrictions. "
            "Empty fields: 'not set'."
        ),
        args_schema=ProfileArgs,
        reader=_read_profile,
        args_reader=_read_profile,
        status_en="Checking your profile…",
        status_ar="ببص على بياناتك…",
    ),
    PlayerReadTool(
        name="get_active_program",
        description=(
            "Read active Program overview: ordered days and muscles, weekly sets, authority and "
            "restriction skips; no prescriptions. Defaults to current week; week_order selects another. "
            "Scope day_name, exercise_name/exercise_id or muscle for matching prescriptions only. "
            "Rows include canonical secondary_muscles group labels and movement_pattern. "
            "weekly_sets_by_muscle gives direct sets by main group; weekly_volume_by_muscle gives planned weighted direct/indirect/total sets for the 12 main muscle groups; logged_volume_7d "
            "gives Home weighted sets, even without a program. how_mayos_counts explains attribution. "
            "Muscle matches primary or secondary muscles and maps sub-regions to one main group. "
            "For next_offset, repeat the same scope with offset to read remaining complete prescriptions."
        ),
        args_schema=ActiveProgramArgs,
        reader=_read_active_program,
        args_reader=lambda ledger, args: _read_active_program(ledger, args),
        status_en="Checking your Training program…",
        status_ar="ببص على برنامجك التدريبي…",
    ),
    PlayerReadTool(
        name="get_program_rationale",
        description=(
            "Read recorded reasons for the active Training program. Use this for every why-question "
            "about the Split, day order, exercises, skipped restricted slots or prescriptions. Scope by day_name/day_order or "
            "exercise_name/exercise_id and week_order; use page/next_page to read large results. "
            "For Focus status 'covered', explain the already-at-target reason using its English or Arabic message for the reply language. "
            "If reason_available is false, no recorded generator reason exists."
        ),
        args_schema=ProgramRationaleArgs,
        reader=lambda ledger, args=None: _read_program_rationale(ledger, args or ProgramRationaleArgs()),
        args_reader=lambda ledger, args: _read_program_rationale(ledger, args),
        status_en="Checking why your program is arranged this way…",
        status_ar="ببص على أسباب ترتيب برنامجك…",
    ),
    PlayerReadTool(
        name="get_player_weight_trend",
        description=(
            "Read the current player's dated body-weight trend and computed changes. Use this "
            "before answering questions about weight changes or progress toward a target weight."
        ),
        args_schema=EmptyToolArgs,
        reader=_read_weight_trend,
        status_en="Checking your weight trend…",
        status_ar="ببص على تغيّر وزنك…",
    ),
    PlayerReadTool(
        name="get_player_nutrition_trend",
        description=(
            "Read the current player's recent Player-local daily Food log totals and the "
            "matching saved calorie and Macro targets, up to the last 14 days. Unlogged "
            "days have null totals; status no_data means no foods are logged in the range. "
            "Days without saved targets have null targets. No food names or entry details "
            "are returned. Read-only."
        ),
        args_schema=NutritionTrendArgs,
        reader=lambda ledger: _read_player_nutrition_trend(ledger, NutritionTrendArgs()),
        args_reader=_read_player_nutrition_trend,
        status_en="Checking your recent Nutrition trend…",
        status_ar="ببص على اتجاه التغذية بتاعك مؤخرًا…",
    ),
    PlayerReadTool(
        name="get_player_cardio",
        description=(
            "Read the current player's own logged Cardio sessions from the requested 1–14 "
            "Player-local days (default 14). Set day to today, yesterday or YYYY-MM-DD "
            "for only that recent day; day overrides days. Includes machine, minutes, recorded settings, saved "
            "per-entry kcal estimates and per-session kcal totals. "
            "A session total is null if any Cardio entry has no saved kcal value. "
            "Returns exact minutes and session totals for the requested window, plus "
            "this Saturday-to-Friday week and rolling 7/14-day totals when fully covered. "
            "status no_data means no Cardio was logged in that window. If next_offset "
            "is set, repeat with the same day/days and that offset. status truncated with "
            "next_offset null is terminal: a session exceeds the result cap; never claim "
            "its omitted entries were returned. Window totals remain complete. Read-only."
        ),
        args_schema=CardioArgs,
        reader=lambda ledger: _read_player_cardio(ledger, CardioArgs()),
        args_reader=_read_player_cardio,
        status_en="Checking your recent Cardio log…",
        status_ar="ببص على سجل الكارديو بتاعك مؤخرًا…",
    ),
    PlayerReadTool(
        name="get_player_nutrition",
        description=(
            "With day (today, yesterday or YYYY-MM-DD) or days (1–14 inclusive through today), "
            "read only that recent period's saved daily Nutrition targets; absent targets are null. "
            "Choose day or days, not both. Without either period argument: "
            "Read the current player's active Nutrition targets, author, Nutrition goal, pace, "
            "last-14-day adherence counts, and today's Cardio calories and calorie adjustment. "
            "Includes today's planned meals for the current day_type, not a Food log. Use "
            "get_player_food_log for logged foods and get_player_nutrition_trend for recent "
            "daily intake against targets. "
            "If next_offset is set, call again with that food offset for the remaining meals. "
            "For meal questions, use only the returned foods and grams; never invent a Coach's reason "
            "or claim allergy safety without restriction data. "
            "Read-only: explain meals and suggest which food to swap; never change the Nutrition plan "
            "or claim a swap was made. Direct swaps to the food's swap action in Nutrition; "
            "Coach-authored plans need a Food swap request. Direct target changes to Nutrition."
        ),
        args_schema=PlayerNutritionArgs,
        reader=lambda ledger: _read_player_nutrition(ledger, PlayerNutritionArgs()),
        args_reader=_read_player_nutrition,
        status_en="Checking your Nutrition targets…",
        status_ar="ببص على أهداف التغذية بتاعتك…",
    ),
    PlayerReadTool(
        name="get_player_food_log",
        description=(
            "Read what the current player ate on one Player-local day and its whole-day "
            "calorie and Macro totals and saved targets for that day. day defaults to today; "
            "accepts today, yesterday, or YYYY-MM-DD within the last 14 days including today. "
            "Personal food names "
            "are the player's own data. Null nutrients are unknown and count as zero in "
            "totals. entry_count 0 means no foods are logged for that day; null targets "
            "mean no saved Nutrition target is available for that date. Names longer "
            "than 200 characters are marked truncated. "
            "If next_offset is set, call again with that offset and the returned "
            "date to read remaining entries; totals always cover the whole day. Read-only."
        ),
        args_schema=FoodLogArgs,
        reader=lambda ledger: _read_player_food_log(ledger, FoodLogArgs()),
        args_reader=_read_player_food_log,
        status_en="Checking your Food log…",
        status_ar="ببص على سجل الطعام بتاعك…",
    ),
    PlayerReadTool(
        name="get_workout_history",
        description=(
            "Read the current player's committed workout history. scope last_session: the newest "
            "session with date, Training-day name, per-exercise sets as weight (kg) × reps, "
            "RIR/RPE when rated, and vs_previous deltas against the previous session. scope date: "
            "sessions on one Player-local date (today, yesterday or YYYY-MM-DD). scope exercise: "
            "the named exercise's most recent sessions (any language). scope recent_sessions: the "
            "newest sessions; limit 1-10 (default 3). offset pages older sessions with the same "
            "args. no_sessions, not_logged or unknown_exercise means nothing is logged; never "
            "invent figures."
        ),
        args_schema=WorkoutHistoryArgs,
        reader=_read_workout_history,
        args_reader=_read_workout_history,
        status_en="Checking your workout history…",
        status_ar="ببص على سجل تمرينك…",
    ),
    PlayerReadTool(
        name="get_assistant_preferences",
        description=(
            "Read preferences the current player explicitly asked the assistant to remember. "
            "Use when answering how the player likes to train. Do not infer or write preferences."
        ),
        args_schema=EmptyToolArgs,
        reader=_read_assistant_preferences,
        status_en="Checking your saved preferences…",
        status_ar="ببص على تفضيلاتك المحفوظة…",
    ),
    PlayerReadTool(
        name="search_chat_history",
        description=(
            "Search the current player's own older chat messages by English or Arabic keywords. "
            "Use when the player refers to something from an older conversation that is outside "
            "the recent chat window. start_date and end_date are inclusive UTC dates in YYYY-MM-DD "
            "format. limit is 1 to 10. Recent-window messages and session-pointer debriefs are "
            "excluded. A no_matches status means nothing older matched."
        ),
        args_schema=ChatHistorySearchArgs,
        reader=_read_chat_history_search,
        args_reader=_read_chat_history_search,
        status_en="Searching your older chats…",
        status_ar="بدور في محادثاتك القديمة…",
    ),
)


def _encode_tool_result(tool_result: Any) -> str:
    rendered = tool_result if isinstance(tool_result, str) else json.dumps(
        tool_result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(rendered.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
        return rendered
    if isinstance(tool_result, dict) and "weekly_sets_by_muscle" in tool_result:
        compact_days = dict(tool_result)
        compact_days.pop("message", None)
        compact_days_rendered = json.dumps(
            compact_days, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        if len(compact_days_rendered.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
            return compact_days_rendered
        compact = {
            "status": "summary_only",
            "program_authority": tool_result.get("program_authority", "player"),
            **({"coach": tool_result["coach"]} if tool_result.get("coach") else {}),
            "weekly_sets_by_muscle": tool_result["weekly_sets_by_muscle"],
            **{key: tool_result[key] for key in ("weekly_volume_by_muscle", "logged_volume_7d", "how_mayos_counts") if key in tool_result},
            "message": "Scope by day_name, exercise_name/exercise_id or muscle for prescriptions.",
        }
        compact_rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(compact_rendered.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
            return compact_rendered
    # Keep the tool message valid JSON and bounded. The assistant can explain
    # that this result was too large and ask the player to narrow the question.
    return json.dumps(
        {
            "status": "truncated",
            "message": "The result exceeded the 4 KB limit; ask a narrower question.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _unavailable_result() -> str:
    return '{"status":"unavailable"}'


def cap_tool_results_for_prompt(
    prompt_messages: Sequence[Any], tool_messages: Sequence[ToolMessage]
) -> list[ToolMessage]:
    """Keeps this round's results within the prompt ceiling and reserves later-round room."""
    prompt_bytes = sum(
        len(str(message.content).encode("utf-8")) for message in prompt_messages
    )
    result_budget = HOSTED_PROMPT_MAX_BYTES - HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES
    capped_messages = []
    for message in tool_messages:
        content = str(message.content)
        content_bytes = len(content.encode("utf-8"))
        if prompt_bytes + content_bytes > result_budget:
            content = _TRUNCATED_PROMPT_RESULT
            content_bytes = len(content.encode("utf-8"))
        if prompt_bytes + content_bytes > HOSTED_PROMPT_MAX_BYTES:
            content = "{}"
            content_bytes = len(content.encode("utf-8"))
        if prompt_bytes + content_bytes > HOSTED_PROMPT_MAX_BYTES:
            content = ""
            content_bytes = 0
        capped_messages.append(message.model_copy(update={"content": content}))
        prompt_bytes += content_bytes
    return capped_messages


def build_player_read_tools(ledger: Any, store: Any = None, player_account_id: str | None = None) -> tuple[list[StructuredTool], dict[str, PlayerReadTool]]:
    """Builds this turn's tools; their readers close over only its own ledger."""
    tools: list[StructuredTool] = []
    recent_window_size = player_prompt_history_settings().window_size
    definitions = {definition.name: definition for definition in PLAYER_READ_TOOL_REGISTRY}
    for definition in PLAYER_READ_TOOL_REGISTRY:
        if definition.args_reader is not None:
            def reader(_definition=definition, **kwargs: Any) -> str:
                args = _definition.args_schema(**kwargs)
                if _definition.name == "get_active_program":
                    return _encode_tool_result(_read_active_program(ledger, args, store, player_account_id))
                if _definition.name == "search_chat_history":
                    return _encode_tool_result(
                        _read_chat_history_search(
                            ledger, args, recent_window_size=recent_window_size
                        )
                    )
                if _definition.name == "get_workout_history":
                    return _encode_tool_result(_read_workout_history(ledger, args, store))
                return _encode_tool_result(_definition.args_reader(ledger, args))
        else:
            def reader(_definition=definition) -> str:
                return _encode_tool_result(_definition.reader(ledger))

        tools.append(
            StructuredTool.from_function(
                func=reader,
                name=definition.name,
                description=definition.description,
                args_schema=definition.args_schema,
            )
        )
    return tools, definitions


def run_player_tool_calls(
    tool_calls: Sequence[dict[str, Any]],
    *,
    tools: Sequence[StructuredTool],
    definitions: dict[str, PlayerReadTool],
    language: str,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[list[ToolMessage], list[tuple[str, float]]]:
    """Runs one tool round in order; reader failures become unavailable results."""
    tools_by_name = {tool.name: tool for tool in tools}
    futures = []
    started_at = []
    names = []
    # Readers share one ledger connection, and sqlite3 rows race across threads on it.
    # One worker keeps each timeout without two reads meeting on that connection.
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        for index, call in enumerate(tool_calls):
            name = str(call.get("name", ""))
            definition = definitions.get(name)
            tool = tools_by_name.get(name)
            tool_call_id = str(call.get("id") or f"tool-call-{index + 1}")
            names.append((name, definition, tool_call_id))
            if definition is None or tool is None:
                futures.append(None)
                started_at.append(time.perf_counter())
                continue
            if status_callback is not None:
                status_callback(definition.status_ar if language == "ar" else definition.status_en)
            args = call.get("args")
            args = args if isinstance(args, dict) else {}
            started_at.append(time.perf_counter())
            futures.append(executor.submit(tool.invoke, args))

        messages: list[ToolMessage] = []
        telemetry: list[tuple[str, float]] = []
        for (name, definition, call_id), future, started in zip(names, futures, started_at):
            elapsed_ms = 0.0
            if definition is None or future is None:
                tool_result = _unavailable_result()
            else:
                try:
                    remaining_seconds = max(
                        0.0,
                        definition.timeout_seconds - (time.perf_counter() - started),
                    )
                    tool_result = str(future.result(timeout=remaining_seconds))
                except TimeoutError:
                    tool_result = _unavailable_result()
                except Exception as error:
                    logger.warning(
                        "Player read tool %s failed (%s); returning unavailable",
                        name,
                        type(error).__name__,
                    )
                    tool_result = _unavailable_result()
                elapsed_ms = (time.perf_counter() - started) * 1000.0
            if len(tool_result.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
                tool_result = _encode_tool_result(tool_result)
            messages.append(
                ToolMessage(content=tool_result, tool_call_id=call_id, name=name or "unavailable")
            )
            if definition is not None:
                telemetry.append((name, elapsed_ms))
        return messages, telemetry
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
