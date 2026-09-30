import '../../../core/api_client.dart';
import '../../../core/active_program.dart';
import '../../../core/models.dart';
import '../../../core/workout_storage.dart';

enum ProgramAuthorityRoute {
  unavailable,
  inconsistent,
  unchanged,
  player,
  coach
}

/// A refusal from a program mutation means the cached authority may be stale.
/// Both Program and the logger refresh through this helper before routing to
/// the authority that the server now reports.
class ProgramAuthorityRecovery {
  const ProgramAuthorityRecovery({
    required this.api,
    required this.cache,
    required this.accountId,
  });

  final ApiClient api;
  final WorkoutCacheStore cache;
  final String? accountId;

  static bool isRefusal(ApiException error) =>
      error.errorCode == 'player_controls_program' ||
      error.errorCode == 'coach_controlled';

  static ProgramAuthorityRoute routeAfterRefusal(
    ProgramAuthorityRefresh refresh, {
    required bool previousPlayerControlsProgram,
  }) {
    final TrainingProgram? program = refresh.program;
    if (program == null) return ProgramAuthorityRoute.unavailable;
    if (!refresh.authorityMatchesRefusal) {
      return ProgramAuthorityRoute.inconsistent;
    }
    if (program.playerControlsProgram == previousPlayerControlsProgram) {
      return ProgramAuthorityRoute.unchanged;
    }
    return program.playerControlsProgram
        ? ProgramAuthorityRoute.player
        : ProgramAuthorityRoute.coach;
  }

  Future<ProgramAuthorityRefresh> refreshAfterRefusal(
    ApiException error,
  ) async {
    final TrainingProgram? program = await api.activeProgram();
    if (program != null && accountId != null) {
      await cacheActiveProgram(cache, accountId!, program);
    }
    return ProgramAuthorityRefresh(
      program: program,
      authorityMatchesRefusal: program != null &&
          program.playerControlsProgram ==
              (error.errorCode == 'player_controls_program'),
    );
  }
}

class ProgramAuthorityRefresh {
  const ProgramAuthorityRefresh({
    required this.program,
    required this.authorityMatchesRefusal,
  });

  final TrainingProgram? program;
  final bool authorityMatchesRefusal;
}
