import 'message_copy.dart';

typedef _MessageTemplate = String? Function(
  Map<String, dynamic> params,
  MessageCopy copy,
);

const Set<String> _regressionBadges = <String>{
  'BASELINE',
  'CONSOLIDATING',
  'GRADUATED',
  'LOAD INCREASE',
  'OVERSHOOT',
  'REP OVERLOAD',
  'regression',
};
const Set<String> _profileFields = <String>{
  'injuries_or_limitations',
  'equipment_access',
};
const Set<String> _deloadReasons = <String>{
  'rolling_readiness_crash',
  'acute_readiness_floor',
  'high_exertion_density',
};

String resolveStructuredMessage({
  required Object? messageCode,
  required Object? messageParams,
  required String? englishFallback,
  required String displayLanguage,
}) {
  final MessageCopy copy = MessageCopy(displayLanguage);
  final String fallback = englishFallback?.trim().isNotEmpty == true
      ? englishFallback!.trim()
      : copy.unavailable;
  if (displayLanguage != 'ar') return fallback;
  if (messageCode is! String || messageParams is! Map<String, dynamic>) {
    return fallback;
  }
  final Set<String>? allowedParams = _paramKeys[messageCode];
  if (allowedParams == null || !_hasExactKeys(messageParams, allowedParams)) {
    return fallback;
  }
  final _MessageTemplate? template = _templates[messageCode];
  // The shared import handler uses the registry key to select localized copy.
  return template?.call(
        <String, dynamic>{...messageParams, '_message_code': messageCode},
        copy,
      ) ??
      fallback;
}

bool _hasExactKeys(Map<String, dynamic> params, Set<String> allowed) =>
    params.length == allowed.length && params.keys.every(allowed.contains);

