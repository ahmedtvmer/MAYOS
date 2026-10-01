"""Optional coach AI analysis of one selected player (issue #45, ADR 016/038/049).

The feature is off unless ``COACH_AI_ENABLED`` is truthy **and** a recorded
evaluation report (``COACH_AI_EVAL_REPORT``) proves both gates passed for the
current prompt version, against the currently configured coach model. See
:func:`resolve_enable_gate` and :func:`validate_report`.

Privacy boundary (ADR 016):

* The model receives only :func:`render_context` output for the selected
  player — deterministic figures computed here in Python — plus the coach's own
  question and the client-held transcript turns. Never the player's username,
  account ids, recovery email, coach name/bio, player-assistant chat,
  check-in note text, or program-request reasons.
* The service persists **nothing** about an exchange: no transcript table, no
  logging of question/answer content. Only the ADR 038 model-usage metering
  rows are written, attributed to the coach's account with role ``coach``.
* The client holds the transcript in memory for one selected player and clears
  it on player switch, revocation, logout, and app close (the Flutter half of
  that rule is a separate ticket).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.effort import min_rir_label, rir_label
from service import coach_history as coach_history_service
from service import dashboard as dashboard_service
from service import check_ins as check_ins_service
from service import program_requests as program_requests_service
from service import evaluation_report_gate
from service.evaluation_report_gate import EvaluationReportConfig, GateStatus, evaluate_gate
from service.assignments import authorized_player_ledger
from service.missed_day_alerts import (
    ALERT_STATES,
    evaluate_ledger_attendance,
    list_alerts as list_coach_alerts,
)

logger = logging.getLogger(__name__)

#: Bumped whenever the prompt or the context shape changes; the eval report's
#: ``prompt_hash`` must match :func:`prompt_version_hash` for the flag to enable.
CONTEXT_VERSION = "coach-context-v3"

#: Schema version of the enablement report; a report written by another
#: runner version is refused (ADR 049).
REPORT_VERSION = 1

SYSTEM_PROMPT = """You are the analysis assistant inside the MAYOS coach console.
You answer one assigned coach's question about ONE selected player, using only the
[PLAYER TELEMETRY] block supplied with the request.

Rules:
- Use the supplied figures exactly as given. Never compute, estimate, or invent
  numbers. Do not derive figures from other figures, such as totals, percentages,
  ratios, averages, or differences. If the telemetry needed for the answer is not
  supplied, say so.
- Refer to the person only as "the player". You are not told who they are; never
  guess names, contact details, or account information.
- Give no medical advice: no diagnosis, no rehabilitation or medication advice.
  When a question needs a clinician, say so plainly.
- Never discuss the player's private chat with the MAYOS assistant; it is not
  supplied and must not be inferred.
