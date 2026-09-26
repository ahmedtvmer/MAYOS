"""Owner review of hosted-model usage for the closed trial (ADR 038, ticket #39).

The owner runs this from the ops console to review actual per-account usage
before expansion. It opens the catalog **read-only** and never provisions
schema. It prints per account id / role / model: model calls, input and output
tokens, and USD cost for a date range (default: the current UTC calendar month),
plus month-to-date actual and projected totals and the current month's alert
status.

Note the vocabulary: the per-row count is **model calls** (one row per call),
while the per-account request limit counts **turns** (one chat turn with several
calls counts once). The report does not track turns, only the calls it meters.

Usage:
    python scripts/model_usage_report.py
    python scripts/model_usage_report.py --start 2026-09-01 --end 2026-09-30
    python scripts/model_usage_report.py --account <account_id> --json
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import DEFAULT_CATALOG_PATH  # noqa: E402
from service import model_metering as metering_service  # noqa: E402
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def _parse_day(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None
    return parsed.replace(tzinfo=UTC)


def _filter_account(report: dict, account_filter: str | None) -> dict:
    """Applies the account filter to the report rows (and JSON totals)."""
    if not account_filter:
        return report
    rows = [row for row in report["rows"] if str(row["account_id"] or "") == account_filter]
    filtered = dict(report)
    filtered["account"] = account_filter
    filtered["rows"] = rows
    filtered["total_requests"] = sum(row["requests"] for row in rows)
    filtered["total_input_tokens"] = sum(row["input_tokens"] for row in rows)
    filtered["total_output_tokens"] = sum(row["output_tokens"] for row in rows)
    filtered["total_cost_usd"] = sum(row["cost_usd"] for row in rows)
    return filtered


def _print_alert(alert: dict | None) -> None:
    if alert is None:
        print("Current month alert: not fired")
        return
    delivered = alert.get("notified_at") or "not delivered"
    print(
        f"Current month alert: fired {str(alert.get('fired_at'))[:19]} "
        f"(notified: {str(delivered)[:19]})"
    )


def _print_report(report: dict) -> None:
    rows = report["rows"]
    suffix = f" (account {report['account']})" if report.get("account") else ""
    print(
        f"Model usage {report['start'][:10]} .. {report['end'][:10] if report['end'] else 'now'}{suffix}"
    )
    print(
        f"{'account':<34} {'role':<8} {'model':<24} {'calls':>6} {'in_tok':>10} {'out_tok':>10} {'cost_usd':>10}"
    )
    for row in rows:
        account = row["account_id"] or "(unattributed)"
        print(
            f"{account:<34} {row['role']:<8} {row['model']:<24} {row['requests']:>6}"
            f" {row['input_tokens']:>10} {row['output_tokens']:>10} {row['cost_usd']:>10.4f}"
        )
    print("-" * 110)
    print(
        f"{'TOTAL':<34} {'':<8} {'':<24} {report['total_requests']:>6}"
        f" {report['total_input_tokens']:>10} {report['total_output_tokens']:>10} {report['total_cost_usd']:>10.4f}"
    )
    print()
    print(f"Month-to-date actual:    ${report['mtd_actual_usd']:,.2f}")
    print(f"Month-to-date projected: ${report['mtd_projected_usd']:,.2f}")
    _print_alert(report.get("alert"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review hosted-model usage by account, role, and model.")
    parser.add_argument("--start", type=_parse_day, default=None, help="Window start (YYYY-MM-DD); default month-to-date.")
    parser.add_argument("--end", type=_parse_day, default=None, help="Window end, inclusive (YYYY-MM-DD).")
    parser.add_argument("--account", default=None, help="Only show this immutable account id.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    args = parser.parse_args(argv)

    start = args.start
    end = args.end + timedelta(days=1) if args.end else None
    if start is not None and end is not None and end <= start:
        parser.error("--end must not be before --start.")

    with metering_service.ReadOnlyModelUsageCatalog(args.catalog) as catalog:
        if not catalog.has_usage_table():
            print(f"No usage recorded yet in {catalog.path}.")
            return 0
        report = _filter_account(metering_service.usage_report(catalog, start=start, end=end), args.account)

    if args.json:
        # Keep stdout machine-readable: no log line here.
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)
        logger.info(
            "Model usage report: %s calls, $%.4f for %s .. %s",
            report["total_requests"],
            report["total_cost_usd"],
            report["start"],
            report["end"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
