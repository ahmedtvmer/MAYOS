import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/baseline_service.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

const String _account = 'account-alice';

const ProgramDay _day = ProgramDay(
  dayName: 'Upper A',
  dayOrder: 2,
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'bench_press',
      exerciseName: 'Bench Press',
      targetSets: 2,
      targetRepsMin: 5,
      targetRepsMax: 8,
      targetRpe: 8.5,
    ),
  ],
);

Map<String, dynamic> _baselineRow() => <String, dynamic>{
      'exercise_id': 'bench_press',
      'sessions_logged': 2,
      'max_weight_kg': 100.0,
      'best_e1rm_kg': 120.0,
      'last_session': <String, dynamic>{
        'performed_date': '2026-09-20',
        'sets': <Map<String, dynamic>>[
          <String, dynamic>{'weight_kg': 90.0, 'reps': 5, 'rir': 2.0},
        ],
      },
    };

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<InMemoryTokenStore> _tokens() async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  return tokens;
}

ApiClient _api(FakeMayosApi fake, TokenStore tokens) => ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );

ProviderContainer _container({
  required FakeMayosApi fake,
  required TokenStore tokens,
  required InMemoryActiveWorkoutStore store,
  required InMemoryBaselineCacheStore cache,
  required InMemoryDraftStore drafts,
  required InMemoryWorkoutCacheStore workoutCache,
}) {
  final ProviderContainer container = ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      draftStoreProvider.overrideWithValue(drafts),
      workoutCacheStoreProvider.overrideWithValue(workoutCache),
      baselineCacheStoreProvider.overrideWithValue(cache),
      activeWorkoutStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWith((Ref ref) => _api(fake, tokens)),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

WorkoutDraft _unsyncedDraft({
  String performedDate = '2026-09-26',
  String capturedAt = '2026-09-26T10:00:00.000Z',
  String exerciseId = 'bench_press',
  List<WorkoutSetLog> sets = const <WorkoutSetLog>[
    WorkoutSetLog(weightKg: 120, reps: 3, rpe: 9.0),
  ],
  String status = DraftStatus.pending,
}) =>
    WorkoutDraft(
      clientSessionId: 'cs-$capturedAt',
      accountId: _account,
      performedDate: performedDate,
      performedTimezone: 'UTC',
      programVersion: 3,
      dayOrder: 2,
      dayName: 'Upper A',
      capturedAt: capturedAt,
      exercises: <DraftExercise>[
        DraftExercise(
          exercise: <String, dynamic>{
            'exercise_id': exerciseId,
            'exercise_name': exerciseId,
            'target_sets': 3,
            'target_reps_min': 5,
            'target_reps_max': 8,
            'target_rpe': 8.5,
            'rest_seconds': 180,
            'notes': null,
          },
          sets: sets,
        ),
      ],
      readiness: 4,
      status: status,
      updatedAt: capturedAt,
    );

const Map<String, dynamic> _plannedExerciseJson = <String, dynamic>{
  'exercise_id': 'bench_press',
  'exercise_name': 'Bench Press',
  'target_sets': 2,
  'target_reps_min': 5,
  'target_reps_max': 8,
  'target_rpe': 8.5,
  'warmup_sets': 0,
  'rest_seconds': 180,
  'notes': null,
};

const Map<String, dynamic> _unplannedExerciseJson = <String, dynamic>{
  'exercise_id': 'cable_row',
  'exercise_name': 'Cable Row',
  'target_sets': 3,
  'target_reps_min': 8,
  'target_reps_max': 12,
  'target_rpe': 8.0,
  'rest_seconds': 120,
  'notes': null,
};

void main() {
  group('Active workout lifecycle', () {
    test('is created, persisted after changes, and restored on restart',
        () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryTokenStore tokens = await _tokens();
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final InMemoryBaselineCacheStore cache = InMemoryBaselineCacheStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore workoutCache =
          InMemoryWorkoutCacheStore();

      final ProviderContainer first = _container(
        fake: fake,
        tokens: tokens,
        store: store,
        cache: cache,
        drafts: drafts,
        workoutCache: workoutCache,
      );
      final ActiveWorkoutController controller =
          first.read(activeWorkoutControllerProvider.notifier);
      final StartWorkoutOutcome outcome = await controller.startFromDay(
        accountId: _account,
        day: _day,
        programVersion: 3,
      );
      expect(outcome, StartWorkoutOutcome.started);
      expect(controller.hasActive, isTrue);

      await controller.updateCell(0, 0, weightKg: 100, reps: 5, rir: 1);
      await controller.setTicked(0, 0, true);
      await controller.addSet(0);
      await controller.toggleWarmup(0, 1);

      // The stored copy is what a fresh process would read.
      final ActiveWorkout? stored = await store.read(_account);
      expect(stored, isNotNull);
      expect(stored!.exercises.single.sets, hasLength(3));
      expect(stored.exercises.single.sets.first.ticked, isTrue);
      expect(stored.exercises.single.sets.first.weightKg, 100);
      expect(stored.exercises.single.sets[1].isWarmup, isTrue);
      expect(stored.baselines.keys, contains('bench_press'));
      expect(stored.dayOrder, 2);
      expect(stored.startedAt, isNotEmpty);

      // Simulated restart: a new container over the same device storage.
      final ProviderContainer second = _container(
        fake: fake,
        tokens: tokens,
        store: store,
        cache: cache,
        drafts: drafts,
        workoutCache: workoutCache,
      );
      final ActiveWorkoutController restored =
          second.read(activeWorkoutControllerProvider.notifier);
      await restored.syncAccount(_account);
      expect(restored.hasActive, isTrue);
      expect(restored.workout!.id, controller.workout!.id);
      expect(restored.workout!.exercises.single.sets.first.ticked, isTrue);
      expect(restored.workout!.exercises.single.sets.first.weightKg, 100);
      expect(restored.workout!.exercises.single.sets[1].isWarmup, isTrue);
    });

    test('refuses a second start until the current workout is discarded',
        () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryTokenStore tokens = await _tokens();
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final ProviderContainer container = _container(
        fake: fake,
        tokens: tokens,
        store: store,
        cache: InMemoryBaselineCacheStore(),
        drafts: InMemoryDraftStore(),
        workoutCache: InMemoryWorkoutCacheStore(),
      );
      final ActiveWorkoutController controller =
          container.read(activeWorkoutControllerProvider.notifier);

      expect(
        await controller.startFromDay(
            accountId: _account, day: _day, programVersion: 3),
        StartWorkoutOutcome.started,
      );
      final String firstId = controller.workout!.id;

      expect(
        await controller.startFromDay(
            accountId: _account, day: _day, programVersion: 3),
        StartWorkoutOutcome.activeExists,
      );
      expect(controller.workout!.id, firstId);

      await controller.discard();
      expect(controller.hasActive, isFalse);
      expect(await store.read(_account), isNull);

      expect(
        await controller.startFromDay(
            accountId: _account, day: _day, programVersion: 3),
        StartWorkoutOutcome.started,
      );
      expect(controller.workout!.id, isNot(firstId));
    });

    test('seeds planned rows like the logger and applies the set operations',
        () async {
      final FakeMayosApi fake = _signedInFake();
      final InMemoryTokenStore tokens = await _tokens();
      final ProviderContainer container = _container(
        fake: fake,
        tokens: tokens,
        store: InMemoryActiveWorkoutStore(),
        cache: InMemoryBaselineCacheStore(),
        drafts: InMemoryDraftStore(),
        workoutCache: InMemoryWorkoutCacheStore(),
      );
      final ActiveWorkoutController controller =
          container.read(activeWorkoutControllerProvider.notifier);
      await controller.startFromDay(
          accountId: _account, day: _day, programVersion: 3);

      final ActiveWorkoutExercise planned =
          controller.workout!.exercises.single;
      expect(planned.sets, hasLength(2));
      expect(planned.sets.first.weightKg, 0);
      expect(planned.sets.first.reps, 5);
      expect(planned.sets.first.rir, 1.5); // 10 - 8.5
      expect(planned.sets.first.ticked, isFalse);
      expect(planned.targetLabel, isNotNull);

      await controller.addSet(0);
      expect(controller.workout!.exercises.single.sets, hasLength(3));
      await controller.removeSet(0, 2);
      expect(controller.workout!.exercises.single.sets, hasLength(2));
      // The last remaining row can never be removed.
      await controller.removeSet(0, 1);
      await controller.removeSet(0, 0);
      expect(controller.workout!.exercises.single.sets, hasLength(1));

      await controller.updateCell(0, 0, weightKg: 80, reps: 8, rir: 2);
      expect(controller.workout!.exercises.single.sets.first.weightKg, 80);
      expect(controller.workout!.exercises.single.sets.first.reps, 8);
      expect(controller.workout!.exercises.single.sets.first.rir, 2);
      await controller.updateCell(0, 0, unrated: true);
      expect(controller.workout!.exercises.single.sets.first.rir, isNull);

      await controller.addUnplannedExercise(
          exerciseId: 'cable_row', exerciseName: 'Cable Row');
      final ActiveWorkoutExercise unplanned =
          controller.workout!.exercises.last;
      expect(unplanned.unplanned, isTrue);
      expect(unplanned.exercise, _unplannedExerciseJson);
      expect(unplanned.sets, hasLength(3));
      expect(unplanned.sets.first.reps, 8);
      expect(unplanned.sets.first.rir, 2.0);
    });
  });

  group('baseline resolution (fresh → cache → empty)', () {
    test('uses the fresh fetch first and caches it', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryBaselineCacheStore cache = InMemoryBaselineCacheStore();
      final BaselinesService service = BaselinesService(
        api: _api(fake, await _tokens()),
        cache: cache,
        drafts: InMemoryDraftStore(),
      );

      final BaselineResolution fresh = await service.resolveForStart(_account);
      expect(fresh.source, BaselineSource.fresh);
      expect(fresh.baselines.single.exerciseId, 'bench_press');
      expect(fresh.baselines.single.maxWeightKg, 100.0);
      expect(fake.baselinesRequests, 1);
      expect(await cache.read(_account), hasLength(1));
    });

    test('falls back to the cache when the fetch fails', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryBaselineCacheStore cache = InMemoryBaselineCacheStore();
      final BaselinesService service = BaselinesService(
        api: _api(fake, await _tokens()),
        cache: cache,
        drafts: InMemoryDraftStore(),
      );
      await service.resolveForStart(_account);

      fake.failOffline('GET', '/workouts/baselines');
      final BaselineResolution cached = await service.resolveForStart(_account);
      expect(cached.source, BaselineSource.cache);
      expect(cached.baselines.single.exerciseId, 'bench_press');

      // A malformed body is a failure like any other, not a parse crash.
      fake.offlineRequests.clear();
      fake.baselinesMalformed = true;
      final BaselineResolution afterMalformed =
          await service.resolveForStart(_account);
      expect(afterMalformed.source, BaselineSource.cache);
      expect(afterMalformed.baselines, hasLength(1));
    });

    test('falls back to empty when there is neither fetch nor cache',
        () async {
      final FakeMayosApi fake = _signedInFake();
      fake.failOffline('GET', '/workouts/baselines');
      final BaselinesService service = BaselinesService(
        api: _api(fake, await _tokens()),
        cache: InMemoryBaselineCacheStore(),
        drafts: InMemoryDraftStore(),
      );

      final BaselineResolution empty = await service.resolveForStart(_account);
      expect(empty.source, BaselineSource.empty);
      expect(empty.baselines, isEmpty);
    });

    test('folds the player unsynced drafts into the frozen baseline',
        () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      await drafts.write(_account, <WorkoutDraft>[
        _unsyncedDraft(sets: const <WorkoutSetLog>[
          WorkoutSetLog(weightKg: 120, reps: 3, rpe: 9.0),
          WorkoutSetLog(
              weightKg: 40, reps: 10, rpe: 8.0, isWarmup: true),
          WorkoutSetLog(weightKg: 0, reps: 8, rpe: 8.0),
        ]),
        _unsyncedDraft(
          exerciseId: 'row',
          sets: const <WorkoutSetLog>[
            WorkoutSetLog(weightKg: 60, reps: 8, rpe: 8.5),
          ],
        ),
        _unsyncedDraft(
          capturedAt: '2026-09-24T10:00:00.000Z',
          performedDate: '2026-09-24',
          status: DraftStatus.synced,
        ),
      ]);
      final BaselinesService service = BaselinesService(
        api: _api(fake, await _tokens()),
        cache: InMemoryBaselineCacheStore(),
        drafts: drafts,
      );

      final BaselineResolution resolved =
          await service.resolveForStart(_account);
      expect(resolved.source, BaselineSource.fresh);

      final BaselineExercise bench =
          resolved.baselines.firstWhere((BaselineExercise b) =>
              b.exerciseId == 'bench_press');
      // Two committed sessions plus this one unsynced draft (the synced draft
      // is already in the server rows and never counted twice).
      expect(bench.sessionsLogged, 3);
      expect(bench.maxWeightKg, 120.0);
      // 120x3 @ RIR 1: effective reps 3 + 1 → 120 * (1 + 4/30) = 136 > 120.
      expect(bench.bestE1rmKg, closeTo(136.0, 1e-9));
      expect(bench.lastSession.performedDate, '2026-09-26');
      expect(bench.lastSession.sets, hasLength(1));

      final BaselineExercise row = resolved.baselines
          .firstWhere((BaselineExercise b) => b.exerciseId == 'row');
      expect(row.sessionsLogged, 1);
    });

    test('malformed responses throw like every other call', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesMalformed = true;
      final ApiClient api = _api(fake, await _tokens());
      await expectLater(
        api.baselines(),
        throwsA(isA<ApiException>().having(
            (ApiException e) => e.message, 'message', contains('baseline'))),
      );
    });

    test('the Home prefetch caches a success and never throws on failure',
        () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryBaselineCacheStore cache = InMemoryBaselineCacheStore();
      final BaselinesService service = BaselinesService(
        api: _api(fake, await _tokens()),
        cache: cache,
        drafts: InMemoryDraftStore(),
      );

      await service.prefetch(_account);
      expect(await cache.read(_account), hasLength(1));
      expect(fake.baselinesRequests, 1);

      fake.failOffline('GET', '/workouts/baselines');
      await service.prefetch(_account); // must not throw
      expect(await cache.read(_account), hasLength(1));
    });
  });

  group('draft payload (today\'s shape)', () {
    final DateTime now = DateTime.utc(2026, 9, 28, 12);

    ActiveWorkout workoutWith(
      List<ActiveWorkoutExercise> exercises, {
      int? programVersion = 3,
    }) =>
        ActiveWorkout(
          id: 'aw-1',
          accountId: _account,
          startedAt: '2026-09-28T08:00:00.000Z',
          dayOrder: 2,
          dayName: 'Upper A',
          programVersion: programVersion,
          exercises: exercises,
          baselines: const <String, BaselineExercise>{},
        );

    test('is identical to what the logger builds for the same input', () {
      // Every set ticked: the same input the current logger would send with
      // its skip checkboxes unticked.
      final ActiveWorkout workout = workoutWith(<ActiveWorkoutExercise>[
        ActiveWorkoutExercise(
          exercise: _plannedExerciseJson,
          targetLabel: '2 × 5–8 @ RPE 8.5',
          sets: const <ActiveWorkoutSet>[
            ActiveWorkoutSet(weightKg: 100, reps: 5, rir: 1, ticked: true),
            ActiveWorkoutSet(
                weightKg: 40, reps: 10, rir: 2, isWarmup: true, ticked: true),
            ActiveWorkoutSet(weightKg: 100, reps: 5, rir: 1, ticked: true),
          ],
        ),
        ActiveWorkoutExercise(
          exercise: _unplannedExerciseJson,
          unplanned: true,
          sets: const <ActiveWorkoutSet>[
            ActiveWorkoutSet(weightKg: 60, reps: 8, rir: 1, ticked: true),
          ],
        ),
      ]);

      // Built exactly the way `_WorkoutLoggerScreenState._finish` builds one.
      final WorkoutDraft reference = WorkoutDraft(
        clientSessionId: 'fixed-session',
        accountId: _account,
        performedDate: '2026-09-28',
        performedTimezone: 'Europe/Berlin',
        programVersion: 3,
        dayOrder: 2,
        dayName: 'Upper A',
        capturedAt: now.toUtc().toIso8601String(),
        exercises: <DraftExercise>[
          DraftExercise(
            exercise: _plannedExerciseJson,
            sets: const <WorkoutSetLog>[
              WorkoutSetLog(weightKg: 100, reps: 5, rpe: 9.0),
              WorkoutSetLog(
                  weightKg: 40, reps: 10, rpe: 8.0, isWarmup: true),
              WorkoutSetLog(weightKg: 100, reps: 5, rpe: 9.0),
            ],
            skipped: false,
          ),
          DraftExercise(
            exercise: _unplannedExerciseJson,
            sets: const <WorkoutSetLog>[
              WorkoutSetLog(weightKg: 60, reps: 8, rpe: 9.0),
            ],
            skipped: false,
          ),
        ],
        readiness: 4,
        notes: 'solid day',
        status: DraftStatus.pending,
        updatedAt: now.toUtc().toIso8601String(),
      );

      final WorkoutDraft? built = workout.buildWorkoutDraft(
        timezone: 'Europe/Berlin',
        clientSessionId: 'fixed-session',
        now: now,
        performedDate: '2026-09-28',
        readiness: 4,
        notes: 'solid day',
      );

      expect(built, isNotNull);
      expect(jsonEncode(built!.toJson()), jsonEncode(reference.toJson()));
    });

    test('logs only ticked sets and sends an untouched exercise as skipped',
        () {
      final ActiveWorkout workout = workoutWith(<ActiveWorkoutExercise>[
        ActiveWorkoutExercise(
          exercise: _plannedExerciseJson,
          sets: const <ActiveWorkoutSet>[
            // Unticked with values: never logged.
            ActiveWorkoutSet(weightKg: 100, reps: 5, rir: 1),
            ActiveWorkoutSet(weightKg: 90, reps: 5, rir: 2, ticked: true),
          ],
        ),
        ActiveWorkoutExercise(
          exercise: _unplannedExerciseJson,
          unplanned: true,
          sets: const <ActiveWorkoutSet>[
            ActiveWorkoutSet(weightKg: 0, reps: 0),
          ],
        ),
      ]);

      final WorkoutDraft? built = workout.buildWorkoutDraft(
        timezone: 'Europe/Berlin',
        clientSessionId: 'fixed-session',
        now: now,
        performedDate: '2026-09-28',
      );

      expect(built, isNotNull);
      expect(built!.exercises, hasLength(2));
      final DraftExercise planned = built.exercises.first;
      expect(planned.sets, hasLength(1));
      expect(planned.sets.single.weightKg, 90);
      expect(planned.sets.single.rpe, 8.0); // RIR 2 → RPE 8
      expect(planned.skipped, isFalse);
      // An exercise with no ticked set is sent as skipped, not with blanks.
      final DraftExercise unplanned = built.exercises.last;
      expect(unplanned.sets, isEmpty);
      expect(unplanned.skipped, isTrue);
    });

    test('defaults the performed date to the day the workout started', () {
      final ActiveWorkout workout = workoutWith(<ActiveWorkoutExercise>[]);
      final WorkoutDraft? built = workout.buildWorkoutDraft(
        timezone: 'UTC',
        clientSessionId: 'fixed-session',
        now: now,
      );
      expect(built!.performedDate, workout.startedDate);
    });

    test('returns null without a program version, like the logger guard', () {
      final ActiveWorkout workout =
          workoutWith(<ActiveWorkoutExercise>[], programVersion: null);
      expect(
        workout.buildWorkoutDraft(
          timezone: 'UTC',
          clientSessionId: 'fixed-session',
          now: now,
          performedDate: '2026-09-28',
        ),
        isNull,
      );
    });
  });
}