- Answer under 120 words: specific, neutral, no pleasantries."""

#: Alert identity fields printed as the alert line prefix (ADR 049 allowlist).
_ALERT_HEAD_FIELDS = ("kind", "state")
#: Alert evidence the model may see; ids, usernames, and free text stay out.
_ALERT_EVIDENCE_FIELDS = (
    "created_at",
    "streak_start_date",
    "last_missed_date",
    "missed_count",
    "due_on",
    "last_check_in_on",
    "severity",
    "exercise_name",
    "status_badge",
    "e1rm_delta",
    "current_e1rm",
    "top_load",
    "top_reps",
    "top_rpe",
    "recent_readiness_avg",
    "volume_multiplier",
    "intensity_cap_rpe",
    "session_date",
    "latest_session_date",
)
#: What :func:`gather_player_context` keeps from an alert row.
_ALERT_KEPT_FIELDS = (*_ALERT_HEAD_FIELDS, *_ALERT_EVIDENCE_FIELDS)

#: Fixed fixture the prompt hash is measured over: any change to the renderer,
#: the field selection, or the message assembly moves ``prompt_version_hash()``
#: and so invalidates every recorded eval report (ADR 049).
CANONICAL_FIXTURE: dict[str, Any] = {
    "as_of": "2026-09-28",
    "assignment": {"started_on": "2026-09-01", "status": "active"},
    "program": {
        "name": "Hypertrophy Block A",
        "split": "Upper/Lower",
        "weekly_frequency": 4,
        "version": 3,
        "days": [
            {
                "order": 1,
                "day": "Upper A",
                "exercises": [{"name": "Bench Press", "sets": 3, "reps": "5-8", "rpe": 8.5}],
            }
        ],
    },
    "volume": {"last_7_days_kg": 12400.0, "last_28_days_kg": 48000.0},
    "recent_sessions": [
        {
            "session_date": "2026-09-26",
            "split_name": "Upper A",
            "sets_count": 18,
            "total_volume_kg": 12400.0,
            "readiness_score": 4,
            "program_version": 3,
            "divergences": [{"kind": "skipped", "exercise_name": "Row"}],
        }
    ],
    "recent_sessions_totals": {"sessions": 1, "sets": 18, "volume_kg": 12400.0},
    "personal_records": [
        {
            "exercise": "Squat",
            "record_type": "e1rm",
            "reps": 5,
            "value": 142.5,
            "prev_value": 138.0,
            "achieved_at": "2026-09-23",
        }
    ],
    "attendance": {
        "timezone": "Europe/Berlin",
        "local_today": "2026-09-28",
        "window_start": "2026-09-01",
        "expected_days": 12,
        "satisfied_days": 10,
        "missed_days": 2,
        "adherence_pct": 83.3,
        "trailing_missed_streak": 0,
        "last_missed_on": "2026-09-17",
    },
    "schedule": {"weekdays": [1, 3, 5], "timezone": "Europe/Berlin"},
    "pauses": [{"starts_on": "2026-10-01", "ends_on": "2026-10-07"}],
    "alerts": [
        {
            "kind": "missed_expected_days",
            "state": "new",
            "created_at": "2026-09-25T10:00:00+00:00",
            "streak_start_date": "2026-09-24",
            "missed_count": 2,
        }
    ],
    "check_ins": [{"checked_in_on": "2026-09-17", "channel": "phone"}],
    "program_requests": {"total": 1, "pending": 1, "pending_by_kind": {"exercise_substitution": 1}},
}
CANONICAL_QUESTION = "How has training been going this week?"
CANONICAL_HISTORY: list[dict[str, str]] = [
    {"role": "coach", "content": "Summarize the last four weeks."},
    {"role": "assistant", "content": "Ten of twelve expected days were satisfied."},
]


def canonical_messages_text() -> str:
    """The exact messages the canonical fixture produces, role-tagged."""
    messages = build_messages(render_context(CANONICAL_FIXTURE), CANONICAL_QUESTION, CANONICAL_HISTORY)
    return "\n".join(f"{type(message).__name__}: {getattr(message, 'content', message)}" for message in messages)


def prompt_version_hash() -> str:
    """SHA-256 over the version, the system prompt, and the canonical messages.

    Hashing the *rendered* canonical prompt (not just the prompt text) means a
    change to ``render_context``, the field selection, ``build_messages``, or
    ``_ALERT_*`` moves the hash and refuses an old report (ADR 049).
    """
    payload = f"{CONTEXT_VERSION}\n{SYSTEM_PROMPT}\n{canonical_messages_text()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Feature flag + enable gate (ADR 049)
# --------------------------------------------------------------------------


def coach_model_identity() -> tuple[str, str]:
    """``(model id, backend)`` the coach role resolves to right now (ADR 012)."""
    from utils import model_downloader

    return model_downloader.model_identity("coach")


_EVALUATION_REPORT_CONFIG = EvaluationReportConfig(
    enabled_flag="COACH_AI_ENABLED",
    report_env_var="COACH_AI_EVAL_REPORT",
    model_identity=coach_model_identity,
    prompt_hash=prompt_version_hash,
    report_version=REPORT_VERSION,
    suite_name="coach_assistant",
    model_label="coach",
    startup_label="Coach AI",
    missing_report_reason=(
        "COACH_AI_EVAL_REPORT is not set; a recorded passing privacy and evaluation report is required."
    ),
    evaluation_gate_name="coach evaluation gate",
)


def validate_report(report: Any) -> tuple[bool, list[str]]:
    """Validates a recorded Coach AI Evaluation report (ADR 049)."""
    return evaluation_report_gate.validate_report(report, _EVALUATION_REPORT_CONFIG)


def _validate_report_file(path: str) -> tuple[bool, str]:
    return evaluation_report_gate.validate_report_file(path, validate_report)


_report_cache = evaluation_report_gate._report_cache
_report_cache_lock = evaluation_report_gate._report_cache_lock
_REPORT_CACHE_LIMIT = evaluation_report_gate._REPORT_CACHE_LIMIT


def _report_passes(path: str) -> tuple[bool, str]:
    return evaluation_report_gate.report_passes(path, _EVALUATION_REPORT_CONFIG, _validate_report_file)


def resolve_enable_gate() -> GateStatus:
    """Evaluates the flag against the recorded report (no logging)."""
    return evaluation_report_gate.resolve_enable_gate(_EVALUATION_REPORT_CONFIG, _validate_report_file)


def log_enable_gate_at_startup() -> GateStatus:
    """Startup check (ADR 049): logs the refusal when the flag cannot be honored."""
    return evaluation_report_gate.log_enable_gate_at_startup(
        _EVALUATION_REPORT_CONFIG,
        resolve_enable_gate,
        logger,
    )


def coach_ai_enabled() -> bool:
    """Effective state: the flag alone is never enough (ADR 049)."""
    return resolve_enable_gate().enabled


# --------------------------------------------------------------------------
# Context: gather (I/O) -> facts dict -> render (pure)
# --------------------------------------------------------------------------


def format_number(value: Any) -> str:
    """Deterministic figure formatting shared by the renderer, tests, and eval."""
    if value is None:
        return "n/a"
    number = float(value)
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return str(round(number, 2))


#: Evidence keys carried as RPE on the alert row but spoken as RIR to the coach
#: (#111: effort is shown as RIR everywhere a player or coach sees it), with the
#: shared formatter each one needs: a top set is a *recorded* effort, an
#: intensity cap is a *target* so it reads as the equivalent minimum RIR.
_RIR_EVIDENCE_KEYS: dict[str, tuple[str, Callable[[Any], str]]] = {
    "top_rpe": ("top_rir", rir_label),
    "intensity_cap_rpe": ("intensity_cap_rir", min_rir_label),
}


def _session_facts(sessions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Allowlisted session fields (never session ids, notes, or audit rows)."""
    kept = []
    for session in sessions:
        kept.append(
            {
                "session_date": session.get("session_date"),
                "split_name": session.get("split_name"),
                "sets_count": session.get("sets_count", 0),
                "total_volume_kg": session.get("total_volume_kg", 0.0),
                "readiness_score": session.get("readiness_score"),
                "program_version": session.get("program_version"),
                "divergences": [
                    {"kind": row.get("kind"), "exercise_name": row.get("exercise_name")}
                    for row in session.get("divergences", [])
                ],
            }
        )
    totals = {
        "sessions": len(kept),
        "sets": sum(int(entry["sets_count"] or 0) for entry in kept),
        "volume_kg": sum(float(entry["total_volume_kg"] or 0.0) for entry in kept),
    }
    return kept, totals


