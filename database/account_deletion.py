"""AccountDeletionMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import os
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from database.backup import remove_ledger_from_daily_backups
from database.program_drafts import discard_assignment_program_draft
from database.registry.assignments import EndedAssignmentSnapshot
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


class AccountDeletionMixin:
    _DELETION_COLUMNS = "account_id, ledger_id, deleted_at, applied_at"

    def _initialize_deletions(self) -> None:
        """Opens the external deletion ledger and ensures its schema exists."""
        os.makedirs(self.deletions_path.parent, exist_ok=True)
        self._deletions_lock = threading.Lock()
        self.deletions_conn = sqlite3.connect(self.deletions_path, check_same_thread=False)
        self.deletions_conn.execute("PRAGMA journal_mode = WAL;")
        self.deletions_conn.execute("PRAGMA busy_timeout = 5000;")
        with self._deletions_lock:
            self.deletions_conn.execute(
                "CREATE TABLE IF NOT EXISTS account_deletions ("
                " account_id TEXT PRIMARY KEY,"
                " ledger_id TEXT NOT NULL,"
                " deleted_at TEXT NOT NULL,"
                " applied_at TEXT)"
            )
            columns = {row[1] for row in self.deletions_conn.execute("PRAGMA table_info(account_deletions)")}
            if "applied_at" not in columns:
                self.deletions_conn.execute("ALTER TABLE account_deletions ADD COLUMN applied_at TEXT")
            if "analytics_deleted_at" not in columns:
                self.deletions_conn.execute("ALTER TABLE account_deletions ADD COLUMN analytics_deleted_at TEXT")
            if "analytics_delete_attempts" not in columns:
                self.deletions_conn.execute(
                    "ALTER TABLE account_deletions ADD COLUMN analytics_delete_attempts INTEGER NOT NULL DEFAULT 0"
                )
            if "analytics_delete_last_attempt_at" not in columns:
                self.deletions_conn.execute(
                    "ALTER TABLE account_deletions ADD COLUMN analytics_delete_last_attempt_at TEXT"
                )
            if "analytics_delete_status" not in columns:
                self.deletions_conn.execute(
                    "ALTER TABLE account_deletions ADD COLUMN analytics_delete_status TEXT NOT NULL DEFAULT 'pending'"
                )
            self.deletions_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_deletions_ledger ON account_deletions(ledger_id)"
            )
            self.deletions_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_deletions_analytics_pending"
                " ON account_deletions(analytics_delete_status, analytics_delete_attempts,"
                " analytics_delete_last_attempt_at, deleted_at)"
            )
            self.deletions_conn.commit()

    def _pending_analytics_deletions(self, not_before: str, limit: int) -> list[tuple[str, str]]:
        """Returns mature, pending ids in bounded retry-fairness order."""
        if limit <= 0:
            return []
        with self._deletions_lock:
            rows = self.deletions_conn.execute(
                "SELECT account_id, deleted_at FROM account_deletions"
                " WHERE analytics_delete_status = 'pending' AND deleted_at <= ?"
                " ORDER BY analytics_delete_attempts ASC, analytics_delete_last_attempt_at ASC,"
                " deleted_at ASC, account_id ASC LIMIT ?",
                (not_before, limit),
            ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def _mark_analytics_deletion_attempt(
        self, account_id: str, outcome: str, *, attempted: bool, delivered: bool
    ) -> None:
        """Persists the provider outcome and advances attempt metadata if a request ran."""
        attempted_at = datetime.now(UTC).isoformat() if attempted else None
        delivered_at = attempted_at if delivered else None
        with self._deletions_lock:
            self.deletions_conn.execute(
                "UPDATE account_deletions SET analytics_delete_attempts = analytics_delete_attempts + ?,"
                " analytics_delete_last_attempt_at = CASE WHEN ? THEN ? ELSE analytics_delete_last_attempt_at END,"
                " analytics_delete_status = ?,"
                " analytics_deleted_at = CASE WHEN ? THEN COALESCE(analytics_deleted_at, ?)"
                " ELSE analytics_deleted_at END"
                " WHERE account_id = ? AND analytics_delete_status = 'pending'",
                (
                    int(attempted),
                    attempted,
                    attempted_at,
                    outcome,
                    delivered,
                    delivered_at,
                    str(account_id),
                ),
            )
            self.deletions_conn.commit()

    def record_account_deletion(
        self, account_id: str, ledger_id: str, deleted_at: str | None = None
    ) -> None:
        """Appends (or refreshes) a durable deletion record. Idempotent on the account id.

        A re-record preserves an existing ``applied_at`` marker; a new record
        starts unapplied so startup/sweep replay completes it.
        """
        if not account_id:
            return
        now = deleted_at or datetime.now(UTC).isoformat()
        with self._deletions_lock:
            self.deletions_conn.execute(
                "INSERT INTO account_deletions (account_id, ledger_id, deleted_at, applied_at)"
                " VALUES (?, ?, ?, NULL)"
                " ON CONFLICT(account_id) DO UPDATE SET"
                " ledger_id = excluded.ledger_id, deleted_at = excluded.deleted_at",
                (str(account_id), str(ledger_id), now),
            )
            self.deletions_conn.commit()

    def is_account_deleted(self, account_id: str) -> bool:
        """True when a durable deletion record exists, even before the catalog commit lands."""
        if not account_id:
            return False
        conn = getattr(self, "deletions_conn", None)
        if conn is None:
            return False
        with self._deletions_lock:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM account_deletions WHERE account_id = ?", (str(account_id),))
            return cursor.fetchone() is not None

    def _ledger_is_deleted(self, ledger_id: str) -> bool:
        """True when ``ledger_id`` is recorded deleted and no live account owns it.

        Cheap indexed lookup: an empty result means the ledger was never deleted;
        otherwise a live owner (a reused username's new account) overrides the
        record, so mounting it is allowed.
        """
        conn = getattr(self, "deletions_conn", None)
        if conn is None:
            return False
        sanitized = self._sanitize_username(ledger_id)
        with self._deletions_lock:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM account_deletions WHERE ledger_id = ? LIMIT 1", (sanitized,))
            recorded = cursor.fetchone() is not None
        if not recorded:
            return False
        return not self._ledger_owned_by_live_account(sanitized)

    def list_account_deletions(self) -> list[dict[str, Any]]:
        """Every durable deletion record, oldest-first."""
        conn = getattr(self, "deletions_conn", None)
        if conn is None:
            return []
        with self._deletions_lock:
            cursor = conn.cursor()
            cursor.execute(f"SELECT {self._DELETION_COLUMNS} FROM account_deletions ORDER BY deleted_at ASC")
            return [
                {
                    "account_id": str(row[0]),
                    "ledger_id": str(row[1]),
                    "deleted_at": str(row[2]),
                    "applied_at": row[3],
                }
                for row in cursor.fetchall()
            ]

    def _mark_deletion_applied(self, account_id: str) -> None:
        """Marks one record as fully applied (catalog + files) for incremental replay."""
        with self._deletions_lock:
            self.deletions_conn.execute(
                "UPDATE account_deletions SET applied_at = ? WHERE account_id = ?",
                (datetime.now(UTC).isoformat(), str(account_id)),
            )
            self.deletions_conn.commit()

    def _mark_deletion_pending(self, account_id: str) -> None:
        """Keeps incomplete cleanup eligible for the next incremental replay."""
        with self._deletions_lock:
            self.deletions_conn.execute(
                "UPDATE account_deletions SET applied_at = NULL WHERE account_id = ?",
                (str(account_id),),
            )
            self.deletions_conn.commit()

    def delete_account(
        self, account_id: str, now_iso: str | None = None, ledger_id: str | None = None
    ) -> dict[str, Any]:
        """Durably deletes an account: record, catalog rows, then ledger/backup files.

        Ordering makes an interrupted deletion fail closed and resumable: the
        record is written before any catalog change, so a later startup/restore
        replay (:meth:`replay_deletions`) finishes the job. An unknown account is
        refused and never recorded.

        ``ledger_id`` is the explicit corpus this call operates on (ADR 041,
        phase B); callers pass the account's ledger id. When omitted, the
        account's own ledger id is re-resolved from the registry.
        """
        now = now_iso or datetime.now(UTC).isoformat()
        account = self.get_account(account_id)
        if account is None:
            return {"ok": False, "error": "Account not found."}
        resolved_ledger_id = ledger_id or account["ledger_id"]
        # (a) durable record first.
        self.record_account_deletion(str(account_id), resolved_ledger_id, now)
        # (b) catalog: mark deleted, revoke sessions, end relationships.
        deletion_state = self._force_delete_account_catalog(str(account_id), now)
        # (c) live ledger + any user-specific backup copies.
        # Keep network I/O off the request path. With R2 configured, the
        # durable record remains pending until startup/hourly replay completes it.
        remote_cleanup_complete = self._remove_account_files(resolved_ledger_id, remove_offsite=False)
        if remote_cleanup_complete:
            self._mark_deletion_applied(str(account_id))
        else:
            self._mark_deletion_pending(str(account_id))
        # model_usage rows keep the opaque account id for billing reconciliation
        # (documented in ADR 039); they carry no username or contact details.
        return {
            "ok": True,
            "account_id": str(account_id),
            "ledger_id": resolved_ledger_id,
            "deleted_at": now,
            "was_coach": deletion_state["was_coach"],
            "ended_assignments": deletion_state["ended_assignments"],
            "roster_counts_by_coach": deletion_state["roster_counts_by_coach"],
        }

    def _force_delete_account_catalog(self, account_id: str, now_iso: str) -> dict[str, Any]:
        """Forces one account's catalog state to deleted in a single transaction.

        Idempotent: calling it again (startup/restore replay) leaves an already
        deleted row alone rather than bumping the epoch further. Assignments are
        ended but retained so the player keeps their history and the deleted
        coach is presented as "Former coach"; relationships that exist only to
        serve the account are removed.
        """
        account_id = str(account_id)
        with self.catalog_transaction():
            conn = self.catalog_conn
            cursor = conn.cursor()
            cursor.execute("SELECT username, is_coach, status FROM accounts WHERE account_id = ?", (account_id,))
            username_row = cursor.fetchone()
            legacy_username = str(username_row[0]) if username_row is not None else account_id
            was_coach = bool(username_row[1]) if username_row is not None else False
            already_deleted = username_row is None or (str(username_row[2]) == "deleted" and not was_coach)
            # The account's assignments, collected before anything is removed.
            cursor.execute(
                "SELECT assignment_id, player_account_id FROM assignments"
                " WHERE coach_account_id = ? OR player_account_id = ?",
                (account_id, account_id),
            )
            assignment_details = [
                (str(row[0]), str(row[1])) for row in cursor.fetchall()
            ]
            assignment_ids = [assignment_id for assignment_id, _ in assignment_details]
            active_assignments: list[EndedAssignmentSnapshot] = []
            if not already_deleted:
                cursor.execute(
                    "SELECT assignment_id, coach_account_id, player_account_id, started_at"
                    " FROM assignments WHERE (coach_account_id = ? OR player_account_id = ?)"
                    " AND status = 'active'",
                    (account_id, account_id),
                )
                active_assignments = [
                    EndedAssignmentSnapshot(
                        assignment_id=str(row[0]),
                        coach_account_id=str(row[1]),
                        player_account_id=str(row[2]),
                        started_at=str(row[3]),
                        ended_at=now_iso,
                        ended_by="account_deleted",
                    )
                    for row in cursor.fetchall()
                ]
            cursor.execute(
                "UPDATE accounts SET status = 'deleted', deleted_at = ?,"
                " session_epoch = CASE WHEN deleted_at IS NULL THEN session_epoch + 1 ELSE session_epoch END,"
                " is_coach = 0"
                " WHERE account_id = ?",
                (now_iso, account_id),
            )
            # Recovery identity and single-use credentials. Live rows are keyed by
            # immutable account id; legacy rows may be keyed by the (now reusable)
            # username. Clear the legacy keys only when no *other* live account
            # already owns that username, so a reincarnated account's recovery
            # rows are never touched (ADR 015/039).
            cursor.execute(
                "SELECT 1 FROM accounts"
                " WHERE username = ? AND status = 'active' AND deleted_at IS NULL LIMIT 1",
                (legacy_username,),
            )
            username_reused_live = cursor.fetchone() is not None
            legacy_key = account_id if username_reused_live else legacy_username
            cursor.execute(
                "DELETE FROM trainee_emails WHERE trainee_id = ? OR trainee_id = ?",
                (account_id, legacy_key),
            )
            cursor.execute(
                "DELETE FROM pending_recovery_emails WHERE account_id = ?",
                (account_id,),
            )
            cursor.execute(
                "DELETE FROM password_reset_tokens WHERE trainee_id = ? OR trainee_id = ?",
                (account_id, legacy_key),
            )
            cursor.execute(
                "DELETE FROM email_verification_codes WHERE account_id = ?",
                (account_id,),
            )
            cursor.execute("DELETE FROM coach_invites WHERE account_id = ?", (account_id,))
            # Linked sign-ins (Google) go with the account, in this same
            # transaction: the subject is freed so it can later create (or
            # link to) a brand-new account, and a replayed deletion clears
            # them too (#114).
            cursor.execute("DELETE FROM linked_sign_ins WHERE account_id = ?", (account_id,))
            # The import audit carries the source file name and operator's
            # opt-in reference, so it is removed with the account (ADR 015/039).
            cursor.execute("DELETE FROM account_imports WHERE account_id = ?", (account_id,))
            cursor.execute("DELETE FROM first_touch_acquisition WHERE account_id = ?", (account_id,))
            cursor.execute("DELETE FROM account_analytics_preferences WHERE account_id = ?", (account_id,))
            cursor.execute("DELETE FROM coach_profiles WHERE account_id = ?", (account_id,))
            cursor.execute(
                "UPDATE coach_exercises SET note = NULL, video_url = NULL WHERE coach_account_id = ?",
                (account_id,),
            )
            cursor.execute("DELETE FROM account_plans WHERE account_id = ?", (account_id,))
            cursor.execute(
                "DELETE FROM assignment_invites"
                " WHERE coach_account_id = ? OR redeemed_by_account_id = ?",
                (account_id, account_id),
            )
            # Notices attached to the deleted account's assignments are removed on
            # both sides: their copy contains the deleted, now-reusable username.
            if assignment_ids:
                placeholders = ",".join("?" for _ in assignment_ids)
                cursor.execute(
                    f"DELETE FROM assignment_notices"
                    f" WHERE account_id = ? OR assignment_id IN ({placeholders})",
                    (account_id, *assignment_ids),
                )
            else:
                cursor.execute("DELETE FROM assignment_notices WHERE account_id = ?", (account_id,))
            cursor.execute(
                "DELETE FROM program_requests WHERE coach_account_id = ? OR player_account_id = ?",
                (account_id, account_id),
            )
            cursor.execute(
                "DELETE FROM check_ins WHERE player_account_id = ?", (account_id,)
            )
            # Assignments are ended (reason 'account_deleted') but retained, so the
            # player's published program keeps its provenance and former-coach
            # attribution can be rendered (ADR 026/039).
            if assignment_ids:
                placeholders = ",".join("?" for _ in assignment_ids)
                cursor.execute(
                    f"UPDATE assignments SET status = 'ended', ended_at = ?, ended_by = 'account_deleted'"
                    f" WHERE assignment_id IN ({placeholders}) AND status = 'active'",
                    (now_iso, *assignment_ids),
                )
                cursor.execute(
                    f"DELETE FROM roster_attendance WHERE assignment_id IN ({placeholders})",
                    assignment_ids,
                )
                cursor.execute(
                    f"DELETE FROM alert_signal_state WHERE assignment_id IN ({placeholders})",
                    assignment_ids,
                )
                cursor.execute(
                    f"DELETE FROM progression_alert_sessions WHERE assignment_id IN ({placeholders})",
                    assignment_ids,
                )
                cursor.execute(
                    f"DELETE FROM coach_alerts WHERE assignment_id IN ({placeholders})",
                    assignment_ids,
                )
            cursor.execute(
                "DELETE FROM coach_alerts WHERE coach_account_id = ? OR player_account_id = ?",
                (account_id, account_id),
            )
            if assignment_ids:
                placeholders = ",".join("?" for _ in assignment_ids)
                cursor.execute(
                    "DELETE FROM coach_analytics_daily_markers"
                    f" WHERE coach_account_id = ? OR assignment_id IN ({placeholders})",
                    (account_id, *assignment_ids),
                )
            else:
                cursor.execute(
                    "DELETE FROM coach_analytics_daily_markers WHERE coach_account_id = ?",
                    (account_id,),
                )
            coach_ids = {assignment.coach_account_id for assignment in active_assignments}
            roster_counts_by_coach: dict[str, int] = {}
            if coach_ids:
                placeholders = ",".join("?" for _ in coach_ids)
                cursor.execute(
                    "SELECT coach_account_id, COUNT(*) FROM assignments"
                    f" WHERE coach_account_id IN ({placeholders}) AND status = 'active'"
                    " GROUP BY coach_account_id",
                    tuple(coach_ids),
                )
                roster_counts_by_coach = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
                roster_counts_by_coach.update(
                    {coach_id: roster_counts_by_coach.get(coach_id, 0) for coach_id in coach_ids}
                )
            deletion_state = {
                "was_coach": was_coach,
                "ended_assignments": active_assignments,
                "roster_counts_by_coach": roster_counts_by_coach,
            }
        self._discard_assignment_program_drafts(account_id, assignment_details)
        return deletion_state

    def _discard_assignment_program_drafts(
        self, deleted_account_id: str, assignment_details: list[tuple[str, str]]
    ) -> None:
        """Account deletion bypasses the normal assignment-end cleanup service."""
        for assignment_id, player_account_id in assignment_details:
            if player_account_id == deleted_account_id:
                continue
            discard_assignment_program_draft(self, assignment_id, player_account_id)

    def _ledger_owned_by_live_account(self, ledger_id: str) -> bool:
        """True when a live account currently maps to ``ledger_id``.

        A deleted account's username (and therefore its ledger id/file) can be
        reused by a new immutable account, so a replayed deletion must never
        remove a ledger that now belongs to a live account (ADR 015/039).
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT 1 FROM accounts"
                " WHERE ledger_id = ? AND status = 'active' AND deleted_at IS NULL"
                " LIMIT 1",
                (str(ledger_id),),
            )
            return cursor.fetchone() is not None

    def _remove_account_files(self, ledger_id: str, *, remove_offsite: bool = True) -> bool:
        """Closes this thread's connection, then removes the live ledger and backups.

        Fails closed on an empty, non-canonical, or reserved (``default``) ledger
        id, so a bad record can never delete an unrelated or shared ledger. A
        deferred or failed remote cleanup returns ``False`` so replay retries it.
        """
        raw = "" if ledger_id is None else str(ledger_id)
        if not raw.strip():
            logger.warning("Refusing to remove ledger files for an empty ledger id.")
            return True
        sanitized = self._sanitize_username(raw)
        if sanitized != raw or sanitized == "default":
            logger.warning(f"Refusing to remove ledger files for non-canonical ledger id '{raw}'.")
            return True
        if self._ledger_owned_by_live_account(sanitized):
            # The username was reused by a new account after the recorded
            # deletion; its ledger is not the deleted account's and must survive.
            return True
        # Ledgers live on explicit handles and are closed by their owners before
        # deletion runs (ADR 041); the store holds no connection to unmount here.
        for suffix in ("", "-wal", "-shm"):
            path = self.ledgers_dir / f"{sanitized}.db{suffix}"
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"Failed to remove ledger file {path}: {exc}")
        ledger_backup_dir = self.backups_dir / sanitized
        if ledger_backup_dir.is_dir():
            try:
                shutil.rmtree(ledger_backup_dir)
            except OSError as exc:
                logger.warning(f"Failed to remove ledger backups {ledger_backup_dir}: {exc}")
        # A daily snapshot's user-specific ledger copy is removed with the
        # account too (ADR 015/039). The catalog rows inside whole-catalog
        # snapshots remain the documented restricted recovery exception (#41).
        try:
            remove_ledger_from_daily_backups(self, sanitized)
        except OSError as exc:
            logger.warning(f"Failed to remove daily-backup copies of ledger {sanitized}: {exc}")
        remote_cleanup_complete = True
        offsite = getattr(self, "offsite_backup", None)
        if offsite is not None:
            if not remove_offsite:
                logger.info("Off-site ledger cleanup deferred to deletion replay.")
                return False
            try:
                offsite.remove_ledger(sanitized)
            except Exception as exc:
                # The durable deletion record makes this cleanup retryable from
                # the normal replay path; provider errors never undo deletion.
                remote_cleanup_complete = False
                logger.warning(
                    "Failed to remove off-site snapshot copies for a deleted ledger (%s); deletion replay will retry.",
                    type(exc).__name__,
                )
        return remote_cleanup_complete

    def _replay_deletions_with_facts(self, *, full: bool = False) -> tuple[int, list[dict[str, Any]]]:
        """Replays durable deletion records; returns how many were processed.

        Incremental (``full=False``, the startup/sweep path) skips records already
        marked applied, so a deletion whose catalog transaction failed completes
        on the next pass without a restart. A full replay (``full=True``, used
        after a restore that may have rolled the catalog back) re-checks every
        record regardless of its marker.
        """
        records = self.list_account_deletions()
        applied = 0
        changed_accounts: list[dict[str, Any]] = []
        for record in records:
            if not full and record.get("applied_at") is not None:
                continue
            deletion_state = self._force_delete_account_catalog(record["account_id"], record["deleted_at"])
            if deletion_state["was_coach"] or deletion_state["ended_assignments"]:
                changed_accounts.append(
                    {
                        "account_id": record["account_id"],
                        "deleted_at": record["deleted_at"],
                        **deletion_state,
                    }
                )
            if not self._remove_account_files(record["ledger_id"]):
                self._mark_deletion_pending(record["account_id"])
                continue
            self._mark_deletion_applied(record["account_id"])
            applied += 1
        return applied, changed_accounts

    def replay_deletions(self, *, full: bool = False) -> int:
        return self._replay_deletions_with_facts(full=full)[0]

    def _reapply_deletions_with_facts(self) -> tuple[int, list[dict[str, Any]]]:
        return self._replay_deletions_with_facts(full=True)

    def reapply_deletions(self) -> int:
        """Full deletion replay for the restore path; re-checks every record."""
        return self._reapply_deletions_with_facts()[0]
