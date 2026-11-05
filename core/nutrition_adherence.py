"""Deterministic Food log verdicts; no calendar or storage dependencies."""

from decimal import Decimal


# Calorie tolerance and protein floor are percentages, with inclusive bounds.
ADHERENCE_THRESHOLDS = (("on_target", 10, 90), ("roughly", 20, 75))


def day_verdict(totals, targets):
    targets = targets or {}
    calorie_target = Decimal(str(targets.get("calories") or 0))
    protein_target = Decimal(str(targets.get("protein_g") or 0))
    if calorie_target <= 0 or protein_target <= 0:
        return None
    calories = Decimal(str(totals.get("energy_kcal") or 0))
    protein = Decimal(str(totals.get("protein_g") or 0))
    for verdict, calorie_tolerance, protein_floor in ADHERENCE_THRESHOLDS:
        if (abs(calories - calorie_target) * 100 <= calorie_target * calorie_tolerance
                and protein * 100 >= protein_target * protein_floor):
            return verdict
    return "off"
