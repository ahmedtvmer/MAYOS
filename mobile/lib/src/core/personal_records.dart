import 'package:flutter/foundation.dart' show immutable;

import 'active_workout.dart';
import 'baselines.dart';
import 'training_status_projection.dart';
import 'workout_equipment.dart';

/// The exercise-wide records a player is told about: weighted records and
/// most reps on zero-load body-weight/band sets.
enum PrRecordKind {
  /// Heaviest weight, any rep count.
  weight,

  /// Best e1RM, by the server's `set_e1rm` formula.
  e1rm,

  /// Most reps in a zero-load working set on body-weight/band equipment.
  mostReps;

  /// The Personal record type stored by the service and ledger.
  static PrRecordKind? fromRecordType(String recordType) =>
      switch (recordType) {
        'max_weight' => PrRecordKind.weight,
        'max_e1rm' => PrRecordKind.e1rm,
        'most_reps' => PrRecordKind.mostReps,
        _ => null,
      };

  /// The logger badge label.
  String get badgeLabel => switch (this) {
        PrRecordKind.weight => 'PR kg',
        PrRecordKind.e1rm => 'PR e1RM',
        PrRecordKind.mostReps => 'Most reps',
      };

  /// The `PR … ` before the value in a celebration line: `PR 140 kg` for a
  /// heaviest-weight record, `PR e1RM 112.5 kg` for an e1RM one (#124).
  String get celebrationPrefix => switch (this) {
        PrRecordKind.weight => 'PR ',
        PrRecordKind.e1rm => 'PR e1RM ',
        PrRecordKind.mostReps => 'Most reps ',
      };

  /// The value this record tracks for one set row: the row's weight for
  /// [weight], its e1RM by the server's `set_e1rm` for [e1rm].
  double valueOf(ActiveWorkoutSet set) => switch (this) {
        PrRecordKind.weight => set.weightKg,
        PrRecordKind.e1rm =>
          setE1rm(weightKg: set.weightKg, reps: set.reps, rir: set.rir),
        PrRecordKind.mostReps => set.reps.toDouble(),
      };
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
/// Rules:
/// - No baseline row → no badge.
/// - Weighted badges use the strict ADR 042 aggregates; most-reps badges use
///   only eligible 0 kg sets on body-weight/band equipment and need an earlier
///   eligible 0 kg working set in the baseline.
/// - Only ticked working sets are considered; warm-ups and unticked rows
///   never earn a badge.
/// - A record needs a strict improvement over the baseline (`ties are not
///   records`), rounded to 2 dp exactly like the server compares.
/// - Within the session, rows are walked in row order; a row that strictly
///   beats the running best takes the solid badge and hands the previous
///   holder a struck-through one. A row that merely ties never takes over.
Map<String, SetRecordBadges> exerciseRecordBadges({
  required List<ActiveWorkoutSet> sets,
  required BaselineExercise? baseline,
  String? equipment,
}) {
  final Map<String, SetRecordBadges> badges = <String, SetRecordBadges>{};
  if (baseline == null) {
    return badges;
  }
  final double? baselineWeight = baseline.maxWeightKg;
  final double? baselineE1rm = baseline.bestE1rmKg;
  double? bestWeight = baselineWeight;
  double? bestE1rm = baselineE1rm;
  int? bestReps = baseline.bestZeroLoadReps;
  String? holderWeight;
  String? holderE1rm;
  String? holderReps;

  for (final ActiveWorkoutSet set in sets) {
    if (!set.ticked || set.isWarmup || set.reps <= 0) {
      continue;
    }

    if (set.weightKg > 0 &&
        baseline.sessionsLogged > 0 &&
        baselineWeight != null &&
        baselineE1rm != null &&
        set.countsAsWorkingSet) {
      final double weight = round2(set.weightKg);
      if (bestWeight != null && weight > bestWeight) {
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
      if (bestE1rm != null && e1rm > bestE1rm) {
        if (holderE1rm != null) {
          _hold(badges, holderE1rm, PrRecordKind.e1rm, solid: false);
        }
        holderE1rm = set.id;
        bestE1rm = e1rm;
        _hold(badges, set.id, PrRecordKind.e1rm, solid: true);
      }
    } else if (set.weightKg == 0 &&
        baseline.performanceSessionsLogged > 0 &&
        bestReps != null &&
        isBodyWeightOrBandEquipment(equipment)) {
      if (set.reps > bestReps) {
        if (holderReps != null) {
          _hold(badges, holderReps, PrRecordKind.mostReps, solid: false);
        }
        holderReps = set.id;
        bestReps = set.reps;
        _hold(badges, set.id, PrRecordKind.mostReps, solid: true);
      }
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
  String get label => kind == PrRecordKind.mostReps
      ? '${kind.celebrationPrefix}${formatRecordKg(value)} reps'
      : '${kind.celebrationPrefix}${formatRecordKg(value)} kg';

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
      equipment: exercise.equipment,
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

/// The workout summary's set totals, volume, and optional Cardio minutes,
/// computed once on the device from the finished workout (#124).
@immutable
class WorkoutSummaryStats {
  const WorkoutSummaryStats({
    required this.exercisesDone,
    required this.workingSets,
    required this.totalVolumeKg,
    this.cardioMinutes,
  });

  /// Exercises with at least one ticked working set — the ones this workout
  /// actually trained (an exercise with no ticked set is `skipped` in the
  /// draft, and a warm-up alone trains nothing).
  final int exercisesDone;

  /// Ticked working sets, warm-ups excluded.
  final int workingSets;

  /// Σ kg × reps over the ticked working sets.
  final double totalVolumeKg;

  /// Logged Cardio minutes, absent when the player left the item unticked.
  final int? cardioMinutes;

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
    cardioMinutes:
        workout.cardio?.isCommitted == true ? workout.cardio!.minutes : null,
  );
}

/// The device's snapshot of a finished workout: the celebration and the stats,
/// computed once when Finish opens the summary and never recomputed afterwards
/// (#124 — a summary already shown is never rewritten after a sync).
@immutable
class WorkoutSummary {
  const WorkoutSummary({
    required this.records,
    required this.stats,
    required this.duration,
    this.trainingLines = const <TrainingStatusSummaryLine>[],
  });

  /// [now] is the caller's clock, read where Finish runs: the duration is a
  /// snapshot of one instant, never a hidden `DateTime.now()` of its own.
  factory WorkoutSummary.of(
    ActiveWorkout workout, {
    required DateTime now,
    List<TrainingStatusSummaryLine> trainingLines =
        const <TrainingStatusSummaryLine>[],
  }) =>
      WorkoutSummary(
        records: workoutRecords(workout),
        stats: workoutSummaryStats(workout),
        duration: workoutElapsed(workout, now: now),
        trainingLines:
            List<TrainingStatusSummaryLine>.unmodifiable(trainingLines),
      );

  final List<WorkoutRecord> records;
  final WorkoutSummaryStats stats;

  /// Weekly streak and Checkpoint lines captured with this summary at Finish.
  final List<TrainingStatusSummaryLine> trainingLines;

  /// The total Workout time, captured when Finish opens the summary (#159).
  /// It is part of the snapshot: once taken it never changes, whatever the
  /// rows or the clock do while the summary is open.
  final Duration duration;
}
