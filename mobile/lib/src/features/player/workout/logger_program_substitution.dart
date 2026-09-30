import '../../../core/active_workout.dart';
import '../../../core/active_program.dart';
import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/models.dart';
import '../../../core/workout_storage.dart';
import '../program/program_authority_recovery.dart';

const String loggerProgramVersionChangedMessage =
    'Your program changed since this workout started; substitute it from the Program tab';

class LoggerProgramSwap {
  const LoggerProgramSwap({
    required this.workout,
    required this.program,
    required this.day,
    required this.oldExercise,
    required this.replacement,
    required this.reason,
  });

  final ActiveWorkout workout;
  final TrainingProgram program;
  final ProgramDay day;
  final ActiveWorkoutExercise oldExercise;
  final ExerciseCatalogEntry replacement;
  final String? reason;
}

class LoggerProgramSubstitutionResult {
  const LoggerProgramSubstitutionResult(
    this.message, {
    this.error = false,
    this.program,
    this.coachReasonRequired = false,
  });

  final String message;
  final bool error;
  final TrainingProgram? program;
  final bool coachReasonRequired;
}

/// Applies a logger's optional program action without ever changing its
/// already-replaced Active workout. The stored workout version is the only
/// version this action is allowed to target.
class LoggerProgramSubstitutionController {
  const LoggerProgramSubstitutionController({
    required this.api,
    required this.cache,
    required this.accountId,
  });

  final ApiClient api;
  final WorkoutCacheStore cache;
  final String? accountId;

  Future<LoggerProgramSubstitutionResult> apply(LoggerProgramSwap swap) async {
    if (!_sameWorkoutVersion(swap.program, swap.workout)) {
      return const LoggerProgramSubstitutionResult(
        loggerProgramVersionChangedMessage,
        error: true,
        program: null,
      );
    }
    try {
      return await _applyForAuthority(swap);
    } on ApiException catch (error) {
      if (ProgramAuthorityRecovery.isRefusal(error)) {
        return _recoverAuthority(error, swap);
      }
      return _failure(error);
    }
  }

  bool _sameWorkoutVersion(TrainingProgram program, ActiveWorkout workout) =>
      program.version != null && program.version == workout.programVersion;

  Future<LoggerProgramSubstitutionResult> _applyForAuthority(
    LoggerProgramSwap swap,
  ) async {
    if (!_sameWorkoutVersion(swap.program, swap.workout)) {
      return const LoggerProgramSubstitutionResult(
        loggerProgramVersionChangedMessage,
        error: true,
      );
    }
    if (swap.program.playerControlsProgram) {
      final ProgramSubstitutionResult result =
          await api.substituteProgramExercise(
        dayName: swap.day.dayName,
        exerciseId: swap.oldExercise.exerciseId,
        replacementExerciseId: swap.replacement.id,
        expectedActiveVersion: swap.workout.programVersion,
      );
      if (accountId != null) {
        await cacheActiveProgram(cache, accountId!, result.program);
      }
      return LoggerProgramSubstitutionResult(
        'The swap was saved to your program.',
        program: result.program,
      );
    }
    final String reason = swap.reason?.trim() ?? '';
    if (reason.isEmpty) {
      return LoggerProgramSubstitutionResult(
        'Add a reason before asking your coach.',
        error: true,
        program: swap.program,
      );
    }
    await _createCoachRequest(swap, reason);
    return LoggerProgramSubstitutionResult(
      'Your coach was asked to make this swap permanent.',
      program: swap.program,
    );
  }

  Future<void> _createCoachRequest(LoggerProgramSwap swap, String reason) =>
      api.createPlayerProgramRequest(
        kind: 'exercise_substitution',
        dayName: swap.day.dayName,
        exerciseId: swap.oldExercise.exerciseId,
        replacementExerciseId: swap.replacement.id,
        reason: reason,
      );

  Future<LoggerProgramSubstitutionResult> _recoverAuthority(
    ApiException error,
    LoggerProgramSwap original,
  ) async {
    TrainingProgram? refreshed;
    try {
      final ProgramAuthorityRefresh recovery = await ProgramAuthorityRecovery(
        api: api,
        cache: cache,
        accountId: accountId,
      ).refreshAfterRefusal(error);
      refreshed = recovery.program;
      final ProgramAuthorityRoute route =
          ProgramAuthorityRecovery.routeAfterRefusal(
        recovery,
        previousPlayerControlsProgram: original.program.playerControlsProgram,
      );
      if (refreshed == null ||
          route == ProgramAuthorityRoute.unavailable ||
          route == ProgramAuthorityRoute.inconsistent ||
          route == ProgramAuthorityRoute.unchanged) {
        return _failure(error, program: refreshed);
      }
      if (!_sameWorkoutVersion(refreshed, original.workout)) {
        return LoggerProgramSubstitutionResult(
          loggerProgramVersionChangedMessage,
          error: true,
          program: refreshed,
        );
      }
      final ProgramDay? day = _findDay(refreshed, original.day.dayName);
      if (day == null ||
          !day.exercises.any((ProgramExercise item) =>
              item.exerciseId == original.oldExercise.exerciseId)) {
        return LoggerProgramSubstitutionResult(
          'The program changed. Substitute this exercise from the Program tab.',
          error: true,
          program: refreshed,
        );
      }
      if (route == ProgramAuthorityRoute.coach &&
          (original.reason?.trim().isEmpty ?? true)) {
        return LoggerProgramSubstitutionResult(
          'Your workout swap is saved. Your coach now controls this program. Add a reason to send the request.',
          error: true,
          program: refreshed,
          coachReasonRequired: true,
        );
      }
      return await _applyForAuthority(LoggerProgramSwap(
        workout: original.workout,
        program: refreshed,
        day: day,
        oldExercise: original.oldExercise,
        replacement: original.replacement,
        reason: original.reason,
      ));
    } on ApiException catch (refreshError) {
      return _failure(refreshError, program: refreshed);
    }
  }

  ProgramDay? _findDay(TrainingProgram program, String dayName) {
    for (final ProgramDay day in program.days) {
      if (day.dayName == dayName) return day;
    }
    return null;
  }

  LoggerProgramSubstitutionResult _failure(
    ApiException error, {
    TrainingProgram? program,
  }) {
    if (error.statusCode == 409) {
      return const LoggerProgramSubstitutionResult(
        loggerProgramVersionChangedMessage,
        error: true,
        program: null,
      );
    }
    return LoggerProgramSubstitutionResult(
      mutationFailureMessage(error),
      error: true,
      program: program,
    );
  }
}
