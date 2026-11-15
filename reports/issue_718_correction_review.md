# #718 correction: static review

Read/edit only. No tests, builds, Python, application code, provider calls or
Git commands were executed. No commit was made. The supplied server log reports
637 passed and 17 failed at d5559b09; the supplied earlier result is 652/653 at
7cd259a5. This report does not claim a new passing count.

## Cause and correction

The relevance filter removed valid tools before the model could choose them.
It missed preferred-name forms such as `قولّي يا سلمى`, the physician report
`كشفت على ركبتي`, goal requests without `هدف`, and English edits using `put`
or `move`. A scripted model can still emit an unavailable tool name, which
explains the tool names in the failure telemetry: execution then returned
`unavailable`, without recording the action receipt. The fake consequently
consumed another ordinary model turn instead of its action-answer turn.

The new selector starts with the full catalog. Only a failed admission projection
can remove actions, and every read tool remains available. Under pressure it
adds actions in registry order while checking capacity for a final answer.
Both chat loops repeat selection against the actual transcript and remaining
budget each round. They execute only the tools bound for that round.

The calibrated estimate previously added ASCII framing byte slack as whole
tokens. It now applies the existing character-to-token calibration to that
slack. The conservative escaped-byte charge is unchanged, as are the 9,500
request / 24,000 turn estimated-token ceilings and the 96,000 escaped-byte
ceiling. This removes unnecessary history trimming and repeated-round refusals
without changing the history policy or shortening recent replies.

Expected restoration by reading the failure assertions and their execution
paths: five Arabic preferred-name cases, one Arabic injury-status case, two
Arabic goal cases, one production edit test (including `put` and `move`), two
Arabic history cases, four staging replay cases and two last-round final-answer
cases. These account for all 17 logged failures, including the one that predates
the reported 16-test regression. Which individual failure predates it was not
identified by the supplied log. Execution is still needed to establish results.

## Function-to-test map

The following map covers these 13 chat test files: `test_player_turn_budget.py`,
`test_player_tool_selection.py`, `test_player_chat_privacy.py`,
`test_player_context_router.py`, `test_chat_program_edits.py`,
`test_chat_rebuild_sse.py`, `test_arabic_swap_routing.py`,
`test_precommit_and_multi_intent.py`, `test_assistant_pipeline.py`,
`test_context_management.py`, `test_player_prompt.py`,
`test_player_program_rationale_tool.py`, and `eval/test_routing_suite.py`, all
under `tests/`. Names below include every parameter variant unless qualified.

For each modified production function:

| Function | Tests exercising it |
| --- | --- |
| `select_player_chat_tools` | The two direct selection tests in the budget group below, plus every model-branch test listed in the buffered and streaming groups. |
| `PlayerTurnInputBudget.fits_tool_round` (new) | The same selection tests and model-branch tests; its projected budget is separate from the live budget. |
| `PlayerTurnInputBudget.admit` | All six budget tests below; every listed model-branch test reaches it through admission and selection projections. |
| `_invoke_player_tool_loop` | The buffered group below. Safety/confirmation-only turns bypass it. |
| `stream_assistant_turn` | The streaming group below, including its listed safety and confirmation bypass cases. Only its model branch reaches selection/admission. |

### Direct budget tests

`tests/test_player_turn_budget.py`:

- `test_718_oversized_request_component_is_refused`
- `test_718_individually_small_rounds_cannot_exceed_the_turn_budget`
- `test_718_transport_retry_reservation_cannot_escape_the_turn_ceiling`
- `test_718_all_read_tool_schemas_fit_repeated_turn_estimate`
- `test_718_turn_pressure_keeps_all_reads_and_room_for_final_answer` (new)
- `test_718_schema_pressure_trims_old_exchanges_but_preserves_current_tool_pairs`

Read confirmation: oversized system/history/schema/arguments/results still fail
before counters advance; retry and cumulative limits still apply; selection
does not consume the live budget; all reads survive both cumulative ceilings;
current tool pairs remain indivisible during history removal. The existing
catalog test now requires all actions when the real fixed prompt fits, replacing
its former phrase-filter expectation that rebuild must be absent. It also
covers the regressed Arabic and English requests. No regression assertion was
removed from the other suites.

### Buffered model branch

`tests/test_player_tool_selection.py`:

