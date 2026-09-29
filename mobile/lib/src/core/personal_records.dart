import 'package:flutter/foundation.dart' show immutable;

import 'active_workout.dart';
import 'baselines.dart';

/// The two exercise-wide records a player is told about (ADR 042, #124):
/// heaviest working-set weight and best working-set e1RM.
enum PrRecordKind {
  /// Heaviest weight, any rep count.
  weight,

  /// Best e1RM, by the server's `set_e1rm` formula.
  e1rm;

  /// The badge text: `PR kg` / `PR e1RM` (#107 resolution, #124).
  String get badgeLabel => this == PrRecordKind.weight ? 'PR kg' : 'PR e1RM';

  /// The `PR … ` before the value in a celebration line: `PR 140 kg` for a
  /// heaviest-weight record, `PR e1RM 112.5 kg` for an e1RM one (#124).
  String get celebrationPrefix =>
      this == PrRecordKind.weight ? 'PR ' : 'PR e1RM ';

  /// The value this record tracks for one set row: the row's weight for
  /// [weight], its e1RM by the server's `set_e1rm` for [e1rm].
  double valueOf(ActiveWorkoutSet set) => this == PrRecordKind.weight
      ? set.weightKg
      : setE1rm(weightKg: set.weightKg, reps: set.reps, rir: set.rir);
}

/// `140`, `112.5`, `139.3` — how a record value reads in the celebration:
/// at most one decimal, a trailing `.0` dropped, so the issue's examples read
/// `140 kg` and `112.5 kg` rather than `140.0 kg`.
String formatRecordKg(double value) {
  final double tenth = (value * 10).round() / 10;
  return tenth == tenth.roundToDouble() ? tenth.round().toString() : '$tenth';
}

/// What one set row earned: the records it still holds solidly (it is the
/// session's current best) and the records a later set of the same exercise
/// has since beaten (kept, struck through and muted, #107 resolution).
@immutable
class SetRecordBadges {
  const SetRecordBadges({
    this.current = const <PrRecordKind>{},
    this.beaten = const <PrRecordKind>{},
  });

  /// Records this row holds as the session's current best — the solid badge.
  final Set<PrRecordKind> current;

  /// Records this row once held and a later row took over — struck through.
  final Set<PrRecordKind> beaten;

  bool get isEmpty => current.isEmpty && beaten.isEmpty;

  @override
  bool operator ==(Object other) =>
      other is SetRecordBadges &&
      other.current.length == current.length &&
      other.current.containsAll(current) &&
      other.beaten.length == beaten.length &&
      other.beaten.containsAll(beaten);

  @override
  int get hashCode => Object.hash(
        Object.hashAll(current),
        Object.hashAll(beaten),
      );
}

/// The record calculator of #124: one exercise's set rows against its frozen
/// baseline → the badge state of every row, keyed by [ActiveWorkoutSet.id].
///
/// Pure and total — recompute it after any change (tick, untick, edit, delete)
/// and it reproduces the badges from the persisted rows alone, so badge state
/// is part of the Active workout and survives a restart without being stored.
///
/// Rules (ADR 042, #124):
/// - No baseline row, `sessions_logged == 0`, or a baseline missing either
///   aggregate (the server's own first-session guard) → no badges at all.
/// - Only ticked working sets are considered: warm-ups and unticked rows
///   never earn a badge.
/// - A record needs a strict improvement over the baseline (`ties are not
///   records`), rounded to 2 dp exactly like the server compares.
/// - Within the session, rows are walked in row order; a row that strictly
///   beats the running best takes the solid badge and hands the previous
///   holder a struck-through one. A row that merely ties never takes over.
Map<String, SetRecordBadges> exerciseRecordBadges({
  required List<ActiveWorkoutSet> sets,
  required BaselineExercise? baseline,
}) {
  final Map<String, SetRecordBadges> badges = <String, SetRecordBadges>{};
  if (baseline == null || baseline.sessionsLogged == 0) {
    return badges;
  }
  final double? baselineWeight = baseline.maxWeightKg;
  final double? baselineE1rm = baseline.bestE1rmKg;
  if (baselineWeight == null || baselineE1rm == null) {
    // The exercise's first committed session is its baseline, not a record
    // (`evaluate_session_prs` returns nothing until both aggregates exist).
    return badges;
  }
  double bestWeight = baselineWeight;
  double bestE1rm = baselineE1rm;
  String? holderWeight;
  String? holderE1rm;

  for (final ActiveWorkoutSet set in sets) {
    if (!set.ticked || !set.countsAsWorkingSet) {
      continue;
    }
    final double weight = round2(set.weightKg);
    if (weight > bestWeight) {
      if (holderWeight != null) {
        _hold(badges, holderWeight, PrRecordKind.weight, solid: false);
      }
      holderWeight = set.id;
      bestWeight = weight;
      _hold(badges, set.id, PrRecordKind.weight, solid: true);
    }
    final double e1rm = round2(setE1rm(
      weightKg: set.weightKg,
      reps: set.reps,
      rir: set.rir,
    ));
    if (e1rm > bestE1rm) {
      if (holderE1rm != null) {
        _hold(badges, holderE1rm, PrRecordKind.e1rm, solid: false);
      }
      holderE1rm = set.id;
      bestE1rm = e1rm;
      _hold(badges, set.id, PrRecordKind.e1rm, solid: true);
    }
  }
  return badges;
}

