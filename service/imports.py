"""Opt-in import of an existing training ledger (ADR 019, ticket #42).

The owner runs ``scripts/import_player.py`` for one consenting person at a time.
There is deliberately no directory, glob, or bulk mode: a local data root mixes
real histories with development/test ledgers, so importing it wholesale would
create unwanted and insecure cloud accounts (ADR 019). A source that looks like
a development/test/fixture ledger is refused with no override. The heuristic is
only a guard against accidental import (renaming a file bypasses it); one
explicit file per run is the real guard.

The import never trusts the source file's schema or credentials. It takes a
consistent SQLite snapshot (``Connection.backup``), counts the raw source's rows
before migrating, migrates the snapshot to the current ledger schema through the
normal migration path, clears any password hash so the new account must claim,
creates a brand-new immutable account, rekeys every embedded ledger-identity
column to the new ledger id (and NULLs program provenance pointing at a foreign
coach account), and writes the migrated snapshot as the account's ledger.
Per-table counts are compared between the **raw source snapshot** and the
imported ledger; any mismatch (or any other failure after the account is
reserved) rolls the new account back through the normal durable deletion path,
so a failed import never leaves a half-imported live account.

An import refuses a source inside the live ledger directory and refuses a
username whose destination ledger file already exists, so rollback only ever
removes what the import created, never a pre-existing person's file.

A successful import writes one catalog audit row (account id, snapshot
fingerprint, source file name, per-table counts, the operator's opt-in
reference, and the import instant) plus an account-bound, single-use, expiring
claim code whose SHA-256 alone is stored. The raw code is returned once for the
operator to hand over out of band. ``issue_claim_code`` mints the same kind of
code for an already-enrolled password-less account (the owner script
``scripts/issue_claim_code.py``). Both rows carry no training data and no
contact details, and both are removed with the account (ADR 015/039); the unique
snapshot fingerprint makes re-running the same import a refusal while the
account lives.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from database.backup import snapshot_sqlite_file
from database.migration_manager import apply_lazy_migrations
from service._tokens import hash_token
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories inside the repo that only ever hold fixtures, evaluation data, or
#: test scaffolding, never a consenting person's real ledger.
DISALLOWED_SOURCE_DIRS = (REPO_ROOT / "tests", REPO_ROOT / "data")

#: Sanitized source-stem patterns that only ever name a development, test, or
#: fixture ledger (see ``db/users`` and the tests). This is a single place the
#: rule lives, and there is no owner override: an import is one real file. It is
#: an accidental-import guard only — renaming a file bypasses it — and it may
#: refuse a real name like ``bob.db``, in which case the owner renames the
#: copied file. Prefixes that read as a category (test/demo/eval/...) match any
#: name that starts with them; reserved person/bootstrap names match exactly or
#: with an underscore.
DENIED_SOURCE_NAME_RE = re.compile(
    r"^(?:test|demo|eval|bughunt|seed|fixture|ci_test)"
    r"|^(?:default|bootstrap|alice|bob|bp)(?:_|$)"
    r"|_default$"
)

#: Ledger tables copied by an import: every table holding the player's own
#: record. ``auth_credentials`` is intentionally absent because the import
#: clears any source password so every imported account must claim; the session
#: ``revoked_tokens`` table is not training data. A table absent from the source
#: is skipped when verifying counts (migration may create it), but every table
#: present in the source must keep its exact row count.
TRAINING_TABLES = (
    "user_profile",
    "assistant_memory",
    "training_programs",
    "program_days",
    "program_exercises",
    "workout_sessions",
    "session_commits",
    "workout_sets",
    "session_divergences",
    "session_warmup_sets",
    "personal_records",
    "performed_date_corrections",
    "chat_history",
    "training_schedules",
    "training_pauses",
    "onboarding_state",
    "intake_answers",
    "intake_state",
    "engine_telemetry",
)

DEFAULT_CLAIM_TTL_HOURS = 72
MIN_CLAIM_TTL_HOURS = 1
MAX_CLAIM_TTL_HOURS = 24 * 30


class ImportVerificationError(RuntimeError):
    """A consistent snapshot could not be reproduced as the imported ledger."""


def claim_ttl(ttl_hours: int | None) -> timedelta:
    """Claim-code lifetime, bounded to the documented 1 hour – 30 day window.

    The script validates again with ``parser.error`` for a friendly operator
    message; here a bad value is an error, never a silent clamp.
    """
    if ttl_hours is None:
        hours = DEFAULT_CLAIM_TTL_HOURS
    elif isinstance(ttl_hours, bool) or not isinstance(ttl_hours, int):
        raise ValueError("Claim-code lifetime must be a whole number of hours.")
    else:
        hours = ttl_hours
    if not MIN_CLAIM_TTL_HOURS <= hours <= MAX_CLAIM_TTL_HOURS:
        raise ValueError(
            f"Claim-code lifetime must be between {MIN_CLAIM_TTL_HOURS} and {MAX_CLAIM_TTL_HOURS} hours."
        )
    return timedelta(hours=hours)


def source_rejection_reason(source_path: str | Path, ledgers_dir: str | Path | None = None) -> str | None:
    """Why a source ledger may not be imported, or ``None`` when it may.

    One documented rule: a single existing file, named like a real ledger, not
    inside the repo's fixture directories, and not inside the live ledger
    directory (the owner snapshots a copy elsewhere first). Directories, globs,
    missing files, and dev/test names are all refused. There is no bulk or
    override path, so no override parameter exists.
    """
    raw = str(source_path or "").strip()
    if not raw:
        return "A single source ledger path is required."
    path = Path(raw).expanduser()
    if not path.exists():
        return f"Source ledger not found: {raw}"
    if not path.is_file():
        return "Source must be a single ledger file, not a directory."
    resolved = path.resolve()
    if ledgers_dir is not None:
        try:
            resolved.relative_to(Path(ledgers_dir).expanduser().resolve())
        except ValueError:
            pass
        else:
            return "Refusing a source inside the live ledger directory; copy it elsewhere first."
    for blocked in DISALLOWED_SOURCE_DIRS:
        try:
            resolved.relative_to(blocked.resolve())
        except ValueError:
            continue
        return "Refusing a source inside the repository's tests/ or data fixture directories."
    stem = path.stem.strip().lower()
    if DENIED_SOURCE_NAME_RE.search(stem):
        return f"Refusing development/test ledger '{path.name}'."
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_training_tables(conn: sqlite3.Connection) -> set[str]:
    """Training tables that exist in a raw snapshot (absent ones are skipped)."""
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    present = {str(row[0]) for row in rows}
    return present.intersection(TRAINING_TABLES)


def _count_training_rows(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts per training-data table; a missing table counts as zero."""
    counts: dict[str, int] = {}
    for table in TRAINING_TABLES:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        except sqlite3.OperationalError:
            counts[table] = 0
            continue
        counts[table] = int(row[0]) if row else 0
    return counts


