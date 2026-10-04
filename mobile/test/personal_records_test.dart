import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/personal_records.dart';

/// The frozen baseline the record calculator is tested against: a real history
/// (three sessions) whose aggregates a first tick can beat.
BaselineExercise _baseline({
  int sessionsLogged = 3,
  double? maxWeightKg = 100.0,
  double? bestE1rmKg = 121.67,
}) =>
    BaselineExercise(
      exerciseId: 'bench_press',
      sessionsLogged: sessionsLogged,
      maxWeightKg: maxWeightKg,
      bestE1rmKg: bestE1rmKg,
      lastSession: const BaselineLastSession(
        performedDate: '2026-09-26',
        sets: <BaselineSet>[BaselineSet(weightKg: 100, reps: 5, rir: 1)],
      ),
    );

ActiveWorkoutSet _set({
  required String id,
  double weightKg = 0,
  int reps = 0,
  double? rir,
  bool isWarmup = false,
  bool ticked = true,
}) =>
    ActiveWorkoutSet(
      id: id,
      weightKg: weightKg,
      reps: reps,
      rir: rir,
      isWarmup: isWarmup,
      ticked: ticked,
    );

/// The badges of [sets], keyed by the row's stable id.
Map<String, SetRecordBadges> _badges(
  List<ActiveWorkoutSet> sets, {
  BaselineExercise? baseline,
}) =>
    exerciseRecordBadges(
      sets: sets,
      baseline: baseline ?? _baseline(),
    );

