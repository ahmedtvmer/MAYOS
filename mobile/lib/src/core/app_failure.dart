/// Stable identifiers for failures authored by the app or its client layers.
/// API detail fields remain unchanged; structured metadata resolves separately.
enum AppFailureId {
  cannotReachService,
  serviceUnavailable,
  requestFailed,
  serviceRejected,
  mutationNeedsConnection,
  invalidServiceData,
  recoveryEmailNotConfirmed,
  programVersionMismatch,
  coachProgramChanged,
  invalidCheckInData,
  invalidAssignmentNotices,
  invalidProgramRequestData,
  invalidProfileData,
  invalidTrainingScheduleData,
  profileUpdateRequired,
  draftNotSignedIn,
  draftUnavailable,
  draftMustBeSynced,
  unexpectedSyncStatus,
  googleUseWebButton,
  googleNotConfigured,
  googleUnavailable,
  googleFailed,
  googleMissingToken,
  googleCannotReach,
  googleDeleteCancelled,
  passwordResetFallback,
  chatAccountNotSignedIn,
  chatReconnectRetry,
  assistantDidNotFinish,
  clearingHistoryNeedsConnection,
}

/// A typed app-authored message, with its exact English rendering retained.
final class AppFailureMessage extends FailureMessage {
  const AppFailureMessage(
    this.id,
    this.englishMessage, {
    this.value,
  });

  final AppFailureId id;
  final String englishMessage;
  final int? value;

  static AppFailureMessage? fromStored({
    required String? id,
    required String? englishMessage,
    int? value,
  }) {
    if (id == null || englishMessage == null) return null;
    for (final AppFailureId candidate in AppFailureId.values) {
      if (candidate.name == id) {
        return AppFailureMessage(candidate, englishMessage, value: value);
      }
    }
    return null;
  }
}

/// Server details remain the English fallback; codes, never detail text, select
/// supported translations.
final class ServerFailureMessage extends FailureMessage {
  const ServerFailureMessage(
    this.detail, {
    this.messageCode,
    this.messageParams,
    this.messageFallback,
  });

  final String detail;
  final String? messageCode;
  final Map<String, dynamic>? messageParams;
  final String? messageFallback;

  String get safeEnglishFallback =>
      messageFallback?.trim().isNotEmpty == true
          ? messageFallback!
          : detail;
}

sealed class FailureMessage {
  const FailureMessage();

  String get englishText => switch (this) {
        AppFailureMessage(:final englishMessage) => englishMessage,
        ServerFailureMessage(:final safeEnglishFallback) => safeEnglishFallback,
      };
}
