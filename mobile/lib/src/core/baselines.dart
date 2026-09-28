import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'models.dart';
import 'secure_store.dart';

/// Exercise baselines for the device's frozen Active workout (#122/#123):
/// `GET /workouts/baselines`, one row per exercise with a committed working set.
///
/// The wire shape mirrors `svc/schemas.py` `BaselinesOut`; effort at the
/// display boundary is RIR (`10 - RPE`, null when unrated, #111).
class BaselineExercise {
  const BaselineExercise({
    required this.exerciseId,
    required this.sessionsLogged,
    required this.maxWeightKg,
    required this.bestE1rmKg,
    required this.lastSession,
  });

  factory BaselineExercise.fromJson(Map<String, dynamic> json) =>
      BaselineExercise(
        exerciseId: json['exercise_id'] as String,
        sessionsLogged: (json['sessions_logged'] as num?)?.toInt() ?? 0,
        maxWeightKg: (json['max_weight_kg'] as num?)?.toDouble(),
        bestE1rmKg: (json['best_e1rm_kg'] as num?)?.toDouble(),
        lastSession: BaselineLastSession.fromJson(
            json['last_session'] as Map<String, dynamic>? ??
                const <String, dynamic>{}),
      );

  /// One exercise's identifier in the catalog.
  final String exerciseId;

  /// How many committed sessions logged a working set for this exercise.
  final int sessionsLogged;

  /// Heaviest working-set weight (ADR 042), or null when none is known.
  final double? maxWeightKg;

  /// Best working-set e1RM (ADR 042), or null when none is known.
  final double? bestE1rmKg;

  /// The latest committed session's working sets, in logged order.
  final BaselineLastSession lastSession;

  BaselineExercise copyWith({
    int? sessionsLogged,
    double? maxWeightKg,
    double? bestE1rmKg,
    BaselineLastSession? lastSession,
  }) =>
      BaselineExercise(
        exerciseId: exerciseId,
        sessionsLogged: sessionsLogged ?? this.sessionsLogged,
        maxWeightKg: maxWeightKg ?? this.maxWeightKg,
        bestE1rmKg: bestE1rmKg ?? this.bestE1rmKg,
        lastSession: lastSession ?? this.lastSession,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise_id': exerciseId,
        'sessions_logged': sessionsLogged,
        'max_weight_kg': maxWeightKg,
        'best_e1rm_kg': bestE1rmKg,
        'last_session': lastSession.toJson(),
      };
}

/// `BaselineLastSessionOut`: the latest committed session's date and working sets.
class BaselineLastSession {
  const BaselineLastSession({required this.performedDate, required this.sets});

  factory BaselineLastSession.fromJson(Map<String, dynamic> json) =>
      BaselineLastSession(
        performedDate: json['performed_date'] as String? ?? '',
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic s) =>
                BaselineSet.fromJson(s as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String performedDate;
  final List<BaselineSet> sets;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'performed_date': performedDate,
        'sets': <Map<String, dynamic>>[
          for (final BaselineSet set in sets) set.toJson(),
        ],
      };
}

/// `BaselineSetOut`: one working set of a baseline's last session.
class BaselineSet {
  const BaselineSet({required this.weightKg, required this.reps, this.rir});

  factory BaselineSet.fromJson(Map<String, dynamic> json) => BaselineSet(
        weightKg: (json['weight_kg'] as num?)?.toDouble() ?? 0,
        reps: (json['reps'] as num?)?.toInt() ?? 0,
        rir: (json['rir'] as num?)?.toDouble(),
      );

  final double weightKg;
  final int reps;

  /// Reps in reserve at the display boundary; null when the set is unrated.
  final double? rir;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'weight_kg': weightKg,
        'reps': reps,
        'rir': rir,
      };
}

/// The server's single working-set definition (`WORKING_SET_PREDICATE`,
/// database/ledger/workouts.py): not a warm-up, and a weight and a rep count
/// that are actually there.
bool isWorkingSet({
  required bool isWarmup,
  required double weightKg,
  required int reps,
}) =>
    !isWarmup && weightKg > 0 && reps > 0;

