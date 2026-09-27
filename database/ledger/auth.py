"""LedgerAuthMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import sqlite3
from datetime import UTC, datetime


class LedgerAuthMixin:
    def revoke_token(self, jti: str, expires_at: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO revoked_tokens (jti, expires_at, revoked_at) VALUES (?, ?, ?)
            ON CONFLICT(jti) DO NOTHING
            """,
            (jti, expires_at, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def is_token_revoked(self, jti: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,))
        return cursor.fetchone() is not None

    def prune_revoked_tokens(self, now_iso: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now_iso,))
        self.conn.commit()
        return cursor.rowcount

    def get_password_hash(self) -> str | None:
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT password_hash FROM auth_credentials WHERE id = 1")
        except sqlite3.OperationalError:
            return None
        row = cursor.fetchone()
        return row["password_hash"] if row and row["password_hash"] else None

    def set_password_hash(self, password_hash: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO auth_credentials (id, password_hash, updated_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash, updated_at = excluded.updated_at
            """,
            (password_hash, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def get_token_version(self) -> int:
        """Session epoch for the bound ledger. Bumped on every password change/reset."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT token_version FROM auth_credentials WHERE id = 1")
        except sqlite3.OperationalError:
            return 1
        row = cursor.fetchone()
        try:
            return max(1, int((row["token_version"] if row else 1) or 1))
        except (TypeError, ValueError, KeyError, IndexError):
            return 1

    def bump_token_version(self) -> int:
        """Invalidates all previously issued JWTs for the bound ledger. Returns new version."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT token_version FROM auth_credentials WHERE id = 1")
            row = cursor.fetchone()
            current = max(1, int((row["token_version"] if row else 1) or 1))
        except sqlite3.OperationalError:
            # Pre-v3 ledger mounted without migration (defensive): add the column.
            cursor.execute("ALTER TABLE auth_credentials ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1")
            current = 1
        except (TypeError, ValueError, KeyError, IndexError):
            current = 1
        new_version = current + 1
        # NOTE: the conflict clause only touches token_version/updated_at, so an
        # existing password_hash is preserved. A fresh '' placeholder row (no
        # password ever set) stays falsy and reads back as "no password".
        cursor.execute(
            """
            INSERT INTO auth_credentials (id, password_hash, token_version, updated_at)
            VALUES (1, '', ?, ?)
            ON CONFLICT(id) DO UPDATE SET token_version = excluded.token_version, updated_at = excluded.updated_at
            """,
            (new_version, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()
        return new_version
