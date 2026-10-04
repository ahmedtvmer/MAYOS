import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

EQUIPMENT_INCREMENTS = {
    "barbell": 2.5,
    "olympic barbell": 2.5,
    "smith machine": 2.5,
    "dumbbell": 2.0,
    "cable": 2.5,
    "machine": 2.5,
    "leverage machine": 2.5,
    "bodyweight": 1.0,
    "weighted bodyweight": 1.25,
}


def calculate_e1rm(weight_kg: float, reps: int, rpe: float) -> float:
    if reps <= 0 or weight_kg <= 0:
        return 0.0
    effective_reps = reps + (10.0 - min(max(rpe, 6.0), 10.0))
    return weight_kg * (1.0 + (effective_reps / 30.0))


def round_to_increment(val: float, increment: float) -> float:
    return round(val / increment) * increment


def project_next_load(
    last_weight: float,
    last_reps: int,
    last_rpe: float | None,
    target_reps_min: int | None = None,
    target_reps_max: int | None = None,
    target_reps: int | tuple[int, int] | str | None = None,
    target_rpe: float = 8.5,
    equipment: str = "barbell",
) -> dict[str, Any]:
    if target_reps is not None:
        if isinstance(target_reps, tuple) and len(target_reps) == 2:
            target_reps_min = target_reps_min or target_reps[0]
            target_reps_max = target_reps_max or target_reps[1]
        elif isinstance(target_reps, int):
            target_reps_min = target_reps_min or target_reps
            target_reps_max = target_reps_max or target_reps
        elif isinstance(target_reps, str) and "-" in target_reps:
            parts = target_reps.split("-")
            target_reps_min = target_reps_min or int(parts[0].strip())
            target_reps_max = target_reps_max or int(parts[1].strip())

    target_reps_min = target_reps_min or 8
    target_reps_max = target_reps_max or 12

    if last_weight <= 0 or last_reps <= 0:
        return {
            "projected_weight": max(last_weight, 20.0),
            "delta_kg": 0.0,
            "e1rm": 0.0,
            "status": "INITIAL_CALIBRATION",
        }

    increment = 2.5
    for key, inc in EQUIPMENT_INCREMENTS.items():
        if key in equipment.lower():
            increment = inc
            break

    current_e1rm = set_e1rm(last_weight, last_reps, last_rpe)

    if last_rpe is None:
        # No effort recorded (#111): never read a blank as 0 or as a default.
        # Both effort-based rules (overshoot deload, ease-based upscale) need an
        # effort reading, so only the objective rep bracket can move the load.
        if last_reps >= target_reps_max:
            target_load = last_weight + increment
            return {
                "projected_weight": target_load,
                "delta_kg": increment,
                "e1rm": round(current_e1rm, 2),
                "status": "PROGRESSION_UP",
            }
        return {
            "projected_weight": last_weight,
            "delta_kg": 0.0,
            "e1rm": round(current_e1rm, 2),
            "status": "LOAD_MAINTAINED",
        }

    if last_rpe >= 10.0 and target_rpe <= 8.5:
        target_load = max(last_weight - increment, increment)
        return {
            "projected_weight": target_load,
            "delta_kg": -increment,
            "e1rm": round(current_e1rm, 2),
            "status": "RPE_OVERSHOOT_DELOAD",
        }

    if last_reps >= target_reps_max and last_rpe <= target_rpe:
        target_load = last_weight + increment
        return {
            "projected_weight": target_load,
            "delta_kg": increment,
            "e1rm": round(current_e1rm, 2),
            "status": "PROGRESSION_UP",
        }

    if last_rpe <= (target_rpe - 1.5):
        target_eff_reps = last_reps + (10.0 - target_rpe)
        raw_projected = current_e1rm / (1.0 + (target_eff_reps / 30.0))
        target_load = max(round_to_increment(raw_projected, increment), last_weight + increment)
        return {
            "projected_weight": target_load,
            "delta_kg": round(target_load - last_weight, 2),
            "e1rm": round(current_e1rm, 2),
            "status": "DYNAMIC_UPSCALE",
        }

    return {
        "projected_weight": last_weight,
        "delta_kg": 0.0,
        "e1rm": round(current_e1rm, 2),
        "status": "LOAD_MAINTAINED",
    }


