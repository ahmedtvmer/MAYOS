from typing import Literal

LOWER_BODY_TARGETS = {
    "quads", "hamstrings", "glutes", "calves", "quadriceps", 
    "adductors", "abductors", "legs", "lower body", "thighs"
}

def get_progression_increment(mechanic: str, body_part: str | None = None) -> float:
    is_compound = "compound" in (mechanic or "").lower()
    target = (body_part or "").strip().lower()
    is_lower = any(part in target for part in LOWER_BODY_TARGETS)

    if is_compound:
        return 5.0 if is_lower else 2.5
    return 2.5 if is_lower else 1.0

def evaluate_progression(
    mechanic: str,
    performed_sets: list[dict],
    target_reps_min: int,
    target_reps_max: int,
    body_part: str | None = None,
    increment_kg: float | None = None
) -> dict:
    if not performed_sets:
        return {"action": "hold", "step": 0.0, "target_text": "No sets logged."}

    step = increment_kg if increment_kg is not None else get_progression_increment(mechanic, body_part)
    is_compound = "compound" in (mechanic or "").lower()

    # 1. Compound: Full Corridor Double Progression
    if is_compound:
        all_topped_out = all(s["reps"] >= target_reps_max for s in performed_sets)
        base_load = performed_sets[0]["weight_kg"]

        if all_topped_out:
            next_load = base_load + step
            return {
                "action": "increase",
                "is_compound": True,
                "step": step,
                "next_load": next_load,
                "status_badge": f"Graduated (+{step} kg)",
                "target_text": f"Advance load to **{next_load} kg** next week for {target_reps_min}–{target_reps_max} reps."
            }
        else:
            min_reps_logged = min(s["reps"] for s in performed_sets)
            return {
                "action": "hold",
                "is_compound": True,
                "step": step,
                "next_load": base_load,
                "status_badge": "Rep Corridor Phase",
                "target_text": f"Maintain **{base_load} kg**. Hit **{target_reps_max} reps** on all sets before loading up."
            }

    # 2. Isolation: Dynamic Double Progression (DDP)
    graduated_sets = []
    holding_sets = []

    for idx, s in enumerate(performed_sets, start=1):
        if s["reps"] >= target_reps_max:
            graduated_sets.append(f"Set {idx}: +{step} kg ({s['weight_kg'] + step} kg)")
        else:
            holding_sets.append(f"Set {idx}: aim for {s['reps'] + 1}+ reps")

    status_parts = []
    if graduated_sets:
        status_parts.append("🚀 " + ", ".join(graduated_sets))
    if holding_sets:
        status_parts.append("🎯 " + ", ".join(holding_sets))

    return {
        "action": "ddp",
        "is_compound": False,
        "step": step,
        "status_badge": f"DDP Evaluated (Step: +{step} kg)",
        "target_text": " | ".join(status_parts)
    }

def calculate_epley_e1rm(weight_kg: float, reps: int) -> float:
    """Calculates estimated 1RM using the standard Epley formula."""
    if reps <= 0 or weight_kg <= 0:
        return 0.0
    if reps == 1:
        return float(weight_kg)
    return round(weight_kg * (1.0 + (reps / 30.0)), 1)