const Map<String, Set<String>> _paramKeys = <String, Set<String>>{
  'coach_alert.missed_expected_days.v1': <String>{
    'count',
    'start_date',
    'end_date',
  },
  'coach_alert.follow_up_due.v1': <String>{'due_on'},
  'coach_alert.stall.v1': <String>{'count', 'window_start_date'},
  'coach_alert.deload_recommended.v1': <String>{
    'reason_code',
    'recent_readiness_avg',
    'choice',
  },
  'coach_alert.performance_regression.v1': <String>{
    'exercise_name',
    'e1rm_delta',
    'status_badge',
  },
  'coach_alert.profile_change.v1': <String>{'changed_fields'},
  'coach_alert.weight_off_target_trend.v1': <String>{
    'distance_change_kg',
    'target_weight_kg',
    'window_days',
    'threshold_kg',
  },
  'app.update_required.v1': <String>{'min_build'},
  'http.bad_request.v1': <String>{},
  'http.unauthorized.v1': <String>{},
  'http.forbidden.v1': <String>{},
  'http.not_found.v1': <String>{},
  'http.conflict.v1': <String>{},
  'http.validation_failed.v1': <String>{},
  'http.input_too_long.v1': <String>{'limit'},
  'http.rate_limited.v1': <String>{},
  'http.server_error.v1': <String>{},
  'http.request_failed.v1': <String>{},
  'ai_limit.request_rate.v1': <String>{},
  'ai_limit.daily_usage.v1': <String>{},
  'chat.failed.v1': <String>{},
  'google.account_already_linked.v1': <String>{},
  'google.invalid_token.v1': <String>{},
  'google.linked_elsewhere.v1': <String>{},
  'google.different_account.v1': <String>{},
  'google.unlink_password_required.v1': <String>{},
  'workout.program_version_mismatch.v1': <String>{},

  'auth.invalid_credentials.v1': <String>{},
  'auth.username_taken.v1': <String>{},
  'auth.invalid_or_expired_token.v1': <String>{},
  'auth.invalid_signup_ticket.v1': <String>{},
  'auth.signup_ticket_missing.v1': <String>{},
  'recovery.invalid_or_expired_code.v1': <String>{},
  'recovery.code_send_limit.v1': <String>{},
  'recovery.invalid_or_expired_token.v1': <String>{},
  'coach_invite.invalid_code.v1': <String>{},
  'assignment.none_active.v1': <String>{},
  'assignment.invite_invalid.v1': <String>{},
  'assignment.self_assignment.v1': <String>{},
  'assignment.already_assigned.v1': <String>{},
  'assignment.consent_required.v1': <String>{},
  'assignment.roster_full.v1': <String>{},
  'assignment.request_invalid.v1': <String>{},
  'assignment.coach_roster_full.v1': <String>{},
  'assignment.coach_capability_required.v1': <String>{},
  'assignment.coach_profile_required.v1': <String>{},
  'assignment.invite_lifetime_invalid.v1': <String>{},
  'assignment.not_participant.v1': <String>{},
  'assignment.already_ended.v1': <String>{},
  'assignment.program_draft_exists.v1': <String>{},
  'assignment.program_draft_changed.v1': <String>{},
  'assignment.program_draft_invalid.v1': <String>{},
  'assignment.check_in_invalid.v1': <String>{},
  'assignment.not_found.v1': <String>{},
  'assignment.program_draft_not_found.v1': <String>{},
  'assignment.notice_not_found.v1': <String>{},
  'program_import.file_too_large.v1': <String>{},
  'program_import.file_type.v1': <String>{},
  'program_import.file_invalid.v1': <String>{},
  'program_import.too_many_tabs.v1': <String>{},
  'program_import.sheet_empty.v1': <String>{},
  'program_import.tab_invalid.v1': <String>{},
  'program_import.too_many_rows.v1': <String>{},
  'program_import.too_many_columns.v1': <String>{},
  'program_import.template_columns.v1': <String>{},
  'program_import.freeform_disabled.v1': <String>{},
  'program_import.interpretation_failed.v1': <String>{},
  'program_import.too_many_cells.v1': <String>{'max_cells'},
  'program_import.week_invalid.v1': <String>{},
  'program_import.unsupported_preserved_as_note.v1': <String>{},
  'program_import.suggestions_unavailable.v1': <String>{},
  'program_import.no_rows.v1': <String>{},
  'program_import.exercise_invalid.v1': <String>{},
  'program_import.too_many_exercises.v1': <String>{},
  'program_import.invalid_day.v1': <String>{},
  'program_import.invalid_order.v1': <String>{},
  'program_import.invalid_sets.v1': <String>{},
  'program_import.invalid_reps.v1': <String>{},
  'program_import.reps_required.v1': <String>{},
  'program_import.reps_as_date.v1': <String>{},
  'program_import.reps_approximated.v1': <String>{},
  'program_import.invalid_effort.v1': <String>{},
  'program_import.rpe_converted.v1': <String>{},
  'program_import.effort_approximated.v1': <String>{},
  'program_import.conflicting_effort.v1': <String>{},
  'program_import.invalid_rest.v1': <String>{},
  'program_import.exercise_required.v1': <String>{},
  'program_import.exercise_name_too_long.v1': <String>{},
  'program_import.day_name_too_long.v1': <String>{},
  'program_import.tempo_too_long.v1': <String>{},
  'program_import.notes_too_long.v1': <String>{},
  'program_import.conflicting_day_name.v1': <String>{},
  'program_import.load_preserved_as_note.v1': <String>{},
  'program_import.exercise_unresolved.v1': <String>{},
  'program_import.exercise_ambiguous.v1': <String>{},
  'program.no_active.v1': <String>{},
  'program.coach_controls.v1': <String>{},
  'program.substitution.day_not_found.v1': <String>{},
  'program.substitution.source_not_on_day.v1': <String>{},
  'program.substitution.replacement_is_source.v1': <String>{},
  'program.substitution.replacement_not_found.v1': <String>{},
  'program.substitution.replacement_already_on_day.v1': <String>{},
  'program.substitution.restore_version_not_found.v1': <String>{},
  'program.substitution.changed.v1': <String>{},
  'program.edit.day_not_found.v1': <String>{},
  'program.edit.exercise_not_on_day.v1': <String>{},
  'program.edit.duplicate_exercise.v1': <String>{},
  'program.edit.empty_day.v1': <String>{},
  'program.edit.invalid_set_count.v1': <String>{},
  'program.edit.changed.v1': <String>{},
  'program_request.invalid_kind.v1': <String>{},
  'program_request.reason_required.v1': <String>{},
  'program_request.reason_too_long.v1': <String>{'limit'},
  'program_request.direct_change.v1': <String>{},
  'program_request.no_active_program.v1': <String>{},
  'program_request.target_incomplete.v1': <String>{},
  'program_request.same_replacement.v1': <String>{},
  'program_request.day_not_in_program.v1': <String>{},
  'program_request.exercise_not_in_day.v1': <String>{},
  'program_request.replacement_not_found.v1': <String>{},
  'program_request.frequency_invalid.v1': <String>{},
  'program_request.split_too_long.v1': <String>{'limit'},
  'program_request.not_found.v1': <String>{},
  'program_request.not_pending.v1': <String>{},
  'program_request.stale.v1': <String>{},
  'program_request.response_required.v1': <String>{},
  'program_request.response_too_long.v1': <String>{'limit'},
  'program_request.selection_invalid.v1': <String>{},
  'intake.structured_active.v1': <String>{},
  'intake.in_progress.v1': <String>{},
  'intake.program_generation_unavailable.v1': <String>{},
  'intake.gender.explanation.v1': <String>{},
  'intake.gender.option.male.v1': <String>{},
  'intake.gender.option.female.v1': <String>{},
  'intake.proportions.explanation.v1': <String>{},
  'intake.proportions.option.long_legs.v1': <String>{},
  'intake.proportions.option.balanced.v1': <String>{},
  'intake.proportions.option.long_torso.v1': <String>{},
  'intake.current_goal.hint.v1': <String>{},
  'intake.current_goal.example.1.v1': <String>{},
  'intake.current_goal.example.2.v1': <String>{},
  'intake.current_goal.example.3.v1': <String>{},
  'intake.long_term_goal.hint.v1': <String>{},
  'intake.long_term_goal.example.1.v1': <String>{},
  'intake.long_term_goal.example.2.v1': <String>{},
  'intake.equipment_access.option.commercial_gym.v1': <String>{},
  'intake.equipment_access.option.home_gym.v1': <String>{},
  'intake.equipment_access.option.bodyweight_only.v1': <String>{},
  'intake.injuries_or_limitations.hint.v1': <String>{},
  'intake.injuries_or_limitations.example.1.v1': <String>{},
  'intake.injuries_or_limitations.example.2.v1': <String>{},
  'intake.stress_and_sleep.hint.v1': <String>{},
  'intake.stress_and_sleep.example.1.v1': <String>{},
  'intake.stress_and_sleep.example.2.v1': <String>{},
  'intake.rep_preference.option.low.v1': <String>{},
  'intake.rep_preference.option.balanced.v1': <String>{},
  'intake.rep_preference.option.high.v1': <String>{},
  'coach.ai_unavailable.v1': <String>{},
  'media.unavailable.v1': <String>{},
  'media.not_found.v1': <String>{},
};