def normalize_muscle_group(muscle_name: str) -> str:
    m = (muscle_name or "").strip().lower()
    if any(k in m for k in ["pectoral", "chest"]):
        return "Chest"
    if any(k in m for k in ["lat", "upper back", "trap", "rhomboid", "spine", "back"]):
        return "Back"
    if any(k in m for k in ["quad", "rectus femoris", "vastus"]):
        return "Quads"
    if any(k in m for k in ["hamstring", "biceps femoris", "glute"]):
        return "Hamstrings & Glutes"
    if any(k in m for k in ["delt", "shoulder"]):
        return "Shoulders"
    if any(k in m for k in ["bicep", "brachialis"]):
        return "Biceps"
    if any(k in m for k in ["tricep"]):
        return "Triceps"
    if any(k in m for k in ["calve", "soleus", "gastrocnemius"]):
        return "Calves"
    if any(k in m for k in ["ab", "core", "oblique"]):
        return "Abs"
    return "Other"


def get_weekly_muscle_volume(db: DatabaseManager, days_lookback: int = 7) -> dict[str, float]:
    cursor = db.conn.cursor()
    cutoff_date = (datetime.now(UTC) - timedelta(days=days_lookback)).isoformat()[:10]

    cursor.execute(
        """
        SELECT ws.exercise_id, e.target_muscle, e.body_part
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        JOIN exercises e ON ws.exercise_id = e.id
        WHERE s.session_date >= ? AND ws.is_warmup = 0
    """,
        (cutoff_date,),
    )
    working_sets = cursor.fetchall()

    volume_tally: dict[str, float] = {
        "Chest": 0.0,
        "Back": 0.0,
        "Shoulders": 0.0,
        "Quads": 0.0,
        "Hamstrings & Glutes": 0.0,
        "Biceps": 0.0,
        "Triceps": 0.0,
        "Calves": 0.0,
        "Abs": 0.0,
    }

    if not working_sets:
        return volume_tally

    distinct_ex_ids = list({row[0] for row in working_sets})
    placeholders = ",".join("?" for _ in distinct_ex_ids)
    cursor.execute(
        f"SELECT exercise_id, muscle FROM catalog.exercise_secondary_muscles WHERE exercise_id IN ({placeholders})",
        distinct_ex_ids,
    )
    secondaries_map: dict[str, list[str]] = {}
    for ex_id, muscle in cursor.fetchall():
        secondaries_map.setdefault(ex_id, []).append(muscle)

    for ex_id, target_muscle, body_part in working_sets:
        primary_group = normalize_muscle_group(target_muscle)
        if primary_group == "Other":
            primary_group = normalize_muscle_group(body_part)

        if primary_group in volume_tally:
            volume_tally[primary_group] += 1.0

        matched_secondaries = {normalize_muscle_group(m) for m in secondaries_map.get(ex_id, [])}
        for sec_group in matched_secondaries:
            if sec_group != "Other" and sec_group != primary_group and sec_group in volume_tally:
                volume_tally[sec_group] += 0.5

    return {k: round(v, 1) for k, v in volume_tally.items()}


def get_exercise_progression_history(db: DatabaseManager, exercise_id: str) -> list[dict[str, Any]]:
    cursor = db.conn.cursor()
    cursor.execute(
        """
        SELECT s.session_date, ws.weight_kg, ws.reps, ws.rpe, ws.set_index
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        WHERE ws.exercise_id = ? AND ws.is_warmup = 0
        ORDER BY s.session_date ASC, ws.weight_kg DESC
    """,
        (exercise_id,),
    )

    history_by_date: dict[str, dict[str, Any]] = {}
    for session_date, weight, reps, rpe, _ in cursor.fetchall():
        if session_date not in history_by_date:
            history_by_date[session_date] = {
                "date": session_date,
                "weight_kg": weight,
                "reps": reps,
                "rpe": rpe,
                "e1rm": round(set_e1rm(weight, reps, rpe), 2),
            }
    return list(history_by_date.values())


def set_e1rm(weight_kg: float, reps: int, rpe: float | None) -> float:
    """e1RM for one set by the current formula: RPE-aware, unrated sets plain Epley (#111).

    The single per-set definition the record aggregates, the ADR 009 history
    rows, the commit comparison and the session export share. A set with no
    effort recorded is scored ``w * (1 + reps / 30)`` — exactly RPE 10 / RIR 0 —
    so an unrated set never scores higher than an honest rating of RIR 0 and
    never inherits a default effort.

    Note that :func:`calculate_e1rm` clamps its effort term at RPE 6, so a set
    logged RIR 5 (or anything above RIR 4) scores exactly like RIR 4. That is
    the formula, not this helper's business: it is left unchanged here.
    """
    return calculate_e1rm(
        float(weight_kg), int(reps), 10.0 if rpe is None else float(rpe)
    )


