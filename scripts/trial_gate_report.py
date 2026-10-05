"""Read-only owner report for the four-week closed-trial release gate.

The report uses catalog-side assignment, publication-notice, and Check-in
records. It never opens a player's Training ledger.
Run it and save its JSON before any participant deletes their Account or before the deletion drill; otherwise use --catalog with a restored copy of a pre-deletion catalog snapshot.

Usage::

    python scripts/trial_gate_report.py
    python scripts/trial_gate_report.py --catalog /data/catalog.db --as-of 2026-10-05
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import DEFAULT_CATALOG_PATH  # noqa: E402

REQUIRED_PAIRS = 5
REQUIRED_WEEKS = 4
REQUIRED_CHECK_INS = 2


def _parse_as_of(value: str) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}")
    return datetime.combine(parsed, time.max, UTC)


def _parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def read_assignment_evidence(catalog_path: str | Path) -> list[sqlite3.Row]:
    """Read catalog evidence without mounting participant Training ledgers."""
    connection = sqlite3.connect(f"file:{Path(catalog_path)}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT a.assignment_id, a.status, a.started_at, a.ended_at,"
            " a.coach_account_id, coach.username AS coach_username,"
            " a.player_account_id, player.username AS player_username,"
            " (SELECT COUNT(*) FROM check_ins ci"
            "  WHERE ci.assignment_id = a.assignment_id) AS check_in_count,"
            " EXISTS (SELECT 1 FROM assignment_notices n"
            "  WHERE n.assignment_id = a.assignment_id AND n.kind = 'program_published')"
            "  AS coach_published"
            " FROM assignments a"
            " LEFT JOIN accounts coach ON coach.account_id = a.coach_account_id"
            " LEFT JOIN accounts player ON player.account_id = a.player_account_id"
            " WHERE a.status IN ('active', 'ended')"
            " ORDER BY a.started_at, a.assignment_id"
        ).fetchall()
    finally:
        connection.close()


def _weeks_completed(started_at: str, ended_at: str | None, as_of: datetime) -> int:
    started = _parse_instant(started_at)
    if started is None:
        return 0
    elapsed_until = _parse_instant(ended_at) if ended_at else as_of
    if elapsed_until is None:
        return 0
    return max(0, int((elapsed_until - started) // timedelta(weeks=1)))


def _assignment_report_row(record: sqlite3.Row, as_of: datetime) -> dict[str, Any]:
    weeks = _weeks_completed(record["started_at"], record["ended_at"], as_of)
    published = bool(record["coach_published"])
    check_ins = int(record["check_in_count"] or 0)
    return {
        "assignment_id": str(record["assignment_id"]),
        "status": str(record["status"]),
        "started_at": str(record["started_at"]),
        "ended_at": record["ended_at"],
        "weeks_completed": weeks,
        "coach_account_id": str(record["coach_account_id"]),
        "coach_username": record["coach_username"],
        "player_account_id": str(record["player_account_id"]),
        "player_username": record["player_username"],
        "coach_published_program": published,
        "check_ins": check_ins,
        "qualifies": weeks >= REQUIRED_WEEKS and published and check_ins >= REQUIRED_CHECK_INS,
    }


def build_trial_gate_report(
    assignment_evidence: list[sqlite3.Row],
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Measure full seven-day periods and catalog evidence for each Assignment."""
    moment = as_of or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    rows = [_assignment_report_row(record, moment) for record in assignment_evidence]
    qualifying_pairs = len(
        {
            (row["coach_account_id"], row["player_account_id"])
            for row in rows
            if row["qualifies"]
        }
    )
    return {
        "as_of": moment.isoformat(),
        "assignments": rows,
        "qualifying_pairs": qualifying_pairs,
        "required_pairs": REQUIRED_PAIRS,
        "passed": qualifying_pairs >= REQUIRED_PAIRS,
    }


def _print_assignment_row(row: dict[str, Any]) -> None:
    coach = f"{row['coach_username'] or '(deleted)'} [{row['coach_account_id']}]"
    player = f"{row['player_username'] or '(deleted)'} [{row['player_account_id']}]"
    print(
        f"{row['assignment_id']:<34} {row['status']:<7} {coach:<36.36} {player:<36.36}"
        f" {row['started_at'][:19]:<20} {row['weeks_completed']:>5}"
        f" {('yes' if row['coach_published_program'] else 'no'):>9}"
        f" {row['check_ins']:>9} {('PASS' if row['qualifies'] else 'FAIL'):>7}"
    )


def _print_report(report: dict[str, Any]) -> None:
    print(f"Closed-trial evidence as of {report['as_of'][:10]}")
    print(f"{'assignment':<34} {'status':<7} {'coach':<36} {'player':<36} {'started':<20} {'weeks':>5} {'published':>9} {'check-ins':>9} {'pair':>7}")
    for row in report["assignments"]:
        _print_assignment_row(row)
    verdict = "PASS" if report["passed"] else "FAIL"
    print(
        f"Closed-trial pairs {verdict} — {report['qualifying_pairs']} qualifying coach/player pairs; "
        f"requires >= {report['required_pairs']} pairs with >= {REQUIRED_WEEKS} full weeks, "
        f"a published program, and >= {REQUIRED_CHECK_INS} check-ins each."
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review catalog evidence for the closed-trial pair gate.")
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=None,
        help="Evaluate active assignments through this UTC date (YYYY-MM-DD); default: now.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    report = build_trial_gate_report(read_assignment_evidence(args.catalog), as_of=args.as_of)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
