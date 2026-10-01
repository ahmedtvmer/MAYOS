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
# upsert, provenance, alias, and embedding behavior during Exercise library loading.
MAYOS_AUTHORED_EXERCISES: tuple[AuthoredExercise, ...] = (
    {
        "id": "mayos:1",
        "name": "Kelso shrug",
        "display_name": "Kelso Shrug",
        "aliases": ("kelso shrug", "chest-supported shrug"),
        "body_part": "back",
        "target_muscle": "traps",
        "secondary_muscles": ("rhomboids", "lats"),
        "equipment": "cable",
        "instructions": (
            "1. Set a cable handle low and brace your chest against an incline bench.\n"
            "2. With your arms long, draw your shoulder blades toward each other and slightly down.\n"
            "3. Pause, then let them spread before the next repetition."
        ),
    },
    {
        "id": "mayos:2",
        "name": "Bayesian curl",
        "display_name": "Bayesian Curl",
        "aliases": ("bayesian curl", "behind-the-body cable curl"),
        "body_part": "upper arms",
        "target_muscle": "biceps",
        "secondary_muscles": ("forearms",),
        "equipment": "cable",
        "instructions": (
            "1. Stand facing away from a low cable with the handle in one hand and that arm held a little behind your torso.\n"
            "2. Keep your upper arm still as you curl the handle toward your shoulder.\n"
            "3. Lower it until the elbow is straight without letting the shoulder roll forward."
        ),
    },
    {
        "id": "mayos:3",
        "name": "Cable Y-raise",
        "display_name": "Cable Y-Raise",
        "aliases": ("cable y raise", "standing cable y raise"),
        "body_part": "shoulders",
        "target_muscle": "delts",
        "secondary_muscles": ("traps",),
        "equipment": "cable",
        "instructions": (
            "1. Set two low cables with handles crossed in front of you.\n"
            "2. Raise your straight arms outward and forward into a comfortable Y shape, keeping your ribs settled and shoulders away from your ears.\n"
            "3. Lower the handles slowly to the starting position."
        ),
    },
    {
        "id": "mayos:4",
        "name": "machine hip thrust",
        "display_name": "Machine Hip Thrust",
        "aliases": ("machine hip thrust", "hip thrust machine"),
        "body_part": "upper legs",
        "target_muscle": "glutes",
        "secondary_muscles": ("hamstrings",),
        "equipment": "leverage machine",
        "instructions": (
            "1. Position the machine pad across your hips and set your feet so your knees bend near a right angle at the top.\n"
            "2. Press through your feet to raise your hips until your torso and thighs line up.\n"
            "3. Tighten your glutes briefly.\n"
            "4. Lower with control."
        ),
    },
)
