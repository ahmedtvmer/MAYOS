"""LedgerDebriefsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import sqlite3
from typing import Any


class LedgerDebriefsMixin:
    BEST_SET_CONVENTION = "heaviest weight, then most reps, then earliest set_index"

    _SESSION_ORDER = "session_date DESC, started_at DESC, rowid DESC"

    @staticmethod
    def _session_metadata(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_date": row["session_date"],
            "started_at": row["started_at"],
            "split_name": row["split_name"],
            "readiness_score": row["readiness_score"],
            "session_notes": row["session_notes"],
        }

    @staticmethod
    def _aggregate_sets(sets: list[dict[str, Any]]) -> dict[str, Any]:
        if not sets:
            return {
                "sets": [],
                "sets_count": 0,
                "total_reps": 0,
                "volume_kg": 0.0,
                "best_set": None,
                "e1rm": None,
            }
        best = max(sets, key=lambda s: (s["weight_kg"], s["reps"], -s["set_index"]))
        e1rm = None
        if best["rpe"] is not None and best["weight_kg"] > 0:
            from agent.progression_engine import calculate_e1rm

            e1rm = calculate_e1rm(best["weight_kg"], best["reps"], best["rpe"])
        return {
            "sets": [
                {"set_index": s["set_index"], "weight_kg": s["weight_kg"], "reps": s["reps"], "rpe": s["rpe"]}
                for s in sets
            ],
            "sets_count": len(sets),
            "total_reps": sum(s["reps"] for s in sets),
            "volume_kg": sum(s["weight_kg"] * s["reps"] for s in sets),
            "best_set": {
                "set_index": best["set_index"],
                "weight_kg": best["weight_kg"],
                "reps": best["reps"],
                "rpe": best["rpe"],
            },
            "e1rm": e1rm,
        }

    @staticmethod
    def _deltas(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        return {
            "load_kg": current["best_set"]["weight_kg"] - previous["best_set"]["weight_kg"],
            "reps": current["best_set"]["reps"] - previous["best_set"]["reps"],
            "sets": current["sets_count"] - previous["sets_count"],
            "volume_kg": current["volume_kg"] - previous["volume_kg"],
            "e1rm": (current["e1rm"] - previous["e1rm"]) if current["e1rm"] is not None and previous["e1rm"] is not None else None,
        }

    @staticmethod
    def _status(current: dict[str, Any], previous: dict[str, Any]) -> str:
        if current["best_set"]["rpe"] is None or previous["best_set"]["rpe"] is None:
            return "insufficient_data"
        deltas = DatabaseManager._deltas(current, previous)
        signs = {
            (delta > 0) - (delta < 0)
            for key in ("load_kg", "reps", "e1rm")
            if (delta := deltas[key]) is not None
        }
        signs.discard(0)
        if not signs:
            return "unchanged"
        if signs == {1}:
            return "improvement"
        if signs == {-1}:
            return "decline"
        return "mixed"

    def _fetch_session_sets(self, session_id: str, exercise_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT ws.set_index, ws.weight_kg, ws.reps, ws.rpe
            FROM workout_sets ws
            WHERE ws.session_id = ? AND ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY ws.set_index ASC
        """,
            (session_id, exercise_id),
        )
        return [dict(r) for r in cursor.fetchall()]

    def _fetch_previous_session_for_exercise(
        self, exercise_id: str, current_session: sqlite3.Row
    ) -> sqlite3.Row | None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT s.id, s.session_date, s.started_at, s.split_name,
                   s.readiness_score, s.session_notes
            FROM workout_sessions s
            WHERE (s.session_date, s.started_at, s.rowid) < (?, ?, ?)
              AND EXISTS (
                  SELECT 1 FROM workout_sets ws
                  WHERE ws.session_id = s.id AND ws.exercise_id = ? AND ws.is_warmup = 0
              )
            ORDER BY s.session_date DESC, s.started_at DESC, s.rowid DESC
            LIMIT 1
            """,
            (current_session["session_date"], current_session["started_at"], current_session["session_rowid"], exercise_id),
        )
        return cursor.fetchone()

    def get_session_comparison_context(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT id, session_date, started_at, split_name, readiness_score,
                   session_notes, rowid AS session_rowid
            FROM workout_sessions ORDER BY {self._SESSION_ORDER} LIMIT 2
        """)
        sessions = cursor.fetchall()
        if not sessions:
            return None
        latest = sessions[0]
        metadata = self._session_metadata(latest)
        prev_metadata = self._session_metadata(sessions[1]) if len(sessions) > 1 else None

        cursor.execute(
            """
            SELECT DISTINCT ws.exercise_id, COALESCE(e.name, ws.exercise_id) AS name
            FROM workout_sets ws
            LEFT JOIN catalog.exercises e ON e.id = ws.exercise_id
            WHERE ws.session_id = ? AND ws.is_warmup = 0
            ORDER BY name COLLATE NOCASE, ws.exercise_id
        """,
            (latest["id"],),
        )
        exercise_rows = cursor.fetchall()

        exercises = []
        for ex_row in exercise_rows:
            exercise_id, name = ex_row["exercise_id"], ex_row["name"]
            current = self._aggregate_sets(self._fetch_session_sets(latest["id"], exercise_id))
            previous_session = self._fetch_previous_session_for_exercise(exercise_id, latest)
            previous = None
            if previous_session is not None:
                previous = self._aggregate_sets(self._fetch_session_sets(previous_session["id"], exercise_id))
                previous["session"] = self._session_metadata(previous_session)

            if previous is None:
                deltas = {"load_kg": None, "reps": None, "sets": None, "volume_kg": None, "e1rm": None}
                status = "insufficient_data"
            else:
                deltas = self._deltas(current, previous)
                status = self._status(current, previous)

            exercises.append(
                {
                    "exercise_id": exercise_id,
                    "name": name,
                    "current": current,
                    "previous": previous,
                    "deltas": deltas,
                    "status": status,
                }
            )

        return {
            "best_set_convention": self.BEST_SET_CONVENTION,
            "session": metadata,
            "previous_session": prev_metadata,
            "exercises": exercises,
        }

    def save_session_debrief(self, session_id: str, debrief: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE workout_sessions SET coach_debrief = ? WHERE id = ?", (debrief.strip(), session_id))
        self._commit_ledger()

    def get_session_debrief(self, session_id: str) -> str | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT coach_debrief FROM workout_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_compact_telemetry(self) -> str:
        prof = self.get_user_profile() or {}
        gender = prof.get("gender", "male").capitalize()
        age = prof.get("age", "?")
        wt = prof.get("weight_kg", "?")
        ht = prof.get("height_cm", "?")
        props = prof.get("proportions", "balanced").replace("_", " ")
        goal = prof.get("current_goal", "Hypertrophy")
        rep_bias = prof.get("rep_preference", "balanced")

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT program_name, weekly_frequency, split_type
            FROM training_programs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1
        """)
        prog_row = cursor.fetchone()
        prog_str = f"{prog_row[0]} ({prog_row[1]}d/wk {prog_row[2]})" if prog_row else "None"

        cursor.execute(
            "SELECT id, session_date, split_name, readiness_score FROM workout_sessions ORDER BY session_date DESC, started_at DESC LIMIT 1"
        )
        last_session = cursor.fetchone()
        if last_session:
            s_id, s_date, s_split, s_readiness = last_session
            cursor.execute(
                """
                SELECT e.name, ws.weight_kg, ws.reps, ws.rpe
                FROM workout_sets ws JOIN catalog.exercises e ON ws.exercise_id = e.id
                WHERE ws.session_id = ? AND ws.is_warmup = 0 ORDER BY ws.weight_kg DESC LIMIT 1
            """,
                (s_id,),
            )
            top_set = cursor.fetchone()
            top_str = f" | Top: {top_set[0]} {top_set[1]}kg x {top_set[2]} @ RPE {top_set[3]}" if top_set else ""
            last_str = f"{s_split} ({s_date}) | Readiness: {s_readiness}/5{top_str}"
        else:
            last_str = "No recorded sessions yet in ledger."

        from agent.progression_engine import (
            evaluate_systemic_fatigue,
            get_progression_signals,
        )

        fatigue_state = evaluate_systemic_fatigue(self)
        if fatigue_state["deload_recommended"]:
            fatigue_line = f"Systemic State: DELOAD RECOMMENDED ({fatigue_state['reason']} | Cap RPE at {fatigue_state['intensity_cap_rpe']})"
        else:
            fatigue_line = (
                f"Systemic State: Recovered (Rolling Readiness: {fatigue_state['recent_readiness_avg'] or 'N/A'}/5)"
            )

        return (
            "[TRAINEE TELEMETRY & SYSTEM STATE]\n"
            f"Trainee: {gender}, {age}yo | {wt}kg @ {ht}cm | Build: {props}\n"
            f"Goal: {goal} | Rep Bias: {rep_bias} | Routine: {prog_str}\n"
            f"Last Session: {last_str}\n"
            f"{get_progression_signals(self)}\n"
            f"{fatigue_line}"
        )


# Alias so moved bodies that referenced ``DatabaseManager._x`` stay byte-identical.
DatabaseManager = LedgerDebriefsMixin