def _set_e1rm(set_data: dict[str, Any]) -> float:
    return set_e1rm(float(set_data["weight_kg"]), int(set_data["reps"]), set_data.get("rpe"))


def is_body_weight_or_band_equipment(equipment: str | None) -> bool:
    """Whether Exercise library equipment labels a zero load as body weight or band."""
    return isinstance(equipment, str) and equipment.strip().lower() in {
        "body weight",
        "band",
        "resistance band",
    }


@dataclass(frozen=True)
class WorkingSetAggregates:
    """Exercise-wide previous bests derived from committed working sets (ADR 042).

    Built only from working-set rows — never from ``personal_records`` — by
    :meth:`from_sets`, so the commit comparison, the ADR 009 history rows, and
    ``GET /workouts/baselines`` all read the same numbers. Empty aggregates
    (both maxima ``None``) mean the exercise has no earlier working set: its
    first session is a baseline. Values are rounded to 2 decimals, the precision
    events and the API report, so equal reported values are always ties.
    """

    best_weight_by_reps: dict[int, float] = field(default_factory=dict)
    max_weight_kg: float | None = None
    best_e1rm_kg: float | None = None

    @classmethod
    def from_sets(cls, rows: Iterable[dict[str, Any]]) -> "WorkingSetAggregates":
        """Aggregates over working-set rows: heaviest weight per rep count, best e1RM."""
        best_by_reps: dict[int, float] = {}
        best_e1rm = 0.0
        counted = False
        for row in rows:
            counted = True
            reps = int(row["reps"])
            weight = round(float(row["weight_kg"]), 2)
            best_by_reps[reps] = max(best_by_reps.get(reps, weight), weight)
            best_e1rm = max(best_e1rm, set_e1rm(float(row["weight_kg"]), reps, row.get("rpe")))
        if not counted:
            return cls()
        return cls(
            best_weight_by_reps=best_by_reps,
            max_weight_kg=max(best_by_reps.values()),
            best_e1rm_kg=round(best_e1rm, 2),
        )


@dataclass(frozen=True)
class SessionExerciseRecord:
    """Exercise sets and Exercise library facts used for one commit's records."""

    session_id: str
    exercise_id: str
    sets: list[dict[str, Any]]
    exercise_name: str | None = None
    equipment: str | None = None
    achieved_at: str | None = None


def exercise_working_set_aggregates(
    db: DatabaseManager,
    exercise_id: str,
    *,
    exclude_session_id: str | None = None,
) -> WorkingSetAggregates:
    """The record aggregates over the player's committed working sets for one exercise (ADR 042).

    The rows come from the ledger mixin's ``working_set_rows`` — the single
    working-set definition — and ``exclude_session_id`` drops the session being
    committed, so a commit compares against the player's *earlier* working sets
    only. This is never ``MAX`` over ``personal_records``. ``GET
    /workouts/baselines`` builds its aggregates from the same rows through
    :meth:`WorkingSetAggregates.from_sets`, so the device and the server agree
    by construction. Empty aggregates mean the exercise's first session has no
    previous best.
    """
    return WorkingSetAggregates.from_sets(
        db.working_set_rows(exercise_id, exclude_session_id=exclude_session_id)
    )