final Map<String, _MessageTemplate> _templates = <String, _MessageTemplate>{
  'coach_alert.missed_expected_days.v1': _missedDays,
  'coach_alert.follow_up_due.v1': _followUp,
  'coach_alert.stall.v1': _stall,
  'coach_alert.deload_recommended.v1': _deload,
  'coach_alert.performance_regression.v1': _regression,
  'coach_alert.profile_change.v1': _profileChange,
  'coach_alert.weight_off_target_trend.v1': _weightOffTargetTrend,
  'program_import.file_too_large.v1': _programImport,
  'program_import.file_type.v1': _programImport,
  'program_import.file_invalid.v1': _programImport,
  'program_import.too_many_tabs.v1': _programImport,
  'program_import.sheet_empty.v1': _programImport,
  'program_import.tab_invalid.v1': _programImport,
  'program_import.too_many_rows.v1': _programImport,
  'program_import.too_many_columns.v1': _programImport,
  'program_import.template_columns.v1': _programImport,
  'program_import.freeform_disabled.v1': _programImport,
  'program_import.interpretation_failed.v1': _programImport,
  'program_import.too_many_cells.v1': _programImport,
  'program_import.week_invalid.v1': _programImport,
  'program_import.unsupported_preserved_as_note.v1': _programImport,
  'program_import.suggestions_unavailable.v1': _programImport,
  'program_import.no_rows.v1': _programImport,
  'program_import.exercise_invalid.v1': _programImport,
  'program_import.too_many_exercises.v1': _programImport,
  'program_import.invalid_day.v1': _programImport,
  'program_import.invalid_order.v1': _programImport,
  'program_import.invalid_sets.v1': _programImport,
  'program_import.invalid_reps.v1': _programImport,
  'program_import.reps_required.v1': _programImport,
  'program_import.reps_as_date.v1': _programImport,
  'program_import.reps_approximated.v1': _programImport,
  'program_import.invalid_effort.v1': _programImport,
  'program_import.rpe_converted.v1': _programImport,
  'program_import.effort_approximated.v1': _programImport,
  'program_import.conflicting_effort.v1': _programImport,
  'program_import.invalid_rest.v1': _programImport,
  'program_import.exercise_required.v1': _programImport,
  'program_import.exercise_name_too_long.v1': _programImport,
  'program_import.day_name_too_long.v1': _programImport,
  'program_import.tempo_too_long.v1': _programImport,
  'program_import.notes_too_long.v1': _programImport,
  'program_import.conflicting_day_name.v1': _programImport,
  'program_import.load_preserved_as_note.v1': _programImport,
  'program_import.exercise_unresolved.v1': _programImport,
  'program_import.exercise_ambiguous.v1': _programImport,
  'app.update_required.v1': _appUpdateRequired,
  'http.bad_request.v1': _badRequest,
  'http.unauthorized.v1': _unauthorized,
  'http.forbidden.v1': _forbidden,
  'http.not_found.v1': _notFound,
  'http.conflict.v1': _conflict,
  'http.validation_failed.v1': _validationFailed,
  'http.input_too_long.v1': _inputTooLong,
  'http.rate_limited.v1': _rateLimited,
  'http.server_error.v1': _requestUnavailable,
  'http.request_failed.v1': _requestFailed,
  'ai_limit.request_rate.v1': _aiRequestRateLimited,
  'ai_limit.daily_usage.v1': _aiDailyLimit,
  'chat.failed.v1': _chatFailed,
  'google.account_already_linked.v1': _googleAlreadyLinked,
  'workout.program_version_mismatch.v1': _programVersionMismatch,
  for (final String code in _paramKeys.keys.where(_isSpecificErrorCode))
    code: (params, copy) => _specificError(code, params, copy),
};

