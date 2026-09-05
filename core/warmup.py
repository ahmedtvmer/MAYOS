import math

def calculate_warmup_sets(target_load_kg: float, bar_weight_kg: float = 20.0) -> list[dict]:
    """
    Generates 3 non-fatiguing potentiating warm-up sets.
    Ramp schedule:
      - Ramp 1: 40% target load x 5 reps (groove pattern, zero fatigue)
      - Ramp 2: 65% target load x 3 reps (velocity intent)
      - Ramp 3: 85% target load x 1 rep (neuromuscular potentiation @ ~5 RPE)
    """
    if target_load_kg <= 0:
        return []

    def round_to_increment(val: float, step: float = 2.5) -> float:
        return round(val / step) * step

    w1 = max(round_to_increment(target_load_kg * 0.40), bar_weight_kg if target_load_kg > bar_weight_kg else 0)
    w2 = max(round_to_increment(target_load_kg * 0.65), w1)
    w3 = max(round_to_increment(target_load_kg * 0.85), w2)

    return [
        {"set": "W1", "load_kg": w1, "reps": 5, "focus": "Pattern calibration (40%)"},
        {"set": "W2", "load_kg": w2, "reps": 3, "focus": "Acceleration intent (65%)"},
        {"set": "W3", "load_kg": w3, "reps": 1, "focus": "Potentiation single (85%)"}
    ]