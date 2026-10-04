import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'effort.dart';
import 'models.dart';
import 'secure_store.dart';

export 'effort.dart' show rirFromRpe, round2;

/// Exercise baselines for the device's frozen Active workout (#122/#123):
/// `GET /workouts/baselines`, previous performance and strict record aggregates.
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

  /// The latest non-warm-up sets with reps at any load, in logged order.
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

/// The latest committed previous-performance session and its sets.
class BaselineLastSession {
  const BaselineLastSession({required this.performedDate, required this.sets});

  factory BaselineLastSession.fromJson(Map<String, dynamic> json) =>
      BaselineLastSession(
        performedDate: json['performed_date'] as String? ?? '',
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic s) => BaselineSet.fromJson(s as Map<String, dynamic>))
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

/// `BaselineSetOut`: one non-warm-up set with reps from a previous session.
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

/// One clamp, two bands: [low]..[high].
double _clamp(double value, double low, double high) =>
    value < low ? low : (value > high ? high : value);

/// The service's accepted RPE band (#111): RPE 5–10 is RIR 5–0. Guards the
/// `rpe` a draft serializes so a commit can never be refused for its effort
/// value, and the target-to-RIR conversions at the display boundary.
double clampRpe(double rpe) => _clamp(rpe, 5.0, 10.0);

/// The e1RM formula's own effort clamp: `calculate_e1rm` in
/// agent/progression_engine.py reads `min(max(rpe, 6.0), 10.0)`, so an effort
/// below RPE 6 scores exactly like RPE 6 — this is the formula, not the
/// accepted input band (#111). Shares [_clamp] with [clampRpe].
double _formulaRpe(double rpe) => _clamp(rpe, 6.0, 10.0);

/// The server's `calculate_e1rm` (agent/progression_engine.py): Epley adjusted
/// for effort, with the formula's RPE term clamped to [6, 10].
double calculateE1rm({
  required double weightKg,
  required int reps,
  required double rpe,
}) {
  if (reps <= 0 || weightKg <= 0) {
    return 0.0;
  }
  final double clamped = _formulaRpe(rpe);
  final double effectiveReps = reps + (10.0 - clamped);
  return weightKg * (1.0 + (effectiveReps / 30.0));
}

/// The server's `set_e1rm` in RIR terms: RIR = 10 - RPE at the boundary, and
/// an unrated set is plain Epley — `w * (1 + reps / 30)`, exactly RPE 10 /
/// RIR 0 (#111), never a default effort.
///
/// Note that [calculateE1rm] clamps its effort term at RPE 6, so a set logged
/// RIR 5 (or anything above RIR 4) scores exactly like RIR 4. That is the
/// formula, not this helper's business: it is left unchanged here.
double setE1rm({
  required double weightKg,
  required int reps,
  required double? rir,
}) =>
    calculateE1rm(
      weightKg: weightKg,
      reps: reps,
      // The one RIR→RPE inverse, shared with the draft payload; unrated is
      // RPE 10 (plain Epley). Out-of-band RIRs clamp identically once
      // calculateE1rm applies its own [6, 10] formula band.
      rpe: rpeFromRir(rir) ?? 10.0,
    );

/// The `rpe` a draft sends for an RIR-logged set: the inverse of [rirFromRpe].
///
/// Unrated sends null — the service's optional effort (#111) — and a rating
/// sends `10 - rir` inside the accepted RPE 5–10 band, so RIR 5 lands as RPE 5
/// rather than being clamped up to the old floor of 6.
double? rpeFromRir(double? rir) =>
    rir == null ? null : clampRpe(10.0 - rir);

/// Whether a draft's working sets will reach the ledger exactly as they stand
/// (#123 item 9).
///
/// - `pending` / `syncing` are on their way to a commit (or mid-commit), so
///   folding them counts this device's uncommitted work that is about to land.
/// - `synced` is already in the server rows the fold starts from, so folding
///   it again would double-count it.
/// - `needs_reconciliation` was refused with a 4xx and is *not* retried
///   automatically: the player must retry or discard it (ADR 033). As-is it
///   will not commit, so folding it would show a PREVIOUS set (and a session
///   count) that history will never contain. The Drafts screen keeps offering
///   it; once it is edited or re-driven it becomes `pending` and folds then.
bool draftWillCommit(WorkoutDraft draft) =>
    draft.status == DraftStatus.pending || draft.status == DraftStatus.syncing;

