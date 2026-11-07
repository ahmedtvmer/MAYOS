"""Nutrient-only Food log projections for hosted Coach and Roster inference."""

from datetime import timedelta
from decimal import Decimal


def nutrient_totals(nutrients, keys):
    # Quick add can omit Macros; unknown nutrients contribute zero to totals.
    return {
        key: float(round(sum((Decimal(str(row.get(key) or 0)) for row in nutrients),
                             Decimal(0)), 2))
        for key in keys
    }


def recent_daily_totals(ledger, today, days):
    """Include unlogged days as null totals, never entry names or food records."""
    start = today - timedelta(days=days - 1)
    adherence = {row["date"]: row for row in ledger.list_nutrition_adherence(
        start.isoformat(), today.isoformat())}
    daily_totals = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        nutrients = ledger.list_food_log_nutrients(day)
        totals = nutrient_totals(nutrients, ("energy_kcal", "protein_g"))
        answer = adherence.get(day.isoformat(), {})
        daily_totals.append({
            "date": day.isoformat(),
            "energy_kcal": totals["energy_kcal"] if nutrients else None,
            "protein_g": totals["protein_g"] if nutrients else None,
            "adherence": answer.get("value"),
            "adherence_source": answer.get("source"),
        })
    return daily_totals