void _hold(
  Map<String, SetRecordBadges> badges,
  String setId,
  PrRecordKind kind, {
  required bool solid,
}) {
  final SetRecordBadges held = badges[setId] ?? const SetRecordBadges();
  badges[setId] = solid
      ? SetRecordBadges(
          current: <PrRecordKind>{...held.current, kind},
          beaten: held.beaten,
        )
      : // A record a later row took over moves: it stops being current and
      // joins the struck-through set, it is never both.
      SetRecordBadges(
          current: held.current.difference(<PrRecordKind>{kind}),
          beaten: <PrRecordKind>{...held.beaten, kind},
        );
}

/// One current record of a workout: the exercise it belongs to, which record
/// it is, and the value the device measured (`Bench Press · PR e1RM 112.5 kg`).
@immutable
class WorkoutRecord {
  const WorkoutRecord({
    required this.exerciseName,
    required this.kind,
    required this.value,
  });

  final String exerciseName;
  final PrRecordKind kind;
  final double value;

  /// The `PR … kg` half of the celebration line.
  String get label => '${kind.celebrationPrefix}${formatRecordKg(value)} kg';

  /// The full celebration line the summary lists.
  String get line => '$exerciseName · $label';
}

/// Every current record of [workout] — the solid badges only, in exercise and
/// then row order. Beaten badges are session bookkeeping and never celebrate.
List<WorkoutRecord> workoutRecords(ActiveWorkout workout) {
  final List<WorkoutRecord> records = <WorkoutRecord>[];
  for (final ActiveWorkoutExercise exercise in workout.exercises) {
    final Map<String, SetRecordBadges> badges = exerciseRecordBadges(
      sets: exercise.sets,
      baseline: workout.baselines[exercise.exerciseId],
    );
    for (final ActiveWorkoutSet set in exercise.sets) {
      final SetRecordBadges? held = badges[set.id];
      if (held == null) {
        continue;
      }
      for (final PrRecordKind kind in held.current) {
        records.add(WorkoutRecord(
          exerciseName: exercise.exerciseName,
          kind: kind,
          value: kind.valueOf(set),
        ));
      }
    }
  }
  return records;
}

/// The three numbers the workout summary shows, computed once on the device
/// from the ticked rows (#124).
@immutable
class WorkoutSummaryStats {
  const WorkoutSummaryStats({
    required this.exercisesDone,
    required this.workingSets,
    required this.totalVolumeKg,
  });

  /// Exercises with at least one ticked working set — the ones this workout
  /// actually trained (an exercise with no ticked set is `skipped` in the
  /// draft, and a warm-up alone trains nothing).
  final int exercisesDone;

  /// Ticked working sets, warm-ups excluded.
  final int workingSets;

  /// Σ kg × reps over the ticked working sets.
  final double totalVolumeKg;

  String get volumeLabel => formatRecordKg(totalVolumeKg);
}

WorkoutSummaryStats workoutSummaryStats(ActiveWorkout workout) {
  int exercisesDone = 0;
  int workingSets = 0;
  double volume = 0;
  for (final ActiveWorkoutExercise exercise in workout.exercises) {
    bool done = false;
    for (final ActiveWorkoutSet set in exercise.sets) {
      if (!set.ticked || !set.countsAsWorkingSet) {
        continue;
      }
      done = true;
      workingSets += 1;
      volume += set.weightKg * set.reps;
    }
    if (done) {
      exercisesDone += 1;
    }
  }
  return WorkoutSummaryStats(
    exercisesDone: exercisesDone,
    workingSets: workingSets,
    totalVolumeKg: round2(volume),
  );
}

/// The device's snapshot of a finished workout: the celebration and the stats,
/// computed once when Finish opens the summary and never recomputed afterwards
/// (#124 — a summary already shown is never rewritten after a sync).
@immutable
class WorkoutSummary {
  const WorkoutSummary({required this.records, required this.stats});

  factory WorkoutSummary.of(ActiveWorkout workout) => WorkoutSummary(
        records: workoutRecords(workout),
        stats: workoutSummaryStats(workout),
      );

  final List<WorkoutRecord> records;
  final WorkoutSummaryStats stats;
}