void main() {
  group('record calculator (#124)', () {
    test(
        'a missing baseline, sessions_logged 0 or empty aggregates never '
        'earn a badge', () {
      final List<ActiveWorkoutSet> sets = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 200, reps: 5, rir: 1),
      ];

      expect(
        exerciseRecordBadges(sets: sets, baseline: null),
        isEmpty,
      );
      expect(
        _badges(sets, baseline: _baseline(sessionsLogged: 0)),
        isEmpty,
      );
      expect(
        _badges(sets, baseline: _baseline(maxWeightKg: null)),
        isEmpty,
      );
      expect(
        _badges(sets, baseline: _baseline(bestE1rmKg: null)),
        isEmpty,
      );
    });

    test('a first tick past the baseline earns both records', () {
      final List<ActiveWorkoutSet> sets = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 105, reps: 5, rir: 1),
      ];

      final Map<String, SetRecordBadges> badges = _badges(sets);
      expect(badges['s1']!.current,
          containsAll(<PrRecordKind>[PrRecordKind.weight, PrRecordKind.e1rm]));
      expect(badges['s1']!.beaten, isEmpty);
    });

    test('ties are not records, against the baseline or within the session',
        () {
      // 100 kg × 5 @RIR 1 is exactly the baseline's max weight, and its
      // e1RM (120) sits under the baseline's 121.67: nothing is beaten.
      final List<ActiveWorkoutSet> tie = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 100, reps: 5, rir: 1),
      ];
      expect(_badges(tie), isEmpty);

      // An e1RM that lands exactly on the baseline's is not a record either.
      final List<ActiveWorkoutSet> e1rmTie = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 105, reps: 5, rir: 1),
      ];
      expect(
        _badges(e1rmTie, baseline: _baseline(bestE1rmKg: 126.0))['s1']!.current,
        <PrRecordKind>{PrRecordKind.weight},
      );

      // Two identical records in a row: the first keeps both, the second
      // merely ties it and never takes over.
      final List<ActiveWorkoutSet> sessionTie = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 105, reps: 5, rir: 1),
        _set(id: 's2', weightKg: 105, reps: 5, rir: 1),
      ];
      final Map<String, SetRecordBadges> badges = _badges(sessionTie);
      expect(badges['s1']!.current, hasLength(2));
      expect(badges['s2'], isNull);
    });

    test('a later set beats an earlier one; the earlier stays struck', () {
      final List<ActiveWorkoutSet> sets = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 105, reps: 5, rir: 1),
        _set(id: 's2', weightKg: 110, reps: 5, rir: 1),
        _set(id: 's3', weightKg: 90, reps: 8, rir: 2),
      ];

      final Map<String, SetRecordBadges> badges = _badges(sets);
      expect(badges['s1']!.current, isEmpty);
      expect(
        badges['s1']!.beaten,
        containsAll(<PrRecordKind>[PrRecordKind.weight, PrRecordKind.e1rm]),
      );
      expect(
        badges['s2']!.current,
        containsAll(<PrRecordKind>[PrRecordKind.weight, PrRecordKind.e1rm]),
      );
      // A set under the baseline holds nothing at all.
      expect(badges['s3'], isNull);
    });

    test('unticking a set recalculates every badge of the exercise', () {
      final ActiveWorkoutSet first =
          _set(id: 's1', weightKg: 105, reps: 5, rir: 1);
      final ActiveWorkoutSet second =
          _set(id: 's2', weightKg: 110, reps: 5, rir: 1);
      expect(
        _badges(<ActiveWorkoutSet>[first, second])['s1']!.beaten,
        hasLength(2),
      );

      final Map<String, SetRecordBadges> unticked = _badges(
        <ActiveWorkoutSet>[first, second.copyWith(ticked: false)],
      );
      expect(unticked['s1']!.current, hasLength(2));
      expect(unticked['s1']!.beaten, isEmpty);
      expect(unticked['s2'], isNull);

      // Untick the holder too: the record moves to the row that still holds
      // it and the unticked one earns nothing.
      final Map<String, SetRecordBadges> holderUnticked = _badges(
        <ActiveWorkoutSet>[first.copyWith(ticked: false), second],
      );
      expect(holderUnticked['s1'], isNull);
      expect(holderUnticked['s2']!.current, hasLength(2));
    });

    test('editing a ticked set recalculates every badge of the exercise', () {
      final ActiveWorkoutSet first =
          _set(id: 's1', weightKg: 110, reps: 5, rir: 1);
      final ActiveWorkoutSet second =
          _set(id: 's2', weightKg: 105, reps: 5, rir: 1);

      Map<String, SetRecordBadges> badges = _badges(<ActiveWorkoutSet>[
        first,
        second,
      ]);
      expect(badges['s1']!.current, hasLength(2));
      expect(badges['s2'], isNull);

      // The second set is edited up past the first.
      badges = _badges(<ActiveWorkoutSet>[
        first,
        second.copyWith(weightKg: 120),
      ]);
      expect(badges['s1']!.current, isEmpty);
      expect(badges['s1']!.beaten, hasLength(2));
      expect(badges['s2']!.current, hasLength(2));

      // …and edited back down below the baseline: the exercise earns nothing.
      badges = _badges(<ActiveWorkoutSet>[
        first.copyWith(weightKg: 90),
        second.copyWith(weightKg: 95),
      ]);
      expect(badges, isEmpty);
    });

    test('warm-ups never earn a badge', () {
      final List<ActiveWorkoutSet> sets = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 200, reps: 1, rir: 0, isWarmup: true),
        _set(id: 's2', weightKg: 0, reps: 0, ticked: false),
      ];
      expect(_badges(sets), isEmpty);
    });

    test('an unticked working set earns nothing until it is ticked', () {
      final List<ActiveWorkoutSet> sets = <ActiveWorkoutSet>[
        _set(id: 's1', weightKg: 150, reps: 5, rir: 1, ticked: false),
      ];
      expect(_badges(sets), isEmpty);
      expect(_badges(<ActiveWorkoutSet>[sets.first.copyWith(ticked: true)]),
          isNotEmpty);
    });

    test('Unrated e1RM is plain Epley, exactly like RIR 0 (#111)', () {
      expect(
        setE1rm(weightKg: 100, reps: 5, rir: null),
        setE1rm(weightKg: 100, reps: 5, rir: 0),
      );
      expect(round2(setE1rm(weightKg: 100, reps: 5, rir: null)), 116.67);

      // An unrated set past the baseline's e1RM earns the e1RM record at the
      // plain-Epley value.
      final Map<String, SetRecordBadges> badges = _badges(
        <ActiveWorkoutSet>[
          _set(id: 's1', weightKg: 100, reps: 5, rir: null),
        ],
        baseline: _baseline(bestE1rmKg: 100.0),
      );
      expect(badges['s1']!.current, contains(PrRecordKind.e1rm));
      expect(badges['s1']!.current, isNot(contains(PrRecordKind.weight)));
    });

    test('badge state survives a restart (#124)', () {
      final ActiveWorkout workout = ActiveWorkout(
        id: 'aw-1',
        accountId: 'account-alice',
        startedAt: '2026-09-28T08:00:00.000Z',
        dayOrder: 2,
        dayName: 'Upper A',
        programVersion: 3,
        exercises: <ActiveWorkoutExercise>[
          ActiveWorkoutExercise(
            exercise: <String, dynamic>{
              'exercise_id': 'bench_press',
              'exercise_name': 'Bench Press',
            },
            sets: <ActiveWorkoutSet>[
              _set(id: 's1', weightKg: 105, reps: 5, rir: 1),
              _set(id: 's2', weightKg: 110, reps: 5, rir: 1),
            ],
          ),
        ],
        baselines: <String, BaselineExercise>{'bench_press': _baseline()},
      );

      final Map<String, SetRecordBadges> before = exerciseRecordBadges(
          sets: workout.exercises.first.sets,
          baseline: workout.baselines['bench_press']);
      // The rows and the baseline are what is persisted, so the badges a
      // restart recomputes are the badges the player last saw.
      final ActiveWorkout restored = ActiveWorkout.fromJson(workout.toJson());
      final Map<String, SetRecordBadges> after = exerciseRecordBadges(
        sets: restored.exercises.first.sets,
        baseline: restored.baselines['bench_press'],
      );
      expect(after, before);
      expect(after['s1']!.beaten, hasLength(2));
      expect(after['s2']!.current, hasLength(2));
    });
  });

  group('workout summary (#124)', () {
    ActiveWorkout summaryWorkout({
      required List<ActiveWorkoutSet> benchSets,
      bool inclineTicked = false,
    }) =>
        ActiveWorkout(
          id: 'aw-1',
          accountId: 'account-alice',
          startedAt: '2026-09-28T08:00:00.000Z',
          dayOrder: 2,
          dayName: 'Upper A',
          programVersion: 3,
          exercises: <ActiveWorkoutExercise>[
            ActiveWorkoutExercise(
              exercise: <String, dynamic>{
                'exercise_id': 'bench_press',
                'exercise_name': 'Bench Press',
              },
              sets: benchSets,
            ),
            ActiveWorkoutExercise(
              exercise: <String, dynamic>{
                'exercise_id': 'incline_press',
                'exercise_name': 'Incline Press',
              },
              sets: <ActiveWorkoutSet>[
                _set(
                  id: 'i1',
                  weightKg: 40,
                  reps: 10,
                  ticked: inclineTicked,
                ),
              ],
            ),
          ],
          baselines: <String, BaselineExercise>{'bench_press': _baseline()},
        );

    test('lists each current record as "Exercise · PR … kg"', () {
      final WorkoutSummary summary = WorkoutSummary.of(
        summaryWorkout(
          benchSets: <ActiveWorkoutSet>[
            _set(id: 's1', weightKg: 105, reps: 5, rir: 1),
            _set(id: 's2', weightKg: 110, reps: 5, rir: 1),
          ],
        ),
        now: DateTime.parse('2026-09-28T09:00:00.000Z'),
      );

      expect(
        summary.records.map((WorkoutRecord r) => r.line).toList(),
        <String>[
          'Bench Press · PR 110 kg',
          'Bench Press · PR e1RM 132 kg',
        ],
      );
    });

    test('a workout with no records has no celebration', () {
      final WorkoutSummary summary = WorkoutSummary.of(
        summaryWorkout(
          benchSets: <ActiveWorkoutSet>[
            _set(id: 's1', weightKg: 100, reps: 5, rir: 1),
          ],
        ),
        now: DateTime.parse('2026-09-28T09:00:00.000Z'),
      );
      expect(summary.records, isEmpty);
    });

    test('stats count exercises done, ticked working sets and volume', () {
      final WorkoutSummaryStats stats = workoutSummaryStats(summaryWorkout(
        benchSets: <ActiveWorkoutSet>[
          _set(id: 's1', weightKg: 105, reps: 5, rir: 1),
          _set(id: 's2', weightKg: 110, reps: 5, rir: 1),
          _set(id: 's3', weightKg: 0, reps: 0, ticked: false),
          _set(id: 's4', weightKg: 60, reps: 8, rir: 2, isWarmup: true),
        ],
        inclineTicked: true,
      ));

      expect(stats.exercisesDone, 2);
      expect(stats.workingSets, 3);
      // 105 × 5 + 110 × 5 + 40 × 10
      expect(stats.totalVolumeKg, 1475);
      expect(stats.volumeLabel, '1475');
    });

    test('zero-load body-weight sets are excluded from working-set totals', () {
      final ActiveWorkoutSet set = _set(id: 'push-up', reps: 12);
      final BaselineExercise baseline = BaselineExercise(
        exerciseId: 'push_up',
        sessionsLogged: 0,
        maxWeightKg: null,
        bestE1rmKg: null,
        lastSession: const BaselineLastSession(
          performedDate: '2026-09-26',
          sets: <BaselineSet>[BaselineSet(weightKg: 0, reps: 12)],
        ),
      );
      final ActiveWorkout workout = ActiveWorkout(
        id: 'aw-1',
        accountId: 'account-alice',
        startedAt: '2026-09-28T08:00:00.000Z',
        dayOrder: 1,
        dayName: 'Push',
        programVersion: 3,
        exercises: <ActiveWorkoutExercise>[
          ActiveWorkoutExercise(
            exercise: <String, dynamic>{
              'exercise_id': 'push_up',
              'exercise_name': 'Push-Up',
              'equipment': 'body weight',
            },
            sets: <ActiveWorkoutSet>[set],
          ),
        ],
        baselines: <String, BaselineExercise>{'push_up': baseline},
      );
      final WorkoutSummary summary = WorkoutSummary.of(
        workout,
        now: DateTime.parse('2026-09-28T09:00:00.000Z'),
      );

      expect(summary.stats.exercisesDone, 0);
      expect(summary.stats.workingSets, 0);
      expect(summary.stats.totalVolumeKg, 0);
      expect(summary.records, isEmpty);
      expect(
        exerciseRecordBadges(sets: <ActiveWorkoutSet>[set], baseline: baseline),
        isEmpty,
      );

      final ActiveWorkoutSet firstWeightedSet = _set(
        id: 'first-weighted-set',
        weightKg: 60,
        reps: 8,
      );
      expect(
        exerciseRecordBadges(
          sets: <ActiveWorkoutSet>[firstWeightedSet],
          baseline: baseline,
        ),
        isEmpty,
      );
    });

    test('an exercise with only unticked or warm-up rows is not done', () {
      final WorkoutSummaryStats stats = workoutSummaryStats(summaryWorkout(
        benchSets: <ActiveWorkoutSet>[
          _set(id: 's4', weightKg: 60, reps: 8, rir: 2, isWarmup: true),
          _set(id: 's3', weightKg: 0, reps: 0, ticked: false),
        ],
      ));
      expect(stats.exercisesDone, 0);
      expect(stats.workingSets, 0);
      expect(stats.totalVolumeKg, 0);
    });
  });
}
