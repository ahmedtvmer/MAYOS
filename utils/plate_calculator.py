# utils/plate_calculator.py
from typing import List, Dict, Any

OLYMPIC_DENOMINATIONS: List[float] = [25.0, 20.0, 15.0, 10.0, 5.0, 2.5, 1.25]
MINIMUM_INCREMENT: float = 2.5  # Smallest symmetric step (1.25kg * 2)


def calculate_barbell_plates(
    target_weight_kg: float,
    bar_weight_kg: float = 20.0,
    available_denominations: List[float] = None
) -> Dict[str, Any]:
    """
    Computes deterministic Olympic plate loading per side.
    - Clamps negative values and handles sub-bar weights safely.
    - Snaps non-divisible weights to the nearest symmetric 2.5kg increment.
    - Uses a greedy change-making pass across available metric denominations.
    """
    if available_denominations is None:
        denominations = OLYMPIC_DENOMINATIONS
    else:
        denominations = sorted(available_denominations, reverse=True)

    if target_weight_kg is None or target_weight_kg <= 0:
        return {
            "target_weight_kg": 0.0,
            "effective_weight_kg": bar_weight_kg,
            "bar_weight_kg": bar_weight_kg,
            "weight_per_side_kg": 0.0,
            "plates_per_side": [],
            "plate_counts_per_side": {},
            "formatted_display": f"{bar_weight_kg:g} kg (Empty Bar)"
        }

    # Snap target to lowest attainable symmetric barbell step
    effective_weight = round(target_weight_kg / MINIMUM_INCREMENT) * MINIMUM_INCREMENT

    if effective_weight <= bar_weight_kg:
        return {
            "target_weight_kg": float(target_weight_kg),
            "effective_weight_kg": float(bar_weight_kg),
            "bar_weight_kg": float(bar_weight_kg),
            "weight_per_side_kg": 0.0,
            "plates_per_side": [],
            "plate_counts_per_side": {},
            "formatted_display": f"{bar_weight_kg:g} kg (Empty Bar)"
        }

    weight_per_side = (effective_weight - bar_weight_kg) / 2.0
    remaining = weight_per_side
    plates_per_side: List[float] = []
    plate_counts: Dict[float, int] = {}

    for plate in denominations:
        while round(remaining, 3) >= round(plate, 3):
            plates_per_side.append(plate)
            plate_counts[plate] = plate_counts.get(plate, 0) + 1
            remaining -= plate

    # Format scannable inline string: e.g. "Bar + [20, 10, 2.5] kg/side"
    if plates_per_side:
        plate_str = ", ".join(f"{p:g}" for p in plates_per_side)
        formatted = f"{effective_weight:g} kg = Bar + [{plate_str}] kg/side"
    else:
        formatted = f"{effective_weight:g} kg (Empty Bar)"

    return {
        "target_weight_kg": float(target_weight_kg),
        "effective_weight_kg": float(effective_weight),
        "bar_weight_kg": float(bar_weight_kg),
        "weight_per_side_kg": float(weight_per_side),
        "plates_per_side": plates_per_side,
        "plate_counts_per_side": plate_counts,
        "formatted_display": formatted
    }