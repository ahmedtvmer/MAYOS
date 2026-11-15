from core.weak_point_suggestions import suggest_weak_points


def test_suggests_ordered_english_arabic_and_mixed_muscles():
    assert suggest_weak_points("grow my glutes and bigger arms") == ["glutes", "biceps", "triceps"]
    assert suggest_weak_points("side delts and upper chest") == ["side_delts", "upper_chest"]
    assert suggest_weak_points("عايز صدر أكبر") == ["chest"]
    assert suggest_weak_points("أكبر كتفي والبايسبس") == ["shoulders", "biceps"]
    assert suggest_weak_points("عايز أوسع كتافي وأكبر دراعي") == [
        "shoulders", "biceps", "triceps"
    ]


def test_does_not_map_broad_legs_or_pain_mentions():
    assert suggest_weak_points("build stronger legs") == []
    assert suggest_weak_points("lower back pain and chest pain") == []


def test_goal_matcher_ignores_non_goal_back_and_injury_clauses():
    for text in (
        "get back in shape", "back to the gym", "come back",
        "back to my old weight", "back on track", "bounce back",
        "my knee and back hurt", "shoulder injury", "sore shoulders",
        "وجع في ضهري", "ألم في الكتف", "إصابة في الظهر",
        "ارجع للجيم", "أرجع تاني",
    ):
        assert suggest_weak_points(text) == [], text
    assert suggest_weak_points("bigger shoulders after my injury healed") == ["shoulders"]
    assert suggest_weak_points("عايز صدر، وكتف") == ["chest", "shoulders"]
    assert suggest_weak_points("عايز صدر؟") == ["chest"]
    assert suggest_weak_points("ضهري وبطني") == ["lats", "abs"]
    assert suggest_weak_points("latissimus dorsi and rhomboids") == ["lats", "traps"]
    assert suggest_weak_points("upper trapezius") == ["traps"]
    assert suggest_weak_points("mid-back") == ["traps"]
    assert suggest_weak_points("اللاتس والترابيس") == ["lats", "traps"]
    assert suggest_weak_points("كرشي") == []
