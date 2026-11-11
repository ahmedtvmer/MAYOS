"""Public, bounded reader for recorded Training program rationale."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

MAX_RESULT_BYTES = 4 * 1024


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _compact(value: Any) -> Any:
    """Keep machine codes and parameters while dropping redundant record keys."""
    if isinstance(value, dict):
        if isinstance(value.get("code"), str):
            result = {"c": value["code"]}
            if value.get("params"):
                result["p"] = _compact(value["params"])
            if value.get("at"):
                result["at"] = value["at"]
            return result
        return {key: _compact(item) for key, item in value.items() if key not in {"rationale"}}
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value


def read_program_rationale(program: Any, scope: Any = None) -> dict[str, Any]:
    """Return recorded reasons and change history for the requested program scope."""
    scope_fields = ("day_name", "day_order", "exercise_name", "exercise_id", "week_order", "position", "page")
    args = SimpleNamespace(**{
        name: (scope.get(name) if isinstance(scope, dict) else getattr(scope, name, None))
        for name in scope_fields
    })
    if args.page is None:
        args.page = 0
    rationale = getattr(program, "program_rationale", None) or {}
    coach = getattr(program, "published_by_coach_account_id", None)
    template = getattr(program, "source_template_id", None)
    if template:
        source = "template_derived"
    elif coach:
        generated_rationale = bool(rationale) and rationale.get(
            "generator_reasons_available", True
        )
        source = "coach_generated" if generated_rationale else "coach_authored"
    elif rationale:
        source = "automatic"
    else:
        source = "imported"

    # Program model rationale is keyed by day order; preserve recorded facts verbatim.
    stored_days = {
        (int(d.get("week_order", 1)), int(d.get("day_order", -1))): d
        for d in rationale.get("days", []) if isinstance(d, dict)
    }
    output_days = []
    weeks = getattr(program, "weeks", ()) or ()
    if weeks:
        day_entries = [
            (int(_field(week, "week_order", week_index)), day)
            for week_index, week in enumerate(weeks, 1)
            for day in (_field(week, "days", ()) or ())
        ]
    else:
        day_entries = [
            (int(_field(day, "week_order", 1)), day)
            for day in (getattr(program, "days", ()) or ())
        ]
    for week_order, day in day_entries:
        order = int(_field(day, "day_order", 0))
        name = str(_field(day, "day_name", "not set"))
        if args.week_order is not None and week_order != args.week_order:
            continue
        if args.day_order is not None and order != args.day_order:
            continue
        if args.day_name and name.casefold() != args.day_name.strip().casefold():
            continue
        stored = stored_days.get((week_order, order), {})
        exercises = []
        by_position = {int(e.get("position", -1)): e for e in stored.get("exercises", []) if isinstance(e, dict)}
        for pos, ex in enumerate(_field(day, "exercises", ()) or (), 1):
            eid = str(_field(ex, "exercise_id", ""))
            ename = str(_field(ex, "exercise_name", "not set"))
            if args.exercise_id and eid != args.exercise_id:
                continue
            if args.exercise_name and ename.casefold() != args.exercise_name.strip().casefold():
                continue
            if args.position is not None and pos != int(args.position):
                continue
            item = by_position.get(pos, {})
            if item.get("exercise_id") not in (None, eid):
                item = {}
            reason = item.get("rationale")
            if reason is None and any(key in item for key in ("selection", "prescription", "position_reason")):
                reason = {key: value for key, value in item.items() if key not in {"position", "exercise_id", "changes"}}
            record = {"position": pos, "exercise_id": eid, "exercise": ename}
            if reason is not None:
                record["rationale"] = reason
                for key in ("selection", "position", "prescription", "day_choice"):
                    if key in reason:
                        record[key] = reason[key]
            if item.get("changes"):
                record["changes"] = item["changes"]
            note = _field(ex, "note")
            if source in {"coach_authored", "coach_generated", "template_derived", "imported"} and note:
                record["coach_note"] = note
            exercises.append(record)
        day_record = {"day": name, "day_order": order, "exercises": exercises}
        for key in ("day_order_reason", "warmup", "cardio", "cardio_restriction", "removed", "skipped"):
            if key in stored:
                day_record[key] = stored[key]
        output_days.append(day_record)

    focus = rationale.get("focus_muscles", [])
    if args.day_order is not None or args.day_name or args.exercise_id or args.exercise_name:
        selected_days = {day["day_order"] for day in output_days}
        selected_ids = {
            item["exercise_id"] for day in output_days for item in day["exercises"]
        }
        focus = [entry for entry in focus if _focus_entry_matches_scope(
            entry, selected_days, selected_ids
        )]
    result: dict[str, Any] = {
        "status": "ok", "source": source,
        "reason_available": bool(rationale) and rationale.get("generator_reasons_available", True),
        "split": rationale.get("split"), "day_order": rationale.get("day_order"),
        "focus_muscles": focus, "days": output_days,
    }
    # Compact codes/params first. If a response still exceeds the contract, return
    # one complete page of exercises and a cursor so callers can retrieve the rest.
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        compact = _compact(result)
        encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) <= MAX_RESULT_BYTES:
            result = compact
        else:
            flat = [(di, ei, ex) for di, d in enumerate(result["days"]) for ei, ex in enumerate(d["exercises"])]
            page = int(getattr(args, "page", 0) or 0)
            base = {k: result[k] for k in ("status", "source", "reason_available", "split", "day_order", "focus_muscles")}
            base["days"] = [{k: v for k, v in d.items() if k != "exercises"} | {"exercises": []} for d in result["days"]]
            start = page
            while start < len(flat):
                di, _, ex = flat[start]
                candidate = json.loads(json.dumps(base))
                candidate["days"][di]["exercises"].append(_compact(ex))
                if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_RESULT_BYTES:
                    break
                base = candidate
                start += 1
            if start < len(flat):
                base["next_page"] = start
            base["page"] = page
            result = base
    return result


def _focus_entry_matches_scope(entry, selected_days, selected_ids):
    return (
        entry.get("day_order") in selected_days
        or entry.get("exercise_id") in selected_ids
        or any(extra.get("day_order") in selected_days
               or extra.get("exercise_id") in selected_ids
               for extra in entry.get("extras", []))
    )