- `test_718_program_options_reach_the_main_model_and_return_five_day_choices` (`streaming=False`)
- `test_previous_forced_read_paths_are_chosen_by_the_main_model`
- `test_718_staging_four_turn_replay_shows_current_split_and_same_split_preview` (`streaming=False`)
- `test_718_failed_preview_has_specific_localized_reply_even_if_model_would_stop_empty` (`streaming=False`)
- `test_718_empty_final_after_last_read_round_reports_unprepared_rebuild` (`streaming=False`)
- `test_718_last_tool_round_still_gets_a_final_answer` (`streaming=False`)
- `test_718_malformed_rebuild_call_discards_narration_and_reports_failure` (`streaming=False`)
- `test_718_preview_storage_failure_returns_honest_localized_reply` (`streaming=False`)
- `test_718_failed_answer_after_preview_cannot_leave_an_unseen_confirmable_offer` (`streaming=False`)

`tests/test_player_context_router.py`:

- `test_buffered_generation_also_receives_scoped_program_before_model`
- `test_buffered_history_intents_do_not_receive_program_prescriptions`

`tests/test_precommit_and_multi_intent.py`:

- `test_multiple_selected_tools_read_history_and_apply_a_swap` (`streaming=False`)

`tests/test_context_management.py`:

- `test_short_conversation_bypasses_canned_clarification`
- `test_shorthand_and_followups`
- `test_unresolved_history_graph_uses_generation_without_injected_comparison`
- `test_assistant_style_follows_safety_core_and_quotes_player_wording`

`tests/test_player_prompt.py`:

- `test_eval_qa_payloads_match_the_offline_prompt_capture`

Read confirmation: prefetch still runs before the first model request; only
non-safety/model turns reach the loop; all read paths remain bound; narration
is still discarded for tool rounds; receipts, explicit confirmation, program
authority, invalid-call handling, failure cleanup and the final unbound answer
are unchanged. Selection is repeated instead of reusing the first catalog.
Direct `generation_node` tests also enter the tool loop, including when no
ledger config is supplied; without a tool call they return the ordinary model
answer without reading ledger facts.

### Streaming model branch and bypass cases

`tests/test_player_tool_selection.py`: every buffered-list test that has a
`streaming` parameter also exercises streaming with `streaming=True`; additionally:

- `test_safety_preempts_model_tools_and_leaves_program_unchanged` (bypass)
- `test_rebuild_uses_separate_confirmation_and_saves_one_version` (bypass)
- `test_model_rebuild_tool_prepares_a_preview_without_writing_the_program`
- `test_718_late_tool_chunks_never_release_the_round_narration`

Read confirmation: real rebuild previews still carry days, exercises and sets;
the displayed offer still matches the saved offer; same-split rebuilds preserve
split family and prefer fresh eligible exercises; only a separate confirmation
publishes a version. Failure cleanup still clears an unseen preview.

`tests/test_chat_program_edits.py`:

- `test_model_selected_edit_keeps_preview_bound_to_displayed_reply`
- `test_production_chat_requests_preview_then_confirm_one_version`
- `test_cancelled_rebuild_preview_keeps_original_program_version`
- `test_egyptian_arabic_program_edit_previews_and_confirms`
- `test_all_rebuild_edit_clause_orders_are_preview_only`
- `test_rebuild_preview_with_optional_item_includes_all_days`
- `test_profile_change_stales_chat_preview_and_preserves_exact_plan` (bypass)
- `test_clinical_clause_records_injury_before_rebuild_edit` (bypass)
- `test_plain_no_cancels_offer_with_explicit_reply` (bypass)
- `test_unchanged_chat_confirm_says_nothing_changed` (bypass)

Read confirmation: the selected edit tool is available for `put`, `move` and
Arabic directives; service validation, optional items, offer binding, stale
version checks and one-version confirmation semantics are untouched. Service-only
edit tests do not call the modified selection or admission functions.

`tests/test_chat_rebuild_sse.py`:

- `test_718_rebuild_streams_real_preview_immediately_and_confirmation_writes_once`
- `test_718_answer_to_legacy_generation_offer_previews_before_separate_confirmation`
- `test_718_model_cannot_confirm_a_preview_created_in_the_same_turn`
- `test_718_stream_failures_log_traceback_and_request_id_without_private_values`

Read confirmation: SSE token/done equality, large structured previews, legacy
generation offers, same-turn confirmation refusal and storage-fault privacy
remain governed by the existing code after the binding change.

`tests/test_arabic_swap_routing.py`:

