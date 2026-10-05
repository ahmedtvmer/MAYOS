import '../models.dart';
import 'message_copy.dart';
import 'message_resolution.dart';

export 'message_resolution.dart' show resolveStructuredMessage;

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
  if (alert.isWeightOffTargetTrend && alert.weightPoints != null) {
    final List<String> evidence = alert.weightPoints!
        .map((WeightTrendPoint point) =>
            copy.weightTrendPoint(point.date, _messageNumber(point.weightKg)))
        .toList(growable: false);
    return '$description\n'
        '${copy.weightTrendEvidence(evidence, alert.targetWeightKg)}';
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
    CoachAlert.weightOffTargetTrendKind => alert.distanceChangeKg == null ||
            alert.targetWeightKg == null ||
            alert.windowDays == null ||
            alert.thresholdKg == null
        ? alert.messageFallback
        : copy.weightOffTargetTrend(
            alert.distanceChangeKg!,
            alert.targetWeightKg!,
            alert.windowDays!,
            alert.thresholdKg!),
    _ => null,
  };
}

String _messageNumber(double value) {
  final String fixed = value.toStringAsFixed(1);
  return fixed.endsWith('.0') ? fixed.substring(0, fixed.length - 2) : fixed;
}
