import '../../../core/active_workout.dart';
import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import 'active_workout_controller.dart';

enum WebWorkoutCommitStatus {
  committed,
  retryable,
  sessionProblem,
  refused,
}

enum WebWorkoutCommitMessage {
  reopenWorkout,
  refreshProgram,
  connection,
  busy,
}

class WebWorkoutCommitResult {
  const WebWorkoutCommitResult(this.status,
      {this.message, this.response, this.messageType, this.failureMessage});

  final WebWorkoutCommitStatus status;
  final String? message;
  final Map<String, dynamic>? response;
  final WebWorkoutCommitMessage? messageType;
  final FailureMessage? failureMessage;
}

/// Owns the web direct-commit policy: durable attempt marking, reconciliation,
/// response classification, and removal after a confirmed commit.
class WebWorkoutCommitter {
  const WebWorkoutCommitter({
    required ApiClient api,
    required ActiveWorkoutController controller,
    this.onCommit,
  })  : _api = api,
        _controller = controller;

  final ApiClient _api;
  final ActiveWorkoutController _controller;
  final Future<void> Function(String accountId, Map<String, dynamic> response)?
      onCommit;

  Future<WebWorkoutCommitResult> save({
    required ActiveWorkout workout,
    required String timezone,
    required DateTime now,
    required String performedDate,
    required int readiness,
    required String notes,
  }) async {
    try {
      final ActiveWorkout current = await _controller.ensureClientSessionId();
      if (current.id != workout.id || current.accountId != workout.accountId) {
        return const WebWorkoutCommitResult(
          WebWorkoutCommitStatus.sessionProblem,
          message: 'Reopen this workout and try saving again.',
          messageType: WebWorkoutCommitMessage.reopenWorkout,
        );
      }
      final Map<String, dynamic>? body = current.buildCommitBody(
        timezone: timezone,
        now: now,
        performedDate: performedDate,
        readiness: readiness,
        notes: notes,
      );
      if (body == null) {
        return const WebWorkoutCommitResult(
          WebWorkoutCommitStatus.sessionProblem,
          message: 'Refresh your program before saving this workout.',
          messageType: WebWorkoutCommitMessage.refreshProgram,
        );
      }

      if (current.commitAttempted) {
        final Map<String, dynamic>? existing =
            await _api.sessionByClientId(current.clientSessionId!);
        if (existing != null) {
          await onCommit?.call(workout.accountId, existing);
          await _removeCommittedWorkout(current);
          return WebWorkoutCommitResult(
            WebWorkoutCommitStatus.committed,
            response: existing,
          );
        }
      } else {
        await _controller.markCommitAttempted(
          accountId: current.accountId,
          workoutId: current.id,
        );
      }

      final WorkoutCommitResult result = await _api.commitWorkoutSession(body);
      await onCommit?.call(workout.accountId, result.body);
      await _removeCommittedWorkout(current);
      return WebWorkoutCommitResult(
        WebWorkoutCommitStatus.committed,
        response: result.body,
      );
    } on ApiException catch (error) {
      return _classify(error);
    } on Object {
      return const WebWorkoutCommitResult(
        WebWorkoutCommitStatus.retryable,
        message: "Couldn't reach MAYOS. Your workout is kept in this browser.",
        messageType: WebWorkoutCommitMessage.connection,
      );
    }
  }

  Future<void> _removeCommittedWorkout(ActiveWorkout workout) =>
      _controller.discard(
        accountId: workout.accountId,
        workoutId: workout.id,
      );

  WebWorkoutCommitResult _classify(ApiException error) {
    final int? status = error.statusCode;
    if (isNetworkFailure(error) ||
        status == 408 ||
        status == 429 ||
        status! >= 500) {
      return WebWorkoutCommitResult(
        WebWorkoutCommitStatus.retryable,
        message: status == null || status == 408
            ? "Couldn't reach MAYOS. Your workout is kept in this browser."
            : 'MAYOS is busy. Your workout is kept in this browser.',
        messageType: status == null || status == 408
            ? WebWorkoutCommitMessage.connection
            : WebWorkoutCommitMessage.busy,
      );
    }
    if (status == 401 || status == 403) {
      return WebWorkoutCommitResult(
        WebWorkoutCommitStatus.sessionProblem,
        message: error.message,
        failureMessage: apiFailureMessage(error),
      );
    }
    return WebWorkoutCommitResult(
      WebWorkoutCommitStatus.refused,
      message: error.message,
      failureMessage: apiFailureMessage(error),
    );
  }
}
