/// Stable identifiers for failures authored by the app or its client layers.
/// API `detail` strings use [ServerFailureMessage] instead and stay untouched.
enum AppFailureId {
  cannotReachService,
  serviceUnavailable,
  requestFailed,
  serviceRejected,
  mutationNeedsConnection,
  invalidServiceData,
  recoveryEmailNotConfirmed,
  programVersionMismatch,
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

/// Server details are displayed verbatim and never looked up by their text.
final class ServerFailureMessage extends FailureMessage {
  const ServerFailureMessage(this.detail);

  final String detail;
}

sealed class FailureMessage {
  const FailureMessage();

  String get englishText => switch (this) {
        AppFailureMessage(:final englishMessage) => englishMessage,
        ServerFailureMessage(:final detail) => detail,
      };
}
