"""RegistryAccountsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

_ANALYTICS_ALLOWED_SQL = (
    "COALESCE((SELECT analytics_allowed FROM account_analytics_preferences "
    "WHERE account_id = accounts.account_id), 1)"
)


FIRST_TOUCH_ACQUISITION_FIELDS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "referrer_host",
    "referring_coach_id",
)


class RegistryAccountsMixin:
    def ledger_exists(self, username: str) -> bool:
        sanitized = self._sanitize_username(username)
        return (self.ledgers_dir / f"{sanitized}.db").is_file() if sanitized else False

    _ACCOUNT_COLUMNS = (
        "account_id, username, ledger_id, status, is_player, is_coach, session_epoch, created_at, deleted_at, last_seen_at, last_seen_build, display_language, "
        + _ANALYTICS_ALLOWED_SQL
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
            "last_seen_at": row[9],
            "last_seen_build": row[10],
            "display_language": row[11] or "en",
            "analytics_allowed": bool(row[12]),
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

    def create_account(self, username: str, *, allow_held_username: bool = False, display_language: str = "en") -> str | None:
        """Atomically reserves ``username`` and returns a new immutable account id.

        Returns ``None`` when a live account owns the username or a live Coach
        invite holds it. The uniqueness is enforced by a partial unique index,
        so concurrent registrations cannot both succeed; deleted rows keep
        their old id, which lets the username be reused later under a new id. A
        reused username gets a distinct ``ledger_id``/ledger path so it never
        aliases a deleted account's ledger.
        """
        clean_id = self._sanitize_username(username)
        if not clean_id:
            return None
        self.ensure_account_schema()
        account_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self.catalog_transaction(immediate=True):
            cursor = self.catalog_conn.cursor()
            try:
                if not allow_held_username:
                    if self._username_has_live_coach_invite_hold(clean_id, now):
                        return None
                ledger_id = self._unique_ledger_id(cursor, clean_id, account_id)
                cursor.execute(
                    "INSERT INTO accounts"
                    " (account_id, username, ledger_id, status, is_player, is_coach, session_epoch, created_at, deleted_at, display_language)"
                    " VALUES (?, ?, ?, 'active', 1, 0, 1, ?, NULL, ?)",
                    (account_id, clean_id, ledger_id, now, display_language if display_language in ("en", "ar") else "en"),
                )
            except sqlite3.IntegrityError:
                self._rollback_catalog()
                return None
        return account_id

    def record_first_touch_acquisition_once(
        self, account_id: str, first_touch: dict[str, str | None]
    ) -> None:
        """Inserts acquisition once; caller includes it in the account transaction."""
        self.ensure_account_schema()
        columns = ", ".join(FIRST_TOUCH_ACQUISITION_FIELDS)
        placeholders = ", ".join("?" for _ in FIRST_TOUCH_ACQUISITION_FIELDS)
        values = tuple(first_touch.get(field) for field in FIRST_TOUCH_ACQUISITION_FIELDS)
        with self._catalog_lock:
            self.catalog_conn.execute(
                f"INSERT OR IGNORE INTO first_touch_acquisition (account_id, {columns}) "
                f"VALUES (?, {placeholders})",
                (str(account_id), *values),
            )
            self._commit_catalog()

    def record_first_touch_referring_coach_once(
        self, account_id: str, coach_account_id: str, referred_at: str
    ) -> str | None:
        """Sets the first redeemed Assignment's Coach inside the caller's transaction."""
        columns = ", ".join(FIRST_TOUCH_ACQUISITION_FIELDS)
        placeholders = ", ".join("NULL" for _ in FIRST_TOUCH_ACQUISITION_FIELDS)
        with self._catalog_lock:
            self.catalog_conn.execute(
                f"INSERT OR IGNORE INTO first_touch_acquisition "
                f"(account_id, {columns}, referred_at) VALUES (?, {placeholders}, NULL)",
                (str(account_id),),
            )
            self.catalog_conn.execute(
                "UPDATE first_touch_acquisition SET referring_coach_id = ?, referred_at = ? "
                "WHERE account_id = ? AND referring_coach_id IS NULL AND referred_at IS NULL",
                (str(coach_account_id), referred_at, str(account_id)),
            )
            row = self.catalog_conn.execute(
                "SELECT referring_coach_id FROM first_touch_acquisition WHERE account_id = ?",
                (str(account_id),),
            ).fetchone()
        return str(row[0]) if row is not None and row[0] is not None else None

    def get_first_touch_acquisition(self, account_id: str) -> dict[str, str | None] | None:
        """Reads the immutable first-touch snapshot for a registered Account."""
        self.ensure_account_schema()
        columns = ", ".join(FIRST_TOUCH_ACQUISITION_FIELDS)
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                f"SELECT {columns} FROM first_touch_acquisition WHERE account_id = ?",
                (str(account_id),),
            ).fetchone()
        if row is None:
            return None
        return dict(zip(FIRST_TOUCH_ACQUISITION_FIELDS, row, strict=True))

    def set_account_display_language(self, account_id: str, language: str) -> bool:
        if language not in ("en", "ar"):
            return False
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.execute(
                "UPDATE accounts SET display_language = ? WHERE account_id = ? AND status = 'active' AND deleted_at IS NULL",
                (language, str(account_id)),
            )
            self._commit_catalog()
            return cursor.rowcount == 1

    def set_account_analytics_allowed(
        self,
        account_id: str,
        allowed: bool,
    ) -> bool | None:
        """Saves an account's analytics preference; returns None if it is not live."""
        self.ensure_account_schema()
        with self.catalog_transaction(immediate=True):
            current = self._live_account_analytics_preference(account_id)
            if current is None:
                return None
            if current == allowed:
                return False
            self._write_account_analytics_preference(account_id, allowed)
        return True

    def _live_account_analytics_preference(self, account_id: str) -> bool | None:
        row = self.catalog_conn.execute(
            f"SELECT {_ANALYTICS_ALLOWED_SQL} FROM accounts "
            "WHERE account_id = ? AND status = 'active' AND deleted_at IS NULL",
            (str(account_id),),
        ).fetchone()
        return None if row is None else bool(row[0])

    def _write_account_analytics_preference(self, account_id: str, allowed: bool) -> None:
        if allowed:
            self.catalog_conn.execute(
                "DELETE FROM account_analytics_preferences WHERE account_id = ?",
                (str(account_id),),
            )
            return
        self.catalog_conn.execute(
            "INSERT INTO account_analytics_preferences (account_id, analytics_allowed)"
            " VALUES (?, 0) ON CONFLICT(account_id) DO UPDATE SET analytics_allowed = 0",
            (str(account_id),),
        )

    def analytics_preference_allows(self, account_id: str) -> bool:
        """Returns true only for a live account whose preference allows sends."""
        account = self.get_account(account_id)
        return self.is_live_account(account) and account["analytics_allowed"] is True

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        """Reads an account by immutable id. Returns ``None`` when absent (fail closed)."""
        if not account_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (str(account_id),))
            return self._account_from_row(cursor.fetchone())

    def get_accounts_by_ids(self, account_ids: list[str]) -> list[dict[str, Any]]:
        """Reads a set of accounts in one query, preserving database row order."""
        unique_ids = list(dict.fromkeys(str(account_id) for account_id in account_ids if account_id))
        if not unique_ids:
            return []
        self.ensure_account_schema()
        placeholders = ", ".join("?" for _ in unique_ids)
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id IN ({placeholders})",
                unique_ids,
            ).fetchall()
        return [self._account_from_row(row) for row in rows]

    def list_accounts(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        """Lists live or deleted account rows newest first for owner metadata views."""
        self.ensure_account_schema()
        predicate = "deleted_at IS NOT NULL" if include_deleted else "status = 'active' AND deleted_at IS NULL"
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE {predicate}"
                " ORDER BY created_at DESC, account_id DESC"
            )
            return [self._account_from_row(row) for row in cursor.fetchall()]

    def set_account_last_seen_at(
        self, account_id: str, day: str, build: int | None = None
    ) -> None:
        """Stores the UTC activity day and, when supplied, the current app build."""
        if not account_id:
            return
        self.ensure_account_schema()
        with self._catalog_lock:
            self._update_account_last_seen(account_id, day, build)
            self._commit_catalog()

    def _update_account_last_seen(self, account_id: str, day: str, build: int | None) -> None:
        if build is None:
            self.catalog_conn.execute(
                "UPDATE accounts SET last_seen_at = ?"
                " WHERE account_id = ? AND status = 'active' AND deleted_at IS NULL"
                " AND (last_seen_at IS NULL OR last_seen_at < ?)",
                (str(day), str(account_id), str(day)),
            )
            return
        self.catalog_conn.execute(
            "UPDATE accounts SET last_seen_at = CASE"
            " WHEN last_seen_at IS NULL OR last_seen_at < ? THEN ? ELSE last_seen_at END,"
            " last_seen_build = ?"
            " WHERE account_id = ? AND status = 'active' AND deleted_at IS NULL"
            " AND ((last_seen_at IS NULL OR last_seen_at < ?)"
            " OR last_seen_build IS NULL OR last_seen_build < ?)",
            (str(day), str(day), int(build), str(account_id), str(day), int(build)),
        )

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

    def get_account_by_ledger_id(self, ledger_id: str) -> dict[str, Any] | None:
        """Reads the live account owning ``ledger_id``."""
        clean_id = self._sanitize_username(ledger_id)
        if not clean_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts"
                " WHERE ledger_id = ? AND status = 'active' AND deleted_at IS NULL",
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
