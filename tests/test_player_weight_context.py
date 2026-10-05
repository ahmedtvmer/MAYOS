from datetime import date

from service.player_weight_context import render_player_weight_context
from service.weight_history import WeightTrend, WeightTrendPoint


def test_player_weight_context_renders_precomputed_eight_week_and_fortnight_facts():
    trend = WeightTrend(
        points=(
            WeightTrendPoint(date(2025, 12, 1), 72.0),
            WeightTrendPoint(date(2026, 1, 1), 72.5),
            WeightTrendPoint(date(2026, 1, 8), 73.0),
            WeightTrendPoint(date(2026, 1, 15), 74.0),
        ),
        change_kg=2.0,
    )

    rendered = render_player_weight_context(
        trend, 70.0, as_of=date(2026, 1, 15)
    )

    assert "2025-12-01: 72 kg" in rendered
    assert "2026-01-15: 74 kg" in rendered
    assert "8-week change (latest minus earliest): +2 kg" in rendered
    assert "Target weight: 70 kg" in rendered
    assert "Latest weight minus target: +4 kg" in rendered
    assert "14-day change (latest minus earliest): +1 kg" in rendered
    assert "14-day movement relative to target: away from target" in rendered


def test_player_weight_context_marks_missing_history_unavailable():
    rendered = render_player_weight_context(
        WeightTrend(points=(), change_kg=None), 70.0, as_of=date(2026, 1, 15)
    )

    assert "8-week dated points (oldest to newest): not available" in rendered
    assert "8-week change (latest minus earliest): not available" in rendered
    assert "Latest weight minus target: not available" in rendered
    assert "14-day movement relative to target: not available" in rendered