/// The server's `calculate_e1rm` (agent/progression_engine.py): Epley adjusted
/// for effort, with the RPE clamped to [6, 10].
double calculateE1rm({
  required double weightKg,
  required int reps,
  required double rpe,
}) {
  if (reps <= 0 || weightKg <= 0) {
    return 0.0;
  }
  final double clamped = rpe < 6.0 ? 6.0 : (rpe > 10.0 ? 10.0 : rpe);
  final double effectiveReps = reps + (10.0 - clamped);
  return weightKg * (1.0 + (effectiveReps / 30.0));
}

/// The server's `set_e1rm` in RIR terms: RIR = 10 - RPE at the boundary, and
/// an unrated set keeps the server's RPE 8.5 default.
double setE1rm({
  required double weightKg,
  required int reps,
  required double? rir,
}) =>
    calculateE1rm(
      weightKg: weightKg,
      reps: reps,
      rpe: rir == null ? 8.5 : 10.0 - rir,
    );

/// Two decimals, the precision the record aggregates and the API report use.
double round2(double value) => double.parse(value.toStringAsFixed(2));

/// Effort at the display boundary for a committed `rpe` (`_to_rir` in
/// service/workouts.py): null only when the set carries no rating.
double? rirFromRpe(double? rpe) =>
    rpe == null ? null : round2(10.0 - rpe);

/// The `rpe` a draft sends for an RIR-logged set: the inverse of [rirFromRpe],
/// with the logger's unrated default of 8.5 and the service's accepted range
/// [6, 10] enforced so a commit can never be refused for its effort value.
double rpeFromRir(double? rir) {
  if (rir == null) {
    return 8.5;
  }
  final double rpe = 10.0 - rir;
  return rpe < 6.0 ? 6.0 : (rpe > 10.0 ? 10.0 : rpe);
}

/// Folds the player's unsynced Workout drafts into the server baselines using
/// the server's aggregate rules, so the frozen Active-workout baseline counts
/// what this device has already logged but not yet committed (#123).
///
/// For every unsynced, non-skipped draft exercise with at least one working
/// set ([isWorkingSet]): `sessions_logged` gains one session, the maxima take
/// the draft's heavier weight and better e1RM (rounded to 2 dp), and
/// `last_session` becomes the draft's working sets when that session is the
/// latest — newest by started time, dates compared first, with a not-yet-
/// committed draft winning a same-day tie against a committed session (its
/// `captured_at` is a real timestamp inside that day, while the committed
/// session only carries a date).
List<BaselineExercise> foldDraftsIntoBaselines({
  required List<BaselineExercise> baselines,
  required Iterable<WorkoutDraft> drafts,
}) {
  final Map<String, BaselineExercise> byExercise =
      <String, BaselineExercise>{
    for (final BaselineExercise baseline in baselines)
      baseline.exerciseId: baseline,
  };
  // Committed baseline rows only carry a date; a folded draft's start time is
  // remembered so two drafts on the same date still order by started time.
  final Map<String, DateTime?> latestStartedAt = <String, DateTime?>{};

  for (final WorkoutDraft draft in drafts) {
    if (draft.isSynced) {
      continue;
    }
    final DateTime? startedAt = _parseTime(draft.capturedAt) ??
        _parseTime(draft.updatedAt);
    for (final DraftExercise exercise in draft.exercises) {
      if (exercise.skipped) {
        continue;
      }
      final List<WorkoutSetLog> working = <WorkoutSetLog>[
        for (final WorkoutSetLog set in exercise.sets)
          if (isWorkingSet(
            isWarmup: set.isWarmup,
            weightKg: set.weightKg,
            reps: set.reps,
          ))
            set,
      ];
      if (working.isEmpty) {
        continue;
      }
      double maxWeight = 0;
      double bestE1rm = 0;
      for (final WorkoutSetLog set in working) {
        final double weight = round2(set.weightKg);
        if (weight > maxWeight) {
          maxWeight = weight;
        }
        final double e1rm = setE1rm(
          weightKg: set.weightKg,
          reps: set.reps,
          rir: rirFromRpe(set.rpe),
        );
        if (e1rm > bestE1rm) {
          bestE1rm = e1rm;
        }
      }
      final BaselineLastSession draftSession = BaselineLastSession(
        performedDate: draft.performedDate,
        sets: <BaselineSet>[
          for (final WorkoutSetLog set in working)
            BaselineSet(
              weightKg: set.weightKg,
              reps: set.reps,
              rir: rirFromRpe(set.rpe),
            ),
        ],
      );
      final String exerciseId = exercise.exerciseId;
      final BaselineExercise? current = byExercise[exerciseId];
      if (current == null) {
        byExercise[exerciseId] = BaselineExercise(
          exerciseId: exerciseId,
          sessionsLogged: 1,
          maxWeightKg: round2(maxWeight),
          bestE1rmKg: round2(bestE1rm),
          lastSession: draftSession,
        );
        latestStartedAt[exerciseId] = startedAt;
        continue;
      }
      final bool draftIsLatest = _isLaterSession(
        date: draftSession.performedDate,
        startedAt: startedAt,
        thanDate: current.lastSession.performedDate,
        thanStartedAt: latestStartedAt[exerciseId],
      );
      if (draftIsLatest) {
        latestStartedAt[exerciseId] = startedAt;
      }
      byExercise[exerciseId] = current.copyWith(
        sessionsLogged: current.sessionsLogged + 1,
        maxWeightKg: _maxOrNull(current.maxWeightKg, round2(maxWeight)),
        bestE1rmKg: _maxOrNull(current.bestE1rmKg, round2(bestE1rm)),
        lastSession: draftIsLatest ? draftSession : current.lastSession,
      );
    }
  }

  return byExercise.values.toList(growable: false);
}

