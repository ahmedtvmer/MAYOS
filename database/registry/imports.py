"""RegistryImportsMixin: opt-in import audit and claim codes (ADR 019, #42).

Catalog-side because the import is an owner/account-level fact, not training
data, and the claim endpoint runs logged out and cannot know which ledger to
open. Only the SHA-256 of a claim code is stored; the raw code is shown once by
``scripts/import_player.py``. The audit fingerprint makes re-importing the same
snapshot a refusal so a rerun cannot create a second cloud account.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Any


class RegistryImportsMixin:
    def record_account_import(
        self,
        *,
        import_id: str,
        account_id: str,
        source_fingerprint: str,
        source_name: str,
        counts_json: str,
        opt_in_reference: str,
        imported_at: str,
        claim_token_hash: str,
        claim_expires_at: str,
    ) -> None:
        """Writes the import audit row and the account's single-use claim code.

        One catalog transaction: the audit and the claim code are committed
        together, so a crash cannot leave an imported account with no audited
        handoff. Only the claim token's hash is persisted, never the raw code.
        """
        self.ensure_account_schema()
        with self.catalog_transaction():
            self.catalog_conn.execute(
                "INSERT INTO account_imports"
                " (import_id, account_id, source_fingerprint, source_name, counts_json,"
                " opt_in_reference, imported_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(import_id),
                    str(account_id),
                    str(source_fingerprint),
                    str(source_name),
                    str(counts_json),
                    str(opt_in_reference),
                    str(imported_at),
                ),
            )
            # Same writer as the standalone issuance path, joined to this
            # transaction so the audit row cannot commit without its code.
            self.create_claim_code(
                account_id,
                claim_token_hash,
                claim_expires_at,
                created_at=imported_at,
            )

    def create_claim_code(
        self,
        account_id: str,
        token_hash: str,
        expires_at: str,
        created_at: str | None = None,
    ) -> None:
        """Stores a hashed, account-bound, single-use claim code (hash only)."""
        self.ensure_account_schema()
        now = created_at or datetime.now(UTC).isoformat()
        with self.catalog_transaction():
            self.catalog_conn.execute(
                "INSERT INTO account_claim_codes (token_hash, account_id, expires_at, used_at, created_at)"
                " VALUES (?, ?, ?, NULL, ?)",
                (str(token_hash), str(account_id), str(expires_at), now),
            )

    def get_account_import_by_fingerprint(self, source_fingerprint: str) -> dict[str, Any] | None:
        """The audit row for a snapshot fingerprint, or ``None`` when never imported."""
        if not source_fingerprint:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT import_id, account_id, source_fingerprint, source_name, counts_json,"
                " opt_in_reference, imported_at"
                " FROM account_imports WHERE source_fingerprint = ?",
                (str(source_fingerprint),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "import_id": str(row[0]),
                "account_id": str(row[1]),
                "source_fingerprint": str(row[2]),
                "source_name": str(row[3]),
                "counts_json": str(row[4]),
                "opt_in_reference": str(row[5]),
                "imported_at": str(row[6]),
            }

    def consume_claim_code(self, token_hash: str, account_id: str, now_iso: str) -> bool:
        """Atomically claims a claim code bound to ``account_id``.

        True only when the code is known, unused, unexpired, and bound to this
        account. The conditional ``UPDATE`` is the single-use gate, so two
        concurrent redemptions cannot both win.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id, expires_at, used_at FROM account_claim_codes WHERE token_hash = ?",
                (str(token_hash),),
            )
            row = cursor.fetchone()
            if row is None or row[2] is not None or str(row[1]) <= str(now_iso):
                return False
            if str(row[0]) != str(account_id):
                return False
            try:
                cursor.execute(
                    "UPDATE account_claim_codes SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                    (str(now_iso), str(token_hash)),
                )
                if cursor.rowcount != 1:
                    self.catalog_conn.rollback()
                    return False
                self.catalog_conn.commit()
            except sqlite3.Error:
                self.catalog_conn.rollback()
                raise
            return True

    def prune_claim_codes(self, now_iso: str) -> int:
        """Removes used or expired claim codes; returns how many were removed."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM account_claim_codes WHERE expires_at <= ? OR used_at IS NOT NULL",
                (str(now_iso),),
            )
            self.catalog_conn.commit()
            return cursor.rowcount