- `test_standard_arabic_swap_resolves_model_selected_natural_names`
- `test_egyptian_bench_request_resolves_single_program_match`
- `test_egyptian_incline_request_resolves_library_style_target`
- `test_leg_press_target_matches_the_english_named_target_path`
- `test_arabic_target_clarifies_without_mutation`
- `test_ar_mixed_03_suggestion_never_executes_scripted_swap`
- `test_ar_mixed_03_mismatched_name_hit_clarifies_without_mutation`
- `test_arabic_swap_with_weight_question_executes_the_selected_operation`
- `test_preferred_name_request_is_written_by_the_selected_tool`
- `test_ambiguous_source_clarifies_without_mutation`
- `test_arabic_coaching_questions_get_normal_coaching_answer`
- `test_composite_swap_request_executes_only_the_selected_operation`
- `test_unresolved_swap_target_clarifies_without_mutation`
- `test_english_swap_with_arabic_politeness_is_authorized_by_selected_operation`
- `test_model_selected_history_tool_resolves_arabic_exercise_names`
- `test_arabic_train_or_rest_advice_does_not_mutate_program`
- `test_arabic_clinical_and_franco_messages_are_intercepted_before_swap_routing` (bypass)

Read confirmation: binding never authorizes a swap. The direct tool tests
`test_718_negated_hedged_or_question_swap_never_writes` and
`test_718_mismatched_model_swap_arguments_never_write` exercise unchanged
authorization instead of the modified loop. Their exact-name, clause, day and
consent checks still reject writes. Companion history/coaching answers and the
exact action receipt still survive completion.

`tests/test_player_context_router.py`:

- `test_program_questions_arrive_scoped_before_first_model_answer`
- `test_router_keeps_system_bytes_fixed_and_fallback_tools_bound`
- `test_day_named_for_muscles_includes_its_other_exercises`
- `test_weekday_without_program_label_does_not_invent_schedule_mapping`
- `test_no_program_is_reported_before_model_answers`
- `test_coach_program_router_retains_authority`
- `test_safety_preempts_model_and_writes_use_selected_tools`
- `test_router_drops_pieces_that_do_not_fit_prompt_reserve`
- `test_multiple_large_unicode_day_pieces_respect_total_budget`

Read confirmation: full read availability does not alter scope matching, system
text, simulated tool pairs, private-field exclusions, 4 KB per-result caps or
the 8 KB prefetch bound. Safety variants still bypass the model.

`tests/test_precommit_and_multi_intent.py`:

- `test_multiple_selected_tools_read_history_and_apply_a_swap` (`streaming=True`)
- `test_banned_movement_preempts_history_question` (bypass)
- `test_streaming_banned_movement_preempts_history_question` (bypass)
- `test_isolated_gen_qa_04_coherent_veto` (`mode=stream`, bypass)
- `test_isolated_clinical_subintent_dominates_entire_turn` (`mode=stream`, bypass)
- `test_safety_gate_preflights_the_whole_request_before_model_actions` (bypass)
- `test_isolated_veto_preempts_the_entire_turn` (`mode=stream`, bypass)

Read confirmation: a compound history/swap still returns both the checked
history and receipt, while whole-turn safety vetoes precede tool construction.

`tests/test_assistant_pipeline.py`:

- `test_deload_pipeline_says_nothing_to_change_in_both_wrong_directions`
- `test_phase2_streaming_generator_qa`
- `test_phase2_streaming_generator_programmatic_bypass` (bypass)
- `test_component1_medical_red_flag_interceptor` (bypass)
- `test_clinical_injury_offer_confirmation_saves_restrictions_and_rebuilds_once`
- `test_injury_offer_decline_and_unrelated_turn_never_save_restrictions`
- `test_superseded_restriction_offer_id_cannot_clear_or_confirm_current_offer` (bypass)
- `test_coach_controlled_chat_confirmation_saves_and_notifies_without_rebuild` (bypass)

Read confirmation: Deload still validates the original directive; ordinary Q&A
retains its streamed text; safety and existing confirmation handling still
precede inference and retain their authority/offer checks.

`tests/test_context_management.py`:

- `test_explicit_name_and_recall`

Read confirmation: saving and recalling the name still produce the exact receipt,
update the existing memory key, and use the separate schema-free answer round.

`tests/eval/test_routing_suite.py`:

