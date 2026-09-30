"""Model usage recording, spend alerting, and owner reporting (ADR 038, #39).

The LangChain metering callback (:mod:`utils.model_metering`) calls
:func:`record_model_usage` once per model call. This module computes the USD
cost from the pricing table and persists the row catalog-side.

The owner spend alert is evaluated on the existing hourly sweep
(:mod:`service.alert_sweep`) — never on an inference thread while a gate slot is
held. The alert is claimed once per UTC month with ``INSERT OR IGNORE`` and its
``notified_at`` is set only after a successful email, so a failed or skipped send
is retried on the next sweep and a delivered alert is never repeated.

The catalog is also readable **read-only** for the owner report via
:class:`ReadOnlyModelUsageCatalog`, which never provisions schema tables.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from service.email_sender import send_model_spend_alert_email
from utils.model_pricing import compute_cost

logger = logging.getLogger(__name__)

DEFAULT_SPEND_ALERT_USD = 50.0
#: A month is projected at least this far "elapsed" so day-1 spend is not
#: extrapolated to an absurd month total (ADR 038). 0.1 of a 30-day month is
#: three days; before that, the projection is conservative rather than wild.
MIN_MONTH_ELAPSED_FRACTION = 0.1

_USAGE_GROUP_COLUMNS = (
    "SELECT account_id, role, model, COUNT(*),"
    " COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0),"
    " COALESCE(SUM(cost_usd), 0), COALESCE(SUM(estimated), 0)"
    " FROM model_usage WHERE {where}"
    " GROUP BY account_id, role, model ORDER BY account_id, role, model"
)


def spend_alert_usd() -> float:
    """Owner alert threshold in USD; non-positive values fall back to the default."""
    try:
        value = float(os.getenv("MODEL_SPEND_ALERT_USD", str(DEFAULT_SPEND_ALERT_USD)))
    except (TypeError, ValueError):
        return DEFAULT_SPEND_ALERT_USD
    return value if value > 0 else DEFAULT_SPEND_ALERT_USD


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Half-open UTC calendar-month bounds ``[start, next)`` containing ``now``."""
    moment = now.astimezone(UTC)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return start, nxt


def account_usage_totals(
    db: Any,
    account_id: str,
    start_iso: str | None = None,
    end_iso: str | None = None,
) -> dict[str, int | float]:
    """Totals model calls, tokens, and cost through the account-scoped SQL aggregate."""
    totals = db._aggregate_model_usage_for_account(account_id, start_iso, end_iso)
    input_tokens = int(totals["input_tokens"])
    output_tokens = int(totals["output_tokens"])
    return {
        "calls": int(totals["calls"]),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
        "cost_usd": float(totals["cost_usd"]),
    }


def project_month_spend(actual_usd: float, now: datetime) -> float:
    """Projects a full-month spend from month-to-date ``actual_usd``.

    ``actual / max(elapsed_fraction, MIN_MONTH_ELAPSED_FRACTION)``, where the
    elapsed fraction is measured over the UTC calendar month. The floor keeps
    day-1 (and early-month) spend from extrapolating to an absurd total.
    """
    start, nxt = month_bounds(now)
    total_seconds = max(1.0, (nxt - start).total_seconds())
    elapsed_seconds = max(0.0, (now.astimezone(UTC) - start).total_seconds())
    elapsed_fraction = min(1.0, elapsed_seconds / total_seconds)
    projection_fraction = max(elapsed_fraction, MIN_MONTH_ELAPSED_FRACTION)
    return float(actual_usd) / projection_fraction


