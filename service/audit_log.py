"""Append-only catalog audit records for owner operations."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any

AUDIT_RETENTION_DAYS = 365
AUDIT_PAGE_SIZE = 50
_ACTOR = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_ACTION = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


@dataclass(frozen=True)
class AuditEvent:
    actor: str
    action: str
    target_account_id: str | None = None
    source_ip: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class AuditQuery:
    action: str | None = None
    account_id: str | None = None
    page: int = 1
    page_size: int = AUDIT_PAGE_SIZE


def write_audit_entry(db: Any, event: AuditEvent) -> str:
    """Appends one event and prunes records outside the one-year window."""
    _validate_event(event)
    now = datetime.now(UTC)
    audit_id = uuid.uuid4().hex
    cutoff = (now - timedelta(days=AUDIT_RETENTION_DAYS)).isoformat()
    with db.catalog_transaction():
        with db.catalog_locked() as conn:
            _insert_entry(conn, event, audit_id, now.isoformat())
            _prune_old_entries(conn, cutoff)
    return audit_id


def list_audit_entries(db: Any, query: AuditQuery) -> tuple[list[dict[str, Any]], int]:
    """Returns one newest-first audit page and the matching total."""
    where_sql, params = _query_conditions(query)
    offset = (query.page - 1) * query.page_size
    with db.catalog_locked() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) FROM audit_log{where_sql}", params
        ).fetchone()
        rows = conn.execute(
            "SELECT id, created_at, actor, action, target_account_id, source_ip, reason"
            f" FROM audit_log{where_sql} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, query.page_size, offset),
        ).fetchall()
    names = ("id", "created_at", "actor", "action", "target_account_id", "source_ip", "reason")
    return [dict(zip(names, row)) for row in rows], int(total_row[0] if total_row else 0)


def _query_conditions(query: AuditQuery) -> tuple[str, tuple[str, ...]]:
    clauses = []
    params = []
    if query.action:
        clauses.append("action = ?")
        params.append(query.action)
    if query.account_id:
        clauses.append("target_account_id = ?")
        params.append(query.account_id)
    return (" WHERE " + " AND ".join(clauses) if clauses else "", tuple(params))


def _insert_entry(conn: Any, event: AuditEvent, audit_id: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO audit_log"
        " (id, created_at, actor, action, target_account_id, source_ip, reason)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            audit_id,
            created_at,
            event.actor,
            event.action,
            event.target_account_id,
            event.source_ip,
            event.reason.strip() if event.reason else None,
        ),
    )


def _prune_old_entries(conn: Any, cutoff: str) -> None:
    conn.execute("DELETE FROM audit_log WHERE created_at < ?", (cutoff,))


def _validate_event(event: AuditEvent) -> None:
    if not _ACTOR.fullmatch(event.actor) or not _ACTION.fullmatch(event.action):
        raise ValueError("Audit actor and action must be bounded identifiers.")
    if event.target_account_id is not None and not _ACCOUNT_ID.fullmatch(event.target_account_id):
        raise ValueError("Audit target must be an immutable account identifier.")
    if event.source_ip is not None:
        ip_address(event.source_ip)
    if event.reason is not None:
        validate_audit_reason(event.reason)


def validate_audit_reason(reason: str) -> str:
    """Returns a trimmed reason after enforcing the audit log's privacy limits."""
    clean_reason = reason.strip()
    if len(clean_reason) > 500:
        raise ValueError("Audit reason must be 500 characters or fewer.")
    if _contains_sensitive_text(clean_reason):
        raise ValueError("Audit reason must not contain email addresses or links.")
    return clean_reason


def _contains_sensitive_text(reason: str) -> bool:
    return bool(_EMAIL.search(reason) or _URL.search(reason))
