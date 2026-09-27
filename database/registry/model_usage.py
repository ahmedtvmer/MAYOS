"""RegistryModelUsageMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import uuid
from datetime import UTC, datetime
from typing import Any


class RegistryModelUsageMixin:
    _MODEL_USAGE_COLUMNS = (
        "id, account_id, role, model, purpose, input_tokens, output_tokens, estimated, cost_usd, created_at"
    )

    @staticmethod
    def _model_usage_from_row(row: Any) -> dict[str, Any]:
        return {
            "id": str(row[0]),
            "account_id": row[1],
            "role": str(row[2]),
            "model": str(row[3]),
            "purpose": row[4],
            "input_tokens": int(row[5]),
            "output_tokens": int(row[6]),
            "estimated": bool(row[7]),
            "cost_usd": float(row[8]),
            "created_at": str(row[9]),
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
            str(role or "unknown"),
            str(model),
            str(purpose) if purpose else None,
            max(0, int(input_tokens)),
            max(0, int(output_tokens)),
            1 if estimated else 0,
            float(cost_usd or 0.0),
            created_at or datetime.now(UTC).isoformat(),
        )
        with self._catalog_lock:
            self.catalog_conn.execute(
                f"INSERT INTO model_usage ({self._MODEL_USAGE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            self._commit_catalog()

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

    def sum_model_tokens_for_account(self, account_id: str, start_iso: str, end_iso: str | None = None) -> int:
        """Total (input + output) tokens for one account in ``[start, end)``."""
        if not account_id:
            return 0
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            if end_iso is None:
                cursor.execute(
                    "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage"
                    " WHERE account_id = ? AND created_at >= ?",
                    (str(account_id), start_iso),
                )
            else:
                cursor.execute(
                    "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage"
                    " WHERE account_id = ? AND created_at >= ? AND created_at < ?",
                    (str(account_id), start_iso, end_iso),
                )
            row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

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
                " COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0),"
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
                "output_tokens": int(row[5]),
                "cost_usd": float(row[6]),
                "estimated_calls": int(row[7]),
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