bool _isSpecificErrorCode(String code) =>
    (code.startsWith('google.') &&
        code != 'google.account_already_linked.v1') ||
    code.startsWith('auth.') ||
    code.startsWith('assignment.') ||
    code.startsWith('program.') ||
    code.startsWith('program_request.') ||
    code.startsWith('intake.') ||
    code.startsWith('coach.') ||
    code.startsWith('media.') ||
    code.startsWith('recovery.') ||
    code.startsWith('coach_invite.');

String? _specificError(
  String code,
  Map<String, dynamic> params,
  MessageCopy copy,
) {
  final String? intakeCopy = copy.intakeCopy(code);
  if (intakeCopy != null) return intakeCopy;
  final int? limit = switch (params['limit']) {
    int value => value,
    _ => null,
  };
  return copy.specificError(code, limit: limit);
}

String? _badRequest(Map<String, dynamic> params, MessageCopy copy) =>
    copy.badRequest;

String? _unauthorized(Map<String, dynamic> params, MessageCopy copy) =>
    copy.unauthorized;

String? _forbidden(Map<String, dynamic> params, MessageCopy copy) =>
    copy.forbidden;

String? _appUpdateRequired(Map<String, dynamic> params, MessageCopy copy) =>
    copy.appUpdateRequired;

String? _notFound(Map<String, dynamic> params, MessageCopy copy) =>
    copy.notFound;

String? _conflict(Map<String, dynamic> params, MessageCopy copy) =>
    copy.conflict;

String? _validationFailed(Map<String, dynamic> params, MessageCopy copy) =>
    copy.invalidRequest;

String? _inputTooLong(Map<String, dynamic> params, MessageCopy copy) {
  final int? limit = switch (params['limit']) {
    int value => value,
    _ => null,
  };
  return limit == null || limit <= 0 ? null : copy.inputTooLong(limit);
}

String? _rateLimited(Map<String, dynamic> params, MessageCopy copy) =>
    copy.rateLimited;

String? _aiRequestRateLimited(
  Map<String, dynamic> params,
  MessageCopy copy,
) =>
    copy.aiRequestRateLimited;