def _program_facts(ledger: Any) -> dict[str, Any] | None:
    """The active program reduced to structure; no provenance ids or free text."""
    program = ledger.get_active_program()
    if program is None:
        return None
    return {
        "name": program.program_name,
        "split": program.split_type,
        "weekly_frequency": program.weekly_frequency,
        "version": program.version,
        "days": [
            {
                "order": day.day_order,
                "day": day.day_name,
                "exercises": [
                    {
                        "name": exercise.exercise_name,
                        "sets": exercise.target_sets,
                        "reps": f"{exercise.target_reps_min}-{exercise.target_reps_max}",
                        "rpe": exercise.target_rpe,
                    }
                    for exercise in day.exercises
                ],
            }
            for day in program.days
        ],
    }


def _attendance_facts(
    ledger: Any, ledger_id: str, assignment: dict[str, Any], now: datetime
) -> dict[str, Any] | None:
    """Deterministic adherence figures from the ADR 030 evaluation (no model)."""
    evaluation = evaluate_ledger_attendance(ledger, assignment, ledger_id, now)
    if evaluation is None:
        return None
    expected = len(evaluation.expected_days)
    satisfied = len(evaluation.satisfied_days)
    return {
        "timezone": evaluation.timezone,
        "local_today": evaluation.local_today.isoformat(),
        "window_start": evaluation.window_start.isoformat(),
        "expected_days": expected,
        "satisfied_days": satisfied,
        "missed_days": len(evaluation.missed_days),
        "adherence_pct": round(100.0 * satisfied / expected, 1) if expected else None,
        "trailing_missed_streak": evaluation.trailing_streak_length,
        "last_missed_on": (
            evaluation.missed_days[-1].isoformat() if evaluation.missed_days else None
        ),
    }


