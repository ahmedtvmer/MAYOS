"""Curated Exercise library vocabulary shared by curation and search."""

PRIMARY_MUSCLES = (
    "Chest",
    "Upper Chest",
    "Front Delts",
    "Side Delts",
    "Rear Delts",
    "Lats",
    "Upper Back",
    "Traps",
    "Lower Back",
    "Biceps",
    "Triceps",
    "Forearms",
    "Abs",
    "Obliques",
    "Quads",
    "Hamstrings",
    "Glutes",
    "Adductors",
    "Abductors",
    "Calves",
    "Neck",
    "Cardio",
)

PRIMARY_ACTIONS = (
    "Shoulder Flexion",
    "Shoulder Extension",
    "Shoulder Abduction",
    "Shoulder Adduction",
    "Shoulder Horizontal Adduction",
    "Shoulder Horizontal Abduction",
    "Shoulder External Rotation",
    "Shoulder Internal Rotation",
    "Scapular Elevation",
    "Scapular Retraction",
    "Scapular Depression",
    "Scapular Protraction",
    "Elbow Flexion",
    "Elbow Extension",
    "Wrist Flexion",
    "Wrist Extension",
    "Spinal Flexion",
    "Spinal Extension",
    "Spinal Rotation",
    "Spinal Lateral Flexion",
    "Anti-Extension",
    "Anti-Rotation",
    "Anti-Lateral Flexion",
    "Hip Flexion",
    "Hip Extension",
    "Hip Abduction",
    "Hip Adduction",
    "Knee Flexion",
    "Knee Extension",
    "Ankle Plantar Flexion",
    "Ankle Dorsiflexion",
    "Neck Flexion",
    "Neck Extension",
    "Conditioning",
)
LOAD_TYPES = ("selectorized", "plate_loaded", "unknown")

EQUIPMENT_CATEGORIES = (
    "Free weight",
    "Machine",
    "Cable",
    "Bodyweight",
    "Band",
    "Other",
)

_EQUIPMENT_CATEGORY_BY_EQUIPMENT = {
    **{
        equipment: "Free weight"
        for equipment in (
            "barbell",
            "dumbbell",
            "ez barbell",
            "kettlebell",
            "trap bar",
            "olympic barbell",
        )
    },
    **{
        equipment: "Machine"
        for equipment in ("leverage machine", "sled machine", "smith machine")
    },
    "cable": "Cable",
    **{
        equipment: "Bodyweight"
        for equipment in ("body weight", "assisted", "weighted")
    },
    **{equipment: "Band" for equipment in ("band", "resistance band")},
}


def equipment_category_for(equipment: object) -> str:
    """Return the one Equipment category for a source Equipment value."""
    normalized = str(equipment or "").strip().casefold()
    return _EQUIPMENT_CATEGORY_BY_EQUIPMENT.get(normalized, "Other")


def equipment_category_sql(column: str) -> str:
    """Build a SQL CASE expression from the same Equipment mapping."""
    cases = " ".join(
        f"WHEN '{equipment}' THEN '{category}'"
        for equipment, category in _EQUIPMENT_CATEGORY_BY_EQUIPMENT.items()
    )
    return f"CASE LOWER(TRIM(COALESCE({column}, ''))) {cases} ELSE 'Other' END"
