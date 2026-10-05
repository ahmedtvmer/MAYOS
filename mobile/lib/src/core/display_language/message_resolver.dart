import 'message_copy.dart';
import '../models.dart';

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

String resolveCoachAlertDescription(
  CoachAlert alert,
  String displayLanguage,
) {
  final MessageCopy copy = MessageCopy(displayLanguage);
  final MessageCopy englishCopy = MessageCopy('en');
  final String? legacyFallback = _legacyAlertFallback(alert, englishCopy);
  final String? fallback = alert.isProfileChange
      ? legacyFallback
      : alert.messageFallback ?? legacyFallback;
  final String description = resolveStructuredMessage(
    messageCode: alert.supportedMessageCode,
    messageParams: alert.messageParams,
    englishFallback: fallback,
    displayLanguage: displayLanguage,
  );
  final String normalizedFallback = fallback?.trim().isNotEmpty == true
      ? fallback!.trim()
      : copy.unavailable;
  if (displayLanguage == 'ar' &&
      alert.isProfileChange &&
      alert.supportedMessageCode == 'coach_alert.profile_change.v1' &&
      description != normalizedFallback) {
    final String evidence = copy.profileChangeEvidence(alert.profileChanges);
    return evidence.isEmpty ? description : '$description\n$evidence';
  }
  return description;
}

String? _legacyAlertFallback(CoachAlert alert, MessageCopy copy) {
  return switch (alert.kind) {
    CoachAlert.missedExpectedDaysKind => copy.missedExpectedDaysFallback(
        alert.missedCount,
        alert.streakStartDate,
        alert.lastMissedDate,
      ),
    CoachAlert.followUpDueKind => copy.followUpDueFallback(alert.dueOn),
    CoachAlert.stallKind =>
      copy.stalledSessions(alert.stallLength, alert.windowStartDate),
    CoachAlert.deloadRecommendedKind => copy.deloadFallback(
        alert.reason,
        alert.playerDeloadChoice?['choice'],
      ),
    CoachAlert.performanceRegressionKind => copy.performanceRegressionFallback(
        alert.exerciseName,
        alert.e1rmDelta,
        alert.statusBadge,
      ),
    CoachAlert.profileChangeKind => copy.profileChangeEvidence(alert.profileChanges),
    _ => null,
  };
}

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
  final _MessageTemplate? template = _templates[messageCode];
  return template?.call(messageParams, copy) ?? fallback;
}

final Map<String, _MessageTemplate> _templates = <String, _MessageTemplate>{
  'coach_alert.missed_expected_days.v1': _missedDays,
  'coach_alert.follow_up_due.v1': _followUp,
  'coach_alert.stall.v1': _stall,
  'coach_alert.deload_recommended.v1': _deload,
  'coach_alert.performance_regression.v1': _regression,
  'coach_alert.profile_change.v1': _profileChange,
};

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
