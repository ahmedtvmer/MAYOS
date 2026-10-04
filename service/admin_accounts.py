"""Account metadata views for the owner dashboard (ADR 051, #208)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from service import model_metering, password_reset, plans as plans_service

ACCOUNT_PAGE_SIZE = 50


class AccountListQuery(BaseModel):
    q: str = Field(default="", max_length=64)
    coach: bool = False
    not_onboarded: bool = False
    inactive_days: int | None = Field(default=None, ge=1, le=3650)
    show_deleted: bool = False
    page: int = Field(default=1, ge=1, le=10000)
    lookup: str = Field(default="", max_length=32)


def account_onboarded(db: Any, account: dict[str, Any]) -> bool:
    """Reads only whether the account ledger has a player profile."""
    if not db.ledger_exists(account["ledger_id"]):
        return False
    with db.open_ledger(account["ledger_id"]) as ledger:
        return bool(ledger.get_player_profile())


def list_account_rows(
    db: Any,
    filters: AccountListQuery,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Filters accounts, then returns one newest-first page and the total."""
    accounts = db.list_accounts(include_deleted=filters.show_deleted)
    if filters.show_deleted:
        total = len(accounts)
        offset = (filters.page - 1) * ACCOUNT_PAGE_SIZE
        return accounts[offset : offset + ACCOUNT_PAGE_SIZE], total
    search = filters.q.strip().casefold()
    if search:
        accounts = [account for account in accounts if search in account["username"].casefold()]
    accounts = _filter_live_accounts(db, accounts, filters, now)
    total = len(accounts)
    offset = (filters.page - 1) * ACCOUNT_PAGE_SIZE
    return accounts[offset : offset + ACCOUNT_PAGE_SIZE], total


def _filter_live_accounts(
    db: Any,
    accounts: list[dict[str, Any]],
    filters: AccountListQuery,
    now: datetime | None,
) -> list[dict[str, Any]]:
    if filters.coach:
        accounts = [account for account in accounts if account["is_coach"]]
    if filters.inactive_days is not None:
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        cutoff = (moment.date() - timedelta(days=filters.inactive_days)).isoformat()
        accounts = [
            account
            for account in accounts
            if account["last_seen_at"] is None or str(account["last_seen_at"]) <= cutoff
        ]
    if filters.not_onboarded:
        accounts = [account for account in accounts if not account_onboarded(db, account)]
    return accounts


def find_by_recovery_email(db: Any, email: Any) -> dict[str, Any] | None:
    """Resolves an exact normalized recovery email to a live account."""
    normalized = password_reset.normalize_email(email)
    if normalized is None:
        return None
    account_id = db.get_account_by_email(normalized)
    account = db.get_account(account_id) if account_id else None
    return account if db.is_live_account(account) else None


def mask_recovery_email(email: str | None) -> str:
    """Returns the owner-view mask without exposing the local part."""
    if not email or "@" not in email:
        return "Not set"
    local, domain = email.rsplit("@", 1)
    if not local or not domain:
        return "Not set"
    prefix = "*" if len(local) == 1 else f"{local[0]}***"
    return f"{prefix}@{domain}"


def account_metadata(db: Any, account: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Builds the allowed owner metadata and operational totals for one live account."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    month_start, month_end = model_metering.month_bounds(moment)
    account_id = account["account_id"]
    return {
        "onboarded": account_onboarded(db, account),
        "plans": plans_service.plans_for_account(db, account),
        "assignments": db.active_assignment_summary(account_id),
        "recovery_email": mask_recovery_email(db.get_account_email(account_id)),
        "recovery_email_verified": db.is_recovery_email_verified(account_id),
        "usage_month": model_metering.account_usage_totals(
            db, account_id, month_start.isoformat(), month_end.isoformat()
        ),
        "usage_all_time": model_metering.account_usage_totals(db, account_id),
        "limit_hits_month": db.count_model_limit_hits(account_id, month_start.isoformat()),
    }
