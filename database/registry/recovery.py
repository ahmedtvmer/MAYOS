"""RegistryRecoveryMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

from datetime import UTC, datetime


class RegistryRecoveryMixin:
    def set_trainee_email(self, trainee_id: str, email: str) -> None:
        """Links a normalized email to a trainee. Raises ValueError if taken by another ledger."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT trainee_id FROM trainee_emails WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row is not None and row[0] != trainee_id:
                raise ValueError("This email is already linked to another ledger.")
            cursor.execute(
                """
                INSERT INTO trainee_emails (trainee_id, email, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(trainee_id) DO UPDATE SET email = excluded.email, updated_at = excluded.updated_at
                """,
                (trainee_id, email, now),
            )
            self.catalog_conn.commit()

    def get_trainee_email(self, trainee_id: str) -> str | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT email FROM trainee_emails WHERE trainee_id = ?", (trainee_id,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def get_trainee_by_email(self, email: str) -> str | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT trainee_id FROM trainee_emails WHERE email = ?", (email,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def store_reset_token(self, token_hash: str, trainee_id: str, expires_at: str) -> None:
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO password_reset_tokens (token_hash, trainee_id, expires_at, used_at, created_at)"
                " VALUES (?, ?, ?, NULL, ?)",
                (token_hash, trainee_id, expires_at, now),
            )
            self.catalog_conn.commit()

    def consume_reset_token(self, token_hash: str, now_iso: str) -> str | None:
        """Atomically marks a valid (unused, unexpired) token used. Returns trainee_id or None."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT trainee_id, expires_at, used_at FROM password_reset_tokens WHERE token_hash = ?",
                (token_hash,),
            )
            row = cursor.fetchone()
            if row is None or row[2] is not None or str(row[1]) <= now_iso:
                return None
            trainee_id = str(row[0])
            cursor.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (now_iso, token_hash),
            )
            if cursor.rowcount != 1:
                return None
            self.catalog_conn.commit()
            return trainee_id

    def prune_reset_tokens(self, now_iso: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM password_reset_tokens WHERE expires_at < ? OR used_at IS NOT NULL",
                (now_iso,),
            )
            self.catalog_conn.commit()
            return cursor.rowcount
