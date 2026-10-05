"""Focused tests for the read-only closed-trial owner report."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from database.database_manager import DatabaseManager
from scripts.trial_gate_report import (
    build_trial_gate_report,
    main,
    read_assignment_evidence,
)


def _create_assignment(
    db: DatabaseManager,
    *,
    index: int,
    coach_id: str,
    player_id: str,
    started_at: datetime,
    published: bool = True,
    check_ins: int = 2,
) -> None:
    assignment_id = f"assignment-{index}"
    ended_at = (started_at + timedelta(weeks=4)).isoformat()
    db.catalog_conn.execute(
        "INSERT INTO assignments"
        " (assignment_id, coach_account_id, player_account_id, status, started_at, ended_at, ended_by)"
        " VALUES (?, ?, ?, 'ended', ?, ?, 'player')",
        (assignment_id, coach_id, player_id, started_at.isoformat(), ended_at),
    )
    if published:
        db.catalog_conn.execute(
            "INSERT INTO assignment_notices"
            " (notice_id, account_id, assignment_id, kind, message, created_at)"
            " VALUES (?, ?, ?, 'program_published', '', ?)",
            (f"notice-{index}", player_id, assignment_id, ended_at),
        )
    for check_index in range(check_ins):
        db.catalog_conn.execute(
            "INSERT INTO check_ins"
            " (check_in_id, assignment_id, coach_account_id, player_account_id,"
            " checked_in_on, channel, created_at) VALUES (?, ?, ?, ?, ?, 'phone', ?)",
            (
                f"check-in-{index}-{check_index}",
                assignment_id,
                coach_id,
                player_id,
                (started_at + timedelta(days=check_index + 1)).date().isoformat(),
                (started_at + timedelta(days=check_index + 1)).isoformat(),
            ),
        )
    db.catalog_conn.commit()


@pytest.fixture
def trial_db(tmp_path: Path) -> DatabaseManager:
    db = DatabaseManager(
        catalog_path=tmp_path / "catalog.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    yield db
    db.catalog_conn.close()


def test_report_counts_qualifying_pairs_from_catalog_only(trial_db: DatabaseManager, capsys):
    db = trial_db
    catalog_path = db.catalog_path
    as_of = datetime(2026, 10, 5, 23, 59, tzinfo=UTC)
    started_at = as_of - timedelta(weeks=5)
    pair_ids: dict[int, tuple[str, str]] = {}
    for index in range(1, 6):
        coach_id = db.create_account(f"coach-{index}")
        player_id = db.create_account(f"player-{index}")
        pair_ids[index] = (coach_id, player_id)
        _create_assignment(
            db, index=index, coach_id=coach_id, player_id=player_id, started_at=started_at
        )
    _create_assignment(
        db,
        index=6,
        coach_id=db.create_account("coach-6"),
        player_id=db.create_account("player-6"),
        started_at=started_at,
        published=False,
    )
    _create_assignment(
        db,
        index=7,
        coach_id=pair_ids[1][0],
        player_id=pair_ids[1][1],
        started_at=started_at,
    )

    report = build_trial_gate_report(read_assignment_evidence(catalog_path), as_of=as_of)

    assert report["qualifying_pairs"] == 5
    assert report["passed"] is True
    assert len(report["assignments"]) == 7
    assert report["assignments"][0]["weeks_completed"] == 4
    assert report["assignments"][0]["coach_published_program"] is True
    assert report["assignments"][0]["check_ins"] == 2
    incomplete_assignment = next(
        row for row in report["assignments"] if row["player_username"] == "player-6"
    )
    assert incomplete_assignment["qualifies"] is False
    assert main(["--catalog", str(catalog_path), "--as-of", "2026-10-05"]) == 0
    assert "Closed-trial pairs PASS" in capsys.readouterr().out


def test_report_fails_below_five_qualifying_pairs(trial_db: DatabaseManager):
    db = trial_db
    as_of = datetime(2026, 10, 5, 23, 59, tzinfo=UTC)
    for index in range(1, 5):
        coach_id = db.create_account(f"coach-{index}")
        player_id = db.create_account(f"player-{index}")
        _create_assignment(
            db,
            index=index,
            coach_id=coach_id,
            player_id=player_id,
            started_at=as_of - timedelta(weeks=5),
        )

    assert main(["--catalog", str(db.catalog_path), "--as-of", "2026-10-05"]) == 1
