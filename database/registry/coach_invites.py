"""RegistryCoachInvitesMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Any


class RegistryCoachInvitesMixin:
    def create_coach_invite(self, token_hash: str, account_id: str, expires_at: str) -> None:
        """Stores a hashed, account-bound invite. The raw token is never persisted."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO coach_invites (token_hash, account_id, expires_at, used_at, created_at)"
                " VALUES (?, ?, ?, NULL, ?)",
                (token_hash, str(account_id), expires_at, now),
            )
            self.catalog_conn.commit()

    def redeem_coach_invite(
        self, token_hash: str, account_id: str, now_iso: str, default_capacity: int
    ) -> dict[str, Any] | None:
        """Atomically claims a coach invite and grants the coach capability.

        ``account_id`` is the caller's verified immutable id; the invite must be
        bound to it, so a leaked code cannot grant an arbitrary account. Returns
        the updated account row on success, or ``None`` when the token is unknown,
        expired, already used, bound to another account, or bound to a
        dead/non-player account. The ``used_at`` claim, the ``is_coach`` flip, and
        the profile seed commit as one transaction, so a leaked code cannot be
        replayed and a crash cannot leave the capability half-granted.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id, expires_at, used_at FROM coach_invites WHERE token_hash = ?",
                (token_hash,),
            )
            row = cursor.fetchone()
            if row is None or row[2] is not None or str(row[1]) <= now_iso:
                return None
            if str(row[0]) != str(account_id):
                return None
            cursor.execute(f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (account_id,))
            account = self._account_from_row(cursor.fetchone())
            if not self.is_live_account(account) or not account["is_player"]:
                return None
            try:
                cursor.execute(
                    "UPDATE coach_invites SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                    (now_iso, token_hash),
                )
                if cursor.rowcount != 1:
                    self.catalog_conn.rollback()
                    return None
                cursor.execute("UPDATE accounts SET is_coach = 1 WHERE account_id = ?", (account_id,))
                cursor.execute(
                    """
                    INSERT INTO coach_profiles
                        (account_id, display_name, bio, specialization, capacity, created_at, updated_at)
                    VALUES (?, ?, '', '', ?, ?, ?)
                    ON CONFLICT(account_id) DO NOTHING
                    """,
                    (account_id, account["username"], int(default_capacity), now_iso, now_iso),
                )
                self.catalog_conn.commit()
            except sqlite3.Error:
                self.catalog_conn.rollback()
                raise
            account["is_coach"] = True
            return account

    def prune_coach_invites(self, now_iso: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM coach_invites WHERE expires_at < ? OR used_at IS NOT NULL",
                (now_iso,),
            )
            self.catalog_conn.commit()
            return cursor.rowcount

    def get_coach_profile(self, account_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id, display_name, bio, specialization, capacity"
                " FROM coach_profiles WHERE account_id = ?",
                (str(account_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "account_id": str(row[0]),
                "display_name": str(row[1]),
                "bio": str(row[2]),
                "specialization": str(row[3]),
                "capacity": int(row[4]),
            }

    def upsert_coach_profile(self, account_id: str, profile: dict[str, Any]) -> None:
        """Writes coach-authored fields; callers validate and bound them first."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                """
                INSERT INTO coach_profiles
                    (account_id, display_name, bio, specialization, capacity, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    bio = excluded.bio,
                    specialization = excluded.specialization,
                    capacity = excluded.capacity,
                    updated_at = excluded.updated_at
                """,
                (
                    str(account_id),
                    profile["display_name"],
                    profile["bio"],
                    profile["specialization"],
                    int(profile["capacity"]),
                    now,
                    now,
                ),
            )
            self.catalog_conn.commit()
