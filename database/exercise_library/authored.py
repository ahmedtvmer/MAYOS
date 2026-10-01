"""MAYOS-authored rows for the shared Exercise library (ADR 053)."""

from typing import TypedDict


class AuthoredExercise(TypedDict):
    id: str
    name: str
    display_name: str
    aliases: tuple[str, ...]
    body_part: str
    target_muscle: str
    secondary_muscles: tuple[str, ...]
    equipment: str
    instructions: str


# Keep additions as rows here so each new MAYOS-authored exercise gets the same
# upsert, provenance, alias, and embedding behavior during catalog loading.
MAYOS_AUTHORED_EXERCISES: tuple[AuthoredExercise, ...] = (
    {
        "id": "mayos:1",
        "name": "Kelso shrug",
        "display_name": "Kelso Shrug",
        "aliases": ("kelso shrug", "chest-supported shrug"),
        "body_part": "Back",
        "target_muscle": "traps",
        "secondary_muscles": ("rhomboids", "lats"),
        "equipment": "cable",
        "instructions": (
            "Set a cable handle low and brace your chest against an incline bench. "
            "With your arms long, draw your shoulder blades toward each other and "
            "slightly down. Pause, then let them spread before the next repetition."
        ),
    },
    {
        "id": "mayos:2",
        "name": "Bayesian curl",
        "display_name": "Bayesian Curl",
        "aliases": ("bayesian curl", "behind-the-body cable curl"),
        "body_part": "Upper Arms",
        "target_muscle": "biceps",
        "secondary_muscles": ("forearms",),
        "equipment": "cable",
        "instructions": (
            "Stand facing away from a low cable with the handle in one hand and "
            "that arm held a little behind your torso. Keep your upper arm still "
            "as you curl the handle toward your shoulder, then lower it until the "
            "elbow is straight without letting the shoulder roll forward."
        ),
    },
    {
        "id": "mayos:3",
        "name": "Cable Y-raise",
        "display_name": "Cable Y-Raise",
        "aliases": ("cable y raise", "standing cable y raise"),
        "body_part": "Shoulders",
        "target_muscle": "delts",
        "secondary_muscles": ("traps",),
        "equipment": "cable",
        "instructions": (
            "Set two low cables with handles crossed in front of you. Raise your "
            "straight arms outward and forward into a comfortable Y shape, keeping "
            "your ribs settled and shoulders away from your ears. Lower the handles "
            "slowly to the starting position."
        ),
    },
    {
        "id": "mayos:4",
        # The display name is the player-facing gym name. Keep the source name
        # descriptive so a broad "hip thrust" search continues to prefer the
        # established ExerciseDB barbell staple before this machine variant.
        "name": "machine hip thrust performed on a leverage machine",
        "display_name": "Machine Hip Thrust",
        "aliases": ("machine hip thrust", "hip thrust machine"),
        "body_part": "Upper Legs",
        "target_muscle": "glutes",
        "secondary_muscles": ("hamstrings",),
        "equipment": "leverage machine",
        "instructions": (
            "Position the machine pad across your hips and set your feet so your "
            "knees bend near a right angle at the top. Press through your feet to "
            "raise your hips until your torso and thighs line up. Tighten your "
            "glutes briefly, then lower with control."
        ),
    },
)
