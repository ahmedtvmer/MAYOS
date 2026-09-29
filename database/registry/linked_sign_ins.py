"""RegistryLinkedSignInsMixin: external identities attached to an account (#113).

A Linked sign-in (CONTEXT.md) is keyed on ``(provider, subject)`` — Google's
``sub`` today — and is never matched by email, so no email, name, or picture
from the provider is ever stored. The provider column is data, so adding
another provider needs no schema change. The rows live in the shared catalog,
not in a player's ledger, because the sign-in runs logged out and cannot know
which ledger to open.

The unique constraint on ``(provider, subject)`` is what makes a concurrent
first sign-in safe: only one transaction can insert the row, so only one
account is ever created for a subject.
"""

import sqlite3
from datetime import UTC, datetime


class RegistryLinkedSignInsMixin:
    def get_linked_sign_in_account_id(self, provider: str, subject: str) -> str | None:
        """The account id linked to ``(provider, subject)``, or ``None`` when absent.

        Liveness is deliberately not checked here: the caller decides what a
        link to a deleted or inactive account means (sign-in falls back to the
        username picker, matching "otherwise" in issue #113).
        """
        if not provider or not subject:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id FROM linked_sign_ins WHERE provider = ? AND subject = ?",
                (str(provider), str(subject)),
            )
            row = cursor.fetchone()
            return str(row[0]) if row is not None else None

    def account_has_linked_sign_in(self, account_id: str) -> bool:
        """True when any external identity is attached to this account.

        Used to close the claim hole and to keep a Google-only account from
        reporting ``claim_required`` on password login (issue #113).
        """
        if not account_id:
            return False
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT 1 FROM linked_sign_ins WHERE account_id = ? LIMIT 1", (str(account_id),))
            return cursor.fetchone() is not None

    def link_sign_in(self, provider: str, subject: str, account_id: str, linked_at: str | None = None) -> None:
        """Inserts the link row; raises :class:`sqlite3.IntegrityError` when already linked.

        Joins the caller's transaction when one is open (the catalog
        transaction is re-entrant), so account creation and the link commit or
        roll back together. The unique constraint is the race backstop: two
        concurrent completions for one subject cannot both insert.
        """
        if not provider or not subject or not account_id:
            raise sqlite3.IntegrityError("A linked sign-in needs a provider, subject and account id.")
        self.ensure_account_schema()
        now = linked_at or datetime.now(UTC).isoformat()
        with self.catalog_transaction():
            self.catalog_conn.execute(
                "INSERT INTO linked_sign_ins (provider, subject, account_id, linked_at) VALUES (?, ?, ?, ?)",
                (str(provider), str(subject), str(account_id), now),
            )

    def remove_linked_sign_in(self, provider: str, subject: str) -> None:
        """Drops a link whose account is no longer live, inside the caller's transaction.

        Only reachable from the signup completion path, where the subject is
        being attached to a fresh account in the same transaction; a live
        account's link is never removed here (connect/disconnect is issue 3).
        """
        if not provider or not subject:
            return
        self.ensure_account_schema()
        with self.catalog_transaction():
            self.catalog_conn.execute(
                "DELETE FROM linked_sign_ins WHERE provider = ? AND subject = ?",
                (str(provider), str(subject)),
            )
