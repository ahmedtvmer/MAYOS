"""RegistryModelUsageMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from utils.utc_day import utc_day_bounds, utc_day_start_iso

#: Model usage recorded under this purpose is metered and costed but never
#: counts toward an account's daily token allowance (ADR 052).
ALLOWANCE_EXEMPT_PURPOSE = "checkpoint_review"
ALLOWANCE_RESERVATION_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class AllowanceReservation:
    account_id: str
    capability: Literal["lifter", "coach"]
    purpose: str | None
    turn_id: str
    request_limit: int
    resource_limit: int


class RegistryModelUsageMixin:
    _MODEL_USAGE_COLUMNS = (
        "id, account_id, turn_id, role, model, purpose, input_tokens, cached_input_tokens, "
        "output_tokens, estimated, cost_usd, created_at"
    )

    @staticmethod
    def _model_usage_from_row(row: Any) -> dict[str, Any]:
        return {
            "id": str(row[0]),
            "account_id": row[1],
            "turn_id": row[2],
            "role": str(row[3]),
            "model": str(row[4]),
            "purpose": row[5],
            "input_tokens": int(row[6]),
            "cached_input_tokens": int(row[7]),
            "output_tokens": int(row[8]),
            "estimated": bool(row[9]),
            "cost_usd": float(row[10]),
            "created_at": str(row[11]),
        }

    def record_model_usage(
        self,
        account_id: str | None,
        role: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        estimated: bool,
        purpose: str | None = None,
        created_at: str | None = None,
        turn_id: str | None = None,
        cached_input_tokens: int = 0,
    ) -> None:
        """Appends one metered model call to the catalog.

        ``account_id`` is ``None`` only for an unattributed call (startup/eval).
        A write failure propagates; the metering callback catches it so inference
        is never broken (ADR 038).
        """
        self.ensure_account_schema()
        row = (
            uuid.uuid4().hex,
            str(account_id) if account_id else None,
            str(turn_id) if turn_id else None,
            str(role or "unknown"),
            str(model),
            str(purpose) if purpose else None,
            max(0, int(input_tokens)),
            min(max(0, int(input_tokens)), max(0, int(cached_input_tokens))),
            max(0, int(output_tokens)),
            1 if estimated else 0,
            float(cost_usd or 0.0),
            created_at or datetime.now(UTC).isoformat(),
        )
        with self._catalog_lock:
            self.catalog_conn.execute(
                f"INSERT INTO model_usage ({self._MODEL_USAGE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            self._commit_catalog()
    def model_usage_rows_for_turn(self, turn_id: str, account_id: str) -> list[dict[str, Any]]:
        """Returns persisted model calls for one attributed inference turn."""
        self.ensure_account_schema()
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                f"SELECT {self._MODEL_USAGE_COLUMNS} FROM model_usage WHERE turn_id = ? AND account_id = ?",
                (str(turn_id), str(account_id)),
            ).fetchall()
        return [self._model_usage_from_row(row) for row in rows]

    def count_model_turns_for_account(self, account_id: str, since_iso: str) -> int:
        """Counts allowance-eligible turns with metering since ``since_iso``."""
        if not account_id:
            return 0
        self.ensure_account_schema()
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                "SELECT COUNT(DISTINCT turn_id) FROM model_usage"
                " WHERE account_id = ? AND turn_id IS NOT NULL AND created_at >= ?"
                " AND (purpose IS NULL OR purpose <> ?)",
                (str(account_id), str(since_iso), ALLOWANCE_EXEMPT_PURPOSE),
            ).fetchone()
        return int(row[0] or 0) if row else 0

    def reserve_ai_allowance_turn(
        self,
        reservation: AllowanceReservation,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically reserves one completed-answer slot and checks capability usage."""
        if reservation.capability not in {"lifter", "coach"}:
            raise ValueError("Unknown AI allowance capability.")
        account_id = str(reservation.account_id)
        capability = reservation.capability
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        start, reset = utc_day_bounds(moment)
        start_iso = start.isoformat()
        now_iso = moment.isoformat()
        reset_iso = reset.isoformat()
        role = "player" if capability == "lifter" else "coach"
        stale_before = (moment - ALLOWANCE_RESERVATION_TTL).isoformat()
        with self.catalog_transaction(immediate=True):
            cursor = self.catalog_conn.cursor()
            self._interrupt_stale_allowance_turns(
                cursor, reservation, now_iso, stale_before
            )
            completed = self._completed_allowance_turns(
                cursor, account_id, capability, start_iso
            )
            active = self._active_allowance_turns(
                cursor, reservation, start_iso, stale_before
            )
            resource_used = self._sum_capability_tokens(
                cursor, account_id, role, start_iso
            )
            if completed >= reservation.request_limit:
                return self._allowance_reservation_state(
                    "requests_exhausted", completed, resource_used, reset_iso
                )
            if completed + active >= reservation.request_limit:
                return self._allowance_reservation_state(
                    "request_in_progress", completed, resource_used, reset_iso
                )
            if resource_used >= reservation.resource_limit:
                return self._allowance_reservation_state(
                    "resource_cutoff", completed, resource_used, reset_iso
                )
            self._insert_allowance_turn(cursor, reservation, now_iso)
            return self._allowance_reservation_state(
                None, completed, resource_used, reset_iso
            )

    def finish_ai_allowance_turn(
        self,
        turn_id: str,
        outcome: str,
        *,
        now: datetime | None = None,
    ) -> None:
        """Releases an in-flight slot and records whether the answer completed."""
        if outcome not in {"completed", "failed", "interrupted", "truncated"}:
            raise ValueError("Unknown AI allowance outcome.")
        timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self._catalog_lock:
            self.catalog_conn.execute(
                "UPDATE ai_allowance_turns SET outcome = ?, updated_at = ?"
                " WHERE turn_id = ? AND outcome = 'in_progress'",
                (outcome, timestamp, str(turn_id)),
            )
            self._commit_catalog()

    def ai_allowance_usage(
        self,
        account_id: str,
        capability: str,
        *,
        now: datetime | None = None,
        projected_completed_turn_id: str | None = None,
    ) -> dict[str, int]:
        """Returns capability usage, optionally projecting a pending completion."""
        if capability not in {"lifter", "coach"}:
            raise ValueError("Unknown AI allowance capability.")
        start_iso = utc_day_start_iso(now)
        role = "player" if capability == "lifter" else "coach"
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            completed = self._completed_allowance_turns(
                cursor, account_id, capability, start_iso
            )
            if projected_completed_turn_id is not None:
                cursor.execute(
                    "SELECT COUNT(*) FROM ai_allowance_turns"
                    " WHERE turn_id = ? AND account_id = ? AND capability = ?"
                    " AND updated_at >= ? AND outcome = 'in_progress'"
                    " AND (purpose IS NULL OR purpose <> ?)",
                    (
                        projected_completed_turn_id,
                        str(account_id),
                        capability,
                        start_iso,
                        ALLOWANCE_EXEMPT_PURPOSE,
                    ),
                )
                completed += int(cursor.fetchone()[0] or 0)
            resource_used = self._sum_capability_tokens(cursor, account_id, role, start_iso)
        return {"requests_used": completed, "resource_used": resource_used}

    @staticmethod
    def _interrupt_stale_allowance_turns(
        cursor: Any,
        reservation: AllowanceReservation,
        now_iso: str,
        stale_before: str,
    ) -> None:
        cursor.execute(
            "UPDATE ai_allowance_turns SET outcome = 'interrupted', updated_at = ?"
            " WHERE account_id = ? AND capability = ? AND outcome = 'in_progress'"
            " AND updated_at < ?",
            (now_iso, reservation.account_id, reservation.capability, stale_before),
        )

    @staticmethod
    def _completed_allowance_turns(
        cursor: Any, account_id: str, capability: str, since_iso: str
    ) -> int:
        cursor.execute(
            "SELECT COUNT(*) FROM ai_allowance_turns"
            " WHERE account_id = ? AND capability = ? AND updated_at >= ?"
            " AND outcome = 'completed' AND (purpose IS NULL OR purpose <> ?)",
            (str(account_id), capability, since_iso, ALLOWANCE_EXEMPT_PURPOSE),
        )
        return int(cursor.fetchone()[0] or 0)

    @staticmethod
    def _active_allowance_turns(
        cursor: Any,
        reservation: AllowanceReservation,
        start_iso: str,
        stale_before: str,
    ) -> int:
        cursor.execute(
            "SELECT COUNT(*) FROM ai_allowance_turns"
            " WHERE account_id = ? AND capability = ?"
            " AND updated_at >= ? AND updated_at >= ? AND outcome = 'in_progress'",
            (reservation.account_id, reservation.capability, start_iso, stale_before),
        )
        return int(cursor.fetchone()[0] or 0)

    @staticmethod
    def _allowance_reservation_state(
        refusal: str | None,
        completed: int,
        resource_used: int,
        reset_iso: str,
    ) -> dict[str, Any]:
        return {
            "refusal": refusal,
            "requests_used": completed,
            "resource_used": resource_used,
            "reset_at": reset_iso,
        }

    @staticmethod
    def _insert_allowance_turn(
        cursor: Any, reservation: AllowanceReservation, timestamp: str
    ) -> None:
        cursor.execute(
            "INSERT INTO ai_allowance_turns"
            " (turn_id, account_id, capability, purpose, outcome, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'in_progress', ?, ?)",
            (
                reservation.turn_id,
                reservation.account_id,
                reservation.capability,
                reservation.purpose,
                timestamp,
                timestamp,
            ),
        )

    @staticmethod
    def _sum_capability_tokens(cursor: Any, account_id: str, role: str, start_iso: str) -> int:
        cursor.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage"
            " WHERE account_id = ? AND role = ? AND created_at >= ?"
            " AND (purpose IS NULL OR purpose <> ?)",
            (str(account_id), role, start_iso, ALLOWANCE_EXEMPT_PURPOSE),
        )
        return int(cursor.fetchone()[0] or 0)

    def sum_model_cost(self, start_iso: str, end_iso: str | None = None) -> float:
        """Total metered USD cost in the half-open window ``[start, end)``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            if end_iso is None:
                cursor.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE created_at >= ?", (start_iso,))
            else:
                cursor.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE created_at >= ? AND created_at < ?",
                    (start_iso, end_iso),
                )
            row = cursor.fetchone()
        return float(row[0] or 0.0) if row else 0.0

    def record_model_limit_hit(
        self, account_id: str, kind: Literal["rate", "daily_tokens"], created_at: str | None = None
    ) -> str:
        """Records one refused account request; retention pruning runs separately."""
        if kind not in {"rate", "daily_tokens"}:
            raise ValueError("Unknown model-limit hit kind.")
        timestamp = created_at or datetime.now(UTC).isoformat()
        self.ensure_account_schema()
        hit_id = uuid.uuid4().hex
        with self._catalog_lock:
            self.catalog_conn.execute(
                "INSERT INTO model_limit_hits (id, account_id, kind, created_at) VALUES (?, ?, ?, ?)",
                (hit_id, str(account_id), kind, timestamp),
            )
            self._commit_catalog()
        return hit_id

    def _prune_model_limit_hits(self, cutoff_iso: str) -> int:
        """Deletes limit-hit history older than the caller's retention cutoff."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.execute("DELETE FROM model_limit_hits WHERE created_at < ?", (cutoff_iso,))
            deleted = cursor.rowcount
            self._commit_catalog()
        return int(deleted)

    def count_model_limit_hits(self, account_id: str, since_iso: str) -> dict[str, int]:
        """Returns rate and daily-token refusal counts since an ISO timestamp."""
        if not account_id:
            return {"rate": 0, "daily_tokens": 0}
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT kind, COUNT(*) FROM model_limit_hits"
                " WHERE account_id = ? AND created_at >= ? GROUP BY kind",
                (str(account_id), str(since_iso)),
            )
            rows = cursor.fetchall()
        totals = {"rate": 0, "daily_tokens": 0}
        for kind, count in rows:
            if kind in totals:
                totals[str(kind)] = int(count)
        return totals

    def count_all_model_limit_hits(self, since_iso: str) -> dict[str, int]:
        """Returns refusal totals across every account id, including orphaned hits."""
        self.ensure_account_schema()
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                "SELECT kind, COUNT(*) FROM model_limit_hits WHERE created_at >= ? GROUP BY kind",
                (str(since_iso),),
            ).fetchall()
        totals = {"rate": 0, "daily_tokens": 0}
        for kind, count in rows:
            if kind in totals:
                totals[str(kind)] = int(count)
        return totals

    def summarize_model_limit_hits_by_account(self, since_iso: str) -> list[dict[str, Any]]:
        """Returns refusal counts grouped by account id and kind since a timestamp."""
        self.ensure_account_schema()
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                "SELECT account_id, kind, COUNT(*) FROM model_limit_hits WHERE created_at >= ?"
                " GROUP BY account_id, kind ORDER BY account_id, kind",
                (str(since_iso),),
            ).fetchall()
        return [{"account_id": row[0], "kind": str(row[1]), "count": int(row[2])} for row in rows]

    def has_model_usage(self) -> bool:
        """Checks whether any usage row exists without aggregating report history."""
        self.ensure_account_schema()
        with self._catalog_lock:
            row = self.catalog_conn.execute("SELECT 1 FROM model_usage LIMIT 1").fetchone()
        return row is not None

    def sum_model_tokens_for_account(self, account_id: str, start_iso: str, end_iso: str | None = None) -> int:
        """Total (input + output) tokens for one account in ``[start, end)``."""
        return self._sum_model_tokens(
            account_id, start_iso, end_iso=end_iso
        )

    def sum_model_tokens_for_account_role(
        self,
        account_id: str,
        role: str,
        start_iso: str,
        end_iso: str | None = None,
    ) -> int:
        """Total (input + output) tokens for one account role in ``[start, end)``."""
        return self._sum_model_tokens(
            account_id, start_iso, role=role, end_iso=end_iso
        )

    def _sum_model_tokens(
        self,
        account_id: str,
        start_iso: str,
        *,
        role: str | None = None,
        end_iso: str | None = None,
    ) -> int:
        """Sums metered tokens for an account, optionally limited to one role."""
        if not account_id:
            return 0
        self.ensure_account_schema()
        filters = [
            "account_id = ?",
            "created_at >= ?",
            "(purpose IS NULL OR purpose <> ?)",
        ]
        parameters: list[Any] = [
            str(account_id), start_iso, ALLOWANCE_EXEMPT_PURPOSE
        ]
        if role is not None:
            filters.append("role = ?")
            parameters.append(role)
        if end_iso is not None:
            filters.append("created_at < ?")
            parameters.append(end_iso)
        query = (
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage"
            " WHERE " + " AND ".join(filters)
        )
        with self._catalog_lock:
            row = self.catalog_conn.execute(query, parameters).fetchone()
        return int(row[0] or 0) if row else 0

    def _aggregate_model_usage_for_account(
        self, account_id: str, start_iso: str | None = None, end_iso: str | None = None
    ) -> dict[str, int | float]:
        """Aggregates calls, tokens, and cost for one account in SQL."""
        if not account_id:
            return {
                "calls": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }
        clauses = ["account_id = ?"]
        params: list[str] = [str(account_id)]
        if start_iso is not None:
            clauses.append("created_at >= ?")
            params.append(str(start_iso))
        if end_iso is not None:
            clauses.append("created_at < ?")
            params.append(str(end_iso))
        self.ensure_account_schema()
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0),"
                " COALESCE(SUM(cached_input_tokens), 0), COALESCE(SUM(output_tokens), 0),"
                " COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE " + " AND ".join(clauses),
                params,
            ).fetchone()
        return {
            "calls": int(row[0] or 0),
            "input_tokens": int(row[1] or 0),
            "cached_input_tokens": int(row[2] or 0),
            "output_tokens": int(row[3] or 0),
            "cost_usd": float(row[4] or 0.0),
        }

    def summarize_model_usage(self, start_iso: str, end_iso: str | None = None) -> list[dict[str, Any]]:
        """Per account/role/model totals for the owner report, ordered for display."""
        self.ensure_account_schema()
        where, params = ("created_at >= ?", [start_iso]) if end_iso is None else (
            "created_at >= ? AND created_at < ?",
            [start_iso, end_iso],
        )
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id, role, model, COUNT(*),"
                " COALESCE(SUM(input_tokens), 0), COALESCE(SUM(cached_input_tokens), 0),"
                " COALESCE(SUM(output_tokens), 0),"
                " COALESCE(SUM(cost_usd), 0), COALESCE(SUM(estimated), 0)"
                f" FROM model_usage WHERE {where}"
                " GROUP BY account_id, role, model ORDER BY account_id, role, model",
                params,
            )
            rows = cursor.fetchall()
        return [
            {
                "account_id": row[0],
                "role": str(row[1]),
                "model": str(row[2]),
                "requests": int(row[3]),
                "input_tokens": int(row[4]),
                "cached_input_tokens": int(row[5]),
                "output_tokens": int(row[6]),
                "cost_usd": float(row[7]),
                "estimated_calls": int(row[8]),
            }
            for row in rows
        ]

    def get_model_spend_alert(self, period: str) -> dict[str, Any] | None:
        """The stored spend-alert row for a UTC ``YYYY-MM`` period, or ``None``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT period, projected_usd, actual_usd, fired_at, notified_at"
                " FROM model_spend_alerts WHERE period = ?",
                (str(period),),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "period": str(row[0]),
            "projected_usd": float(row[1]),
            "actual_usd": float(row[2]),
            "fired_at": row[3],
            "notified_at": row[4],
        }

    def claim_model_spend_alert(
        self, period: str, projected_usd: float, actual_usd: float, fired_at: str
    ) -> bool:
        """Claims the once-per-month alert slot; ``True`` only for the first writer.

        ``INSERT OR IGNORE`` on the ``period`` primary key means exactly one
        caller observes ``True`` under concurrent sweeps. ``notified_at`` starts
        NULL and is set only after a successful send (ADR 038).
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO model_spend_alerts"
                " (period, projected_usd, actual_usd, fired_at, notified_at) VALUES (?, ?, ?, ?, NULL)",
                (str(period), float(projected_usd), float(actual_usd), str(fired_at)),
            )
            inserted = cursor.rowcount == 1
            self._commit_catalog()
        return inserted

    def mark_model_spend_alert_notified(self, period: str, notified_at: str) -> None:
        """Records that the alert email was delivered for ``period`` (retry-complete)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            self.catalog_conn.execute(
                "UPDATE model_spend_alerts SET notified_at = ? WHERE period = ? AND notified_at IS NULL",
                (str(notified_at), str(period)),
            )
            self._commit_catalog()
