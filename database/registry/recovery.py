"""RegistryRecoveryMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

MAX_EMAIL_CODE_FAILED_ATTEMPTS = 5
MAX_EMAIL_CODES_PER_HOUR = 5
RECOVERY_EMAIL_VERIFICATION_PURPOSE = "recovery_email"


@dataclass(frozen=True)
class EmailVerificationIdentity:
    account_id: str
    address: str
    purpose: str


@dataclass(frozen=True)
class EmailVerificationIssue:
    identity: EmailVerificationIdentity
    code_hash: str
    address_hash: str
    expires_at: str
    created_at: str
    rolling_cutoff: str


@dataclass(frozen=True)
class EmailVerificationCheck:
    identity: EmailVerificationIdentity
    code_hash: str
    address_hash: str
    checked_at: str
    mark_recovery_email: bool


class RegistryRecoveryMixin:
    def set_account_email(self, account_id: str, email: str) -> None:
        """Links a normalized email to an account. Raises ValueError if taken by another ledger."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self.catalog_transaction():
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT trainee_id FROM trainee_emails WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row is not None and row[0] != account_id:
                raise ValueError("This email is already linked to another ledger.")
            cursor.execute("SELECT email FROM trainee_emails WHERE trainee_id = ?", (account_id,))
            current = cursor.fetchone()
            changed = current is None or str(current[0]) != email
            cursor.execute(
                """
                INSERT INTO trainee_emails (trainee_id, email, updated_at, verified) VALUES (?, ?, ?, 0)
                ON CONFLICT(trainee_id) DO UPDATE SET
                    email = excluded.email,
                    updated_at = excluded.updated_at,
                    verified = CASE WHEN trainee_emails.email = excluded.email
                                    THEN trainee_emails.verified ELSE 0 END
                """,
                (account_id, email, now),
            )
            if changed:
                cursor.execute(
                    "UPDATE email_verification_codes SET used_at = ?"
                    " WHERE account_id = ? AND used_at IS NULL",
                    (now, account_id),
                )

    def mark_recovery_email_verified_if_matches(self, account_id: str, email: str) -> bool:
        """Verifies only the current unverified recovery address that matches ``email``."""
        self.ensure_account_schema()
        with self.catalog_transaction():
            updated = self.catalog_conn.execute(
                "UPDATE trainee_emails SET verified = 1"
                " WHERE trainee_id = ? AND lower(trim(email)) = ? AND verified = 0",
                (account_id, email),
            )
            return updated.rowcount == 1

    def get_account_email(self, account_id: str) -> str | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT email FROM trainee_emails WHERE trainee_id = ?", (account_id,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def is_recovery_email_verified(self, account_id: str) -> bool:
        """Returns whether this immutable account's current recovery email is verified."""
        self.ensure_account_schema()
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                "SELECT verified FROM trainee_emails WHERE trainee_id = ?", (account_id,)
            ).fetchone()
            return bool(row and row[0] == 1)

    def get_account_by_email(self, email: str) -> str | None:
        """Returns the immutable account id linked to a normalized email, or None."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT trainee_id FROM trainee_emails WHERE email = ?", (email,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def prune_expired_notice_claims(self, cutoff: str) -> int:
        """Deletes address-hash notice claims older than the retention window."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM password_reset_notice_limits WHERE claimed_at <= ?",
                (cutoff,),
            )
            self._commit_catalog()
            return cursor.rowcount

    def claim_no_account_notice(self, email_hash: str, claimed_at: str) -> bool:
        """Claims an address-hash notice slot without retaining the address."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO password_reset_notice_limits (email_hash, claimed_at)"
                " VALUES (?, ?)",
                (email_hash, claimed_at),
            )
            claimed = cursor.rowcount == 1
            self._commit_catalog()
            return claimed

    def store_reset_token(self, token_hash: str, account_id: str, expires_at: str) -> None:
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO password_reset_tokens (token_hash, trainee_id, expires_at, used_at, created_at)"
                " VALUES (?, ?, ?, NULL, ?)",
                (token_hash, account_id, expires_at, now),
            )
            self._commit_catalog()

    def invalidate_unused_reset_tokens(self, account_id: str, now_iso: str) -> int:
        """Marks every outstanding reset token for an account as used."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE trainee_id = ? AND used_at IS NULL",
                (now_iso, account_id),
            )
            self._commit_catalog()
            return cursor.rowcount

    def consume_reset_token(self, token_hash: str, now_iso: str) -> str | None:
        """Atomically marks a valid (unused, unexpired) token used. Returns account_id or None."""
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
            account_id = str(row[0])
            cursor.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (now_iso, token_hash),
            )
            if cursor.rowcount != 1:
                return None
            self.catalog_conn.commit()
            return account_id

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

    def _store_email_verification_code(self, issue: EmailVerificationIssue) -> bool:
        """Stores a code only for the current unverified address within its send budget."""
        self.ensure_account_schema()
        with self.catalog_transaction(immediate=True):
            if (
                issue.identity.purpose == RECOVERY_EMAIL_VERIFICATION_PURPOSE
                and not self._email_verification_identity_is_current(issue.identity)
            ):
                return False
            if self._email_verification_send_limit_reached(issue):
                return False
            self.catalog_conn.execute(
                "DELETE FROM email_verification_codes WHERE created_at < ?",
                (issue.rolling_cutoff,),
            )
            self.catalog_conn.execute(
                "UPDATE email_verification_codes SET used_at = ?"
                " WHERE account_id = ? AND purpose = ? AND used_at IS NULL",
                (issue.created_at, issue.identity.account_id, issue.identity.purpose),
            )
            self.catalog_conn.execute(
                "INSERT INTO email_verification_codes"
                " (code_id, code_hash, account_id, address_hash, purpose, expires_at, used_at, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    uuid4().hex,
                    issue.code_hash,
                    issue.identity.account_id,
                    issue.address_hash,
                    issue.identity.purpose,
                    issue.expires_at,
                    issue.created_at,
                ),
            )
            return True

    def _email_verification_identity_is_current(self, identity: EmailVerificationIdentity) -> bool:
        row = self.catalog_conn.execute(
            "SELECT email, verified FROM trainee_emails WHERE trainee_id = ?",
            (identity.account_id,),
        ).fetchone()
        return bool(
            row
            and str(row[0]).strip().lower() == identity.address
            and row[1] == 0
        )

    def _email_verification_send_limit_reached(self, issue: EmailVerificationIssue) -> bool:
        issued = self.catalog_conn.execute(
            "SELECT COUNT(*) FROM email_verification_codes"
            " WHERE account_id = ? AND purpose = ? AND created_at >= ?",
            (issue.identity.account_id, issue.identity.purpose, issue.rolling_cutoff),
        ).fetchone()[0]
        return issued >= MAX_EMAIL_CODES_PER_HOUR

    def _consume_email_verification_code(self, check: EmailVerificationCheck) -> bool:
        """Counts failures and atomically consumes a valid code and verifies its address."""
        self.ensure_account_schema()
        with self.catalog_transaction(immediate=True):
            if check.mark_recovery_email:
                if not self._email_verification_identity_is_current(check.identity):
                    return False
            row = self._unexpired_email_verification_code(check)
            if row is None:
                return False
            code_id, stored_hash, _, failed_attempts = row
            if not hmac.compare_digest(str(stored_hash), check.code_hash):
                self._record_email_verification_failure(code_id, failed_attempts, check.checked_at)
                return False
            if not self._claim_email_verification_code(code_id, check.checked_at):
                return False
            if check.mark_recovery_email and not self._mark_recovery_email_verified(check.identity):
                self._release_email_verification_code(code_id, check.checked_at)
                return False
            return True

    def _unexpired_email_verification_code(
        self, check: EmailVerificationCheck
    ) -> tuple[str, str, str, int] | None:
        row = self.catalog_conn.execute(
            "SELECT code_id, code_hash, expires_at, failed_attempts FROM email_verification_codes"
            " WHERE account_id = ? AND address_hash = ? AND purpose = ? AND used_at IS NULL"
            " ORDER BY created_at DESC LIMIT 1",
            (
                check.identity.account_id,
                check.address_hash,
                check.identity.purpose,
            ),
        ).fetchone()
        if row is None or str(row[2]) <= check.checked_at:
            return None
        return str(row[0]), str(row[1]), str(row[2]), int(row[3])

    def _record_email_verification_failure(self, code_id: str, attempts: int, checked_at: str) -> None:
        attempts += 1
        self.catalog_conn.execute(
            "UPDATE email_verification_codes SET failed_attempts = ?,"
            " used_at = CASE WHEN ? >= ? THEN ? ELSE used_at END"
            " WHERE code_id = ? AND used_at IS NULL",
            (attempts, attempts, MAX_EMAIL_CODE_FAILED_ATTEMPTS, checked_at, code_id),
        )

    def _claim_email_verification_code(self, code_id: str, checked_at: str) -> bool:
        claimed = self.catalog_conn.execute(
            "UPDATE email_verification_codes SET used_at = ?"
            " WHERE code_id = ? AND used_at IS NULL",
            (checked_at, code_id),
        )
        return claimed.rowcount == 1

    def _mark_recovery_email_verified(self, identity: EmailVerificationIdentity) -> bool:
        marked = self.catalog_conn.execute(
            "UPDATE trainee_emails SET verified = 1"
            " WHERE trainee_id = ? AND lower(trim(email)) = ? AND verified = 0",
            (identity.account_id, identity.address),
        )
        return marked.rowcount == 1

    def _release_email_verification_code(self, code_id: str, checked_at: str) -> None:
        self.catalog_conn.execute(
            "UPDATE email_verification_codes SET used_at = NULL"
            " WHERE code_id = ? AND used_at = ?",
            (code_id, checked_at),
        )
