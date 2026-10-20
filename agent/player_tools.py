"""Read-only, turn-scoped tools for the player assistant."""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from database.ledger.profile import PLAYER_PROFILE_STORAGE_DEFAULTS
from service.injuries import render_public_injury_record
from service.player_weight_context import render_player_weight_context
from service.weight_history import WeightTrendQuery, get_weight_trend, player_local_date
from agent.player_prompt import (
    HOSTED_PROMPT_MAX_BYTES,
    HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES,
)

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_BYTES = 4 * 1024
TOOL_TIMEOUT_SECONDS = 5.0
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


@dataclass(frozen=True)
class PlayerReadTool:
    """A reusable entry in the player read-tool registry."""

    name: str
    description: str
    args_schema: type[BaseModel]
    reader: Callable[[Any], dict[str, Any]]
    status_en: str
    status_ar: str
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


_PROFILE_FIELDS = (
    ("gender", "gender"),
    ("proportions", "proportions"),
    ("age", "age"),
    ("height_cm", "height_cm"),
    ("weight_kg", "weight_kg"),
    ("target_weight_kg", "target_weight_kg"),
    ("current_goal", "current_goal"),
    ("long_term_goal", "long_term_goal"),
    ("training_age_years", "training_age_years"),
    ("rep_preference", "rep_preference"),
    ("equipment_access", "equipment_access"),
    # Backward-compatible projection maintained by the injury-record writer.
    ("injuries_or_limitations", "injuries_or_limitations"),
    ("weekly_frequency", "weekly_frequency"),
    ("stress_and_sleep", "stress_and_sleep"),
)


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


def _read_profile(ledger: Any) -> dict[str, Any]:
    profile = ledger.get_player_profile() or {}
    answers = ledger.load_intake_answers()
    onboarding_completed = _profile_has_completion_evidence(ledger)
    profile_fields = {}
    for label, key in _PROFILE_FIELDS:
        if key in answers:
            answer = answers[key]
            value = answer.get("value")
            if (
                answer.get("prefilled")
                and not onboarding_completed
                and _is_storage_default(key, value)
            ):
                value = None
        else:
            value = profile.get(key)
            if not onboarding_completed and _is_storage_default(key, value):
                value = None
        profile_fields[label] = _not_set(value)
    return {
        "status": "ok",
        "profile": profile_fields,
    }


def _read_weight_trend(ledger: Any) -> dict[str, Any]:
    ledger_id = ledger.ledger_id
    as_of = player_local_date(ledger, ledger_id)
    trend = get_weight_trend(
        None,
        WeightTrendQuery(ledger_id=ledger_id, weeks=8, as_of=as_of),
        ledger=ledger,
    )
    profile = ledger.get_player_profile() or {}
    return {
        "status": "ok",
        "weight_context": render_player_weight_context(
            trend, profile.get("target_weight_kg"), as_of=as_of
        ),
    }


def _read_player_injuries(ledger: Any) -> dict[str, Any]:
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
    return {"status": "ok", "injuries": records}


def _read_assistant_preferences(ledger: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "preferences": [
            preference["text"] for preference in ledger.list_assistant_preferences()
        ],
    }


def _read_active_program(ledger: Any) -> dict[str, Any]:
    program = ledger.get_active_program()
    if program is None:
        return {"status": "not_set", "active_program": "not set"}

    days = []
    for day in getattr(program, "days", ()) or ():
        exercises = []
        for exercise in getattr(day, "exercises", ()) or ():
            raw_rpe = getattr(exercise, "target_rpe", None)
            try:
                rir = 10 - float(raw_rpe) if raw_rpe is not None else "not set"
            except (TypeError, ValueError):
                rir = "not set"
            exercises.append(
                {
                    "name": str(getattr(exercise, "exercise_name", "not set")),
                    "sets": getattr(exercise, "working_sets", getattr(exercise, "target_sets", "not set")),
                    "reps_min": getattr(exercise, "target_reps_min", "not set"),
                    "reps_max": getattr(exercise, "target_reps_max", "not set"),
                    "rir": rir,
                    "set_groups": [
                        {"sets": group.sets, "reps_min": group.reps_min,
                         "reps_max": group.reps_max, "rir": group.target_rir}
                        for group in getattr(exercise, "set_groups", ()) or ()
                    ],
                    "rest_seconds": getattr(exercise, "rest_seconds", "not set"),
                }
            )
        days.append(
            {
                "day": str(getattr(day, "day_name", "not set")),
                "exercises": exercises,
            }
        )
    return {
        "status": "ok",
        "weekly_frequency": getattr(program, "weekly_frequency", "not set"),
        "split_type": _not_set(getattr(program, "split_type", None)),
        "days": days,
    }


PLAYER_READ_TOOL_REGISTRY: tuple[PlayerReadTool, ...] = (
    PlayerReadTool(
        name="get_player_profile",
        description=(
            "Read the current player's saved profile facts. Use this before answering "
            "questions about the player's own profile. Empty fields are returned as 'not set'."
        ),
        args_schema=EmptyToolArgs,
        reader=_read_profile,
        status_en="Checking your profile…",
        status_ar="ببص على بياناتك…",
    ),
    PlayerReadTool(
        name="get_active_program",
        description=(
            "Read the current player's active Training program, including its training days "
            "and prescribed exercises. Use this before answering questions about the program."
        ),
        args_schema=EmptyToolArgs,
        reader=_read_active_program,
        status_en="Checking your Training program…",
        status_ar="ببص على برنامجك التدريبي…",
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
        name="get_player_injuries",
        description=(
            "Read the current player's injury records, body areas, descriptions, and statuses. "
            "Use this before answering questions about injuries or physician follow-up."
        ),
        args_schema=EmptyToolArgs,
        reader=_read_player_injuries,
        status_en="Checking your injury records…",
        status_ar="ببص على سجلات إصاباتك…",
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
)


def _encode_tool_result(tool_result: Any) -> str:
    rendered = tool_result if isinstance(tool_result, str) else json.dumps(
        tool_result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(rendered.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
        return rendered
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


def build_player_read_tools(ledger: Any) -> tuple[list[StructuredTool], dict[str, PlayerReadTool]]:
    """Builds this turn's tools; their readers close over only its own ledger."""
    tools: list[StructuredTool] = []
    definitions = {definition.name: definition for definition in PLAYER_READ_TOOL_REGISTRY}
    for definition in PLAYER_READ_TOOL_REGISTRY:
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
    """Runs one parallel tool round; reader failures become unavailable results."""
    tools_by_name = {tool.name: tool for tool in tools}
    futures = []
    started_at = []
    names = []
    executor = ThreadPoolExecutor(max_workers=max(1, min(len(tool_calls), 4)))
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
                except Exception:
                    logger.warning("Player read tool %s failed; returning unavailable", name)
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