def gather_player_context(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Builds the model facts for one assigned player from coach-visible data.

    Runs behind the ADR 025 catalog gate: ``None`` means unknown, ended, or
    other-coach, and no ledger is opened. Everything returned is telemetry the
    coach can already read; identity and free text are dropped field by field.
    """
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    now = now or datetime.now(UTC)
    with ledger:
        ledger_id = context["player"]["ledger_id"]
        schedule, pauses = coach_history_service.schedule_and_pauses(db, ledger, ledger_id)
        sessions, session_totals = _session_facts(
            coach_history_service.recent_sessions(ledger, coach_history_service.DEFAULT_RECENT_SESSIONS)
        )
        records = dashboard_service.recent_personal_records(db, ledger_id, limit=10, ledger=ledger)
        personal_records = [
            {
                "exercise": record["name"],
                "record_type": record["record_type"],
                "reps": record["reps"],
                "value": record["value"],
                "prev_value": record["prev_value"],
                "achieved_at": str(record["achieved_at"])[:10],
            }
            for record in records
        ]
        attendance = _attendance_facts(ledger, ledger_id, context["assignment"], now)
        volumes = dashboard_service.working_set_volume(db, ledger_id, days_lookback=(7, 28), ledger=ledger)
        facts: dict[str, Any] = {
            "as_of": (attendance or {}).get("local_today") or now.date().isoformat(),
            "assignment": {
                "started_on": str(context["assignment"].get("started_at", ""))[:10],
                "status": context["assignment"].get("status", "active"),
            },
            "program": _program_facts(ledger),
            "volume": {
                "last_7_days_kg": volumes[7],
                "last_28_days_kg": volumes[28],
            },
            "recent_sessions": sessions,
            "recent_sessions_totals": session_totals,
            "personal_records": personal_records,
            "attendance": attendance,
            "schedule": schedule,
            "pauses": pauses,
        }

    check_ins = check_ins_service.list_coach_check_ins(db, coach_account_id, assignment_id) or []
    facts["check_ins"] = [
        {"checked_in_on": row.get("checked_in_on"), "channel": row.get("channel")} for row in check_ins
    ]

    requests = program_requests_service.list_assignment_requests(db, coach_account_id, assignment_id) or []
    pending_kinds: dict[str, int] = {}
    for request in requests:
        if request.get("status") == "pending":
            kind = str(request.get("kind", "unknown"))
            pending_kinds[kind] = pending_kinds.get(kind, 0) + 1
    facts["program_requests"] = {
        "total": len(requests),
        "pending": sum(pending_kinds.values()),
        "pending_by_kind": pending_kinds,
    }

    facts["alerts"] = [
        {key: alert[key] for key in _ALERT_KEPT_FIELDS if key in alert}
        for alert in list_coach_alerts(db, coach_account_id, ALERT_STATES)
        if alert.get("assignment_id") == str(assignment_id)
    ]
    return facts


# --------------------------------------------------------------------------
# Rendering: one pure section helper per block (ADR 049)
# --------------------------------------------------------------------------


def _render_program(facts: dict[str, Any]) -> list[str]:
    lines = ["program:"]
    program = facts.get("program")
    if not program:
        return [*lines, "  none recorded"]
    lines.append(f"  name: {program.get('name')}")
    lines.append(f"  split: {program.get('split')}")
    lines.append(f"  weekly_frequency: {format_number(program.get('weekly_frequency'))}")
    lines.append(f"  version: {format_number(program.get('version'))}")
    for day in program.get("days", []):
        prescriptions = ", ".join(
            f"{exercise.get('name')} {format_number(exercise.get('sets'))}x{exercise.get('reps')}"
            f" @RIR {min_rir_label(exercise.get('rpe'))}"
            for exercise in day.get("exercises", [])
        )
        lines.append(f"  day {format_number(day.get('order'))} {day.get('day')}: {prescriptions}")
    return lines


def _render_volume(facts: dict[str, Any]) -> list[str]:
    volume = facts.get("volume") or {}
    return [
        f"volume_last_7_days_kg: {format_number(volume.get('last_7_days_kg'))}",
        f"volume_last_28_days_kg: {format_number(volume.get('last_28_days_kg'))}",
    ]


def _render_sessions(facts: dict[str, Any]) -> list[str]:
    sessions = facts.get("recent_sessions") or []
    if not sessions:
        return ["recent_sessions: none recorded"]
    lines = ["recent_sessions (newest first):"]
    for session in sessions:
        divergences = session.get("divergences") or []
        divergence_text = (
            "; ".join(f"{row.get('kind')} {row.get('exercise_name')}" for row in divergences)
            if divergences
            else "none"
        )
        lines.append(
            f"  {session.get('session_date')} {session.get('split_name')}:"
            f" sets {format_number(session.get('sets_count'))},"
            f" volume_kg {format_number(session.get('total_volume_kg'))},"
            f" readiness {format_number(session.get('readiness_score'))},"
            f" program_version {format_number(session.get('program_version'))},"
            f" divergences {divergence_text}"
        )
    totals = facts.get("recent_sessions_totals") or {}
    lines.append(
        "recent_sessions_totals:"
        f" sessions {format_number(totals.get('sessions'))},"
        f" sets {format_number(totals.get('sets'))},"
        f" volume_kg {format_number(totals.get('volume_kg'))}"
    )
    return lines


def _render_records(facts: dict[str, Any]) -> list[str]:
    records = facts.get("personal_records") or []
    if not records:
        return ["personal_records: none yet"]
    lines = ["personal_records (newest first):"]
    for record in records:
        lines.append(
            f"  {record.get('achieved_at')} {record.get('exercise')}"
            f" {record.get('record_type')} {format_number(record.get('reps'))} reps:"
            f" {format_number(record.get('value'))} kg"
            f" (previous {format_number(record.get('prev_value'))})"
        )
    return lines


def _render_attendance(facts: dict[str, Any]) -> list[str]:
    attendance = facts.get("attendance")
    if not attendance:
        return ["attendance: unavailable (no training schedule recorded)"]
    return [
        f"attendance (window {attendance.get('window_start')} to {attendance.get('local_today')},"
        f" timezone {attendance.get('timezone')}):",
        f"  expected_days: {format_number(attendance.get('expected_days'))}",
        f"  satisfied_days: {format_number(attendance.get('satisfied_days'))}",
        f"  missed_days: {format_number(attendance.get('missed_days'))}",
        f"  adherence_pct: {format_number(attendance.get('adherence_pct'))}",
        f"  trailing_missed_streak: {format_number(attendance.get('trailing_missed_streak'))}",
        f"  last_missed_on: {attendance.get('last_missed_on') or 'none'}",
    ]


def _render_schedule(facts: dict[str, Any]) -> list[str]:
    schedule = facts.get("schedule")
    if schedule:
        weekdays = ",".join(str(day) for day in schedule.get("weekdays", []))
        lines = [f"schedule: weekdays [{weekdays}] timezone {schedule.get('timezone')}"]
    else:
        lines = ["schedule: none recorded"]
    pauses = facts.get("pauses") or []
    if pauses:
        lines.extend(f"pause: {pause.get('starts_on')}..{pause.get('ends_on')}" for pause in pauses)
    else:
        lines.append("pauses: none")
    return lines


def _render_alerts(facts: dict[str, Any]) -> list[str]:
    alerts = facts.get("alerts") or []
    if not alerts:
        return ["alerts: none"]
    lines = ["alerts:"]
    for alert in alerts:
        evidence_parts = []
        for key in _ALERT_EVIDENCE_FIELDS:
            if key not in alert or alert[key] is None:
                continue
            raw = alert[key]
            if key in _RIR_EVIDENCE_KEYS:
                # Stored RPE, spoken as RIR at the display boundary (#111).
                label, formatter = _RIR_EVIDENCE_KEYS[key]
                evidence_parts.append(f"{label} {formatter(raw)}")
            elif isinstance(raw, (int, float)):
                evidence_parts.append(f"{key} {format_number(raw)}")
            else:
                evidence_parts.append(f"{key} {raw}")
        lines.append(
            f"  {alert.get('kind')} {alert.get('state')}: {', '.join(evidence_parts)}"
        )
    return lines


def _render_check_ins(facts: dict[str, Any]) -> list[str]:
    check_ins = facts.get("check_ins") or []
    if not check_ins:
        return ["check_ins: none yet"]
    return [
        "check_ins (dates and channels only): "
        + "; ".join(f"{row.get('checked_in_on')} {row.get('channel')}" for row in check_ins)
    ]


def _render_program_requests(facts: dict[str, Any]) -> list[str]:
    requests = facts.get("program_requests") or {}
    pending = int(requests.get("pending", 0) or 0)
    if not pending:
        return ["program_requests: none pending"]
    kinds = ", ".join(
        f"{kind} {count}" for kind, count in sorted(requests.get("pending_by_kind", {}).items())
    )
    return [f"program_requests: pending {pending} ({kinds})"]


#: Render order; ``render_context`` joins these blocks with one blank line each.
_SECTIONS = (
    _render_program,
    _render_volume,
    _render_sessions,
    _render_records,
    _render_attendance,
    _render_schedule,
    _render_alerts,
    _render_check_ins,
    _render_program_requests,
)


def render_context(facts: dict[str, Any]) -> str:
    """Renders gathered facts as the model-facing telemetry block (pure).

    Every figure is formatted with :func:`format_number`, so a test can
    recompute the same value through the service and match it exactly. Missing
    sections are stated explicitly, which is what lets the model report
    insufficient data instead of inventing it.
    """
    lines: list[str] = [
        "[PLAYER TELEMETRY]",
        f"as_of: {facts.get('as_of') or 'unknown'}",
    ]
    assignment = facts.get("assignment") or {}
    if assignment:
        lines.append(f"assignment_started_on: {assignment.get('started_on') or 'unknown'}")
        lines.append(f"assignment_status: {assignment.get('status') or 'unknown'}")
    for section in _SECTIONS:
        lines.append("")
        lines.extend(section(facts))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Prompt assembly and the turn
# --------------------------------------------------------------------------


def build_messages(context_text: str, question: str, history: list[dict[str, Any]]) -> list[Any]:
    """Assembles the model messages: prompt, telemetry, transcript, question.

    Shared with the eval runner so the evaluation exercises the production
    prompt. History turns arrive from the client (role ``coach``/``assistant``).
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    messages: list[Any] = [SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{context_text}")]
    for turn in history:
        content = str(turn.get("content", ""))
        if turn.get("role") == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    messages.append(HumanMessage(content=question))
    return messages


def extract_answer(reply: Any) -> str:
    """Extraction + finalization for one model reply, shared by live and eval.

    The scrubber runs first; if it removes everything, the standard empty-reply
    fallback is returned instead of an empty answer (ADR 049).
    """
    from utils.text_scrubber import finalize_coach_output

    content = getattr(reply, "content", reply)
    return finalize_coach_output("" if content is None else str(content))


def _invoke_coach_model(messages: list[Any]) -> str:
    """Lowest model entry: the coach-role model only (ADR 012/016)."""
    from utils import model_downloader

    return extract_answer(model_downloader.get_coach_llm().invoke(messages))


def ask(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Answers one coach question for one assigned player; persists nothing.

    ``None`` is the generic denial for an unknown, ended, or other-coach
    assignment (ADR 025). The telemetry block is gathered and the ledger
    handle closed *before* the model call, so no ledger is held during
    inference and nothing about the exchange is written anywhere.
    """
    facts = gather_player_context(db, coach_account_id, assignment_id)
    if facts is None:
        return None
    messages = build_messages(render_context(facts), question, list(history or []))
    from svc.llm import InferenceScope, run_inference_sync

    answer = run_inference_sync(
        _invoke_coach_model,
        messages,
        scope=InferenceScope(
            account_id=coach_account_id, role="coach", purpose="coach_assistant", store=db
        ),
    )
    return {"answer": answer}


__all__ = [
    "CANONICAL_FIXTURE",
    "CONTEXT_VERSION",
    "REPORT_VERSION",
    "SYSTEM_PROMPT",
    "GateStatus",
    "ask",
    "build_messages",
    "canonical_messages_text",
    "coach_ai_enabled",
    "coach_model_identity",
    "evaluate_gate",
    "extract_answer",
    "format_number",
    "gather_player_context",
    "log_enable_gate_at_startup",
    "prompt_version_hash",
    "render_context",
    "resolve_enable_gate",
    "validate_report",
]
