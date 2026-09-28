import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/models.dart';

BaselineExercise _serverBaseline({
  String exerciseId = 'bench_press',
  int sessionsLogged = 2,
  double? maxWeightKg = 100.0,
  double? bestE1rmKg = 120.0,
  String performedDate = '2026-09-20',
  List<BaselineSet> sets = const <BaselineSet>[
    BaselineSet(weightKg: 90, reps: 5, rir: 2),
  ],
}) =>
    BaselineExercise(
      exerciseId: exerciseId,
      sessionsLogged: sessionsLogged,
      maxWeightKg: maxWeightKg,
      bestE1rmKg: bestE1rmKg,
      lastSession:
          BaselineLastSession(performedDate: performedDate, sets: sets),
    );

WorkoutDraft _draft({
  required String performedDate,
  required String capturedAt,
  required List<DraftExercise> exercises,
  String status = DraftStatus.pending,
}) =>
    WorkoutDraft(
      clientSessionId: 'cs-$capturedAt',
      accountId: 'account-alice',
      performedDate: performedDate,
      performedTimezone: 'UTC',
      programVersion: 1,
      dayOrder: 1,
      dayName: 'Day 1',
      capturedAt: capturedAt,
      exercises: exercises,
      readiness: 4,
      status: status,
      updatedAt: capturedAt,
    );

Map<String, dynamic> _exerciseJson(String id) => <String, dynamic>{
      'exercise_id': id,
      'exercise_name': id,
      'target_sets': 3,
      'target_reps_min': 5,
      'target_reps_max': 8,
      'target_rpe': 8.5,
      'rest_seconds': 180,
      'notes': null,
    };

