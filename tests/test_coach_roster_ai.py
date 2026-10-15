"""Unit tests for the de-identified Coach roster assistant prompt."""

from service import coach_roster_ai


def _signal(player_id, rank):
    return {
        "player_id": player_id,
        "urgency_rank": rank,
        "urgency_inputs": {
            "new_lapsing_alerts": rank,
            "other_new_coach_alerts": 0,
            "pending_program_requests": 0,
            "missed_day_streak": 0,
            "follow_up_overdue_days": 0,
            "days_since_last_workout": rank,
            "stall_length_sessions": 0,
            "private_note": "PRIVATE_NESTED_NOTE_SHOULD_BE_DROPPED",
        },
        "missed_expected_days_7d": rank,
        "missed_expected_days_14d": rank,
        "adherence_pct_28d": 100 - rank,
        "weeks_without_personal_record": 0,
        "stall_threshold_met": False,
        "effort_rising_same_load_main_lift": False,
        "days_since_last_check_in": 1,
        "bodyweight_trend": None,
        "coaching_subscription_end": None,
        "username": "PRIVATE_USERNAME_SHOULD_BE_DROPPED",
    }


def test_token_budget_keeps_the_urgency_prefix_and_separate_identity_map():
    first_id = "aaaaaaaaaaaa11111111111111111111"
    second_id = "bbbbbbbbbbbb22222222222222222222"
    first = _signal(first_id, 1)
    second = _signal(second_id, 2)
    base_snapshot = {
        "as_of": "2026-10-11",
        "stall_threshold_weeks": 3,
        "players": [],
    }
    one_player_tokens = coach_roster_ai._snapshot_token_count(
        {**base_snapshot, "players": [
            {
                **{key: value for key, value in first.items() if key != "username"},
                "player_id": coach_roster_ai.player_alias(first_id),
            }
        ]}
    )
    response = coach_roster_ai.prepare_roster_question(
        {
            "snapshot": {
                **base_snapshot,
                "players": [first, second],
            },
            "client_mapping": [
                {
                    "player_id": first_id,
                    "assignment_id": "assignment_01",
                    "player_display_name": "Alice Example",
                },
                {
                    "player_id": second_id,
                    "assignment_id": "assignment_02",
                    "player_display_name": "Bob Example",
                },
            ],
            "excluded_for_missing_disclosure": 4,
        },
        "Who needs attention?",
        [],
        token_budget=one_player_tokens,
    )

    payload = response.messages[0].content
    assert '"player_id":"Paaaaaaaaaaaa"' in payload
    assert '"player_id":"Pbbbbbbbbbbbb"' not in payload
    assert "PRIVATE_USERNAME_SHOULD_BE_DROPPED" not in payload
    assert "PRIVATE_NESTED_NOTE_SHOULD_BE_DROPPED" not in payload
    assert response.included_count == 1
    assert response.left_out_for_budget == 1
    assert response.excluded_for_missing_disclosure == 4
    assert response.client_mapping == [
        {
            "player_id": "Paaaaaaaaaaaa",
            "assignment_id": "assignment_01",
            "player_display_name": "Alice Example",
        }
    ]


def test_snapshot_smaller_than_one_player_excludes_all_without_leaking_map():
    signal = _signal("cccccccccccc22222222222222222222", 1)
    response = coach_roster_ai.prepare_roster_question(
        {
            "snapshot": {
                "as_of": "2026-10-11",
                "stall_threshold_weeks": 3,
                "players": [signal],
            },
            "client_mapping": [
                {
                    "player_id": "cccccccccccc22222222222222222222",
                    "assignment_id": "secret",
                    "player_display_name": "Private name",
                }
            ],
            "excluded_for_missing_disclosure": 0,
        },
        "Who needs attention?",
        [],
        token_budget=1,
    )
    assert '"players":[]' in response.messages[0].content
    assert "secret" not in response.messages[0].content
    assert response.client_mapping == []
    assert response.left_out_for_budget == 1


def test_coverage_summary_is_fixed_and_localized():
    prepared = coach_roster_ai.PreparedRosterQuestion(
        messages=[],
        client_mapping=[],
        included_count=2,
        left_out_for_budget=3,
        excluded_for_missing_disclosure=4,
    )
    english = coach_roster_ai.coverage_summary("en", prepared)
    arabic = coach_roster_ai.coverage_summary("ar", prepared)
    assert "3 eligible player(s) left out" in english
    assert "4 active assignment(s) excluded" in english
    assert "3 من اللاعبين المؤهلين" in arabic
    assert "4 علاقة تدريب نشطة" in arabic


def test_alias_format_matches_production_uuid_prefix():
    assert coach_roster_ai.player_alias("0123456789abef00") == "P0123456789ab"
    assert coach_roster_ai.PLAYER_ALIAS_PATTERN.fullmatch("P0123456789ab")


def test_snapshot_serialization_is_the_prompt_and_budget_serialization():
    snapshot = {
        "as_of": "2026-10-11",
        "stall_threshold_weeks": 3,
        "players": [_signal("aaaaaaaaaaaa11111111111111111111", 1)],
    }
    messages = coach_roster_ai.build_messages(snapshot, "Question", [])
    assert coach_roster_ai.serialize_snapshot(snapshot) in messages[0].content
    assert coach_roster_ai._snapshot_token_count(snapshot) > 0


def test_roster_feature_is_off_by_default(monkeypatch):
    monkeypatch.delenv("COACH_ROSTER_AI_ENABLED", raising=False)
    monkeypatch.delenv("COACH_ROSTER_AI_EVAL_REPORT", raising=False)
    assert not coach_roster_ai.coach_roster_ai_enabled()


def test_prompt_hash_changes_when_allowlisted_signal_schema_changes(monkeypatch):
    original_hash = coach_roster_ai.prompt_version_hash()
    monkeypatch.setattr(
        coach_roster_ai,
        "_SIGNAL_FIELDS",
        (*coach_roster_ai._SIGNAL_FIELDS, "new_roster_signal"),
    )

    assert coach_roster_ai.prompt_version_hash() != original_hash
