"""RegistryAssignmentsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class EndedAssignmentSnapshot:
    assignment_id: str
    coach_account_id: str
    player_account_id: str
    started_at: str
    ended_at: str
    ended_by: str


@dataclass(frozen=True)
class AssignmentNoticeRecord:
    account_id: str
    assignment_id: str | None
    kind: str
    message: str
    created_at: str
    program_change_summary: dict[str, Any] | None = None


class RegistryAssignmentsMixin:
    _ASSIGNMENT_COLUMNS = (
        "assignment_id, coach_account_id, player_account_id, status, started_at, ended_at, ended_by"
    )

    @classmethod
    def _assignment_from_row(cls, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "assignment_id": str(row[0]),
            "coach_account_id": str(row[1]),
            "player_account_id": str(row[2]),
            "status": str(row[3]),
            "started_at": str(row[4]),
            "ended_at": row[5],
            "ended_by": row[6],
        }

    def create_assignment_invite(self, token_hash: str, coach_account_id: str, expires_at: str) -> int:
        """Stores a hashed, capacity-bound assignment invite. The raw code is never persisted."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO assignment_invites"
                " (token_hash, coach_account_id, expires_at, used_at, redeemed_by_account_id, assignment_id, created_at)"
                " VALUES (?, ?, ?, NULL, NULL, NULL, ?)",
                (token_hash, str(coach_account_id), expires_at, now),
            )
            roster_size = self.count_active_assignments_for_coach(coach_account_id)
            self.catalog_conn.commit()
            return roster_size

    def get_assignment_invite(self, token_hash: str) -> dict[str, Any] | None:
        """Reads an invite by hash for preview. Never consumes it."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT coach_account_id, expires_at, used_at, redeemed_by_account_id, assignment_id"
                " FROM assignment_invites WHERE token_hash = ?",
                (str(token_hash),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "coach_account_id": str(row[0]),
                "expires_at": str(row[1]),
                "used_at": row[2],
                "redeemed_by_account_id": row[3],
                "assignment_id": row[4],
            }

    def prune_assignment_invites(self, now_iso: str) -> int:
        """Retains invite hashes so expiry and redemption retries keep distinct reasons."""
        self.ensure_account_schema()
        return 0

    def get_coach_capacity(self, coach_account_id: str) -> int | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT capacity FROM coach_profiles WHERE account_id = ?", (str(coach_account_id),))
            row = cursor.fetchone()
            return int(row[0]) if row is not None else None

    def count_active_assignments_for_coach(self, coach_account_id: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM assignments WHERE coach_account_id = ? AND status = 'active'",
                (str(coach_account_id),),
            )
            return int(cursor.fetchone()[0])

    def active_assignment_summary(self, account_id: str) -> dict[str, int]:
        """Counts active assignments for an account in both participant roles."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT"
                " SUM(CASE WHEN coach_account_id = ? THEN 1 ELSE 0 END),"
                " SUM(CASE WHEN player_account_id = ? THEN 1 ELSE 0 END)"
                " FROM assignments WHERE status = 'active'",
                (str(account_id), str(account_id)),
            )
            row = cursor.fetchone()
        return {"as_coach": int(row[0] or 0), "as_player": int(row[1] or 0)}

    def get_active_assignment_for_player(self, player_account_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ASSIGNMENT_COLUMNS} FROM assignments"
                " WHERE player_account_id = ? AND status = 'active'",
                (str(player_account_id),),
            )
            return self._assignment_from_row(cursor.fetchone())

    def get_active_assignment_for_coach(self, coach_account_id: str, assignment_id: str) -> dict[str, Any] | None:
        """Reads one active assignment only when it belongs to this coach.

        The catalog-only gate for a coach's drill-down reads; ``None`` for an
        unknown, ended, or other coach's assignment, so callers deny all three
        identically and never mount a ledger.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ASSIGNMENT_COLUMNS} FROM assignments"
                " WHERE assignment_id = ? AND coach_account_id = ? AND status = 'active'",
                (str(assignment_id), str(coach_account_id)),
            )
            return self._assignment_from_row(cursor.fetchone())

    def list_active_assignments_for_coach(self, coach_account_id: str) -> list[dict[str, Any]]:
        """Lists active assignments with the player's username; catalog-only, no ledger mount."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT a.assignment_id, a.player_account_id, a.started_at, a.status, acc.username"
                " FROM assignments a LEFT JOIN accounts acc ON acc.account_id = a.player_account_id"
                " WHERE a.coach_account_id = ? AND a.status = 'active'"
                " ORDER BY a.started_at DESC",
                (str(coach_account_id),),
            )
            return [
                {
                    "assignment_id": str(row[0]),
                    "player_account_id": str(row[1]),
                    "started_at": str(row[2]),
                    "status": str(row[3]),
                    "player_username": str(row[4]) if row[4] is not None else "former player",
                }
                for row in cursor.fetchall()
            ]

    def _begin_immediate(self) -> None:
        """Starts a write transaction now, so reads in the block see a locked catalog.

        The catalog lock only orders threads in this process; ``BEGIN IMMEDIATE``
        takes SQLite's write lock before any capacity/account read, so a second
        connection or process cannot interleave between the check and the insert.
        """
        self.catalog_conn.execute("BEGIN IMMEDIATE")

    def _redemption_target(
        self, cursor: Any, token_hash: str, player_account_id: str, now_iso: str
    ) -> dict[str, Any]:
        """Validates a redemption inside the caller's held write transaction.

        Returns ``{"ok": False, "reason": ...}`` for a safe failure, or
        ``{"ok": True, "coach_account_id": ..., "player_username": ...}`` with the
        data the caller needs to write the assignment.
        """
        cursor.execute(
            "SELECT coach_account_id, expires_at, used_at, created_at"
            " FROM assignment_invites WHERE token_hash = ?",
            (str(token_hash),),
        )
        invite = cursor.fetchone()
        if invite is None:
            return {"ok": False, "reason": "unknown_code"}
        if invite[2] is not None:
            return {"ok": False, "reason": "already_redeemed"}
        if str(invite[1]) <= now_iso:
            return {"ok": False, "reason": "expired"}
        coach_account_id = str(invite[0])
        if coach_account_id == str(player_account_id):
            return {"ok": False, "reason": "self_assignment"}

        cursor.execute(f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (coach_account_id,))
        coach = self._account_from_row(cursor.fetchone())
        if not self.is_live_account(coach) or not coach["is_coach"]:
            return {"ok": False, "reason": "coach_unavailable"}

        cursor.execute(
            f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (str(player_account_id),)
        )
        player = self._account_from_row(cursor.fetchone())
        if not self.is_live_account(player) or not player["is_player"]:
            return {"ok": False, "reason": "not_a_player"}

        cursor.execute(
            "SELECT 1 FROM assignments WHERE player_account_id = ? AND status = 'active'",
            (str(player_account_id),),
        )
        if cursor.fetchone() is not None:
            return {"ok": False, "reason": "already_assigned"}

        cursor.execute("SELECT capacity FROM coach_profiles WHERE account_id = ?", (coach_account_id,))
        capacity_row = cursor.fetchone()
        capacity = int(capacity_row[0]) if capacity_row is not None else 0
        if self.count_active_assignments_for_coach(coach_account_id) >= capacity:
            return {"ok": False, "reason": "capacity"}
        return {
            "ok": True,
            "coach_account_id": coach_account_id,
            "player_username": player["username"],
            "invite_created_at": str(invite[3]),
        }

    def redeem_assignment_invite(
        self, token_hash: str, player_account_id: str, now_iso: str
    ) -> dict[str, Any]:
        """Atomically claims an assignment invite, creates the assignment and the coach notice.

        A single ``BEGIN IMMEDIATE`` transaction spans the invite read, account and
        capacity checks, the one-use claim, the assignment insert, and the coach
        notice, so concurrent redeemers on the same catalog cannot overfill a coach.
        Returns a reason-tagged result without leaking whether a code exists.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            conn = self.catalog_conn
            self._begin_immediate()
            cursor = conn.cursor()

            def fail(reason: str) -> dict[str, Any]:
                conn.rollback()
                return {"ok": False, "reason": reason}

            try:
                target = self._redemption_target(cursor, token_hash, player_account_id, now_iso)
                if not target["ok"]:
                    return fail(target["reason"])
                coach_account_id = target["coach_account_id"]
                player_username = target["player_username"]

                assignment_id = uuid.uuid4().hex
                notice_id = uuid.uuid4().hex
                cursor.execute(
                    "UPDATE assignment_invites"
                    " SET used_at = ?, redeemed_by_account_id = ?, assignment_id = ?"
                    " WHERE token_hash = ? AND used_at IS NULL",
                    (now_iso, str(player_account_id), assignment_id, str(token_hash)),
                )
                if cursor.rowcount != 1:
                    return fail("already_redeemed")
                cursor.execute(
                    "INSERT INTO assignments"
                    " (assignment_id, coach_account_id, player_account_id, status, started_at, ended_at, ended_by)"
                    " VALUES (?, ?, ?, 'active', ?, NULL, NULL)",
                    (assignment_id, coach_account_id, str(player_account_id), now_iso),
                )
                cursor.execute(
                    "INSERT INTO assignment_notices"
                    " (notice_id, account_id, assignment_id, kind, message, created_at, read_at)"
                    " VALUES (?, ?, ?, 'assignment_redeemed', ?, ?, NULL)",
                    (
                        notice_id,
                        coach_account_id,
                        assignment_id,
                        f"{player_username} accepted your coaching invite and is now assigned to you.",
                        now_iso,
                    ),
                )
                referring_coach_id = self.record_first_touch_referring_coach_once(
                    player_account_id, coach_account_id, now_iso
                )
                roster_size = self.count_active_assignments_for_coach(coach_account_id)
                conn.commit()
            except sqlite3.IntegrityError:
                return fail("already_assigned")
            except sqlite3.Error:
                conn.rollback()
                raise
            return {
                "ok": True,
                "assignment_id": assignment_id,
                "coach_account_id": coach_account_id,
                "player_account_id": str(player_account_id),
                "player_username": player_username,
                "notice_id": notice_id,
                "started_at": now_iso,
                "invite_created_at": target["invite_created_at"],
                "roster_size": roster_size,
                "referring_coach_id": referring_coach_id,
            }

    def end_assignment(self, assignment_id: str, account_id: str, now_iso: str, ended_by: str) -> dict[str, Any]:
        """Ends an active assignment when the caller is a participant. Revocation is immediate."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT coach_account_id, player_account_id, status, started_at"
                " FROM assignments WHERE assignment_id = ?",
                (str(assignment_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return {"ok": False, "reason": "not_found"}
            if str(row[0]) != str(account_id) and str(row[1]) != str(account_id):
                return {"ok": False, "reason": "forbidden"}
            if str(row[2]) != "active":
                return {"ok": False, "reason": "already_ended"}
            cursor.execute(
                "UPDATE assignments SET status = 'ended', ended_at = ?, ended_by = ?"
                " WHERE assignment_id = ? AND status = 'active'",
                (now_iso, str(ended_by), str(assignment_id)),
            )
            if cursor.rowcount != 1:
                self.catalog_conn.rollback()
                return {"ok": False, "reason": "already_ended"}
            roster_size = self.count_active_assignments_for_coach(str(row[0]))
            self.catalog_conn.commit()
            return {
                "ok": True,
                "ended_assignment": EndedAssignmentSnapshot(
                    assignment_id=str(assignment_id),
                    coach_account_id=str(row[0]),
                    player_account_id=str(row[1]),
                    started_at=str(row[3]),
                    ended_at=now_iso,
                    ended_by=str(ended_by),
                ),
                "roster_size": roster_size,
            }

    def disable_coach_account(self, coach_account_id: str, now_iso: str, ended_by: str) -> dict[str, Any]:
        """Ends every active assignment and clears the coach capability in one transaction.

        A redemption that commits before this transaction is ended by it; one that
        arrives after blocks on ``BEGIN IMMEDIATE`` and then sees the cleared
        capability. Either way no assignment can remain active with a disabled coach.
        The player ledger is never touched.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            conn = self.catalog_conn
            self._begin_immediate()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?",
                    (str(coach_account_id),),
                )
                account = self._account_from_row(cursor.fetchone())
                if not self.is_live_account(account) or not account["is_coach"]:
                    conn.rollback()
                    return {"ok": False}
                cursor.execute(
                    "SELECT assignment_id, player_account_id, started_at FROM assignments"
                    " WHERE coach_account_id = ? AND status = 'active'",
                    (str(coach_account_id),),
                )
                active_assignments = [
                    EndedAssignmentSnapshot(
                        assignment_id=str(row[0]),
                        coach_account_id=str(coach_account_id),
                        player_account_id=str(row[1]),
                        started_at=str(row[2]),
                        ended_at=now_iso,
                        ended_by=str(ended_by),
                    )
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    "UPDATE assignments SET status = 'ended', ended_at = ?, ended_by = ?"
                    " WHERE coach_account_id = ? AND status = 'active'",
                    (now_iso, str(ended_by), str(coach_account_id)),
                )
                ended = int(cursor.rowcount)
                cursor.execute(
                    "UPDATE accounts SET is_coach = 0"
                    " WHERE account_id = ? AND status = 'active' AND deleted_at IS NULL",
                    (str(coach_account_id),),
                )
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise
            return {
                "ok": True,
                "ended_assignments": ended,
                "ended_assignment_records": active_assignments,
                "roster_size": 0,
            }

    def create_assignment_notice(
        self,
        account_id: str,
        assignment_id: str | None,
        kind: str,
        message: str,
        now_iso: str,
    ) -> str:
        """Writes one in-app notice for an account (coach or player)."""
        return self.create_assignment_notice_record(
            AssignmentNoticeRecord(account_id, assignment_id, kind, message, now_iso)
        )

    def create_assignment_notice_record(self, notice: AssignmentNoticeRecord) -> str:
        notice_id = uuid.uuid4().hex
        self.ensure_account_schema()
        with self._catalog_lock:
            self.catalog_conn.execute(
                "INSERT INTO assignment_notices"
                " (notice_id, account_id, assignment_id, kind, message, created_at, read_at,"
                " program_change_summary_json) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    notice_id,
                    str(notice.account_id),
                    notice.assignment_id,
                    notice.kind,
                    notice.message,
                    notice.created_at,
                    json.dumps(notice.program_change_summary)
                    if notice.program_change_summary is not None
                    else None,
                ),
            )
            self.catalog_conn.commit()
        return notice_id

    def list_assignment_notices(self, account_id: str, limit: int = 20) -> list[dict[str, Any]]:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT notice_id, assignment_id, kind, message, created_at, read_at,"
                " program_change_summary_json"
                " FROM assignment_notices WHERE account_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (str(account_id), max(1, int(limit))),
            )
            return [
                {
                    "notice_id": str(row[0]),
                    "assignment_id": row[1],
                    "kind": str(row[2]),
                    "message": str(row[3]),
                    "created_at": str(row[4]),
                    "read_at": row[5],
                    "program_change_summary": json.loads(row[6]) if row[6] is not None else None,
                }
                for row in cursor.fetchall()
            ]

    def mark_assignment_notices_read(self, account_id: str, now_iso: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE assignment_notices SET read_at = ? WHERE account_id = ? AND read_at IS NULL",
                (now_iso, str(account_id)),
            )
            self.catalog_conn.commit()
            return int(cursor.rowcount)

    def list_all_active_assignments(self) -> list[dict[str, Any]]:
        """Every active assignment across coaches, for the sweep (catalog-only)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ASSIGNMENT_COLUMNS} FROM assignments"
                " WHERE status = 'active' ORDER BY started_at ASC",
            )
            return [self._assignment_from_row(row) for row in cursor.fetchall()]