def _ledger_id_reserved(db: Any, candidate: str) -> bool:
    """True when any account row (live or deleted) already maps to ``candidate``.

    Mirrors the registry's first-candidate rule so the import can tell whether
    ``create_account`` will keep ``ledger_id = username`` (and therefore whether
    a pre-existing unenrolled ``<username>.db`` would be clobbered).
    """
    with db.catalog_locked() as conn:
        row = conn.execute("SELECT 1 FROM accounts WHERE ledger_id = ? LIMIT 1", (candidate,)).fetchone()
    return row is not None


def _rekey_ledger_identity(conn: sqlite3.Connection, ledger_id: str) -> None:
    """Rewrites the ledger's embedded self-identity to its new ledger id.

    ``training_schedules``/``training_pauses`` store the old ledger id in
    ``trainee_id`` and the ledger readers filter on it, so without this the
    imported schedule and pauses are invisible. A program published by a coach
    in the source references a foreign account id; the new account has no coach
    assignment, so provenance is NULLed and the program becomes self-service.
    """
    conn.execute("UPDATE training_schedules SET trainee_id = ?", (ledger_id,))
    conn.execute("UPDATE training_pauses SET trainee_id = ?", (ledger_id,))
    conn.execute(
        "UPDATE training_programs SET published_by_coach_account_id = NULL"
        " WHERE published_by_coach_account_id IS NOT NULL"
    )
    conn.commit()