def evaluate_spend_alert(
    db: Any, now: datetime | None = None, *, send_email: bool = True
) -> dict[str, Any]:
    """Fires/retries the owner alert when projected spend crosses the threshold.

    Dedupe is persisted catalog-side: the first crossing claims the UTC month
    (``fired_at``), and ``notified_at`` is set only after a successful send. A
    listed row with ``notified_at IS NULL`` is retried on a later sweep; a
    notified month is never re-sent. A WARNING is logged on every attempt.
    """
    moment = now or datetime.now(UTC)
    threshold = spend_alert_usd()
    start, nxt = month_bounds(moment)
    period = start.strftime("%Y-%m")
    actual = db.sum_model_cost(start.isoformat(), nxt.isoformat())
    projected = project_month_spend(actual, moment)
    result = {
        "period": period,
        "actual_usd": actual,
        "projected_usd": projected,
        "threshold_usd": threshold,
        "fired": False,
        "retrying": False,
        "notified": False,
        "deduped": False,
    }
    if projected < threshold:
        return result

    existing = db.get_model_spend_alert(period)
    if existing is None:
        if db.claim_model_spend_alert(period, projected, actual, moment.isoformat()):
            result["fired"] = True
            existing = db.get_model_spend_alert(period)
        else:
            existing = db.get_model_spend_alert(period)

    if existing is not None and existing.get("notified_at"):
        result["deduped"] = True
        return result

    # Unnotified (freshly claimed or a previously failed send): attempt delivery.
    if not result["fired"]:
        result["retrying"] = True
    logger.warning(
        "MODEL SPEND ALERT: projected $%.2f >= $%.2f for %s (month-to-date $%.2f).",
        projected,
        threshold,
        period,
        actual,
    )
    owner_email = os.getenv("OWNER_ALERT_EMAIL", "").strip()
    if send_email and owner_email:
        if send_model_spend_alert_email(owner_email, projected, actual, threshold):
            db.mark_model_spend_alert_notified(period, moment.isoformat())
            result["notified"] = True
        else:
            logger.warning("Model spend alert email failed; it will be retried on the next sweep.")
    elif not owner_email:
        logger.warning("OWNER_ALERT_EMAIL is unset; the spend alert was recorded without email.")
    return result


def record_model_usage(
    *,
    store: Any = None,
    account_id: str | None,
    role: str,
    purpose: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    estimated: bool,
) -> None:
    """Computes cost and persists one metered call (called by the metering callback).

    The app-owned ``store`` travels on the usage context set by the inference
    entry points (ADR 041). An **unattributed** call with no store (startup) is
    dropped; an attributed call (``account_id`` set) with no store is a
    programming error and raises rather than silently losing the usage row.
    """
    if store is None:
        if account_id:
            raise RuntimeError(
                f"Model usage for account {account_id!r} has no store to persist to; "
                "refusing to drop the row (ADR 041)."
            )
        return
    cost = compute_cost(model, input_tokens, output_tokens)
    store.record_model_usage(
        account_id=account_id,
        role=role,
        model=model,
        purpose=purpose,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated=estimated,
        cost_usd=cost,
    )