/// Folds unsynced drafts into previous performance and record baselines (#123).
///
/// Only [draftWillCommit] drafts are folded.
///
/// Previous performance accepts non-warm-up sets with reps at any load.
/// `sessions_logged` and the maxima still accept only weighted working sets
/// ([isWorkingSet]), matching the server's record baseline.
///
/// "Latest" mirrors the server's `LAST_SESSION_ORDER`
/// (`database/ledger/workouts.py`: `started_at DESC, rowid DESC`), **not** the
/// performed date: a session is ordered by its start instant, so an ADR 035
/// performed-date correction can never reorder it differently here than on the
/// server. A draft carries a real capture instant; a committed baseline row
/// carries only its performed date, which stands in for its start instant as
/// that date's midnight. When both sides land on the same instant the
/// incumbent wins, so a not-yet-committed draft beats a committed session only
/// when it really started later, and the fold stays order-independent.
List<BaselineExercise> foldDraftsIntoBaselines({
  required List<BaselineExercise> baselines,
  required Iterable<WorkoutDraft> drafts,
}) {
  final Map<String, BaselineExercise> byExercise = <String, BaselineExercise>{
    for (final BaselineExercise baseline in baselines)
      baseline.exerciseId: baseline,
  };
  // Committed baseline rows only carry a date; a folded draft's start time is
  // remembered so two drafts on the same date still order by started time.
  final Map<String, DateTime?> latestStartedAt = <String, DateTime?>{};

  for (final WorkoutDraft draft in drafts) {
    if (!draftWillCommit(draft)) {
      continue;
    }
    final DateTime? startedAt =
        _parseTime(draft.capturedAt) ?? _parseTime(draft.updatedAt);
    for (final DraftExercise exercise in draft.exercises) {
      if (exercise.skipped) {
        continue;
      }
      final List<WorkoutSetLog> previousPerformance = <WorkoutSetLog>[
        for (final WorkoutSetLog set in exercise.sets)
          if (!set.isWarmup && set.reps > 0) set,
      ];
      if (previousPerformance.isEmpty) {
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
          for (final WorkoutSetLog set in previousPerformance)
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
          sessionsLogged: working.isEmpty ? 0 : 1,
          maxWeightKg: working.isEmpty ? null : round2(maxWeight),
          bestE1rmKg: working.isEmpty ? null : round2(bestE1rm),
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
        sessionsLogged: current.sessionsLogged + (working.isEmpty ? 0 : 1),
        maxWeightKg: working.isEmpty
            ? current.maxWeightKg
            : _maxOrNull(current.maxWeightKg, round2(maxWeight)),
        bestE1rmKg: working.isEmpty
            ? current.bestE1rmKg
            : _maxOrNull(current.bestE1rmKg, round2(bestE1rm)),
        lastSession: draftIsLatest ? draftSession : current.lastSession,
      );
    }
  }

  return byExercise.values.toList(growable: false);
}

double? _maxOrNull(double? current, double candidate) =>
    current == null ? candidate : (candidate > current ? candidate : current);

/// True when the session at [date]/[startedAt] comes after
/// [thanDate]/[thanStartedAt], ordered by start instant the way the server's
/// `LAST_SESSION_ORDER` orders sessions (`started_at DESC`).
///
/// A session that carries a start instant is compared on it; one that carries
/// only a date (a committed baseline row exposes just its performed date) is
/// compared on that date at midnight. Equal instants keep the incumbent so the
/// fold is order-independent, except that a real instant beats a bare date at
/// the same moment — the not-yet-committed draft that started inside a
/// committed session's day.
bool _isLaterSession({
  required String date,
  required DateTime? startedAt,
  required String thanDate,
  required DateTime? thanStartedAt,
}) {
  final DateTime start = startedAt ?? _startOfDay(date);
  final DateTime than = thanStartedAt ?? _startOfDay(thanDate);
  if (start.isAfter(than)) {
    return true;
  }
  if (than.isAfter(start)) {
    return false;
  }
  return startedAt != null && thanStartedAt == null;
}

/// A date string (`YYYY-MM-DD`) as that day's local midnight, the stand-in
/// start instant of a committed session that exposes no `started_at`.
DateTime _startOfDay(String date) =>
    DateTime.tryParse(date) ?? DateTime.fromMillisecondsSinceEpoch(0);

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
