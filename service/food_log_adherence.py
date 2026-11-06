"""Finalize ended Food log days without replacing a Player's answer."""

from datetime import date, timedelta
from decimal import Decimal

from core.nutrition_adherence import day_verdict
from service import nutrition


def recompute_day(ledger, entry_date, today):
    if entry_date == today - timedelta(days=1):
        _store_day_verdict(ledger, entry_date)


def finalize_pending_days(ledger, today):
    for entry_date in ledger.list_pending_food_log_dates(today):
        _store_day_verdict(ledger, date.fromisoformat(entry_date))


def _store_day_verdict(ledger, entry_date):
    with ledger.ledger_transaction(immediate=True):
        entries = ledger.list_food_log_nutrients(entry_date)
        targets = nutrition.targets_for_day(ledger, entry_date) if entries else None
        totals = {key: sum((Decimal(str(entry.get(key) or 0))
                            for entry in entries), Decimal(0))
                  for key in ("energy_kcal", "protein_g")}
        ledger.replace_computed_nutrition_adherence(entry_date, day_verdict(totals, targets))
