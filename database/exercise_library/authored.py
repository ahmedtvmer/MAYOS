"""MAYOS-authored rows for the shared Exercise library (ADR 053)."""

from typing import NotRequired, TypedDict


class AuthoredExercise(TypedDict):
    id: str
    name: str
    body_part: str
    target_muscle: str
    secondary_muscles: tuple[str, ...]
    equipment: str
    instructions: str
    # Owner-reviewed demo media in the media store (ADR 053); absent until reviewed.
    image_path: NotRequired[str]
    gif_path: NotRequired[str]


# Keep authored definitions here; display names and aliases live in the
# Exercise curation file so reviewed names have a single source.
MAYOS_AUTHORED_EXERCISES: tuple[AuthoredExercise, ...] = (
    {
        "id": "mayos:1",
        "name": "Kelso shrug",
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
        "body_part": "upper arms",
        "target_muscle": "biceps",
        "secondary_muscles": ("forearms",),
        "equipment": "cable",
        "instructions": (
            "1. Stand facing away from a low cable with the handle in one hand and that arm held a little behind your torso.\n"
            "2. Keep your upper arm still as you curl the handle toward your shoulder.\n"
            "3. Lower it until the elbow is straight without letting the shoulder roll forward."
        ),
        "image_path": "images/mayos-2-bayesian-curl.jpg",
        "gif_path": "videos/mayos-2-bayesian-curl.gif",
    },
    {
        "id": "mayos:3",
        "name": "Cable Y-raise",
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