- `test_hermetic_routing_bootstraps_catalog_before_ci_initialization`
- `test_hermetic_routing_never_loads_embedding_models`
- `test_en_history_03_whole_session_request_stays_on_history_route`
- `test_hermetic_routing_counts_every_owner_reviewed_case`
- `test_hermetic_routing_excludes_unreviewed_arabic_from_score`
- `test_gate_summary_reports_unauthorized_actions_and_clinical_misses`
- `test_hermetic_cli_counts_reviewed_arabic_cases`
- `test_partial_suite_cli_marks_player_gate_not_run`
- `test_second_action_in_arabic_compound_request_fails_even_above_routing_bar`

Read confirmation: `_observe_case` enters the streaming loop; the actual
selected operations and ledger writes remain the scoring inputs. The expected
40-case set, action authorization checks and companion-answer requirements were
not edited. Scoring-only tests in this file do not call the modified functions.

### HTTP privacy and regression coverage

`tests/test_player_chat_privacy.py` enters `stream_assistant_turn` through
`POST /chat/messages` for both TestClient request styles. The following tests
cover selection/admission and their observable effects:

- `test_chat_sse_done_frame_contains_structured_program_edit_preview`
- `test_active_program_tool_context_reports_player_authority_without_coach`
- `test_chat_writes_weak_points_in_english_and_arabic_without_guessing`
- `test_goal_change_chat_offers_and_saves_named_weak_points`
- `test_declining_goal_weak_point_suggestion_does_not_save_it`
- `test_goal_suggestion_over_two_asks_which_to_keep_without_saving`
- `test_goal_weak_point_acceptance_on_coach_program_saves_without_regeneration`
- `test_goal_offer_is_not_accepted_by_unrelated_two_muscle_text`
- `test_new_goal_supersedes_pending_goal_offer`
- `test_unrelated_turn_clears_goal_offer_before_later_yes`
- `test_clearing_chat_clears_pending_goal_offer`
- `test_expired_goal_offer_cannot_be_accepted`
- `test_other_confirmation_cannot_accept_goal_offer`
- `test_chat_accepts_canonical_weak_point_keys`
- `test_player_model_input_excludes_identifying_fields`
- `test_chat_turn_keeps_recent_six_full_and_trims_only_older_assistant_replies`
- `test_tool_bound_chat_fetches_profile_and_program_only_after_parallel_calls`
- `test_chat_search_finds_old_english_and_arabic_messages_with_filters`
- `test_chat_history_search_backfills_legacy_messages_on_first_mount`
- `test_delete_chat_history_removes_old_messages_from_search`
- `test_arabic_tool_status_uses_fixed_localized_text`
- `test_turn_without_tool_call_sends_no_profile_telemetry_or_program_data`
- `test_age_question_sends_body_without_injury_or_weak_point_data`
- `test_unset_profile_fields_return_not_set_without_invented_defaults`
- `test_legacy_completed_profile_keeps_values_equal_to_storage_defaults`
- `test_explicit_none_limitations_answer_is_reported_as_none`
- `test_weight_trend_tool_returns_bounded_dated_progress_facts`
- `test_unyielded_text_before_tool_call_is_discarded`
- `test_completed_tool_round_never_releases_buffered_text`
- `test_http_stream_buffers_until_model_round_completes`
- `test_partial_profile_update_does_not_expose_storage_defaults`
- `test_tool_loop_stops_after_three_rounds_and_still_streams_a_reply`
- `test_tool_timeout_returns_unavailable_and_turn_continues`
- `test_oversized_tool_result_is_capped_at_four_kilobytes`
- `test_tool_result_keeps_followup_payload_under_the_prompt_ceiling`
- `test_indirect_biceps_question_receives_exact_tool_counts`
- `test_english_arabic_and_ordinary_gym_digits_keep_model_chat_behavior`
- `test_chat_preferred_name_forms_sync_to_profile_and_prompt`
- `test_chat_does_not_store_invalid_preferred_name`
- `test_profile_preferred_name_reaches_prompt_and_clearing_removes_it`
- `test_unresolved_history_reads_keep_the_hosted_fallback_without_injected_comparison`
- `test_all_exercises_followup_reaches_model_without_injected_comparison`
- `test_chat_accepts_messages_at_the_character_limit`
- `test_retried_failed_turn_persists_one_user_and_one_assistant`
- `test_arabic_program_change_runs_through_http_chat_with_validated_split`
- `test_arabic_frequency_change_runs_through_http_chat`
- `test_arabic_program_change_questions_do_not_mutate_through_http_chat`
- `test_arabic_program_change_without_target_clarifies_without_mutation`
- `test_arabic_frequency_change_retires_glute_priority_split`
- `test_arabic_history_fallback_does_not_inject_ledger_figures`
- `test_arabic_missing_program_day_or_exercise_clarifies_without_change`
- `test_arabic_program_change_rejects_unsupported_frequency_or_split`
- `test_english_program_tool_previews_before_confirmation`
- `test_clinical_chat_records_injury_and_clarifies_only_area_replies`
- `test_pending_injury_clarification_expires_after_one_unrelated_turn`
- `test_injury_status_reply_uses_arabic_label`
- `test_profile_injury_text_import_survives_later_chat_injury_write`
- `test_pending_injury_ordinary_area_chat_does_not_attach_area`
- `test_player_chat_reads_injuries_through_limitations_section`
- `test_limitations_clearances_hide_internal_ids_but_keep_player_wording`
- `test_physician_followup_appends_without_swallowing_chat_and_reasks_for_area_advice`
- `test_physician_followup_only_skips_a_reply_ending_with_a_question_mark`
- `test_physician_followup_stream_tokens_match_done_reply`
- `test_arabic_chat_appends_arabic_physician_followup`
- `test_full_physician_clearance_requires_player_confirmation`
- `test_doctor_cleared_my_knee_is_not_saved_as_an_exercise_clearance`
- `test_remember_tool_saves_once`
- `test_forget_proposes_closest_preference_and_requires_confirmation`
- `test_stale_forget_confirmation_cannot_answer_physician_question`
- `test_preference_limits_are_enforced_and_clear_chat_keeps_preferences`
- `test_preferences_api_edit_is_read_by_later_tool_call_and_ordinary_chat_does_not_write`
- `test_player_nutrition_tool_omits_targets_after_positive_rescreen`
- `test_player_nutrition_tool_returns_ready_payload_for_player_local_window`
- `test_player_nutrition_tool_reports_under_18_as_unavailable`

