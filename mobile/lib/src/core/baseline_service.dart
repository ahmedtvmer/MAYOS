import 'api_client.dart';
import 'baselines.dart';
import 'models.dart';
import 'workout_storage.dart';

/// Where a workout-start baseline set came from (#123).
enum BaselineSource {
  /// The fresh fetch inside the short start timeout.
  fresh,

  /// The device cache from an earlier successful fetch.
  cache,

  /// Neither a fetch nor a cache: no baselines at all.
  empty,
}

/// The baselines resolved for a workout start, plus how they were obtained.
class BaselineResolution {
  const BaselineResolution(this.baselines, this.source);

  final List<BaselineExercise> baselines;
  final BaselineSource source;
}

/// Reads `GET /workouts/baselines` for the two moments the app needs it:
/// the Home prefetch (fire-and-forget, cached on success) and the workout
/// start that freezes the result into the Active workout.
///
/// The start resolution is fresh fetch with a short timeout → the per-account
/// cache → empty, with the player's unsynced Workout drafts folded in either
/// way, so this device's uncommitted working sets already count (#123).
class BaselinesService {
  BaselinesService({
    required ApiClient api,
    required BaselineCacheStore cache,
    required DraftStore drafts,
    this.freshTimeout = const Duration(seconds: 5),
  })  : _api = api,
        _cache = cache,
        _drafts = drafts;

  final ApiClient _api;
  final BaselineCacheStore _cache;
  final DraftStore _drafts;

  /// How long a fresh fetch may take before the cache is used instead.
  final Duration freshTimeout;

  /// Fire-and-forget Home prefetch: fetches and caches, and never throws, so
  /// a failed prefetch can never affect Home.
  Future<void> prefetch(String accountId) async {
    try {
      final List<BaselineExercise> rows = await _api.baselines();
      await _cache.write(accountId, rows);
    } on Object {
      // Best-effort: the workout-start path falls back to the cache anyway.
    }
  }

  /// Resolves the baseline to freeze at workout start: a fresh fetch inside
  /// [freshTimeout], otherwise the cache, otherwise empty — always with the
  /// account's unsynced, still-committing drafts folded in.
  Future<BaselineResolution> resolveForStart(String accountId) async {
    List<BaselineExercise>? fresh;
    try {
      // One overall deadline for the whole request (connect *and* receive),
      // so a stuck handshake falls back to the cache too (#123 item 8).
      fresh = await _api
          .baselines(receiveTimeout: freshTimeout)
          .timeout(freshTimeout);
      try {
        await _cache.write(accountId, fresh);
      } on Object {
        // A cache failure must not lose the fresh result.
      }
    } on Object {
      fresh = null;
    }
    List<BaselineExercise>? cached;
    if (fresh == null) {
      try {
        cached = await _cache.read(accountId);
      } on Object {
        cached = null;
      }
    }
    final List<BaselineExercise> base =
        fresh ?? cached ?? const <BaselineExercise>[];
    final BaselineSource source = fresh != null
        ? BaselineSource.fresh
        : (cached != null ? BaselineSource.cache : BaselineSource.empty);

    List<WorkoutDraft> drafts = const <WorkoutDraft>[];
    try {
      drafts = await _drafts.read(accountId);
    } on Object {
      drafts = const <WorkoutDraft>[];
    }
    // `foldDraftsIntoBaselines` keeps only the drafts that will commit
    // (#123 item 9), so a refused `needs_reconciliation` draft never shows a
    // previous set history will not contain.
    final List<BaselineExercise> folded =
        foldDraftsIntoBaselines(baselines: base, drafts: drafts);
    return BaselineResolution(folded, source);
  }
}
