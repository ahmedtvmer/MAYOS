import pytest

from core.injuries import (
    INJURY_BODY_PARTS,
    body_area_in_text,
    clarification_body_area_in_text,
    injury_body_area_label,
    injury_body_parts,
    injury_status_label,
    normalize_body_area,
)
from service import injuries as injuries_service


def test_body_area_to_exercise_catalog_body_parts_is_pinned():
    assert INJURY_BODY_PARTS == {
        "knee": ("upper legs", "lower legs"),
        "hip": ("upper legs", "waist"),
        "lower_back": ("back", "waist"),
        "shoulder": ("shoulders", "upper arms"),
        "elbow": ("upper arms", "lower arms"),
        "wrist": ("lower arms",),
        "ankle": ("lower legs",),
        "neck": ("neck", "back"),
    }
    assert injury_body_parts("knee") == ("upper legs", "lower legs")
    assert injury_body_parts("shoulder") == ("shoulders", "upper arms")


def test_body_area_detection_handles_english_arabic_and_unknown():
    assert body_area_in_text("My right knee hurts") == "knee"
    assert body_area_in_text("كتفي بيوجعني") == "shoulder"
    assert body_area_in_text("I have a sharp pain") is None


def test_bare_back_is_only_an_area_in_clear_injury_context():
    assert body_area_in_text("My back hurts during deadlifts") == "lower_back"
    assert body_area_in_text("I have lower back pain") == "lower_back"
    assert body_area_in_text("lumbar pain") == "lower_back"
    assert body_area_in_text("I need to come back tomorrow") is None
    assert body_area_in_text("back squat") is None
    assert body_area_in_text("my back squat is improving") is None
    assert clarification_body_area_in_text("back") == "lower_back"
    assert normalize_body_area("back") is None


@pytest.mark.parametrize("message", [
    "back pain",
    "I have back pain",
    "I hurt back",
    "I hurt my back",
    "lower-back",
    "lower back",
    "lumbar",
    "spine",
    "my back",
    "ظهري",
    "ألم في الظهر",
    "أسفل الظهر",
    "وجع ضهري",
])
def test_lower_back_detection_matches_injury_phrases(message):
    assert body_area_in_text(message) == "lower_back"


@pytest.mark.parametrize("message", [
    "back squat",
    "my back squat is improving",
    "come back tomorrow",
    "back to training",
    "back extension",
    "back extension exercise",
])
def test_lower_back_detection_ignores_exercises_and_ordinary_phrases(message):
    assert body_area_in_text(message) is None


def test_clarification_area_requires_a_short_direct_reply():
    assert clarification_body_area_in_text("my left knee") == "knee"
    assert clarification_body_area_in_text("الركبة") == "knee"
    assert clarification_body_area_in_text("how's my knee workout?") is None


@pytest.mark.parametrize(
    ("area", "arabic"),
    [
        ("knee", "الركبة"),
        ("hip", "الورك"),
        ("lower_back", "أسفل الظهر"),
        ("shoulder", "الكتف"),
        ("elbow", "الكوع"),
        ("wrist", "الرسغ"),
        ("ankle", "الكاحل"),
        ("neck", "الرقبة"),
    ],
)
def test_player_facing_injury_area_labels(area, arabic):
    assert injury_body_area_label(area, "en") == area.replace("_", " ")
    assert injury_body_area_label(area, "ar") == arabic


@pytest.mark.parametrize(
    ("status", "arabic"),
    [
        ("reported", "تم الإبلاغ"),
        ("physician_seen", "تمت مراجعة الطبيب"),
        ("resolved", "تم التعافي"),
    ],
)
def test_player_facing_injury_status_labels(status, arabic):
    assert injury_status_label(status, "en") == status.replace("_", " ")
    assert injury_status_label(status, "ar") == arabic


@pytest.mark.parametrize("message", [
    "the doctor said I'm fully cleared",
    "my doctor said I'm fully cleared",
    "my physician fully cleared me",
    "doctor cleared me completely",
])
def test_full_physician_clearance_phrases_are_recognized(message):
    assert injuries_service.full_physician_clearance(message)


def test_doctor_cleared_my_knee_is_not_an_exercise_clearance_statement():
    assert injuries_service.parse_clearance_statement("my doctor cleared my knee") is None


def test_clearance_candidate_numbers_only_apply_to_bare_numeric_replies():
    candidates = [
        {"id": "one", "name": "Cable Curl"},
        {"id": "two", "name": "Leg Extension"},
    ]
    assert injuries_service.choose_clearance_candidate(candidates, "2") == candidates[1]
    assert injuries_service.choose_clearance_candidate(candidates, "the 2nd") == candidates[1]
    assert injuries_service.choose_clearance_candidate(candidates, "2 sets of leg curls") is None


def test_arabic_physician_visit_is_recognized_by_status_parser():
    assert injuries_service._status_from_message("رحت للدكتور") == "physician_seen"
