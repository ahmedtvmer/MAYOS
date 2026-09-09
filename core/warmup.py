from typing import List, Dict, Any

def calculate_warmup_sets(target_load_kg: float, bar_weight_kg: float = 20.0) -> List[Dict[str, Any]]:
    """Generates 3 non-fatiguing potentiating warm-up sets snapped to 2.5kg steps."""
    if target_load_kg <= 0:
        return []

    def round_to_increment(val: float, step: float = 2.5) -> float:
        return round(val / step) * step

    w1 = max(round_to_increment(target_load_kg * 0.40), bar_weight_kg if target_load_kg > bar_weight_kg else 0.0)
    w2 = max(round_to_increment(target_load_kg * 0.65), w1)
    w3 = max(round_to_increment(target_load_kg * 0.85), w2)

    return [
        {"set": "W1", "load_kg": w1, "reps": 5, "focus": "Pattern calibration (40%)"},
        {"set": "W2", "load_kg": w2, "reps": 3, "focus": "Acceleration intent (65%)"},
        {"set": "W3", "load_kg": w3, "reps": 1, "focus": "Potentiation single (85%)"}
    ]