def _insert_record_row(
    db: DatabaseManager,
    exercise_id: str,
    record_type: str,
    reps: int,
    value: float,
    prev_value: float | None,
    session_id: str,
    achieved_at: str,
) -> None:
    """Appends one ADR 009 history row: history views only, never an event."""
    db.conn.execute(
        """
            INSERT INTO personal_records (
                id, exercise_id, record_type, reps, value, prev_value, achieved_at, session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), exercise_id, record_type, reps, value, prev_value, achieved_at, session_id),
    )
    # ``commit_ledger`` defers to an enclosing ledger transaction.
    db.commit_ledger()


def _store_history_rows(
    db: DatabaseManager,
    exercise_id: str,
    working: list[dict[str, Any]],
    previous: WorkingSetAggregates,
    *,
    session_id: str,
    achieved_at: str,
) -> None:
    """ADR 009 rows for history views: heaviest set per rep count plus the best-e1RM set.

    Stored on every session except the exercise's first (ADR 042) and only when
    the value strictly beats ``previous`` — the aggregate over the player's
    earlier committed working sets, per rep count for ``max_weight`` and
    exercise-wide for ``max_e1rm`` — never ``MAX`` over ``personal_records``, so
    a lighter later session cannot write a lower "best". Rows are history only:
    they are never returned as events.
    """
    best_e1rm_set = max(working, key=_set_e1rm)

    groups: dict[int, list[dict[str, Any]]] = {}
    for s in working:
        groups.setdefault(int(s["reps"]), []).append(s)

    candidates: list[tuple[dict[str, Any], set[str]]] = []
    for _reps, group in sorted(groups.items()):
        best_weight_set = max(group, key=lambda s: float(s["weight_kg"]))
        record_types = {"max_weight"}
        if best_weight_set is best_e1rm_set:
            record_types.add("max_e1rm")
        candidates.append((best_weight_set, record_types))
    if all(candidate is not best_e1rm_set for candidate, _ in candidates):
        candidates.append((best_e1rm_set, {"max_e1rm"}))

    for candidate, record_types in candidates:
        reps = int(candidate["reps"])
        if "max_weight" in record_types:
            value = round(float(candidate["weight_kg"]), 2)
            previous_weight = previous.best_weight_by_reps.get(reps)
            if value > 0 and (previous_weight is None or value > previous_weight):
                _insert_record_row(
                    db, exercise_id, "max_weight", reps, value, previous_weight, session_id, achieved_at
                )
        if "max_e1rm" in record_types:
            value = round(_set_e1rm(candidate), 2)
            previous_e1rm = previous.best_e1rm_kg
            if value > 0 and (previous_e1rm is None or value > previous_e1rm):
                _insert_record_row(
                    db, exercise_id, "max_e1rm", reps, value, previous_e1rm, session_id, achieved_at
                )


def _record_event(
    exercise_id: str,
    record_type: str,
    set_data: dict[str, Any],
    value: float,
    prev_value: float,
    achieved_at: str,
    session_id: str,
) -> dict[str, Any]:
    return {
        "exercise_id": exercise_id,
        "record_type": record_type,
        "reps": int(set_data["reps"]),
        "value": value,
        "prev_value": prev_value,
        "achieved_at": achieved_at,
        "session_id": session_id,
    }


def _weighted_working_sets(sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        set_row
        for set_row in sets
        if not set_row.get("is_warmup", False)
        and float(set_row.get("weight_kg", 0) or 0) > 0
        and int(set_row.get("reps", 0) or 0) > 0
    ]


def _zero_load_working_sets(record: SessionExerciseRecord) -> list[dict[str, Any]]:
    if not is_body_weight_or_band_equipment(record.equipment):
        return []
    return [
        set_row
        for set_row in record.sets
        if not set_row.get("is_warmup", False)
        and float(set_row.get("weight_kg", 0) or 0) == 0
        and int(set_row.get("reps", 0) or 0) > 0
    ]


def best_zero_load_reps(sets: Iterable[dict[str, Any]]) -> int | None:
    """Best prior working-set reps at exactly 0 kg, or ``None`` without one."""
    return max(
        (
            int(row["reps"])
            for row in sets
            if float(row.get("weight_kg", 0) or 0) == 0
            and int(row.get("reps", 0) or 0) > 0
        ),
        default=None,
    )


def _weighted_record_events(
    record: SessionExerciseRecord,
    working: list[dict[str, Any]],
    previous: WorkingSetAggregates,
    stamp: str,
) -> list[dict[str, Any]]:
    if not working or previous.max_weight_kg is None or previous.best_e1rm_kg is None:
        return []
    heaviest_set = max(working, key=lambda set_row: float(set_row["weight_kg"]))
    best_e1rm_set = max(working, key=_set_e1rm)
    events = []

    heaviest = round(float(heaviest_set["weight_kg"]), 2)
    if heaviest > previous.max_weight_kg:
        events.append(
            _record_event(
                record.exercise_id,
                "max_weight",
                heaviest_set,
                heaviest,
                previous.max_weight_kg,
                stamp,
                record.session_id,
            )
        )
    best_e1rm = round(_set_e1rm(best_e1rm_set), 2)
    if best_e1rm > previous.best_e1rm_kg:
        events.append(
            _record_event(
                record.exercise_id,
                "max_e1rm",
                best_e1rm_set,
                best_e1rm,
                previous.best_e1rm_kg,
                stamp,
                record.session_id,
            )
        )
    return events


def _most_reps_event(
    record: SessionExerciseRecord,
    zero_load_sets: list[dict[str, Any]],
    previous_performance: list[dict[str, Any]],
    stamp: str,
) -> dict[str, Any] | None:
    if not zero_load_sets:
        return None
    best_set = max(zero_load_sets, key=lambda set_row: int(set_row["reps"]))
    previous_reps = best_zero_load_reps(previous_performance)
    if previous_reps is None:
        return None
    best_reps = int(best_set["reps"])
    if best_reps <= previous_reps:
        return None
    return _record_event(
        record.exercise_id,
        "most_reps",
        best_set,
        best_reps,
        previous_reps,
        stamp,
        record.session_id,
    )


def _store_most_reps_event(
    db: DatabaseManager,
    record: SessionExerciseRecord,
    event: dict[str, Any],
    achieved_at: str,
) -> None:
    _insert_record_row(
        db,
        record.exercise_id,
        "most_reps",
        int(event["reps"]),
        float(event["value"]),
        float(event["prev_value"]),
        record.session_id,
        achieved_at,
    )


def evaluate_session_prs(
    db: DatabaseManager,
    record: SessionExerciseRecord,
    *,
    include_most_reps: bool = True,
) -> list[dict[str, Any]]:
    """Returns strict Personal records for one exercise in a committed session.

    Weighted records use ADR 042 aggregates. A ``most_reps`` record compares
    against prior 0 kg sets on body-weight/band equipment; the first eligible
    zero-load working session is its baseline. Warm-up sets never count.
    """
    working = _weighted_working_sets(record.sets)
    zero_load_sets = _zero_load_working_sets(record)
    if not working and not zero_load_sets:
        return []
    previous_sets = db.rep_working_set_rows(record.exercise_id, exclude_session_id=record.session_id)
    if not previous_sets:
        return []

    stamp = record.achieved_at or datetime.now(UTC).isoformat()
    weighted_previous = exercise_working_set_aggregates(
        db, record.exercise_id, exclude_session_id=record.session_id
    )
    events = _weighted_record_events(record, working, weighted_previous, stamp)
    if working and weighted_previous.max_weight_kg is not None and weighted_previous.best_e1rm_kg is not None:
        _store_history_rows(
            db,
            record.exercise_id,
            working,
            weighted_previous,
            session_id=record.session_id,
            achieved_at=stamp,
        )

    most_reps_event = (
        _most_reps_event(record, zero_load_sets, previous_sets, stamp)
        if include_most_reps
        else None
    )
    if most_reps_event is not None:
        events.append(most_reps_event)
        _store_most_reps_event(db, record, most_reps_event, stamp)

    for event in events:
        event["name"] = record.exercise_name or record.exercise_id
    return events


def evaluate_session_most_reps(
    db: DatabaseManager,
    record: SessionExerciseRecord,
) -> list[dict[str, Any]]:
    """Evaluates one session-wide, exercise-wide most-reps comparison."""
    zero_load_sets = _zero_load_working_sets(record)
    if not zero_load_sets:
        return []
    previous_sets = db.rep_working_set_rows(
        record.exercise_id,
        exclude_session_id=record.session_id,
    )
    stamp = record.achieved_at or datetime.now(UTC).isoformat()
    event = _most_reps_event(record, zero_load_sets, previous_sets, stamp)
    if event is None:
        return []
    _store_most_reps_event(db, record, event, stamp)
    event["name"] = record.exercise_name or record.exercise_id
    return [event]


def get_progression_signals(db: DatabaseManager) -> str:
    cursor = db.conn.cursor()
    active_program = db.get_active_program()
    target_ceilings = {}
    if active_program:
        for day in active_program.days:
            for ex in day.exercises:
                target_ceilings[str(ex.exercise_id)] = (ex.target_reps_min, ex.target_reps_max, ex.target_rpe or 8.5)

    cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()[:10]
    cursor.execute(
        """
        SELECT DISTINCT ws.exercise_id, e.name, e.equipment
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        JOIN exercises e ON ws.exercise_id = e.id
        WHERE s.session_date >= ? AND ws.is_warmup = 0
        LIMIT 5
    """,
        (cutoff,),
    )

    signals = []
    for ex_id, name, eq in cursor.fetchall():
        history = get_exercise_progression_history(db, ex_id)
        if len(history) >= 2:
            last = history[-1]
            rmin, rmax, rpe_target = target_ceilings.get(str(ex_id), (8, 12, 8.5))
            proj = project_next_load(
                last_weight=last["weight_kg"],
                last_reps=last["reps"],
                last_rpe=last["rpe"],
                target_reps_min=rmin,
                target_reps_max=rmax,
                target_rpe=rpe_target,
                equipment=eq or "barbell",
            )
            if proj["status"] in ("PROGRESSION_UP", "DYNAMIC_UPSCALE") and proj["delta_kg"] > 0:
                signals.append(f"{name}: +{proj['delta_kg']}kg target ({proj['projected_weight']}kg)")
            elif len(history) >= 3 and history[-1]["e1rm"] <= history[-3]["e1rm"]:
                signals.append(f"{name}: Stalled (3 exposures @ ~{last['weight_kg']}kg)")

    if signals:
        return "Progression Targets: " + " | ".join(signals[:3])
    cursor.execute("SELECT 1 FROM workout_sessions LIMIT 1")
    if cursor.fetchone() is None:
        return "Progression: Establishing baseline loads across routine."
    return "Progression: No progression or stall signals in the last 30 days."


def evaluate_systemic_fatigue(db_manager) -> dict[str, Any]:
    cursor = db_manager.conn.cursor()
    cursor.execute("""
        SELECT id, session_date, readiness_score
        FROM workout_sessions
        WHERE readiness_score IS NOT NULL
        ORDER BY session_date DESC, rowid DESC
        LIMIT 5
    """)
    recent_sessions = cursor.fetchall()

    default_result = {
        "deload_recommended": False,
        "severity": "NORMAL",
        "reason": "Fatigue within recoverable limits.",
        "volume_multiplier": 1.0,
        "intensity_cap_rpe": None,
        "recent_readiness_avg": None,
    }
    if not recent_sessions:
        return default_result

    readiness_scores = [row[2] for row in recent_sessions]
    last_3_readiness = readiness_scores[:3]
    avg_readiness_3 = sum(last_3_readiness) / len(last_3_readiness)
    default_result["recent_readiness_avg"] = round(avg_readiness_3, 2)

    session_ids = [row[0] for row in recent_sessions[:3]]
    placeholders = ",".join("?" for _ in session_ids)
    # Effort density is judged on rated sets only (#111): unrated sets are
    # excluded from both the numerator and the denominator, so a blank never
    # reads as 0 and never dilutes the ratio.
    cursor.execute(
        f"SELECT session_id, rpe FROM workout_sets WHERE session_id IN ({placeholders}) AND is_warmup = 0 AND rpe IS NOT NULL",
        session_ids,
    )
    rated_sets = cursor.fetchall()

    high_rpe_count = sum(1 for s in rated_sets if s[1] >= 9.5)
    total_rated_sets = len(rated_sets)
    overshoot_ratio = (high_rpe_count / total_rated_sets) if total_rated_sets > 0 else 0.0

    if len(last_3_readiness) >= 3 and avg_readiness_3 <= 2.0:
        return {
            "deload_recommended": True,
            "severity": "HIGH",
            "reason": f"Rolling readiness crash (avg {avg_readiness_3:.1f}/5 across last 3 sessions).",
            "volume_multiplier": 0.5,
            "intensity_cap_rpe": 7.0,
            "recent_readiness_avg": round(avg_readiness_3, 2),
        }

    if readiness_scores[0] == 1:
        return {
            "deload_recommended": True,
            "severity": "HIGH",
            "reason": "Acute readiness floor (1/5 logged). Systemic recovery compromised.",
            "volume_multiplier": 0.5,
            "intensity_cap_rpe": 7.0,
            "recent_readiness_avg": round(avg_readiness_3, 2),
        }

    if total_rated_sets >= 6 and overshoot_ratio >= 0.50 and avg_readiness_3 <= 3.0:
        return {
            "deload_recommended": True,
            "severity": "MODERATE",
            "reason": f"High exertion density ({overshoot_ratio * 100:.0f}% of recent rated sets at RIR 0.5 or less) alongside declining readiness.",
            "volume_multiplier": 0.6,
            "intensity_cap_rpe": 8.0,
            "recent_readiness_avg": round(avg_readiness_3, 2),
        }

    return default_result
