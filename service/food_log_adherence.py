"""Finalize ended Food log days without replacing a Player's answer."""

from datetime import timedelta
from decimal import Decimal

from core.nutrition_adherence import day_verdict
from service import nutrition


def recompute_day(ledger, entry_date, today):
    # Today is progress only; older days are outside the Food log write window.
    if entry_date != today - timedelta(days=1):
        return
    with ledger.ledger_transaction(immediate=True):
        entries = ledger.list_food_log_nutrients(entry_date)
        targets = nutrition.read(ledger, today=entry_date).get("targets") if entries else None
        totals = {key: sum((Decimal(str(entry.get(key) or 0))
                            for entry in entries), Decimal(0))
                  for key in ("energy_kcal", "protein_g")}
        ledger.replace_computed_nutrition_adherence(entry_date, day_verdict(totals, targets))
