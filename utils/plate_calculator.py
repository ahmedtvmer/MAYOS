from typing import List, Dict, Any, Optional

OLYMPIC_DENOMINATIONS: List[float] = [25.0, 20.0, 15.0, 10.0, 5.0, 2.5, 1.25]
MINIMUM_INCREMENT: float = 2.5

def calculate_barbell_plates(
    target_weight_kg: float,
    bar_weight_kg: float = 20.0,
    available_denominations: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Computes deterministic Olympic plate loading per side.
    Snaps non-divisible weights to the nearest symmetric 2.5kg increment.
    """
    denominations = (
        sorted(available_denominations, reverse=True)
        if available_denominations is not None
        else OLYMPIC_DENOMINATIONS
    )

    empty_bar_payload = {
        "target_weight_kg": float(target_weight_kg) if target_weight_kg else 0.0,
        "effective_weight_kg": float(bar_weight_kg),
        "bar_weight_kg": float(bar_weight_kg),
        "weight_per_side_kg": 0.0,
        "plates_per_side": [],
        "plate_counts_per_side": {},
        "formatted_display": f"{bar_weight_kg:g} kg (Empty Bar)"
    }

    if target_weight_kg is None or target_weight_kg <= 0:
        return empty_bar_payload

    effective_weight = round(target_weight_kg / MINIMUM_INCREMENT) * MINIMUM_INCREMENT
    if effective_weight <= bar_weight_kg:
        empty_bar_payload["target_weight_kg"] = float(target_weight_kg)
        return empty_bar_payload

    remaining = (effective_weight - bar_weight_kg) / 2.0
    weight_per_side = remaining
    plates_per_side: List[float] = []
    plate_counts: Dict[float, int] = {}

    for plate in denominations:
        while round(remaining, 3) >= round(plate, 3):
            plates_per_side.append(plate)
            plate_counts[plate] = plate_counts.get(plate, 0) + 1
            remaining -= plate

    formatted = (
        f"{effective_weight:g} kg = Bar + [{', '.join(f'{p:g}' for p in plates_per_side)}] kg/side"
        if plates_per_side
        else f"{effective_weight:g} kg (Empty Bar)"
    )

    return {
        "target_weight_kg": float(target_weight_kg),
        "effective_weight_kg": float(effective_weight),
        "bar_weight_kg": float(bar_weight_kg),
        "weight_per_side_kg": float(weight_per_side),
        "plates_per_side": plates_per_side,
        "plate_counts_per_side": plate_counts,
        "formatted_display": formatted
    }