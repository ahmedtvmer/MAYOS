"""English and Arabic clinical-guard false triggers and keyword-free injuries (#754)."""

import json
from pathlib import Path

import pytest

from agent import assistant_graph as graph
from agent import clinical_guard

CASES = json.loads(
    (Path(__file__).parent / "data" / "clinical_guard_regression_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{index}-{case['source']}" for index, case in enumerate(CASES)]
)
def test_regression_set_intercepts_exactly_the_clinical_messages(case):
    intercepted = graph._clinical_turn_metadata(case["text"]) is not None
    assert intercepted is case["clinical"], case["text"]


@pytest.mark.parametrize(
    "text",
    [
        # Reported in use: a rest-day observation, no symptom.
        "هو كداو لاحظ ان ف يوم راحة بعد legs و بعد ال full arm",
        "هو كدا ولاحظ ان في يوم راحة بعد legs وبعد ال full arm",
        "تمام هو كداو لاحظ ان ف يوم راحة بعد legs و بعد ال full arm بس",
        "ايوه هو كده ولاحظ ان في يوم راحه بعد اللegs وبعد الfull arm",
        "لاحظت ان في يوم راحة بعد يوم الرجل وبعد يوم الدراع",
        "ممكن تشرحلي ليه في يوم راحة بعد legs day",
        "فيه حاجة غلط في البرنامج يوم الرجل",
        "مش قادر افهم ليه البنش في يوم الكتف",
    ],
)
def test_arabic_training_talk_does_not_trigger(text):
    assert graph._clinical_turn_metadata(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "كتفي مش مظبوط من ساعة ما عملت bench امبارح",
        "حاسس ان في حاجة غلط في ركبتي لما بنزل",
        "ضهري مش قادر اتحرك بيه من الصبح",
        "ركبتي مش طبيعية بعد السكوات",
        "رسغي بيضايقني من التمرين",
        "لا أستطيع تحريك كتفي بعد التمرين",
    ],
)
def test_arabic_keyword_free_injury_reports_intercept(text):
    assert graph._clinical_turn_metadata(text) is not None


def test_arabic_soreness_is_benign_only_without_joints_or_escalation():
    doms = "عضلات رجلي بتوجعني زي كل مرة تاني يوم التمرين، أتعامل مع الـ DOMS إزاي؟"
    assert graph._clinical_turn_metadata(doms) is None
    # A joint, a sharper symptom or no soreness marker keeps the safeguard.
    assert graph._clinical_turn_metadata(
        "ركبتي بتوجعني تاني يوم التمرين، ده DOMS؟"
    ) is not None
    assert graph._clinical_turn_metadata(
        "عضلات رجلي بتوجعني وفيها تنميل تاني يوم التمرين"
    ) is not None
    assert graph._clinical_turn_metadata("عضلات رجلي بتوجعني") is not None


@pytest.mark.parametrize(
    "text",
    [
        # Both Arabic swaps hit the safeguard before #754.
        "بدل Dead Bug بـ Kneeling Crunch (Cable)",
        "بدل ال crunch بال plank",
        "swap Cable Crunch for Plank",
        "Can I replace the bicycle crunch with leg raises?",
        "عايز اعمل reverse crunch بدل ال sit up",
    ],
)
def test_crunch_as_an_exercise_name_does_not_trigger(text):
    assert graph._clinical_turn_metadata(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "I felt a crunching sound in my knee on the way down",
        "There was a crunch in my shoulder when I pressed",
        "my knee makes a crunch noise on squats",
    ],
)
def test_crunching_as_a_symptom_still_triggers(text):
    assert graph._clinical_turn_metadata(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "My wrist has been bothering me since Tuesday's pressing",
        "Something in my lower back went when I deadlifted and now I can't bend",
        "I tweaked my shoulder on the incline press",
        "My knee feels off when I squat deep",
        "I can't straighten my elbow after curls",
    ],
)
def test_english_keyword_free_injury_reports_intercept(text):
    assert clinical_guard.RE_ENGLISH_INJURY_PHRASES.search(text)
    assert graph._clinical_turn_metadata(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "The loud music at the gym is bothering me",
        "I noticed there's a rest day after legs and after the full arm day",
        "Can I train arms the day after legs?",
        "This program feels off to me, can you explain the order?",
    ],
)
def test_english_training_talk_does_not_trigger(text):
    assert not clinical_guard.RE_ENGLISH_INJURY_PHRASES.search(text)
    assert graph._clinical_turn_metadata(text) is None


def test_category_patterns_do_not_match_every_message():
    # A category without Latin stems once built an empty alternative that
    # matched any text (#754).
    assert clinical_guard._arabic_lexical_categories("رسالة عادية عن البرنامج") == set()
    assert clinical_guard._arabic_lexical_categories("كتفي بيوجعني") == {"pain"}
