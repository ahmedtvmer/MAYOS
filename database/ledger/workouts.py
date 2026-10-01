"""LedgerWorkoutsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
import uuid
from pathlib import Path
from datetime import UTC, datetime
from typing import Any
from database.migration_manager import create_atomic_backup
from database.migration_manager import prune_ledger_backups

#: The one committed-working-set definition for records (#122, ADR 042): not a
#: warm-up, with a load and a rep count that can carry a record. The record
#: aggregates, the first-session rule, the ADR 009 history rows, and
#: ``GET /workouts/baselines`` all filter through it, so a device reading a
#: baseline and the server's first-session rule cannot disagree.
#: ``get_last_performance`` deliberately keeps plain ``is_warmup = 0``: a 0 kg
#: bodyweight set is still previous performance and must reach progression.
WORKING_SET_PREDICATE = "ws.is_warmup = 0 AND ws.weight_kg > 0 AND ws.reps > 0"

#: How the "last" session of an exercise is chosen: commit start time, then
#: rowid as a stable tie. Performed-date corrections (ADR 035) rewrite
#: ``session_date`` only, so they can never move this ordering; sharing it
#: keeps ``get_last_performance`` and the baseline ``last_session`` agreeing.
LAST_SESSION_ORDER = "s.started_at DESC, s.rowid DESC"


def _stall_session_key(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "session_id": str(row[0]),
        "session_date": str(row[1]),
        "started_at": str(row[2]),
        "session_order": int(row[3]),
    }


class LedgerWorkoutsMixin:
    def backup_ledger(self) -> Path:
        """Creates an on-demand rolling snapshot of the active player ledger."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        ledger_backup_dir = self.backups_dir / self.ledger_id
        backup_path = ledger_backup_dir / f"{self.ledger_id}_auto_{timestamp}.db"
        create_atomic_backup(self.conn, backup_path)
        prune_ledger_backups(ledger_backup_dir, max_rolling=3)
        return backup_path

    @staticmethod
    def _session_commit_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "client_session_id": str(row[0]),
            "session_id": str(row[1]),
            "response_json": str(row[2]),
            "committed_at": str(row[3]),
        }

    def get_session_commit(self, client_session_id: str) -> dict[str, Any] | None:
        """The stored commit for a client session id, or None when never committed."""
        if not client_session_id:
            return None
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT client_session_id, session_id, response_json, committed_at"
            " FROM session_commits WHERE client_session_id = ?",
            (str(client_session_id),),
        )
        return self._session_commit_from_row(cursor.fetchone())

    def record_session_commit(
        self, client_session_id: str, session_id: str, response_json: str, committed_at: str
    ) -> None:
        """Stores the exact response for a client session id (idempotency record)."""
        self.conn.execute(
            "INSERT INTO session_commits (client_session_id, session_id, response_json, committed_at)"
            " VALUES (?, ?, ?, ?)",
            (str(client_session_id), str(session_id), response_json, committed_at),
        )
        self._commit_ledger()

    def get_workout_session(self, session_id: str) -> dict[str, Any] | None:
        """One session's dates and sync identity, or None when not in this ledger."""
        if not session_id:
            return None
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, session_date, client_session_id, performed_timezone,"
            " captured_at, uploaded_at, edited_at, started_at"
            " FROM workout_sessions WHERE id = ?",
            (str(session_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "session_id": row["id"],
            "session_date": row["session_date"],
            "client_session_id": row["client_session_id"],
            "performed_timezone": row["performed_timezone"],
            "captured_at": row["captured_at"],
            "uploaded_at": row["uploaded_at"],
            "edited_at": row["edited_at"],
            "started_at": row["started_at"],
        }

    def update_session_performed_date(
        self, session_id: str, performed_date: str, edited_at: str
    ) -> None:
        """Rewrites the performed date and stamps ``edited_at``; capture/upload stay."""
        self.conn.execute(
            "UPDATE workout_sessions SET session_date = ?, edited_at = ? WHERE id = ?",
            (str(performed_date), str(edited_at), str(session_id)),
        )
        self._commit_ledger()

    def record_performed_date_correction(
        self, session_id: str, previous_date: str, corrected_date: str, corrected_at: str
    ) -> None:
        """Appends one immutable correction row for a session."""
        self.conn.execute(
            "INSERT INTO performed_date_corrections"
            " (id, session_id, previous_date, corrected_date, corrected_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), str(session_id), str(previous_date), str(corrected_date), str(corrected_at)),
        )
        self._commit_ledger()

    @staticmethod
    def _correction_from_row(row: Any) -> dict[str, Any]:
        return {
            "previous_date": row["previous_date"],
            "corrected_date": row["corrected_date"],
            "corrected_at": row["corrected_at"],
        }

    def list_performed_date_corrections(self, session_id: str) -> list[dict[str, Any]]:
        """Every correction for one session, oldest-first."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT previous_date, corrected_date, corrected_at"
            " FROM performed_date_corrections WHERE session_id = ?"
            " ORDER BY corrected_at ASC, rowid ASC",
            (str(session_id),),
        )
        return [self._correction_from_row(row) for row in cursor.fetchall()]

    def get_session_audit_metadata(self) -> dict[str, dict[str, Any]]:
        """Per-session upload/edit timestamps and correction history, keyed by session id.

        Kept separate from ``get_session_log`` so the ledger export shape is
        unchanged while the coach history can annotate corrections (ADR 035).
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, uploaded_at, edited_at FROM workout_sessions")
        audit: dict[str, dict[str, Any]] = {
            row["id"]: {
                "uploaded_at": row["uploaded_at"],
                "edited_at": row["edited_at"],
                "corrections": [],
            }
            for row in cursor.fetchall()
        }
        cursor.execute(
            "SELECT session_id, previous_date, corrected_date, corrected_at"
            " FROM performed_date_corrections ORDER BY corrected_at ASC, rowid ASC"
        )
        for row in cursor.fetchall():
            entry = audit.get(row["session_id"])
            if entry is not None:
                entry["corrections"].append(self._correction_from_row(row))
        return audit

    def log_workout_session(
        self,
        session_id: str,
        session_date: str,
        split_name: str,
        started_at: str,
        completed_at: str,
        readiness_score: int = 4,
        notes: str = "",
        client_session_id: str | None = None,
        performed_timezone: str | None = None,
        program_version: int | None = None,
        active_program_version_at_sync: int | None = None,
        captured_at: str | None = None,
        uploaded_at: str | None = None,
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO workout_sessions (
                id, session_date, split_name, started_at, completed_at, session_notes, readiness_score,
                client_session_id, performed_timezone, program_version, active_program_version_at_sync,
                captured_at, uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session_id,
                session_date,
                split_name,
                started_at,
                completed_at,
                notes,
                readiness_score,
                client_session_id,
                performed_timezone,
                program_version,
                active_program_version_at_sync,
                captured_at,
                uploaded_at,
            ),
        )
        self._commit_ledger()

    def log_workout_set(
        self,
        set_id: str,
        session_id: str,
        exercise_id: str,
        set_index: int,
        weight_kg: float,
        reps: int,
        rpe: float | None,
        is_warmup: int = 0,
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                set_id,
                session_id,
                exercise_id,
                set_index,
                weight_kg,
                reps,
                rpe,
                is_warmup,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.conn.commit()

    def log_workout_sets_batch(self, sets_payload: list[dict[str, Any]]) -> None:
        """Persists all session sets in a single atomic transaction."""
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (:id, :session_id, :exercise_id, :set_index, :weight_kg, :reps, :rpe, :is_warmup, :logged_at)
        """,
            sets_payload,
        )
        self._commit_ledger()

    def log_session_warmup_movements(
        self, session_id: str, movements: list[dict[str, Any]], logged_at: str
    ) -> None:
        rows = self._warmup_set_rows(session_id, movements, logged_at)
        if not rows:
            return
        self.conn.executemany(
            "INSERT INTO session_warmup_sets ("
            "session_id, movement_index, exercise_id, exercise_name, set_index,"
            " weight_kg, reps, logged_at)"
            " VALUES (:session_id, :movement_index, :exercise_id, :exercise_name,"
            " :set_index, :weight_kg, :reps, :logged_at)",
            rows,
        )
        self._commit_ledger()

    def log_session_cardio(
        self, session_id: str, cardio: dict[str, Any] | None, logged_at: str
    ) -> None:
        """Stores the committed Cardio item outside working-set history."""
        if cardio is None:
            return
        self.conn.execute(
            "INSERT INTO session_cardio (session_id, prescription, minutes, logged_at)"
            " VALUES (?, ?, ?, ?)",
            (session_id, cardio["prescription"], int(cardio["minutes"]), logged_at),
        )
        self._commit_ledger()

    def get_session_cardio(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT prescription, minutes FROM session_cardio WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {"prescription": row["prescription"], "minutes": row["minutes"]}

    def list_session_cardio_by_session(self) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT session_id, prescription, minutes FROM session_cardio"
        ).fetchall()
        return {
            row["session_id"]: {
                "prescription": row["prescription"],
                "minutes": row["minutes"],
            }
            for row in rows
        }

    @staticmethod
    def _warmup_set_rows(
        session_id: str, movements: list[dict[str, Any]], logged_at: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "session_id": session_id,
                "movement_index": movement_index,
                "exercise_id": movement.get("exercise_id"),
                "exercise_name": movement["exercise_name"],
                "set_index": set_index,
                "weight_kg": set_row["weight_kg"],
                "reps": set_row["reps"],
                "logged_at": logged_at,
            }
            for movement_index, movement in enumerate(movements)
            for set_index, set_row in enumerate(movement["sets"], start=1)
        ]

    @staticmethod
    def _group_warmup_set_rows(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, dict[int, dict[str, Any]]] = {}
        for row in rows:
            session_movements = grouped.setdefault(row["session_id"], {})
            movement = session_movements.setdefault(
                row["movement_index"],
                {
                    "exercise_id": row["exercise_id"],
                    "exercise_name": row["exercise_name"],
                    "sets": [],
                },
            )
            movement["sets"].append(
                {"weight_kg": row["weight_kg"], "reps": row["reps"]}
            )
        return {
            session_id: [movements[index] for index in sorted(movements)]
            for session_id, movements in grouped.items()
        }

    def list_session_warmup_movements(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT session_id, movement_index, exercise_id, exercise_name,"
            " set_index, weight_kg, reps FROM session_warmup_sets"
            " WHERE session_id = ? ORDER BY movement_index, set_index",
            (session_id,),
        ).fetchall()
        return self._group_warmup_set_rows(rows).get(session_id, [])

    def list_warmup_movements_by_session(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.conn.execute(
            "SELECT session_id, movement_index, exercise_id, exercise_name,"
            " set_index, weight_kg, reps FROM session_warmup_sets"
            " ORDER BY session_id, movement_index, set_index"
        ).fetchall()
        return self._group_warmup_set_rows(rows)

    def get_latest_committed_session(self) -> dict[str, Any] | None:
        """The player's most recent committed session, for Home's next day (#53).

        Reads only the ledger identity columns. ``split_name`` is the day name
        written at commit; ``day_order`` is not stored on the ledger, so it is
        reported as null and the client matches the program day by name. Ordering
        is by performed date, then commit start time, then rowid as a stable tie.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, session_date, split_name, program_version
            FROM workout_sessions
            ORDER BY session_date DESC, started_at DESC, rowid DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "session_date": row[1],
            "split_name": row[2],
            "day_order": None,
            "program_version": row[3],
            "warmup_movements": self.list_session_warmup_movements(row[0]),
            "cardio": self.get_session_cardio(row[0]),
        }

    def get_latest_session_summary(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, session_date, split_name, readiness_score,
                   program_version, active_program_version_at_sync,
                   uploaded_at, edited_at
            FROM workout_sessions
            ORDER BY session_date DESC, started_at DESC, rowid DESC
            LIMIT 1
        """)
        session = cursor.fetchone()
        if session is None:
            return None

        cursor.execute(
            """
            SELECT COALESCE(e.name, ws.exercise_id) AS name,
                   COUNT(*) AS sets, SUM(ws.reps) AS reps,
                   SUM(ws.weight_kg * ws.reps) AS volume_kg
            FROM workout_sets ws
            LEFT JOIN exercises e ON e.id = ws.exercise_id
            WHERE ws.session_id = ? AND ws.is_warmup = 0
            GROUP BY ws.exercise_id, e.name
            ORDER BY name COLLATE NOCASE, ws.exercise_id
            """,
            (session["id"],),
        )
        exercises = [dict(row) for row in cursor.fetchall()]
        return {
            "session_id": session["id"],
            "session_date": session["session_date"],
            "split_name": session["split_name"],
            "readiness_score": session["readiness_score"],
            "program_version": session["program_version"],
            "active_program_version_at_sync": session["active_program_version_at_sync"],
            "uploaded_at": session["uploaded_at"],
            "edited_at": session["edited_at"],
            "corrections": self.list_performed_date_corrections(session["id"]),
            "warmup_movements": self.list_session_warmup_movements(session["id"]),
            "cardio": self.get_session_cardio(session["id"]),
            "sets_count": sum(exercise["sets"] for exercise in exercises),
            "total_volume_kg": sum((exercise["volume_kg"] for exercise in exercises), 0.0),
            "exercises": exercises,
            "divergences": [
                {
                    "kind": row["kind"],
                    "exercise_id": row["exercise_id"],
                    "exercise_name": row["exercise_name"],
                }
                for row in self.list_session_divergences(session["id"])
            ],
        }

    def get_session_program_versions(self) -> dict[str, dict[str, Any]]:
        """Per-session program version and the active version at sync, keyed by session id (ADR 034).

        Kept separate from ``get_session_log`` so the ledger export shape is
        unchanged while the coach history can annotate version differences. The
        derived ``is_historical_program`` flag is computed in the service layer,
        not here.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, program_version, active_program_version_at_sync FROM workout_sessions")
        return {
            row["id"]: {
                "program_version": row["program_version"],
                "active_program_version_at_sync": row["active_program_version_at_sync"],
            }
            for row in cursor.fetchall()
        }

    def list_performed_dates(self) -> list[str]:
        """One local date per committed session, oldest-first, including duplicates.

        Two workouts on the same day are two performed dates so attendance can
        satisfy two expected days, one per workout (ADR 030).
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT session_date FROM workout_sessions ORDER BY session_date ASC")
        return [str(row[0]) for row in cursor.fetchall()]

    def stall_recount_facts(self, program_version: int, exercise_ids: list[str], limit: int) -> dict[str, Any]:
        """Recent committed sessions and reset points for the active program's stall length.

        The bounded session window is supplied by the stall evaluator. The two
        anchors are queried across the full ledger so a long-running program or
        an older personal record still gives the correct start point.
        """
        if not exercise_ids:
            return {"first_program_session": None, "latest_record_session": None, "sessions": []}
        placeholders = ",".join("?" for _ in exercise_ids)
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, session_date, started_at, rowid FROM workout_sessions"
            " WHERE program_version = ? ORDER BY session_date, started_at, rowid LIMIT 1",
            (int(program_version),),
        )
        first_row = cursor.fetchone()
        cursor.execute(
            "SELECT s.id, s.session_date, s.started_at, s.program_version, s.rowid"
            " FROM workout_sessions s ORDER BY s.session_date DESC, s.started_at DESC, s.rowid DESC LIMIT ?",
            [max(1, int(limit))],
        )
        sessions = [
            {
                "session_id": str(row[0]),
                "session_date": str(row[1]),
                "started_at": str(row[2]),
                "program_version": row[3],
                "session_order": int(row[4]),
                "has_record": False,
            }
            for row in cursor.fetchall()
        ]
        e1rm_record_sessions: set[str] = set()
        prior_weight: dict[str, float] = {}
        session_weights: dict[str, dict[str, float]] = {}
        if sessions:
            earliest = sessions[-1]
            before_window = (
                "(s.session_date < ? OR (s.session_date = ? AND s.started_at < ?)"
                " OR (s.session_date = ? AND s.started_at = ? AND s.rowid < ?))"
            )
            cursor.execute(
                "SELECT ws.exercise_id, MAX(ws.weight_kg)"
                " FROM workout_sets ws JOIN workout_sessions s ON s.id = ws.session_id"
                f" WHERE ws.exercise_id IN ({placeholders}) AND {WORKING_SET_PREDICATE}"
                f" AND {before_window} GROUP BY ws.exercise_id",
                [
                    *exercise_ids,
                    earliest["session_date"],
                    earliest["session_date"],
                    earliest["started_at"],
                    earliest["session_date"],
                    earliest["started_at"],
                    earliest["session_order"],
                ],
            )
            prior_weight = {str(exercise_id): float(value) for exercise_id, value in cursor.fetchall()}
            cursor.execute(
                "SELECT DISTINCT pr.session_id"
                " FROM personal_records pr JOIN workout_sessions s ON s.id = pr.session_id"
                f" WHERE pr.exercise_id IN ({placeholders}) AND pr.record_type = 'max_e1rm'"
                " AND s.id IN (" + ",".join("?" for _ in sessions) + ")"
                " ORDER BY s.session_date, s.started_at, s.rowid",
                [*exercise_ids, *[session["session_id"] for session in sessions]],
            )
            e1rm_record_sessions = {str(row[0]) for row in cursor.fetchall()}
            cursor.execute(
                "SELECT ws.session_id, ws.exercise_id, MAX(ws.weight_kg)"
                " FROM workout_sets ws"
                f" WHERE ws.exercise_id IN ({placeholders}) AND {WORKING_SET_PREDICATE}"
                " AND ws.session_id IN (" + ",".join("?" for _ in sessions) + ")"
                " GROUP BY ws.session_id, ws.exercise_id",
                [*exercise_ids, *[session["session_id"] for session in sessions]],
            )
            for session_id, exercise_id, max_weight in cursor.fetchall():
                session_weights.setdefault(str(session_id), {})[str(exercise_id)] = float(max_weight)
            latest_rows = sorted(sessions, key=lambda session: (session["session_date"], session["started_at"], session["session_order"]))
            for session in latest_rows:
                for exercise_id, value in session_weights.get(session["session_id"], {}).items():
                    if exercise_id in prior_weight and value > prior_weight[exercise_id]:
                        session["has_record"] = True
                    prior_weight[exercise_id] = max(prior_weight.get(exercise_id, value), value)
                if session["session_id"] in e1rm_record_sessions:
                    session["has_record"] = True
        session_ids = [session["session_id"] for session in sessions]
        if session_ids:
            session_placeholders = ",".join("?" for _ in session_ids)
            cursor.execute(
                "SELECT session_id, response_json FROM session_commits"
                f" WHERE session_id IN ({session_placeholders})",
                session_ids,
            )
            committed_records: dict[str, set[str]] = {}
            for session_id, response_json in cursor.fetchall():
                try:
                    events = json.loads(response_json).get("new_prs", [])
                except (TypeError, ValueError):
                    events = []
                committed_records[str(session_id)] = {
                    str(event.get("exercise_id"))
                    for event in events
                    if isinstance(event, dict) and event.get("exercise_id")
                }
            for session in sessions:
                if session["session_id"] in committed_records:
                    session["has_record"] = bool(
                        committed_records[session["session_id"]].intersection(exercise_ids)
                    )
        latest_record = next((session for session in sessions if session["has_record"]), None)
        return {
            "first_program_session": _stall_session_key(first_row),
            "latest_record_session": _stall_session_key(
                (
                    latest_record["session_id"],
                    latest_record["session_date"],
                    latest_record["started_at"],
                    latest_record["session_order"],
                )
                if latest_record
                else None
            ),
            "sessions": sessions,
        }

    def get_session_log(self) -> list[dict[str, Any]]:
        """Chronological session→set rows (exercise names resolved) for ledger export.

        Returns a flat, one-row-per-set list; grouping/nesting happens in the service layer.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT s.id AS session_id, s.session_date, s.split_name, s.readiness_score,
                   s.session_notes, s.started_at, s.completed_at,
                   ws.exercise_id, COALESCE(e.name, ws.exercise_id) AS exercise_name,
                   ws.set_index, ws.weight_kg, ws.reps, ws.rpe, ws.is_warmup, ws.logged_at
            FROM workout_sets ws
            JOIN workout_sessions s ON ws.session_id = s.id
            LEFT JOIN exercises e ON e.id = ws.exercise_id
            ORDER BY s.session_date ASC, s.started_at ASC, s.rowid ASC, ws.rowid ASC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def record_session_divergences(
        self, session_id: str, divergences: list[dict[str, Any]], now_iso: str
    ) -> None:
        """Persists the prescribed-vs-performed differences for one session.

        Recording is factual history only and never touches the training program
        (ADR 018/028). An empty batch is accepted and writes nothing. A duplicate
        fact is the same fact, so conflicting inserts are ignored rather than
        failing.
        """
        if not divergences:
            return
        payload = [
            {
                "session_id": session_id,
                "exercise_id": str(divergence["exercise_id"]),
                "exercise_name": divergence["exercise_name"],
                "kind": divergence["kind"],
                "created_at": now_iso,
            }
            for divergence in divergences
        ]
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO session_divergences (
                session_id, exercise_id, exercise_name, kind, created_at
            ) VALUES (:session_id, :exercise_id, :exercise_name, :kind, :created_at)
        """,
            payload,
        )
        self._commit_ledger()

    def list_session_divergences(self, session_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT sd.session_id, sd.exercise_id,
                   COALESCE(e.name, sd.exercise_name) AS exercise_name, sd.kind, sd.created_at
            FROM session_divergences sd
            LEFT JOIN exercises e ON e.id = sd.exercise_id
            WHERE sd.session_id = ?
            ORDER BY kind ASC, exercise_id ASC
        """,
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_divergences_by_session(self) -> dict[str, list[dict[str, Any]]]:
        """Every session's divergences keyed by session id, in a single query."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT sd.session_id, sd.exercise_id,
                   COALESCE(e.name, sd.exercise_name) AS exercise_name, sd.kind
            FROM session_divergences sd
            LEFT JOIN exercises e ON e.id = sd.exercise_id
            ORDER BY sd.kind ASC, sd.exercise_id ASC
        """)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in cursor.fetchall():
            grouped.setdefault(row["session_id"], []).append(
                {
                    "kind": row["kind"],
                    "exercise_id": row["exercise_id"],
                    "exercise_name": row["exercise_name"],
                }
            )
        return grouped

    def working_set_rows(
        self,
        exercise_id: str | None = None,
        *,
        exclude_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Every committed working set, optionally scoped to one exercise (#122).

        The single query behind the record aggregates (ADR 042): callers group
        or aggregate these rows, so the working-set definition cannot drift
        between the commit comparison, the ADR 009 history rows, and
        ``GET /workouts/baselines``.
        """
        sql = (
            "SELECT ws.exercise_id, ws.session_id, ws.weight_kg, ws.reps, ws.rpe"
            " FROM workout_sets ws"
            " JOIN workout_sessions s ON ws.session_id = s.id"
            f" WHERE {WORKING_SET_PREDICATE}"
        )
        params: list[Any] = []
        if exercise_id is not None:
            sql += " AND ws.exercise_id = ?"
            params.append(exercise_id)
        if exclude_session_id is not None:
            sql += " AND ws.session_id <> ?"
            params.append(exclude_session_id)
        sql += " ORDER BY ws.exercise_id ASC, ws.rowid ASC"
        cursor = self.conn.cursor()
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def baseline_last_sessions(self) -> list[dict[str, Any]]:
        """Each exercise's latest committed session and that session's working sets.

        One window-function query for the whole ledger (#122), so ``GET
        /workouts/baselines`` stays bounded in queries rather than one per
        exercise. The latest session is chosen by :data:`LAST_SESSION_ORDER` —
        the same order ``get_last_performance`` uses — so an ADR 035
        performed-date correction cannot make the two disagree. Rows arrive
        grouped by exercise, in logged order (``set_index``, then rowid).
        """
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            WITH ranked AS (
                SELECT ws.exercise_id, ws.session_id, s.session_date,
                       ws.set_index, ws.rowid AS set_rowid,
                       ws.weight_kg, ws.reps, ws.rpe,
                       DENSE_RANK() OVER (
                           PARTITION BY ws.exercise_id ORDER BY {LAST_SESSION_ORDER}
                       ) AS session_rank
                FROM workout_sets ws
                JOIN workout_sessions s ON ws.session_id = s.id
                WHERE {WORKING_SET_PREDICATE}
            )
            SELECT exercise_id, session_id, session_date, set_index, weight_kg, reps, rpe
            FROM ranked
            WHERE session_rank = 1
            ORDER BY exercise_id ASC, set_index ASC, set_rowid ASC
        """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_last_performance(self, exercise_id: str) -> list[dict[str, Any]]:
        """The exercise's most recent non-warm-up sets, for previous performance.

        Deliberately not :data:`WORKING_SET_PREDICATE`: bodyweight exercises log
        0 kg working sets, and previous performance / progression must keep
        seeing them. Records and ``GET /workouts/baselines`` use the stricter
        definition. The session is chosen with the shared
        :data:`LAST_SESSION_ORDER`, so it cannot disagree with the baseline
        ``last_session`` after an ADR 035 performed-date correction.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT s.id
            FROM workout_sessions s
            JOIN workout_sets ws ON ws.session_id = s.id
            WHERE ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY {LAST_SESSION_ORDER}
            LIMIT 1
        """,
            (exercise_id,),
        )
        session_row = cursor.fetchone()
        if not session_row:
            return []

        cursor.execute(
            """
            SELECT ws.set_index, ws.weight_kg, ws.reps, ws.rpe
            FROM workout_sets ws
            WHERE ws.session_id = ? AND ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY ws.set_index ASC
        """,
            (session_row[0], exercise_id),
        )
        return [dict(r) for r in cursor.fetchall()]
