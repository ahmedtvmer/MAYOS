"""RegistryAccountsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any


class RegistryAccountsMixin:
    def ledger_exists(self, username: str) -> bool:
        sanitized = self._sanitize_username(username)
        return (self.ledgers_dir / f"{sanitized}.db").is_file() if sanitized else False

    _ACCOUNT_COLUMNS = (
        "account_id, username, ledger_id, status, is_player, is_coach, session_epoch, created_at, deleted_at"
    )

    @staticmethod
    def _account_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "account_id": str(row[0]),
            "username": str(row[1]),
            "ledger_id": str(row[2]),
            "status": str(row[3]),
            "is_player": bool(row[4]),
            "is_coach": bool(row[5]),
            "session_epoch": max(1, int(row[6] or 1)),
            "created_at": str(row[7]),
            "deleted_at": row[8],
        }

    @staticmethod
    def is_live_account(account: dict[str, Any] | None) -> bool:
        """True only when an account row is live.

        Deletion is authoritative: a non-NULL ``deleted_at`` makes the row dead
        even if ``status`` was left as ``'active'`` by an interrupted deletion.
        Callers use this to fail closed before mounting a ledger.
        """
        return bool(account) and account["status"] == "active" and account["deleted_at"] is None

    def _ledger_id_available(self, cursor: Any, candidate: str) -> bool:
        """True when no account row, ledger file, or backup dir uses ``candidate``.

        ``candidate`` must already be sanitised so the value checked is exactly
        the value returned by :meth:`_unique_ledger_id`. Used for the fresh,
        suffixed candidate a reused username gets; the first-time username keeps
        its backward-compatible ``ledger_id = username`` even when a bare local
        ledger file exists (registration/adoption rules handle that case).
        """
        if cursor.execute("SELECT 1 FROM accounts WHERE ledger_id = ? LIMIT 1", (candidate,)).fetchone() is not None:
            return False
        if (self.ledgers_dir / f"{candidate}.db").exists():
            return False
        return not (self.backups_dir / candidate).exists()

    def _unique_ledger_id(self, cursor: Any, base: str, account_id: str) -> str:
        """Returns a sanitised ledger id not used by any account row, file, or backup.

        ``ledger_id = username`` for a first-time username (backward compatible),
        but a reused username (one with an existing account row) must get a fresh
        ledger path so replaying the old deletion record cannot remove the new
        account's ledger (ADR 015/039). Fresh candidates are checked against the
        filesystem too, after sanitisation.
        """
        candidate = self._sanitize_username(base)
        if cursor.execute("SELECT 1 FROM accounts WHERE ledger_id = ? LIMIT 1", (candidate,)).fetchone() is None:
            return candidate
        stem = f"{candidate}-{account_id[:12]}"
        candidate = self._sanitize_username(stem)
        if self._ledger_id_available(cursor, candidate):
            return candidate
        suffix = 1
        while True:
            candidate = self._sanitize_username(f"{stem}-{suffix}")
            if self._ledger_id_available(cursor, candidate):
                return candidate
            suffix += 1

    def create_account(self, username: str) -> str | None:
        """Atomically reserves ``username`` and returns a new immutable account id.

        Returns ``None`` when a live account already owns the username. The
        uniqueness is enforced by a partial unique index, so concurrent
        registrations cannot both succeed; deleted rows keep their old id, which
        lets the username be reused later under a new id. A reused username gets
        a distinct ``ledger_id``/ledger path so it never aliases a deleted
        account's ledger.
        """
        clean_id = self._sanitize_username(username)
        if not clean_id:
            return None
        self.ensure_account_schema()
        account_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            try:
                ledger_id = self._unique_ledger_id(cursor, clean_id, account_id)
                cursor.execute(
                    "INSERT INTO accounts"
                    " (account_id, username, ledger_id, status, is_player, is_coach, session_epoch, created_at, deleted_at)"
                    " VALUES (?, ?, ?, 'active', 1, 0, 1, ?, NULL)",
                    (account_id, clean_id, ledger_id, now),
                )
                # Joins an open catalog transaction when there is one (issue
                # #113 signs an account and its link up atomically); standalone
                # calls commit exactly as before.
                self._commit_catalog()
            except sqlite3.IntegrityError:
                self._rollback_catalog()
                return None
        return account_id

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        """Reads an account by immutable id. Returns ``None`` when absent (fail closed)."""
        if not account_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (str(account_id),))
            return self._account_from_row(cursor.fetchone())

    def get_active_account_by_username(self, username: str) -> dict[str, Any] | None:
        """Reads the live account owning ``username``.

        Requires both ``status = 'active'`` and ``deleted_at IS NULL`` so an
        inactive row with an unset deletion timestamp can never be treated as
        live by login, claim, or recovery.
        """
        clean_id = self._sanitize_username(username)
        if not clean_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts"
                " WHERE username = ? AND status = 'active' AND deleted_at IS NULL",
                (clean_id,),
            )
            return self._account_from_row(cursor.fetchone())

    def bump_account_session_epoch(self, account_id: str) -> int | None:
        """Advances the registry session epoch, invalidating every prior token. Returns the new epoch."""
        if not account_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT session_epoch FROM accounts WHERE account_id = ?", (str(account_id),))
            row = cursor.fetchone()
            if row is None:
                return None
            new_epoch = max(1, int(row[0] or 1)) + 1
            cursor.execute("UPDATE accounts SET session_epoch = ? WHERE account_id = ?", (new_epoch, str(account_id)))
            self.catalog_conn.commit()
            return new_epoch
