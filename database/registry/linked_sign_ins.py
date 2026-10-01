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

    def list_linked_sign_in_providers(self, account_id: str) -> list[str]:
        """Providers attached to this account, deduplicated and stably ordered.

        ``GET /auth/me`` reports these as ``linked_sign_ins``; only the provider
        names leave the server, never the subject.
        """
        if not account_id:
            return []
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT DISTINCT provider FROM linked_sign_ins WHERE account_id = ? ORDER BY provider",
                (str(account_id),),
            )
            return [str(row[0]) for row in cursor.fetchall()]

    def get_linked_sign_in_subject(self, account_id: str, provider: str) -> str | None:
        """The subject ``provider`` is linked to on this account, or ``None``.

        Used by disconnect (#114): the subject is read and removed inside the
        same catalog transaction, so a race cannot delete another account's
        row. Subjects never leave the service layer.
        """
        if not account_id or not provider:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT subject FROM linked_sign_ins WHERE account_id = ? AND provider = ?",
                (str(account_id), str(provider)),
            )
            row = cursor.fetchone()
            return str(row[0]) if row is not None else None

    def remove_linked_sign_in(self, provider: str, subject: str) -> None:
        """Drops a link keyed on its subject, inside the caller's transaction.

        The signup completion path uses it to repoint a dead account's subject
        at a fresh account; disconnect reads the caller's own subject first
        (:meth:`get_linked_sign_in_subject`) and removes it in that same
        transaction (#114).
        """
        if not provider or not subject:
            return
        self.ensure_account_schema()
        with self.catalog_transaction():
            self.catalog_conn.execute(
                "DELETE FROM linked_sign_ins WHERE provider = ? AND subject = ?",
                (str(provider), str(subject)),
            )