Read confirmation for the logged failures: every preferred-name spelling in the
parameter table now has `preferred_name` available; the existing parser still
normalizes diacritics/Alef/Yaa and saves the original spelling. The exact
confirmation and next-turn prompt name assertions remain intact. The physician
report reaches `update_injury`, whose existing localized receipt contains
`تمت مراجعة الطبيب`, never `physician_seen`. The two goal requests now reach
`update_training_goal`, retaining the separate weak-point offer confirmation.
Arabic history cases retain the same ten-message selection, recent-six full
text, 600-character older-reply cap and unmodified stored chat history.

Read confirmation for the remaining HTTP checks: tools still fetch facts only
on demand, omit identifying fields, respect Profile scopes, cap results, retain
the tool-round text buffer and finish after at most three tool rounds plus the
final answer. Making a write tool available does not bypass its original-message
validation, pending-offer confirmation or Program authority checks.

The same file's clinical/Franco/refusal and structured-intake tests exercise
the unchanged pre-model bypass inside `stream_assistant_turn`, not admission.
Direct Profile/program-reader tests, CRUD/history endpoints and oversize
HTTP rejection do not exercise the modified functions.

### Reviewed files without direct modified-function coverage

`tests/test_player_program_rationale_tool.py` calls `build_player_read_tools`
and the individual readers directly. No changed function is exercised. Its
authority, scope, source attribution, 4 KB and pagination assertions remain
unchanged; the rationale tool remains in the always-bound read catalog.

Apart from the offline payload-capture test listed above,
`tests/test_player_prompt.py` tests prompt construction directly. The fixed
prompt, script-neutral history policy, calibrated English/Arabic rates, style
quoting and safety literals were not edited. Their assertions still match the
source. Likewise the prompt-only/history-reader tests in
`tests/test_context_management.py` do not exercise the modified budget functions.

## Review limits

This is a source-based compatibility review, not an executed proof of restored
tests. Future tool results and provider retries still require fresh admission;
the selector's final-answer projection cannot predict their size. If the full
read catalog and required current context cannot fit, existing admission still
refuses the request. Compact turns bind more actions than d5559b09, so provider
cost must be measured separately. The server log was removed as requested.

clean-code-guard: clean

test-guard: no new review findings

docs-guard: behavior and limits checked against the edited source