def usage_report(
    db: Any, start: datetime | None = None, end: datetime | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Owner report: per account/role/model totals for a window plus month-to-date totals.

    Defaults to the current UTC calendar month when no window is given. ``db`` is
    any object exposing ``summarize_model_usage``, ``sum_model_cost``, and
    ``get_model_spend_alert`` (the catalog manager or the read-only reader).
    """
    moment = now or datetime.now(UTC)
    month_start, month_end = month_bounds(moment)
    window_start = start.astimezone(UTC) if start else month_start
    window_end = end.astimezone(UTC) if end else None
    report = _usage_window_report(db, window_start, window_end)
    mtd_actual = db.sum_model_cost(month_start.isoformat(), month_end.isoformat())
    return {
        **report,
        "mtd_actual_usd": mtd_actual,
        "mtd_projected_usd": project_month_spend(mtd_actual, moment),
        "alert": db.get_model_spend_alert(moment.strftime("%Y-%m")),
    }


def _usage_window_report(db: Any, start: datetime, end: datetime | None) -> dict[str, Any]:
    """Builds window totals from the shared registry aggregate used by both reports."""
    rows = db.summarize_model_usage(start.isoformat(), end.isoformat() if end else None)
    return {
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "rows": rows,
        "total_requests": sum(row["requests"] for row in rows),
        "total_input_tokens": sum(row["input_tokens"] for row in rows),
        "total_output_tokens": sum(row["output_tokens"] for row in rows),
        "total_cost_usd": sum(row["cost_usd"] for row in rows),
    }


def usage_dashboard_report(db: Any, now: datetime | None = None) -> dict[str, Any]:
    """Builds the owner page using the CLI report's shared usage aggregation."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    month_start, windows = _usage_dashboard_windows(moment)
    periods = [_dashboard_usage_period(db, window) for window in windows]
    actual = db.sum_model_cost(month_start.isoformat(), month_bounds(moment)[1].isoformat())
    projected = project_month_spend(actual, moment)
    alert = db.get_model_spend_alert(moment.strftime("%Y-%m"))
    threshold = spend_alert_usd()
    periods[1]["report"].update(
        {
            "mtd_actual_usd": actual,
            "mtd_projected_usd": projected,
            "alert": alert,
        }
    )
    return {
        "periods": periods,
        "top_accounts": _top_usage_accounts(db, periods[1]["report"]["rows"]),
        "limit_hits": count_all_model_limit_hits(db, month_start.isoformat()),
        "spend_alert": _spend_alert_summary(actual, projected, threshold, alert),
        "has_usage": db.has_model_usage(),
    }


def _usage_dashboard_windows(
    moment: datetime,
) -> tuple[datetime, tuple[tuple[str, str, datetime, datetime | None], ...]]:
    month_start, _ = month_bounds(moment)
    prior_month_start, _ = month_bounds(month_start - timedelta(microseconds=1))
    today_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return month_start, (
        ("today", "Today (UTC)", today_start, today_start + timedelta(days=1)),
        ("this-month", "This UTC month", month_start, None),
        ("last-month", "Last month", prior_month_start, month_start),
    )


def _dashboard_usage_period(
    db: Any,
    window: tuple[str, str, datetime, datetime | None],
) -> dict[str, Any]:
    key, label, start, end = window
    report = _usage_window_report(db, start, end)
    rows = report["rows"]
    unattributed_rows = [row for row in rows if row["account_id"] is None]
    return {
        "key": key,
        "label": label,
        "report": report,
        "by_model": _rollup_usage_rows(rows, ("model",)),
        "by_role": _rollup_usage_rows(rows, ("role",)),
        "unattributed": _rollup_usage_rows(unattributed_rows, ("role", "model")),
    }


def _rollup_usage_rows(rows: list[dict[str, Any]], dimensions: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, int | float]] = {}
    for row in rows:
        key = tuple(row[dimension] for dimension in dimensions)
        totals = groups.setdefault(
            key,
            {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "estimated_calls": 0},
        )
        totals["requests"] += row["requests"]
        totals["input_tokens"] += row["input_tokens"]
        totals["output_tokens"] += row["output_tokens"]
        totals["cost_usd"] += row["cost_usd"]
        totals["estimated_calls"] += row["estimated_calls"]
    return [_usage_group(key, groups[key], dimensions) for key in sorted(groups, key=_usage_group_sort_key)]


def _usage_group(
    key: tuple[Any, ...], totals: dict[str, int | float], dimensions: tuple[str, ...]
) -> dict[str, Any]:
    return {**dict(zip(dimensions, key)), **totals}