void main() {
  group('working-set predicate (WORKING_SET_PREDICATE)', () {
    test('counts a plain set with weight and reps', () {
      expect(
        isWorkingSet(isWarmup: false, weightKg: 100, reps: 5),
        isTrue,
      );
    });

    test('excludes warm-ups, 0 kg sets, and 0-rep sets', () {
      expect(
        isWorkingSet(isWarmup: true, weightKg: 100, reps: 5),
        isFalse,
      );
      expect(isWorkingSet(isWarmup: false, weightKg: 0, reps: 5), isFalse);
      expect(isWorkingSet(isWarmup: false, weightKg: 100, reps: 0), isFalse);
    });
  });

  group('set_e1rm port', () {
    test('rated set uses RIR as 10 - RPE', () {
      // RIR 1 → RPE 9 → effective reps 5 + 1 → 100 * 1.2.
      expect(setE1rm(weightKg: 100, reps: 5, rir: 1), closeTo(120.0, 1e-9));
    });

    test('unrated set keeps the RPE 8.5 default', () {
      // RPE 8.5 → effective reps 5 + 1.5 → 100 * (1 + 6.5/30).
      expect(
        round2(setE1rm(weightKg: 100, reps: 5, rir: null)),
        121.67,
      );
    });

    test('RIR 0 is a maximal-effort set', () {
      expect(
        round2(setE1rm(weightKg: 100, reps: 5, rir: 0)),
        116.67,
      );
    });

    test('an effort below the RPE floor clamps like the server', () {
      // RIR 5 → RPE 5, clamped to 6 → effective reps 5 + 4 → 100 * 1.3.
      expect(setE1rm(weightKg: 100, reps: 5, rir: 5), closeTo(130.0, 1e-9));
    });

    test('no weight or no reps scores zero', () {
      expect(calculateE1rm(weightKg: 0, reps: 5, rpe: 9), 0.0);
      expect(calculateE1rm(weightKg: 100, reps: 0, rpe: 9), 0.0);
    });

    test('rpe round-trips through the display boundary', () {
      expect(rirFromRpe(9.0), 1.0);
      expect(rirFromRpe(null), isNull);
      expect(rpeFromRir(1.0), 9.0);
      expect(rpeFromRir(null), 8.5);
      // Outside the service's accepted RPE band, clamp so a commit can land.
      expect(rpeFromRir(5.0), 6.0);
      expect(rpeFromRir(-1.0), 10.0);
    });
  });

  group('foldDraftsIntoBaselines', () {
    test('folds a newer unsynced draft: count, maxima, and last session', () {
      final List<BaselineExercise> folded = foldDraftsIntoBaselines(
        baselines: <BaselineExercise>[_serverBaseline()],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T10:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                sets: const <WorkoutSetLog>[
                  // Warm-up: excluded from every aggregate.
                  WorkoutSetLog(
                      weightKg: 40, reps: 10, rpe: 8.0, isWarmup: true),
                  // 0 kg: excluded.
                  WorkoutSetLog(weightKg: 0, reps: 8, rpe: 8.0),
                  WorkoutSetLog(weightKg: 110, reps: 5, rpe: 9.0),
                ],
              ),
            ],
          ),
        ],
      );

      expect(folded, hasLength(1));
      final BaselineExercise bench = folded.single;
      expect(bench.sessionsLogged, 3);
      expect(bench.maxWeightKg, 110.0);
      // e1RM of 110x5 @ RIR 1 is 132, past the server's 120.
      expect(bench.bestE1rmKg, 132.0);
      expect(bench.lastSession.performedDate, '2026-09-26');
      expect(bench.lastSession.sets, hasLength(1));
      expect(bench.lastSession.sets.single.weightKg, 110.0);
      expect(bench.lastSession.sets.single.reps, 5);
      expect(bench.lastSession.sets.single.rir, 1.0);
    });

    test('keeps the server last session when the draft is older', () {
      final List<BaselineExercise> folded = foldDraftsIntoBaselines(
        baselines: <BaselineExercise>[_serverBaseline()],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-10',
            capturedAt: '2026-09-10T10:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 95, reps: 5, rpe: 9.0),
                ],
              ),
            ],
          ),
        ],
      );

      final BaselineExercise bench = folded.single;
      expect(bench.sessionsLogged, 3);
      expect(bench.maxWeightKg, 100.0); // the draft's 95 is not heavier
      expect(bench.bestE1rmKg, 120.0); // 95x5 @RIR1 = 114 < 120
      expect(bench.lastSession.performedDate, '2026-09-20');
      expect(bench.lastSession.sets.single.weightKg, 90.0);
    });

    test('creates a baseline for an exercise only a draft has logged', () {
      final List<BaselineExercise> folded = foldDraftsIntoBaselines(
        baselines: const <BaselineExercise>[],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T10:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('row'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 60, reps: 8, rpe: 8.5),
                ],
              ),
            ],
          ),
        ],
      );

      expect(folded, hasLength(1));
      final BaselineExercise row = folded.single;
      expect(row.exerciseId, 'row');
      expect(row.sessionsLogged, 1);
      expect(row.maxWeightKg, 60.0);
      expect(row.bestE1rmKg, 79.0);
      expect(row.lastSession.performedDate, '2026-09-26');
      expect(row.lastSession.sets.single.rir, 1.5);
    });

    test('ignores synced drafts, skipped exercises, and empty drafts', () {
      final List<BaselineExercise> folded = foldDraftsIntoBaselines(
        baselines: <BaselineExercise>[_serverBaseline()],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T10:00:00.000Z',
            status: DraftStatus.synced,
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 200, reps: 5, rpe: 9.0),
                ],
              ),
            ],
          ),
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T11:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                skipped: true,
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 300, reps: 5, rpe: 9.0),
                ],
              ),
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(
                      weightKg: 40, reps: 10, rpe: 8.0, isWarmup: true),
                ],
              ),
            ],
          ),
        ],
      );

      final BaselineExercise bench = folded.single;
      expect(bench.sessionsLogged, 2);
      expect(bench.maxWeightKg, 100.0);
      expect(bench.bestE1rmKg, 120.0);
      expect(bench.lastSession.performedDate, '2026-09-20');
    });

    test('folds a syncing draft but never one needing reconciliation', () {
      // A draft mid-commit will land, so its working sets count now.
      final List<BaselineExercise> syncing = foldDraftsIntoBaselines(
        baselines: <BaselineExercise>[_serverBaseline()],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T10:00:00.000Z',
            status: DraftStatus.syncing,
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 110, reps: 5, rpe: 9.0),
                ],
              ),
            ],
          ),
        ],
      );
      expect(syncing.single.sessionsLogged, 3);
      expect(syncing.single.lastSession.performedDate, '2026-09-26');

      // A refused draft is not retried as-is (ADR 033), so folding it would
      // show a previous set history will never contain (#123 item 9).
      final List<BaselineExercise> refused = foldDraftsIntoBaselines(
        baselines: <BaselineExercise>[_serverBaseline()],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T10:00:00.000Z',
            status: DraftStatus.needsReconciliation,
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 300, reps: 5, rpe: 9.0),
                ],
              ),
            ],
          ),
        ],
      );
      expect(refused.single.sessionsLogged, 2);
      expect(refused.single.maxWeightKg, 100.0);
      expect(refused.single.lastSession.performedDate, '2026-09-20');
    });

    test('orders last_session by start instant, not the performed date', () {
      // LAST_SESSION_ORDER is `started_at DESC` (database/ledger/workouts.py),
      // so a draft captured after a committed session's day wins the last
      // session even though its own performed date is older — a performed-date
      // comparison would have kept the server row (#123 item 9, ADR 035).
      final List<BaselineExercise> folded = foldDraftsIntoBaselines(
        baselines: <BaselineExercise>[_serverBaseline()],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-18',
            capturedAt: '2026-09-22T10:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('bench_press'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 110, reps: 5, rpe: 9.0),
                ],
              ),
            ],
          ),
        ],
      );

      final BaselineExercise bench = folded.single;
      expect(bench.sessionsLogged, 3);
      expect(bench.maxWeightKg, 110.0);
      expect(bench.lastSession.performedDate, '2026-09-18');
      expect(bench.lastSession.sets.single.weightKg, 110.0);
    });

    test('orders two same-day drafts by their captured start time', () {
      final List<BaselineExercise> folded = foldDraftsIntoBaselines(
        baselines: const <BaselineExercise>[],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T18:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('row'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 50, reps: 8, rpe: 8.5),
                ],
              ),
            ],
          ),
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T09:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('row'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 55, reps: 8, rpe: 8.5),
                ],
              ),
            ],
          ),
        ],
      );

      final BaselineExercise row = folded.single;
      expect(row.sessionsLogged, 2);
      expect(row.maxWeightKg, 55.0);
      // The 18:00 draft is the latest session even though it was listed first.
      expect(row.lastSession.sets.single.weightKg, 50.0);
    });

    test('rounds aggregates to two decimals', () {
      final List<BaselineExercise> folded = foldDraftsIntoBaselines(
        baselines: const <BaselineExercise>[],
        drafts: <WorkoutDraft>[
          _draft(
            performedDate: '2026-09-26',
            capturedAt: '2026-09-26T10:00:00.000Z',
            exercises: <DraftExercise>[
              DraftExercise(
                exercise: _exerciseJson('row'),
                sets: const <WorkoutSetLog>[
                  WorkoutSetLog(weightKg: 33.333, reps: 7, rpe: 8.7),
                ],
              ),
            ],
          ),
        ],
      );

      final BaselineExercise row = folded.single;
      expect(row.maxWeightKg, 33.33);
      expect(row.bestE1rmKg, round2(row.bestE1rmKg!));
    });
  });

  test('round2 keeps two decimals', () {
    expect(round2(121.66666666666667), 121.67);
    expect(round2(120.0), 120.0);
    expect(round2(33.333), 33.33);
  });
}