String? _aiDailyLimit(Map<String, dynamic> params, MessageCopy copy) =>
    copy.aiDailyLimit;

String? _requestUnavailable(Map<String, dynamic> params, MessageCopy copy) =>
    copy.requestUnavailable;

String? _requestFailed(Map<String, dynamic> params, MessageCopy copy) =>
    copy.requestFailed;

String? _chatFailed(Map<String, dynamic> params, MessageCopy copy) =>
    copy.chatFailure;

String? _googleAlreadyLinked(Map<String, dynamic> params, MessageCopy copy) =>
    copy.googleAlreadyLinked;

String? _programVersionMismatch(
  Map<String, dynamic> params,
  MessageCopy copy,
) =>
    copy.programVersionMismatch;

String? _missedDays(Map<String, dynamic> params, MessageCopy copy) {
  final int? count = _count(params['count']);
  final String? start = _date(params['start_date']);
  final String? end = _date(params['end_date']);
  if (count == null || start == null || end == null) return null;
  return copy.missedExpectedDays(count, start, end);
}

String? _followUp(Map<String, dynamic> params, MessageCopy copy) {
  final String? due = _date(params['due_on']);
  return due == null ? null : copy.followUpDue(due);
}

String? _stall(Map<String, dynamic> params, MessageCopy copy) {
  final int? count = _count(params['count']);
  final Object? rawDate = params['window_start_date'];
  if (rawDate != null && _date(rawDate) == null) return null;
  if (count == null) return null;
  return copy.stalledSessions(count, rawDate as String?);
}

String? _deload(Map<String, dynamic> params, MessageCopy copy) {
  final Object? reason = params['reason_code'];
  final double? average = _number(params['recent_readiness_avg']);
  final Object? rawChoice = params['choice'];
  if (!_deloadReasons.contains(reason) || average == null) return null;
  if (rawChoice != null && rawChoice != 'apply' && rawChoice != 'undo') {
    return null;
  }
  final String message = switch (reason) {
    'rolling_readiness_crash' => copy.rollingReadinessDeload(average),
    'acute_readiness_floor' => copy.acuteReadinessDeload(),
    _ => copy.highExertionDeload(),
  };

  return copy.deloadChoice(message, rawChoice as String?);
}

String? _regression(Map<String, dynamic> params, MessageCopy copy) {
  final Object? rawName = params['exercise_name'];
  final double? delta = _number(params['e1rm_delta']);
  final Object? rawBadge = params['status_badge'];
  if (rawName is! String || rawName.isEmpty || delta == null) return null;
  if (rawBadge is! String || !_regressionBadges.contains(rawBadge)) return null;
  return copy.performanceRegression(rawName, delta, rawBadge);
}

String? _profileChange(Map<String, dynamic> params, MessageCopy copy) {
  final Object? rawFields = params['changed_fields'];
  if (rawFields is! List<dynamic> || rawFields.isEmpty) return null;
  if (rawFields.any(
    (dynamic field) => field is! String || !_profileFields.contains(field),
  )) {
    return null;
  }
  return copy.profileChange(rawFields.cast<String>());
}

String? _weightOffTargetTrend(Map<String, dynamic> params, MessageCopy copy) {
  final double? distanceChange = _number(params['distance_change_kg']);
  final double? target = _number(params['target_weight_kg']);
  final int? windowDays = _count(params['window_days']);
  final double? threshold = _number(params['threshold_kg']);
  if (distanceChange == null || target == null || windowDays == null || threshold == null) {
    return null;
  }
  return copy.weightOffTargetTrend(distanceChange, target, windowDays, threshold);
}

int? _count(Object? value) => value is int && value >= 0 ? value : null;

String? _date(Object? value) {
  if (value is! String || !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) {
    return null;
  }
  final DateTime? parsed = DateTime.tryParse(value);
  return parsed != null && parsed.toIso8601String().startsWith(value)
      ? value
      : null;
}

double? _number(Object? value) {
  if (value is! num || !value.isFinite) return null;
  return value.toDouble();
}

String? _programImport(Map<String, dynamic> params, MessageCopy copy) {
  final Object? code = params['_message_code'];
  return code is String
      ? copy.programImportMessage(code, maxCells: _count(params['max_cells']))
      : null;
}