def _usage_group_sort_key(key: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(str(dimension_value or "") for dimension_value in key)


def _top_usage_accounts(db: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accounts = _rollup_usage_rows([row for row in rows if row["account_id"] is not None], ("account_id",))
    ordered = sorted(accounts, key=lambda row: (-float(row["cost_usd"]), str(row["account_id"])))[:20]
    accounts_by_id = {account["account_id"]: account for account in db.get_accounts_by_ids([row["account_id"] for row in ordered])}
    for row in ordered:
        account = accounts_by_id.get(row["account_id"])
        row["deleted"] = not db.is_live_account(account)
        row["username"] = account["username"] if account else None
    return ordered


def count_all_model_limit_hits(db: Any, since_iso: str) -> dict[str, Any]:
    """Counts limit refusals with registry aggregates across every account id."""
    totals = db.count_all_model_limit_hits(since_iso)
    grouped = db.summarize_model_limit_hits_by_account(since_iso)
    accounts_by_id: dict[str | None, dict[str, Any]] = {}
    for hit in grouped:
        account_id = hit["account_id"]
        row = accounts_by_id.setdefault(account_id, {"account_id": account_id, "rate": 0, "daily_tokens": 0})
        if hit["kind"] in {"rate", "daily_tokens"}:
            row[hit["kind"]] += hit["count"]
    ordered = sorted(
        accounts_by_id.values(), key=lambda row: (-(row["rate"] + row["daily_tokens"]), str(row["account_id"] or ""))
    )[:20]
    ids = [row["account_id"] for row in ordered if row["account_id"] is not None]
    accounts = {account["account_id"]: account for account in db.get_accounts_by_ids(ids)}
    for row in ordered:
        account = accounts.get(row["account_id"])
        row["deleted"] = not db.is_live_account(account)
        row["username"] = account["username"] if account else None
    return {**totals, "top_accounts": ordered}


def _spend_alert_summary(
    actual: float, projected: float, threshold: float, alert: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "actual_usd": actual,
        "projected_usd": projected,
        "threshold_usd": threshold,
        "alert": alert,
    }


class ReadOnlyModelUsageCatalog:
    """Read-only catalog access for the owner report; never creates schema.

    Opens the catalog with ``mode=ro`` so a review can never write, and exposes
    the same read methods as ``DatabaseManager`` for :func:`usage_report`. A
    catalog without a ``model_usage`` table raises ``UsageNotRecordedError``.
    """

    def __init__(self, catalog_path: str | Path) -> None:
        self.path = Path(catalog_path)
        uri = f"file:{self.path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ReadOnlyModelUsageCatalog":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def has_usage_table(self) -> bool:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='model_usage'"
        ).fetchone()
        return row is not None

    def _require_usage_table(self) -> None:
        if not self.has_usage_table():
            raise UsageNotRecordedError(f"No model usage recorded yet in {self.path}.")

    def summarize_model_usage(self, start_iso: str, end_iso: str | None = None) -> list[dict[str, Any]]:
        self._require_usage_table()
        where, params = ("created_at >= ?", [start_iso]) if end_iso is None else (
            "created_at >= ? AND created_at < ?",
            [start_iso, end_iso],
        )
        cursor = self._conn.execute(_USAGE_GROUP_COLUMNS.format(where=where), params)
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
            for row in cursor.fetchall()
        ]

    def sum_model_cost(self, start_iso: str, end_iso: str | None = None) -> float:
        self._require_usage_table()
        if end_iso is None:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE created_at >= ?", (start_iso,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE created_at >= ? AND created_at < ?",
                (start_iso, end_iso),
            ).fetchone()
        return float(row[0] or 0.0) if row else 0.0

    def get_model_spend_alert(self, period: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='model_spend_alerts'"
        ).fetchone()
        if row is None:
            return None
        record = self._conn.execute(
            "SELECT period, projected_usd, actual_usd, fired_at, notified_at"
            " FROM model_spend_alerts WHERE period = ?",
            (str(period),),
        ).fetchone()
        if record is None:
            return None
        return {
            "period": str(record[0]),
            "projected_usd": float(record[1]),
            "actual_usd": float(record[2]),
            "fired_at": record[3],
            "notified_at": record[4],
        }


class UsageNotRecordedError(RuntimeError):
    """Raised by the read-only reader when the catalog has no usage table."""


__all__ = [
    "DEFAULT_SPEND_ALERT_USD",
    "MIN_MONTH_ELAPSED_FRACTION",
    "ReadOnlyModelUsageCatalog",
    "UsageNotRecordedError",
    "account_usage_totals",
    "count_all_model_limit_hits",
    "evaluate_spend_alert",
    "month_bounds",
    "project_month_spend",
    "record_model_usage",
    "spend_alert_usd",
    "usage_report",
    "usage_dashboard_report",
]