def import_player(
    db: Any,
    source_path: str | Path,
    username: str,
    opt_in_reference: str,
    *,
    ttl_hours: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Imports one consenting person's ledger under a new account identity.

    Returns a plain result dict (``ok`` and ``error``/``code`` on failure). On
    success it returns the account id, the new ledger id, the verified per-table
    counts, and the raw single-use claim code exactly once.
    """
    reference = str(opt_in_reference or "").strip()
    if not reference:
        return {"ok": False, "error": "An explicit opt-in reference is required.", "code": "missing_opt_in"}

    reason = source_rejection_reason(source_path, db.ledgers_dir)
    if reason:
        return {"ok": False, "error": reason, "code": "rejected_source"}

    clean_username = db._sanitize_username(username)
    if not clean_username:
        return {"ok": False, "error": "A new username is required.", "code": "bad_username"}
    if db.get_active_account_by_username(clean_username) is not None:
        return {"ok": False, "error": f"Account '{clean_username}' already exists.", "code": "username_taken"}
    # A first-time username keeps ``ledger_id = username``; refuse rather than
    # overwrite a pre-existing unenrolled ledger at that destination.
    if not _ledger_id_reserved(db, clean_username) and (Path(db.ledgers_dir) / f"{clean_username}.db").exists():
        return {
            "ok": False,
            "error": f"A ledger file already exists for '{clean_username}'; choose another username or move it first.",
            "code": "destination_exists",
        }

    try:
        ttl = claim_ttl(ttl_hours)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "bad_ttl"}

    moment = now or datetime.now(UTC)
    source = Path(source_path).expanduser().resolve()
    staging = Path(tempfile.mkdtemp(prefix="mayos-import-", dir=str(db.backups_dir)))
    snapshot_path = staging / "snapshot.db"
    account_id: str | None = None
    ledger_id: str | None = None

    try:
        # Consistent snapshot of the source (works for WAL; never a raw copy).
        snapshot_sqlite_file(source, snapshot_path)
        fingerprint = _file_sha256(snapshot_path)
        if db.get_account_import_by_fingerprint(fingerprint) is not None:
            return {"ok": False, "error": "This ledger snapshot was already imported.", "code": "already_imported"}

        # Count the RAW source before any migration, so a migration that drops or
        # duplicates a row is caught instead of compared against a byte copy of
        # itself. Tables absent from the source are skipped: migration may
        # legitimately create (and backfill) them.
        raw = sqlite3.connect(str(snapshot_path))
        raw.row_factory = sqlite3.Row
        try:
            source_tables = _existing_training_tables(raw)
            source_counts = _count_training_rows(raw)
        finally:
            raw.close()

        # Migrate the snapshot to the current schema through the engine path,
        # then clear any password hash so the imported account must claim.
        migrated = sqlite3.connect(str(snapshot_path))
        migrated.row_factory = sqlite3.Row
        try:
            apply_lazy_migrations(migrated, clean_username, staging / "ledgers", staging / "backups")
            db.create_ledger_schema_on(migrated)
            migrated.execute("DELETE FROM auth_credentials")
            migrated.commit()
        finally:
            migrated.close()

        account_id = db.create_account(clean_username)
        if account_id is None:
            return {"ok": False, "error": f"Account '{clean_username}' already exists.", "code": "username_taken"}
        account = db.get_account(account_id) or {}
        ledger_id = str(account.get("ledger_id") or clean_username)
        destination = Path(db.ledgers_dir) / f"{ledger_id}.db"
        # Write the migrated snapshot as the new account's ledger (consistent
        # copy, no WAL side files). Never reuse the source file name as identity.
        snapshot_sqlite_file(snapshot_path, destination)

        imported = sqlite3.connect(str(destination))
        imported.row_factory = sqlite3.Row
        try:
            _rekey_ledger_identity(imported, ledger_id)
            imported_counts = _count_training_rows(imported)
        finally:
            imported.close()
        mismatches = {
            table: (source_counts.get(table, 0), imported_counts.get(table, 0))
            for table in source_tables
            if source_counts.get(table, 0) != imported_counts.get(table, 0)
        }
        if mismatches:
            detail = ", ".join(f"{table} {raw_n}->{got_n}" for table, (raw_n, got_n) in sorted(mismatches.items()))
            raise ImportVerificationError(
                f"Record counts differ between the source and imported ledger for '{clean_username}': {detail}."
            )

        raw_code = secrets.token_urlsafe(32)
        expires_at = (moment + ttl).isoformat()
        try:
            db.record_account_import(
                import_id=uuid.uuid4().hex,
                account_id=account_id,
                source_fingerprint=fingerprint,
                source_name=source.name,
                counts_json=json.dumps(imported_counts, sort_keys=True),
                opt_in_reference=reference,
                imported_at=moment.isoformat(),
                claim_token_hash=hash_token(raw_code),
                claim_expires_at=expires_at,
            )
        except sqlite3.IntegrityError as exc:
            raise ImportVerificationError("This ledger snapshot was already imported.") from exc
        logger.info("Imported ledger %s as account %s (%s).", source.name, account_id, ledger_id)
        return {
            "ok": True,
            "claim_code": raw_code,
            "account_id": account_id,
            "username": clean_username,
            "ledger_id": ledger_id,
            "expires_at": expires_at,
            "counts": imported_counts,
        }
    except Exception as exc:
        # Roll back through the normal durable deletion path: a failed import
        # leaves no half-imported live account. The source itself is never
        # touched: it was copied to a snapshot made outside the live directory,
        # and the destination was checked free before writing.
        if account_id is not None:
            try:
                db.delete_account(account_id, ledger_id=ledger_id)
            except Exception:
                logger.exception("Failed to roll back imported account %s.", account_id)
        if isinstance(exc, ImportVerificationError):
            logger.warning("Import of %s failed verification: %s", source, exc)
            return {"ok": False, "error": str(exc), "code": "verification_failed"}
        logger.exception("Import of %s failed.", source)
        return {"ok": False, "error": f"Import failed: {exc}", "code": "import_failed"}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def issue_claim_code(
    db: Any,
    username: str,
    *,
    ttl_hours: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Owner issuance of a claim code for a live, password-less player account.

    Enrolled accounts that predate imports (or whose password hash was cleared)
    cannot use ``/auth/claim`` without a code, and only an import used to mint
    one. This gives the operator the same single-use, account-bound, expiring
    code for such an account; only its SHA-256 is stored. Refuses a non-player
    or an account that already has a password (use password reset for that).
    """
    clean_id = db._sanitize_username(username)
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return {"ok": False, "error": f"Unknown player account '{username}'.", "code": "unknown_account"}
    with db.open_ledger(account["ledger_id"]) as ledger:
        if ledger.get_password_hash() is not None:
            return {
                "ok": False,
                "error": "This account already has a password; it is not waiting to be claimed.",
                "code": "already_claimed",
            }
    try:
        ttl = claim_ttl(ttl_hours)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "bad_ttl"}
    moment = now or datetime.now(UTC)
    raw_code = secrets.token_urlsafe(32)
    expires_at = (moment + ttl).isoformat()
    db.prune_claim_codes(moment.isoformat())
    db.create_claim_code(
        account["account_id"],
        hash_token(raw_code),
        expires_at,
        created_at=moment.isoformat(),
    )
    logger.info("Issued claim code for account %s.", account["account_id"])
    return {
        "ok": True,
        "token": raw_code,
        "account_id": account["account_id"],
        "username": clean_id,
        "expires_at": expires_at,
    }
