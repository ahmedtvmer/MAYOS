"""Seeded synthetic coach roster for #139 (no real player data).

Each player is a ``facts`` dict in exactly the shape
``service.coach_ai.gather_player_context`` returns, so the production
``render_context`` renders it. Ground truth for the coach questions in
``arabic_eval_set.json`` is computed here from the same facts.

Players are pseudonymous (``P001``..``P150``). A roster of size N is the first N
players of the fixed 150, so smaller rosters are prefixes of larger ones.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

AS_OF = date(2026, 9, 28)
SEED = 139

PROGRAMS = [
    ("Hypertrophy Block A", "Upper/Lower", 4, [
        ("Upper A", ["Bench Press", "Barbell Row", "Overhead Press", "Lat Pulldown"]),
        ("Lower A", ["Squat", "Romanian Deadlift", "Leg Press", "Calf Raise"]),
        ("Upper B", ["Incline Dumbbell Press", "Pull Up", "Lateral Raise", "Cable Row"]),
        ("Lower B", ["Deadlift", "Front Squat", "Leg Curl", "Hip Thrust"]),
    ]),
    ("Strength Base", "Full Body", 3, [
        ("Full A", ["Squat", "Bench Press", "Barbell Row"]),
        ("Full B", ["Deadlift", "Overhead Press", "Pull Up"]),
        ("Full C", ["Front Squat", "Incline Dumbbell Press", "Cable Row"]),
    ]),
    ("PPL Volume", "Push/Pull/Legs", 6, [
        ("Push", ["Bench Press", "Overhead Press", "Triceps Pushdown"]),
        ("Pull", ["Deadlift", "Lat Pulldown", "Biceps Curl"]),
        ("Legs", ["Squat", "Leg Press", "Leg Curl"]),
    ]),
]
WEEKDAYS_BY_FREQ = {3: [1, 3, 5], 4: [1, 2, 4, 5], 6: [1, 2, 3, 4, 5, 6]}
PR_EXERCISES = ["Squat", "Bench Press", "Deadlift", "Overhead Press"]


def player_id(index: int) -> str:
    return f"P{index + 1:03d}"


def _player(rng: random.Random, index: int) -> dict[str, Any]:
    name, split, freq, days = PROGRAMS[index % len(PROGRAMS)]
    program = {
        "name": name, "split": split, "weekly_frequency": freq, "version": rng.randint(1, 5),
        "days": [
            {"order": order, "day": day,
             "exercises": [{"name": ex, "sets": rng.choice([3, 4]), "reps": rng.choice(["5-8", "6-10", "8-12"]),
                            "rpe": rng.choice([7.0, 7.5, 8.0, 8.5])} for ex in exercises]}
            for order, (day, exercises) in enumerate(days, start=1)
        ],
    }
    # Attendance: a minority of players slip, a few disengage.
    started = AS_OF - timedelta(days=rng.randint(21, 90))
    window_start = max(started, AS_OF - timedelta(days=28))
    expected = max(4, round((AS_OF - window_start).days / 7 * freq))
    profile = rng.random()
    if profile < 0.12:
        streak = rng.randint(3, 7)
        satisfied = rng.randint(1, max(1, expected // 2))
    elif profile < 0.25:
        streak = rng.randint(1, 2)
        satisfied = rng.randint(expected // 2, expected - 1)
    else:
        streak = 0
        satisfied = rng.randint(max(1, int(expected * 0.6)), expected)
    satisfied = min(satisfied, expected - streak)
    missed = expected - satisfied
    # Unique adherence values keep "lowest adherence" unambiguous.
    adherence = round(100.0 * satisfied / expected, 1)
    if streak:
        last_missed = (AS_OF - timedelta(days=1)).isoformat()
    else:
        last_missed = (AS_OF - timedelta(days=rng.randint(2, 20))).isoformat() if missed else None

    sessions = []
    n_sessions = 0 if satisfied == 0 else min(8, satisfied)
    day_cursor = AS_OF - timedelta(days=streak + 1)
    for s in range(n_sessions):
        day_name = days[s % len(days)][0]
        sets = rng.randint(12, 22)
        volume = float(rng.randint(40, 160) * 100)
        divergences = [{"kind": "skipped", "exercise_name": rng.choice(days[s % len(days)][1])}] if rng.random() < 0.15 else []
        sessions.append({"session_date": day_cursor.isoformat(), "split_name": day_name, "sets_count": sets,
                         "total_volume_kg": volume, "readiness_score": rng.randint(2, 5),
                         "program_version": program["version"], "divergences": divergences})
        day_cursor -= timedelta(days=rng.randint(1, 3))
    totals = {"sessions": len(sessions), "sets": sum(s["sets_count"] for s in sessions),
              "volume_kg": sum(s["total_volume_kg"] for s in sessions)}
    vol7 = sum(s["total_volume_kg"] for s in sessions if s["session_date"] >= (AS_OF - timedelta(days=7)).isoformat())

    records = []
    for ex in PR_EXERCISES:
        if ex == "Squat" or rng.random() < 0.5:
            base = {"Squat": 100, "Bench Press": 75, "Deadlift": 130, "Overhead Press": 45}[ex]
            prev = round(base + rng.randint(-20, 60) + rng.choice([0.0, 2.5]), 1)
            value = round(prev + rng.choice([2.5, 5.0, 7.5]), 1)
            records.append({"exercise": ex, "record_type": "e1rm", "reps": rng.choice([3, 5, 6]), "value": value,
                            "prev_value": prev, "achieved_at": (AS_OF - timedelta(days=rng.randint(1, 40))).isoformat()})
    records.sort(key=lambda r: r["achieved_at"], reverse=True)

    alerts = []
    if streak >= 2:
        alerts.append({"kind": "missed_expected_days", "state": "new" if rng.random() < 0.7 else "acknowledged",
                       "created_at": f"{(AS_OF - timedelta(days=1)).isoformat()}T09:00:00+00:00",
                       "streak_start_date": (AS_OF - timedelta(days=streak)).isoformat(), "missed_count": streak})
    if rng.random() < 0.08:
        alerts.append({"kind": "progression_regression", "state": "new", "severity": "warning",
                       "exercise_name": "Bench Press", "e1rm_delta": -5.0, "current_e1rm": 90.0})
    pending = 1 if rng.random() < 0.12 else 0
    kind = rng.choice(["exercise_substitution", "schedule_change", "program_rebuild"])
    follow_up = (AS_OF + timedelta(days=rng.randint(-5, 10))).isoformat() if rng.random() < 0.4 else None

    return {
        "id": player_id(index),
        "facts": {
            "as_of": AS_OF.isoformat(),
            "assignment": {"started_on": started.isoformat(), "status": "active"},
            "program": program,
            "volume": {"last_7_days_kg": vol7, "last_28_days_kg": totals["volume_kg"]},
            "recent_sessions": sessions,
            "recent_sessions_totals": totals,
            "personal_records": records,
            "attendance": {"timezone": "Africa/Cairo", "local_today": AS_OF.isoformat(),
                           "window_start": window_start.isoformat(), "expected_days": expected,
                           "satisfied_days": satisfied, "missed_days": missed, "adherence_pct": adherence,
                           "trailing_missed_streak": streak, "last_missed_on": last_missed},
            "schedule": {"weekdays": WEEKDAYS_BY_FREQ[freq], "timezone": "Africa/Cairo"},
            "pauses": [],
            "alerts": alerts,
            "check_ins": ([{"checked_in_on": (AS_OF - timedelta(days=rng.randint(1, 20))).isoformat(),
                            "channel": rng.choice(["phone", "in_person", "message"])}] if rng.random() < 0.5 else []),
            "program_requests": {"total": pending + rng.randint(0, 2), "pending": pending,
                                 "pending_by_kind": {kind: 1} if pending else {}},
        },
        "roster_row": {
            "player_username": player_id(index),
            "alerts_new": sum(1 for a in alerts if a["state"] == "new"),
            "pending_requests": pending,
            "current_missed_streak": streak,
            "next_follow_up_on": follow_up,
            "last_workout_on": sessions[0]["session_date"] if sessions else None,
        },
    }


def build_players(total: int = 150) -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    # Ties on the lowest adherence are allowed; the scorer accepts any tied ID.
    return [_player(rng, i) for i in range(total)]


def roster(size: int) -> list[dict[str, Any]]:
    """First ``size`` players, in the production roster urgency order."""
    from service.roster_order import roster_urgency_key

    players = build_players()[:size]
    return sorted(players, key=lambda p: roster_urgency_key(p["roster_row"], AS_OF))


def render_roster_full(players: list[dict[str, Any]]) -> str:
    """Full briefing: the production per-player telemetry block for every player."""
    from service.coach_ai import render_context

    blocks = [f"=== player {p['id']} ===\n{render_context(p['facts'])}" for p in players]
    return "[ROSTER TELEMETRY]\nplayers: " + str(len(players)) + " (roster urgency order)\n\n" + "\n\n".join(blocks)


def render_roster_compact(players: list[dict[str, Any]]) -> str:
    """Compact briefing: one deterministic line per player (harness design, not production)."""
    from service.coach_ai import format_number

    lines = ["[ROSTER TELEMETRY]", f"players: {len(players)} (roster urgency order)",
             "columns: id | adherence_pct | trailing_missed_streak | new_alerts | pending_requests | "
             "last_workout_on | latest_squat_e1rm_kg"]
    for p in players:
        f = p["facts"]
        squat = next((r for r in f["personal_records"] if r["exercise"] == "Squat"), None)
        lines.append(" | ".join([
            p["id"], format_number(f["attendance"]["adherence_pct"]),
            format_number(f["attendance"]["trailing_missed_streak"]),
            str(p["roster_row"]["alerts_new"]), str(p["roster_row"]["pending_requests"]),
            p["roster_row"]["last_workout_on"] or "never", format_number(squat["value"]) if squat else "n/a",
        ]))
    return "\n".join(lines)


def needle(players: list[dict[str, Any]]) -> dict[str, Any]:
    return players[int(len(players) * 0.7)]


def roster_truth(players: list[dict[str, Any]]) -> dict[str, Any]:
    att = {p["id"]: p["facts"]["attendance"] for p in players}
    lowest = min(a["adherence_pct"] for a in att.values())
    target = needle(players)
    squat = next(r for r in target["facts"]["personal_records"] if r["exercise"] == "Squat")
    pending = {p["id"] for p in players if p["roster_row"]["pending_requests"]}
    return {
        "streak_ge_3": {pid for pid, a in att.items() if a["trailing_missed_streak"] >= 3},
        "count_adherence_lt_60": sum(1 for a in att.values() if a["adherence_pct"] < 60),
        "pending_requests": pending,
        "count_pending_requests": len(pending),
        "lowest_adherence": {pid for pid, a in att.items() if a["adherence_pct"] == lowest},
        "new_alerts": {p["id"] for p in players if p["roster_row"]["alerts_new"]},
        "needle_squat_pr": squat["value"],
        "needle_id": target["id"],
    }


def single_truth(player: dict[str, Any]) -> dict[str, Any]:
    f = player["facts"]
    squat = next(r for r in f["personal_records"] if r["exercise"] == "Squat")
    return {
        "adherence_pct": f["attendance"]["adherence_pct"],
        "recent_sets": f["recent_sessions_totals"]["sets"],
        "squat_pr_pair": [squat["value"], squat["prev_value"]],
        "volume_7d": f["volume"]["last_7_days_kg"],
        "missed_streak": f["attendance"]["trailing_missed_streak"],
    }