double? _maxOrNull(double? current, double candidate) =>
    current == null ? candidate : (candidate > current ? candidate : current);

/// True when the session at [date]/[startedAt] comes after
/// [thanDate]/[thanStartedAt].
///
/// ISO dates compare correctly as strings. A session that carries a started
/// time wins a same-day tie against one that only carries a date (a committed
/// baseline row never has a time), and equal dates with no times keep the
/// incumbent so the fold is order-independent.
bool _isLaterSession({
  required String date,
  required DateTime? startedAt,
  required String thanDate,
  required DateTime? thanStartedAt,
}) {
  if (date != thanDate) {
    return date.compareTo(thanDate) > 0;
  }
  if (startedAt == null || thanStartedAt == null) {
    return startedAt != null && thanStartedAt == null;
  }
  return startedAt.isAfter(thanStartedAt);
}

DateTime? _parseTime(String? iso) =>
    iso == null || iso.isEmpty ? null : DateTime.tryParse(iso);

/// Device cache of the last successful `GET /workouts/baselines`, keyed by the
/// immutable account id so two accounts sharing a device never read each
/// other's baselines (#123).
abstract class BaselineCacheStore {
  /// The last successful fetch, or null when this account never fetched one —
  /// null (cache miss) and an empty list (fetched, no baselines yet) are
  /// different states for the workout-start fallback.
  Future<List<BaselineExercise>?> read(String accountId);

  Future<void> write(String accountId, List<BaselineExercise> baselines);

  Future<void> deleteForAccount(String accountId);
}

class SecureBaselineCacheStore implements BaselineCacheStore {
  SecureBaselineCacheStore({FlutterSecureStorage? storage})
      : _store = SecureStore(storage: storage);

  final SecureStore _store;

  static String _key(String accountId) => 'baselines.$accountId';

  @override
  Future<List<BaselineExercise>?> read(String accountId) async {
    final dynamic decoded = await _store.readJson(_key(accountId));
    if (decoded == null) {
      return null;
    }
    if (decoded is! List<dynamic>) {
      return null;
    }
    try {
      return decoded
          .map((dynamic item) =>
              BaselineExercise.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  @override
  Future<void> write(String accountId, List<BaselineExercise> baselines) =>
      _store.writeJson(key: _key(accountId), value: <Map<String, dynamic>>[
        for (final BaselineExercise baseline in baselines) baseline.toJson(),
      ]);

  @override
  Future<void> deleteForAccount(String accountId) =>
      _store.deleteExactOrPrefixed(_key(accountId), '${_key(accountId)}.');
}

/// In-memory fake for tests. Sharing one instance across provider containers
/// simulates an app restart reading the same protected storage.
class InMemoryBaselineCacheStore implements BaselineCacheStore {
  final Map<String, List<BaselineExercise>> _byAccount =
      <String, List<BaselineExercise>>{};

  @override
  Future<List<BaselineExercise>?> read(String accountId) async =>
      _byAccount[accountId];

  @override
  Future<void> write(String accountId, List<BaselineExercise> baselines) async {
    _byAccount[accountId] = List<BaselineExercise>.of(baselines);
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    _byAccount.remove(accountId);
  }
}
