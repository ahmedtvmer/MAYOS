"""Opt-in import of existing training history (ADR 019, ticket #42)."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from database.backup import snapshot_sqlite_file
from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION
from service import auth as auth_service
from service import imports as import_service


def _sources_dir(db):
    """A source shelf outside the live ledger directory (the runbook's copy)."""
    directory = db.backups_dir.parent / "import-sources"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _make_source(
    db,
    name="realplayer",
    *,
    password="source-pass-1",
    sessions=2,
    schedule=False,
    coach_program=False,
):
    """Builds a real-looking ledger file outside the live ledger dir and snapshots it there."""
    with db.open_ledger(name) as ledger:
        if password:
            ledger.set_password_hash(auth_service.hash_password(password))
        conn = ledger.conn
        for i in range(sessions):
            session_id = f"{name}-s{i}"
            conn.execute(
                "INSERT INTO workout_sessions (id, session_date, split_name, started_at) VALUES (?, ?, ?, ?)",
                (session_id, f"2026-01-0{i + 1}", "Full Body", f"2026-01-0{i + 1}T10:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO workout_sets"
                " (id, session_id, exercise_id, set_index, weight_kg, reps, logged_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"{session_id}-set", session_id, "squat", 0, 100.0 + i, 5, f"2026-01-0{i + 1}T10:01:00+00:00"),
            )
        if schedule:
            conn.execute(
                "INSERT INTO training_schedules (id, trainee_id, weekdays, timezone, effective_from, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("sched-1", name, json.dumps([1, 3, 5]), "UTC", "2026-01-01", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO training_pauses (id, trainee_id, starts_on, ends_on, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("pause-1", name, "2026-02-01", "2026-02-14", "2026-01-20T00:00:00+00:00"),
            )
        if coach_program:
            conn.execute(
                "INSERT INTO training_programs"
                " (id, program_name, name, split_type, weekly_frequency, instructions, is_active, created_at,"
                "  version, published_by_coach_account_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "prog-1",
                    "Coach Program",
                    "Coach Program",
                    "Full Body",
                    3,
                    "",
                    1,
                    "2026-01-01T00:00:00+00:00",
                    1,
                    "coach-account-xyz",
                ),
            )
        conn.commit()
    source = _sources_dir(db) / f"{name}.db"
    snapshot_sqlite_file(db.ledgers_dir / f"{name}.db", source)
    return source


def _make_old_schema_source(db, name="oldschema"):
    """A pre-migration ledger (schema v1) built from the migration version history."""
    source = _sources_dir(db) / f"{name}.db"
    conn = sqlite3.connect(str(source))
    conn.executescript(
        """
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            proportions TEXT NOT NULL,
            age INTEGER NOT NULL,
            weight_kg REAL NOT NULL,
            height_cm REAL NOT NULL,
            current_goal TEXT NOT NULL,
            long_term_goal TEXT NOT NULL,
            weekly_frequency INTEGER NOT NULL,
            training_age_years REAL NOT NULL,
            equipment_access TEXT NOT NULL,
            stress_and_sleep TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO user_profile
            (id, proportions, age, weight_kg, height_cm, current_goal, long_term_goal,
             weekly_frequency, training_age_years, equipment_access, stress_and_sleep, created_at, updated_at)
        VALUES
            (1, 'balanced', 30, 80.0, 180.0, 'Strength', 'Longevity', 3, 4.0, 'Full gym', 'Okay',
             '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00');
        PRAGMA user_version = 1;
        """
    )
    conn.commit()
    conn.close()
    return source


def _audit_row(db, account_id):
    with db.catalog_locked() as conn:
        row = conn.execute(
            "SELECT source_fingerprint, source_name, counts_json, opt_in_reference, imported_at"
            " FROM account_imports WHERE account_id = ?",
            (account_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "source_fingerprint": row[0],
        "source_name": row[1],
        "counts_json": row[2],
        "opt_in_reference": row[3],
        "imported_at": row[4],
    }


def test_import_requires_opt_in_reference(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer")
    result = import_service.import_player(db, source, "cloudplayer", "   ")
    assert not result["ok"]
    assert result["code"] == "missing_opt_in"
    assert db.get_active_account_by_username("cloudplayer") is None


@pytest.mark.parametrize(
    "name",
    [
        "default",
        "bp_male_1_default",
        "alice",
        "bob",
        "test_user",
        "testuser",
        "demo_final_output",
        "demouser",
        "eval_user",
        "evalrun",
        "bughunt_poor",
        "bughunt",
        "seed_data",
        "fixture_x",
        "ci_test_x",
    ],
)
def test_import_rejects_development_and_test_sources(fresh_store, name):
    db = fresh_store
    source = _sources_dir(db) / f"{name}.db"
    source.touch()
    result = import_service.import_player(db, source, "cloudplayer", "consent given")
    assert not result["ok"]
    assert result["code"] == "rejected_source"
    assert db.get_active_account_by_username("cloudplayer") is None


@pytest.mark.parametrize("name", ["realplayer", "bobby", "alicecooper", "bpromo", "defaultvalue"])
def test_dev_name_guard_allows_ordinary_names(name):
    assert import_service.DENIED_SOURCE_NAME_RE.search(name.lower()) is None


def test_import_rejects_sources_inside_fixture_directories(fresh_store, tmp_path, monkeypatch):
    db = fresh_store
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    source = fixtures / "realname.db"
    source.touch()
    monkeypatch.setattr(import_service, "DISALLOWED_SOURCE_DIRS", (fixtures,))
    result = import_service.import_player(db, source, "cloudplayer", "consent given")
    assert not result["ok"]
    assert result["code"] == "rejected_source"


def test_import_rejects_a_directory_source(fresh_store):
    db = fresh_store
    result = import_service.import_player(db, db.ledgers_dir, "cloudplayer", "consent given")
    assert not result["ok"]
    assert result["code"] == "rejected_source"


def test_import_refuses_a_source_inside_the_live_ledger_directory(fresh_store):
    db = fresh_store
    _make_source(db, "realplayer")
    in_ledger_dir = db.ledgers_dir / "realplayer.db"
    assert in_ledger_dir.is_file()
    result = import_service.import_player(db, in_ledger_dir, "cloudplayer", "consent given")
    assert not result["ok"]
    assert result["code"] == "rejected_source"
    assert db.get_active_account_by_username("cloudplayer") is None


def test_import_refuses_an_existing_unenrolled_destination_file(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer")
    collision = db.ledgers_dir / "cloudplayer.db"
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_bytes(b"pre-existing-personal-ledger")
    result = import_service.import_player(db, source, "cloudplayer", "consent given")
    assert not result["ok"]
    assert result["code"] == "destination_exists"
    assert db.get_active_account_by_username("cloudplayer") is None
    assert collision.read_bytes() == b"pre-existing-personal-ledger"


def test_import_creates_new_account_clears_password_and_verifies(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer")
    with db.open_ledger("realplayer") as ledger:
        source_counts = import_service._count_training_rows(ledger.conn)

    result = import_service.import_player(db, source, "cloudplayer", "in person 2026-09-28, consent note 12")

    assert result["ok"], result
    assert result["ledger_id"] != "realplayer"
    account = db.get_active_account_by_username("cloudplayer")
    assert account is not None and account["account_id"] == result["account_id"]
    with db.open_ledger(result["ledger_id"]) as ledger:
        assert ledger.get_password_hash() is None, "imported accounts must claim"
        assert import_service._count_training_rows(ledger.conn) == source_counts
    assert source_counts["workout_sessions"] == 2

    audit = _audit_row(db, result["account_id"])
    assert audit is not None
    assert audit["source_name"] == source.name
    assert audit["opt_in_reference"] == "in person 2026-09-28, consent note 12"
    assert json.loads(audit["counts_json"]) == result["counts"]

    # The printed code is the only way to claim, and it is single-use.
    assert auth_service.claim_player(db, "cloudplayer", "not-the-code", "cloud-horse-99")["ok"] is False
    claimed = auth_service.claim_player(db, "cloudplayer", result["claim_code"], "cloud-horse-99")
    assert claimed["ok"], claimed
    assert auth_service.login_player(db, "cloudplayer", "cloud-horse-99")["ok"] is True
    assert auth_service.claim_player(db, "cloudplayer", result["claim_code"], "cloud-horse-88")["ok"] is False


def test_import_of_an_old_schema_source_matches_raw_counts(fresh_store):
    db = fresh_store
    source = _make_old_schema_source(db)

    result = import_service.import_player(db, source, "cloudplayer", "consent given")

    assert result["ok"], result
    with db.open_ledger(result["ledger_id"]) as ledger:
        counts = import_service._count_training_rows(ledger.conn)
        version = ledger.conn.execute("PRAGMA user_version").fetchone()[0]
    assert counts["user_profile"] == 1
    assert result["counts"]["user_profile"] == 1
    assert version == CURRENT_LEDGER_SCHEMA_VERSION


def test_migration_that_drops_a_row_fails_verification_and_rolls_back(fresh_store, monkeypatch):
    db = fresh_store
    source = _make_source(db, "realplayer")
    real_apply = import_service.apply_lazy_migrations

    def dropping(conn, *args, **kwargs):
        real_apply(conn, *args, **kwargs)
        conn.execute("DELETE FROM workout_sessions WHERE id = (SELECT id FROM workout_sessions LIMIT 1)")
        conn.commit()

    monkeypatch.setattr(import_service, "apply_lazy_migrations", dropping)

    result = import_service.import_player(db, source, "cloudplayer", "consent given")

    assert not result["ok"]
    assert result["code"] == "verification_failed"
    assert db.get_active_account_by_username("cloudplayer") is None
    assert not (db.ledgers_dir / "cloudplayer.db").exists()


def test_wal_source_with_uncheckpointed_rows_is_imported(fresh_store):
    db = fresh_store
    source = _make_source(db, "walplayer", sessions=1)
    writer = sqlite3.connect(str(source))
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute(
            "INSERT INTO workout_sessions (id, session_date, split_name, started_at) VALUES (?, ?, ?, ?)",
            ("wal-session", "2026-02-01", "Full Body", "2026-02-01T10:00:00+00:00"),
        )
        writer.commit()
        # The row still lives in the -wal file while the writer connection is open.
        assert (source.parent / f"{source.name}-wal").is_file()
        result = import_service.import_player(db, source, "cloudplayer", "consent given")
    finally:
        writer.close()

    assert result["ok"], result
    with db.open_ledger(result["ledger_id"]) as ledger:
        count = ledger.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0]
    assert count == 2


def test_import_rekeys_schedule_and_pause_and_nulls_coach_provenance(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer", schedule=True, coach_program=True)

    result = import_service.import_player(db, source, "cloudplayer", "consent given")

    assert result["ok"], result
    with db.open_ledger(result["ledger_id"]) as ledger:
        schedules = ledger.list_training_schedules(result["ledger_id"])
        pauses = ledger.list_training_pauses(result["ledger_id"])
        assert [s["trainee_id"] for s in schedules] == [result["ledger_id"]]
        assert [p["trainee_id"] for p in pauses] == [result["ledger_id"]]
        assert ledger.list_training_schedules("realplayer") == []
        provenance = ledger.conn.execute("SELECT published_by_coach_account_id FROM training_programs").fetchone()
        assert provenance[0] is None


def test_verification_failure_never_touches_the_source(fresh_store, monkeypatch):
    db = fresh_store
    source = _make_source(db, "realplayer")
    original = source.read_bytes()

    def boom(conn, ledger_id):
        raise import_service.ImportVerificationError("boom")

    monkeypatch.setattr(import_service, "_rekey_ledger_identity", boom)

    result = import_service.import_player(db, source, "cloudplayer", "consent given")

    assert not result["ok"]
    assert result["code"] == "verification_failed"
    assert source.is_file() and source.read_bytes() == original
    assert db.get_active_account_by_username("cloudplayer") is None


def test_reimporting_the_same_source_is_refused(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer")
    first = import_service.import_player(db, source, "cloudplayer", "consent given")
    assert first["ok"], first

    second = import_service.import_player(db, source, "cloudplayer2", "consent given")
    assert not second["ok"]
    assert second["code"] == "already_imported"
    assert db.get_active_account_by_username("cloudplayer2") is None


def test_expired_claim_code_is_refused(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer")
    result = import_service.import_player(
        db,
        source,
        "cloudplayer",
        "consent given",
        ttl_hours=1,
        now=datetime.now(UTC) - timedelta(days=2),
    )
    assert result["ok"], result
    claim = auth_service.claim_player(db, "cloudplayer", result["claim_code"], "cloud-horse-99")
    assert claim["ok"] is False


@pytest.mark.parametrize("bad_ttl", [0, -1, 721, 10**6])
def test_import_rejects_out_of_range_claim_ttl(fresh_store, bad_ttl):
    db = fresh_store
    source = _make_source(db, "realplayer")
    result = import_service.import_player(db, source, "cloudplayer", "consent given", ttl_hours=bad_ttl)
    assert not result["ok"]
    assert result["code"] == "bad_ttl"
    assert db.get_active_account_by_username("cloudplayer") is None


def test_count_mismatch_rolls_back_the_new_account(fresh_store, monkeypatch):
    db = fresh_store
    source = _make_source(db, "realplayer")
    real_count = import_service._count_training_rows
    calls = {"count": 0}

    def mismatched(conn):
        counts = dict(real_count(conn))
        calls["count"] += 1
        if calls["count"] >= 2:
            counts["workout_sessions"] = counts.get("workout_sessions", 0) + 1
        return counts

    monkeypatch.setattr(import_service, "_count_training_rows", mismatched)

    result = import_service.import_player(db, source, "cloudplayer", "consent given")

    assert not result["ok"]
    assert result["code"] == "verification_failed"
    assert db.get_active_account_by_username("cloudplayer") is None
    assert not (db.ledgers_dir / "cloudplayer.db").exists()


def test_deleting_an_imported_account_removes_audit_and_claim_code(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer")
    result = import_service.import_player(db, source, "cloudplayer", "consent given")
    assert result["ok"], result
    audit = _audit_row(db, result["account_id"])
    assert audit is not None
    fingerprint = audit["source_fingerprint"]

    db.delete_account(result["account_id"], ledger_id=result["ledger_id"])

    assert db.get_active_account_by_username("cloudplayer") is None
    assert db.get_account_import_by_fingerprint(fingerprint) is None
    assert auth_service.claim_player(db, "cloudplayer", result["claim_code"], "cloud-horse-99")["ok"] is False


def test_running_twice_with_a_new_username_after_deletion_creates_a_new_account(fresh_store):
    db = fresh_store
    source = _make_source(db, "realplayer")
    first = import_service.import_player(db, source, "cloudplayer", "consent given")
    assert first["ok"], first
    db.delete_account(first["account_id"], ledger_id=first["ledger_id"])

    second = import_service.import_player(db, source, "cloudplayer", "fresh consent after deletion")
    assert second["ok"], second
    assert second["account_id"] != first["account_id"]
    assert second["ledger_id"] != first["ledger_id"]


def _enrolled_passwordless(db, username="legacy"):
    account_id = db.create_account(username)
    assert account_id is not None
    with db.open_ledger(username) as ledger:
        ledger.set_password_hash(auth_service.hash_password("initial-pass-1"))
    with db.open_ledger(username) as ledger:
        ledger.conn.execute("DELETE FROM auth_credentials")
        ledger.conn.commit()
    return account_id


def test_issue_claim_code_for_enrolled_passwordless_account(fresh_store):
    db = fresh_store
    _enrolled_passwordless(db)

    result = import_service.issue_claim_code(db, "legacy")

    assert result["ok"], result
    claim = auth_service.claim_player(db, "legacy", result["token"], "new-horse-22")
    assert claim["ok"], claim
    assert auth_service.login_player(db, "legacy", "new-horse-22")["ok"] is True
    # A claimed account is no longer a target for a new code.
    assert import_service.issue_claim_code(db, "legacy")["code"] == "already_claimed"


def test_issue_claim_code_refuses_unknown_or_non_player(fresh_store):
    db = fresh_store
    assert import_service.issue_claim_code(db, "ghost")["code"] == "unknown_account"


def test_issue_claim_code_cli_prints_a_working_code(fresh_store, capsys):
    db = fresh_store
    _enrolled_passwordless(db)
    from scripts.issue_claim_code import main

    code = main(
        [
            "legacy",
            "--catalog",
            str(db.catalog_path),
            "--users-dir",
            str(db.ledgers_dir),
            "--backups-dir",
            str(db.backups_dir),
        ]
    )

    assert code == 0
    raw = capsys.readouterr().out.strip().splitlines()[-1]
    assert auth_service.claim_player(db, "legacy", raw, "new-horse-22")["ok"] is True


@pytest.mark.parametrize("value", ["0", "-5", "721"])
def test_issue_claim_code_cli_rejects_out_of_range_ttl(value):
    from scripts.issue_claim_code import main

    with pytest.raises(SystemExit) as exc:
        main(["alice", f"--ttl-hours={value}"])
    assert exc.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "721"])
def test_import_player_cli_rejects_out_of_range_ttl(value):
    from scripts.import_player import main

    with pytest.raises(SystemExit) as exc:
        main(["source.db", "--username", "alice", "--opt-in-reference", "consent", f"--ttl-hours={value}"])
    assert exc.value.code == 2


def test_unknown_path_is_refused(fresh_store, tmp_path):
    db = fresh_store
    result = import_service.import_player(db, tmp_path / "missing.db", "cloudplayer", "consent given")
    assert not result["ok"]
    assert result["code"] == "rejected_source"


def test_source_rejection_reason_allows_a_plain_name(fresh_store, tmp_path):
    path = tmp_path / "realplayer.db"
    path.touch()
    assert import_service.source_rejection_reason(path) is None
