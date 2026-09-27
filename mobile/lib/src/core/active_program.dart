import 'dart:async';

import 'api_client.dart';
import 'models.dart';
import 'workout_storage.dart';

/// A cache read on the offline path may never block indefinitely.
const Duration kActiveProgramCacheTimeout = Duration(seconds: 3);

/// The active program plus whether it was served from the offline cache after a
/// failed fetch. [program] is null only when the account genuinely has none.
class ActiveProgram {
  const ActiveProgram({required this.program, required this.fromCache});

  final TrainingProgram? program;

  /// True only when the online fetch failed and [program] is the cached copy —
  /// never merely because a cache exists alongside a successful fetch.
  final bool fromCache;
}

/// Fetches the active program, caching a successful online result and falling
/// back to the last cached copy when the fetch fails. Home and the Program tab
/// both use this so an offline launch behaves identically (one helper, #54).
///
/// Rethrows the original [ApiException] when offline with nothing cached, so
/// callers keep their existing error state. Caching is fire-and-forget: a slow
/// or failing store must never hide an otherwise-successful online fetch.
Future<ActiveProgram> loadActiveProgram({
  required ApiClient api,
  required WorkoutCacheStore cache,
  required String? accountId,
}) async {
  try {
    final TrainingProgram? online = await api.activeProgram();
    if (online != null && accountId != null) {
      unawaited(cacheActiveProgram(cache, accountId, online));
    }
    return ActiveProgram(program: online, fromCache: false);
  } on ApiException {
    final TrainingProgram? cached =
        accountId == null ? null : await _readCachedProgram(cache, accountId);
    if (cached == null) {
      rethrow;
    }
    return ActiveProgram(program: cached, fromCache: true);
  }
}

/// Best-effort cache write: a slow or failing store must never affect a
/// successful online fetch (ADR 020/033).
Future<void> cacheActiveProgram(
    WorkoutCacheStore cache, String accountId, TrainingProgram program) async {
  try {
    await cache.writeProgram(accountId, program);
  } on Object {
    // Offline logging simply won't have this program cached; not fatal here.
  }
}

Future<TrainingProgram?> _readCachedProgram(
    WorkoutCacheStore cache, String accountId) async {
  try {
    return await cache
        .readProgram(accountId)
        .timeout(kActiveProgramCacheTimeout);
  } on Object {
    return null;
  }
}
