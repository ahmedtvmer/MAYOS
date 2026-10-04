"""RegistryCoachAlertsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
from typing import Any


class RegistryCoachAlertsMixin:
    _COACH_ALERT_COLUMNS = (
        "alert_id, assignment_id, coach_account_id, player_account_id, kind,"
        " dedupe_key, details, state, created_at, acknowledged_at, resolved_at, resolved_by"
    )

    @classmethod
    def _coach_alert_from_row(cls, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            details = json.loads(row[6]) if row[6] else {}
        except (TypeError, ValueError):
            details = {}
        if not isinstance(details, dict):
            details = {}
        # The kind-specific fields stay under ``details`` here; the service layer
        # flattens them into the API response shape (ADR 031).
        return {
            "alert_id": str(row[0]),
            "assignment_id": str(row[1]),
            "coach_account_id": str(row[2]),
            "player_account_id": str(row[3]),
            "kind": str(row[4]),
            "dedupe_key": str(row[5]),
            "details": details,
            "state": str(row[7]),
            "created_at": str(row[8]),
            "acknowledged_at": row[9],
            "resolved_at": row[10],
            "resolved_by": row[11],
        }

    def insert_coach_alert(
        self,
        alert_id: str,
        assignment_id: str,
        coach_account_id: str,
        player_account_id: str,
        kind: str,
        dedupe_key: str,
        details: dict[str, Any],
        now_iso: str,
    ) -> dict[str, Any]:
        """Inserts one alert for a dedupe key, ignoring a retry of the same key.

        Returns ``{"alert": ..., "created": bool}``. The unique
        ``(assignment_id, kind, dedupe_key)`` key means a concurrent or repeated
        sweep cannot create a second alert for one recurring fact.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO coach_alerts"
                " (alert_id, assignment_id, coach_account_id, player_account_id, kind,"
                " dedupe_key, details, state, created_at, acknowledged_at, resolved_at, resolved_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, NULL, NULL, NULL)",
                (
                    str(alert_id),
                    str(assignment_id),
                    str(coach_account_id),
                    str(player_account_id),
                    str(kind),
                    str(dedupe_key),
                    json.dumps(details),
                    now_iso,
                ),
            )
            created = cursor.rowcount == 1
            self._commit_catalog()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE assignment_id = ? AND kind = ? AND dedupe_key = ?",
                (str(assignment_id), str(kind), str(dedupe_key)),
            )
            return {"alert": self._coach_alert_from_row(cursor.fetchone()), "created": created}

    def get_coach_alert_by_dedupe(
        self, assignment_id: str, kind: str, dedupe_key: str
    ) -> dict[str, Any] | None:
        """The alert for one exact ``(assignment, kind, dedupe_key)``, or ``None``.

        Read-only, so an episode extension can look the open alert up without
        risking the creation of a new one (ADR 032).
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE assignment_id = ? AND kind = ? AND dedupe_key = ?",
                (str(assignment_id), str(kind), str(dedupe_key)),
            )
            return self._coach_alert_from_row(cursor.fetchone())

    def get_coach_alert(self, alert_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts WHERE alert_id = ?",
                (str(alert_id),),
            )
            return self._coach_alert_from_row(cursor.fetchone())

    def list_coach_alerts(self, coach_account_id: str, states: tuple[str, ...]) -> list[dict[str, Any]]:
        """Alerts for a coach's still-active assignments only, newest-first, with the player name."""
        self.ensure_account_schema()
        if not states:
            return []
        placeholders = ", ".join("?" for _ in states)
        columns = ", ".join("c." + column for column in self._COACH_ALERT_COLUMNS.split(", "))
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {columns}, acc.username"
                " FROM coach_alerts c"
                " JOIN assignments a ON a.assignment_id = c.assignment_id AND a.status = 'active'"
                " JOIN accounts acc ON acc.account_id = c.player_account_id"
                f" WHERE c.coach_account_id = ? AND c.state IN ({placeholders})"
                " ORDER BY c.created_at DESC, c.rowid DESC",
                (str(coach_account_id), *states),
            )
            alerts = []
            for row in cursor.fetchall():
                alert = self._coach_alert_from_row(row)
                alert["player_username"] = str(row[12])
                alerts.append(alert)
            return alerts

    def update_coach_alert_details(self, alert_id: str, details: dict[str, Any]) -> int:
        """Extends an open alert's kind-specific fields; a no-op reports ``rowcount == 0``."""
        self.ensure_account_schema()
        encoded = json.dumps(details)
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET details = ?"
                " WHERE alert_id = ? AND state IN ('new', 'acknowledged')"
                " AND details != ?",
                (encoded, str(alert_id), encoded),
            )
            self._commit_catalog()
            return int(cursor.rowcount)

    def acknowledge_coach_alert_transition(
        self, alert_id: str, coach_account_id: str, now_iso: str
    ) -> tuple[dict[str, Any] | None, bool]:
        """Moves ``new`` → ``acknowledged``; already-acknowledged and resolved are left as-is.

        Returns the alert for its owning coach, or ``None`` when it does not
        belong to that coach.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'acknowledged', acknowledged_at = ?"
                " WHERE alert_id = ? AND coach_account_id = ? AND state = 'new'",
                (now_iso, str(alert_id), str(coach_account_id)),
            )
            transitioned = cursor.rowcount == 1
            self._commit_catalog()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE alert_id = ? AND coach_account_id = ?",
                (str(alert_id), str(coach_account_id)),
            )
            alert = self._coach_alert_from_row(cursor.fetchone())
            return alert, transitioned

    def resolve_coach_alert_transition(
        self, alert_id: str, coach_account_id: str, now_iso: str, resolved_by: str
    ) -> tuple[dict[str, Any] | None, bool]:
        """Moves ``new``/``acknowledged`` → ``resolved``; already-resolved is left as-is.

        Returns the alert for its owning coach, or ``None`` when it does not
        belong to that coach.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'resolved', resolved_at = ?, resolved_by = ?"
                " WHERE alert_id = ? AND coach_account_id = ? AND state IN ('new', 'acknowledged')",
                (now_iso, str(resolved_by), str(alert_id), str(coach_account_id)),
            )
            transitioned = cursor.rowcount == 1
            self._commit_catalog()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE alert_id = ? AND coach_account_id = ?",
                (str(alert_id), str(coach_account_id)),
            )
            alert = self._coach_alert_from_row(cursor.fetchone())
            return alert, transitioned

    def resolve_open_coach_alerts_for_assignment(
        self,
        assignment_id: str,
        now_iso: str,
        kind: str,
        except_dedupe_key: str | None = None,
    ) -> int:
        """Auto-resolves open alerts of one kind when their dedupe key is no longer current.

        With ``except_dedupe_key`` set, only alerts for a different key are
        resolved, so a continuing fact's alert is updated rather than closed.
        Scoping to ``kind`` keeps resolutions from crossing alert kinds.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'resolved', resolved_at = ?, resolved_by = 'system'"
                " WHERE assignment_id = ? AND kind = ? AND state IN ('new', 'acknowledged')"
                " AND (? IS NULL OR dedupe_key != ?)",
                (now_iso, str(assignment_id), str(kind), except_dedupe_key, except_dedupe_key),
            )
            self._commit_catalog()
            return int(cursor.rowcount)

    def resolve_open_coach_alerts_for_dedupe(
        self, assignment_id: str, kind: str, dedupe_key: str, now_iso: str
    ) -> int:
        """Auto-resolves the open alert for one exact dedupe key (ADR 032).

        Used by a progression episode close: each exercise's alert carries its own
        ``<subject>:<episode_key>`` dedupe key, so resolving by key closes only
        that episode's alert, never a sibling exercise's.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'resolved', resolved_at = ?, resolved_by = 'system'"
                " WHERE assignment_id = ? AND kind = ? AND dedupe_key = ?"
                " AND state IN ('new', 'acknowledged')",
                (now_iso, str(assignment_id), str(kind), str(dedupe_key)),
            )
            self._commit_catalog()
            return int(cursor.rowcount)

    _ALERT_SIGNAL_STATE_COLUMNS = "assignment_id, kind, subject, active, episode_key"

    @classmethod
    def _alert_signal_state_from_row(cls, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "assignment_id": str(row[0]),
            "kind": str(row[1]),
            "subject": str(row[2]),
            "active": int(row[3]),
            "episode_key": row[4],
        }

    def get_alert_signal_state(self, assignment_id: str, kind: str, subject: str) -> dict[str, Any] | None:
        """The episode state for one (assignment, kind, subject), or ``None``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ALERT_SIGNAL_STATE_COLUMNS} FROM alert_signal_state"
                " WHERE assignment_id = ? AND kind = ? AND subject = ?",
                (str(assignment_id), str(kind), str(subject)),
            )
            return self._alert_signal_state_from_row(cursor.fetchone())

    def upsert_alert_signal_state(
        self,
        assignment_id: str,
        kind: str,
        subject: str,
        active: int,
        episode_key: str | None,
        now_iso: str,
    ) -> None:
        """Opens, extends, or closes one episode state row."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO alert_signal_state"
                " (assignment_id, kind, subject, active, episode_key, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(assignment_id, kind, subject) DO UPDATE SET"
                " active = excluded.active,"
                " episode_key = excluded.episode_key,"
                " updated_at = excluded.updated_at",
                (str(assignment_id), str(kind), str(subject), int(active), episode_key, now_iso),
            )
            self._commit_catalog()

    def is_progression_session_processed(self, assignment_id: str, session_id: str) -> bool:
        """Whether this session's progression signals were already evaluated (ADR 032)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT 1 FROM progression_alert_sessions"
                " WHERE assignment_id = ? AND session_id = ?",
                (str(assignment_id), str(session_id)),
            )
            return cursor.fetchone() is not None

    def mark_progression_session_processed(
        self, assignment_id: str, session_id: str, now_iso: str
    ) -> None:
        """Records a processed session in the same transaction as its alert changes (ADR 032)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO progression_alert_sessions"
                " (assignment_id, session_id, processed_at) VALUES (?, ?, ?)",
                (str(assignment_id), str(session_id), now_iso),
            )
            self._commit_catalog()

    def is_stall_session_processed(self, assignment_id: str, session_id: str) -> bool:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT 1 FROM stall_alert_sessions WHERE assignment_id = ? AND session_id = ?",
                (str(assignment_id), str(session_id)),
            )
            return cursor.fetchone() is not None

    def mark_stall_session_processed(self, assignment_id: str, session_id: str, now_iso: str) -> None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO stall_alert_sessions"
                " (assignment_id, session_id, processed_at) VALUES (?, ?, ?)",
                (str(assignment_id), str(session_id), now_iso),
            )
            self._commit_catalog()
