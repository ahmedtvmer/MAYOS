"""Shared Focus muscle dose and exercise-slot policy."""

from core.weak_points import WEAK_POINT_MUSCLES
from core.muscle_volume import FOCUS_MAIN_GROUPS

FOCUS_MULTIPLIER = 1.3

FOCUS_REGION_POLICY = {
    "chest": {"home_region": "upper", "isolation_cross_regions": ()},
    "upper_chest": {"home_region": "upper", "isolation_cross_regions": ()},
    "back": {"home_region": "upper", "isolation_cross_regions": ()},
    "shoulders": {"home_region": "upper", "isolation_cross_regions": ()},
    "side_delts": {"home_region": "upper", "isolation_cross_regions": ("lower",)},
    "biceps": {"home_region": "upper", "isolation_cross_regions": ("lower",)},
    "triceps": {"home_region": "upper", "isolation_cross_regions": ("lower",)},
    "forearms": {"home_region": "upper", "isolation_cross_regions": ("lower",)},
    "quads": {"home_region": "lower", "isolation_cross_regions": ()},
    "hamstrings": {"home_region": "lower", "isolation_cross_regions": ()},
    "glutes": {"home_region": "lower", "isolation_cross_regions": ()},
    "adductors": {"home_region": "lower", "isolation_cross_regions": ("upper",)},
    "calves": {"home_region": "lower", "isolation_cross_regions": ("upper",)},
    "abs": {"home_region": "neutral", "isolation_cross_regions": ("upper", "lower")},
}

FOCUS_EXTRA_TABLE = {
    "chest": {
        "candidate_slots": ("chest_fly", "incline_press", "flat_press"),
        "main_slot": "flat_press",
        "excluded_equipment": ("barbell", "ez barbell"),
    },
    "upper_chest": {
        "candidate_slots": ("chest_fly", "incline_press"),
        "main_slot": "incline_press",
        "preferred_exercise_ids_by_slot": {"chest_fly": ("171",)},
        "excluded_equipment": ("barbell", "ez barbell"),
    },
    "back": {
        "candidate_slots": ("pullover", "upper_back_pull", "vertical_pull", "horizontal_row"),
        "main_slot": "vertical_pull",
    },
    "shoulders": {"candidate_slots": ("shoulder_press", "side_delts"), "main_slot": "shoulder_press"},
    "side_delts": {"candidate_slots": ("side_delts",), "main_slot": "side_delts"},
    "biceps": {"candidate_slots": ("biceps_alt", "biceps_preacher"), "main_slot": "biceps_alt"},
    "triceps": {"candidate_slots": ("triceps_overhead", "triceps_pushdown"), "main_slot": "triceps_overhead"},
    "forearms": {"candidate_slots": ("forearm_wrist", "forearm_reverse"), "main_slot": "forearm_wrist"},
    "quads": {"candidate_slots": ("quad_iso", "quad_lunge", "quad_compound"), "main_slot": "quad_compound"},
    "hamstrings": {"candidate_slots": ("ham_curl", "ham_hinge"), "main_slot": "ham_curl"},
    "glutes": {"candidate_slots": ("glute_thrust", "glute_iso"), "main_slot": "glute_thrust"},
    "adductors": {"candidate_slots": ("adductors",), "main_slot": "adductors"},
    "calves": {
        "candidate_slots": ("calf",),
        "main_slot": "calf",
        "preferred_exercise_ids_by_slot": {"calf": ("1371", "1375", "1372", "1373")},
    },
    "abs": {"candidate_slots": ("abs",), "main_slot": "abs"},
}

FOCUS_MUSCLE_SLOTS = {
    "chest": {"incline_press", "flat_press", "chest_fly"},
    "upper_chest": {"incline_press", "chest_fly"},
    "back": {"vertical_pull", "horizontal_row", "upper_back_pull", "pullover"},
    "shoulders": {"shoulder_press", "side_delts"},
    "side_delts": {"side_delts"},
    "biceps": {"biceps_preacher", "biceps_alt"},
    "triceps": {"triceps_pushdown", "triceps_overhead"},
    "forearms": {"forearm_wrist", "forearm_reverse"},
    "quads": {"quad_compound", "quad_lunge", "quad_iso"},
    "hamstrings": {"ham_curl", "ham_hinge"},
    "glutes": {"glute_thrust", "glute_iso"},
    "adductors": {"adductors"},
    "calves": {"calf"},
    "abs": {"abs"},
}

FOCUS_REVIEW_MUSCLES = {
    muscle: ({FOCUS_MAIN_GROUPS[muscle]} if FOCUS_MAIN_GROUPS.get(muscle) else set())
    for muscle in WEAK_POINT_MUSCLES
}

assert set(FOCUS_EXTRA_TABLE) == set(WEAK_POINT_MUSCLES)
assert set(FOCUS_REGION_POLICY) == set(WEAK_POINT_MUSCLES)
assert set(FOCUS_MUSCLE_SLOTS) == set(WEAK_POINT_MUSCLES)
assert set(FOCUS_REVIEW_MUSCLES) == set(WEAK_POINT_MUSCLES)
