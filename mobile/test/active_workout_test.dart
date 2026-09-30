import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/baseline_service.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/personal_records.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_rest_alerts.dart';
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

const ProgramDay _dayWithWarmup = ProgramDay(
  dayName: 'Upper A',
  dayOrder: 2,
  warmupExercises: <WarmupExercise>[
    WarmupExercise(exerciseName: 'Cat-Cow', sets: 2, reps: 10),
  ],
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

/// A day with two planned exercises, so an edit to one of them can be told
/// apart from a rest running on the other (#162).
const ProgramDay _dayTwo = ProgramDay(
  dayName: 'Upper B',
  dayOrder: 3,
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'bench_press',
      exerciseName: 'Bench Press',
      targetSets: 2,
      targetRepsMin: 5,
      targetRepsMax: 8,
      targetRpe: 8.5,
    ),
    ProgramExercise(
      exerciseId: 'incline_press',
      exerciseName: 'Incline Press',
      targetSets: 2,
      targetRepsMin: 8,
      targetRepsMax: 12,
      targetRpe: 8.0,
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
  List<Override> extraOverrides = const <Override>[],
}) {
  final ProviderContainer container = ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      draftStoreProvider.overrideWithValue(drafts),
      workoutCacheStoreProvider.overrideWithValue(workoutCache),
      baselineCacheStoreProvider.overrideWithValue(cache),
      activeWorkoutStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWith((Ref ref) => _api(fake, tokens)),
      ...extraOverrides,
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

/// A store whose writes finish in the order they arrive *and* at their own
/// pace: latency is chosen per write index, so an unserialized queue would let
/// a later, faster write land before an earlier one (#123 item 5).
class _LatencyStore implements ActiveWorkoutStore {
  _LatencyStore(this.latencies);

  final List<Duration> latencies;
  final List<int> landed = <int>[];
  int _arrived = 0;
  bool deleted = false;
  bool wroteAfterDelete = false;
  ActiveWorkout? latest;

  @override
  Future<ActiveWorkout?> read(String accountId) async => latest;

  @override
  Future<void> write(String accountId, ActiveWorkout workout) async {
    final int index = _arrived++;
    if (deleted) {
      wroteAfterDelete = true;
    }
    await Future<void>.delayed(latencies[index % latencies.length]);
    if (deleted) {
      wroteAfterDelete = true;
    }
    landed.add(workout.exercises.single.sets.first.reps);
    latest = workout;
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    deleted = true;
    latest = null;
  }
}

void main() {
  group('Active workout lifecycle', () {
    test('warm-up movements seed from the day and survive an app restart',
        () async {
      final FakeMayosApi fake = _signedInFake();
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
      await controller.startFromDay(
        accountId: _account,
        day: _dayWithWarmup,
        programVersion: 3,
      );
      expect(controller.workout!.warmupMovements.single.sets, hasLength(2));
      expect(controller.workout!.warmupMovements.single.sets.first.reps, 10);
      await controller.updateWarmupMovementSet(
        0,
        0,
        const ActiveWarmupSet(reps: 10, ticked: true),
      );

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
      expect(restored.workout!.warmupMovements.single.sets.first.ticked, isTrue);
      expect(restored.workout!.warmupMovements.single.sets[1].ticked, isFalse);
    });

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

      // The stored copy is what a fresh process would read. The fresh
      // prescription supplies the row count, exactly as the old logger did
      // (#123 item 4): three rows for bench, plus the one "+ Add set".
      final ActiveWorkout? stored = await store.read(_account);
      expect(stored, isNotNull);
      expect(stored!.exercises.single.sets, hasLength(4));
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

      await controller.discard(accountId: _account);
      expect(controller.hasActive, isFalse);
      expect(await store.read(_account), isNull);

      expect(
        await controller.startFromDay(
            accountId: _account, day: _day, programVersion: 3),
        StartWorkoutOutcome.started,
      );
      expect(controller.workout!.id, isNot(firstId));
    });

    test('a target RPE cap is shown as its equivalent minimum RIR (#111)',
        () async {
      final FakeMayosApi fake = _signedInFake();
      fake.prescriptionTargetRpe['bench_press'] = 7.0;
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

      // A target RPE cap of 7.0 is a *maximum* effort, so the hint players read
      // is the equivalent *minimum* RIR: 10 - 7 = 3.
      expect(controller.workout!.exercises.single.prescriptionHint!.rir, 3.0);
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
      // Rows start empty, exactly like the #107 prototype: nothing is
      // pre-entered for the player to correct (#123 item 2), while the fresh
      // prescription decides how many there are and what the empty cells hint
      // (#123 item 4).
      expect(
          planned.sets, hasLength(3)); // effective_sets from the prescription
      expect(planned.sets.first.weightKg, 0);
      expect(planned.sets.first.reps, 0);
      expect(planned.sets.first.rir, isNull);
      expect(planned.sets.first.ticked, isFalse);
      // The caption keeps what was actually seeded: the prescription's
      // effective sets (3) and the frozen projection, not the program's raw
      // target (2) — #108, #158.
      expect(planned.targetLabel, '3 sets · 5–8 reps · 60 kg · RIR ≥ 2');
      expect(planned.effectiveSets, 3);
      expect(planned.prescriptionHint, isNotNull);
      expect(planned.prescriptionHint!.reps, 5); // target_reps_min
      expect(planned.prescriptionHint!.rir, 1.5); // 10 - 8.5
      expect(planned.prescriptionHint!.weightKg, 60.0); // projected

      // Row identities are stable across edits, so the swipe-to-delete key is
      // stable too (#123 item 3).
      List<String> idsOf() => controller.workout!.exercises.single.sets
          .map((ActiveWorkoutSet set) => set.id)
          .toList();
      final List<String> seededIds = idsOf();
      expect(seededIds.toSet(), hasLength(3));

      // "+ Add set" adds another empty row with an identity of its own.
      await controller.addSet(0);
      expect(controller.workout!.exercises.single.sets, hasLength(4));
      final List<String> afterAdd = idsOf();
      expect(afterAdd, <String>[...seededIds, afterAdd.last]);
      expect(seededIds.contains(afterAdd.last), isFalse);
      expect(controller.workout!.exercises.single.sets.last.weightKg, 0);
      expect(controller.workout!.exercises.single.sets.last.reps, 0);
      expect(controller.workout!.exercises.single.sets.last.rir, isNull);

      // Removing it leaves the original rows, identities untouched.
      await controller.removeSet(0, 3);
      expect(idsOf(), seededIds);
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
      // Three empty rows, with the unplanned default targets as the hint.
      expect(unplanned.sets, hasLength(3));
      expect(unplanned.sets.first.weightKg, 0);
      expect(unplanned.sets.first.reps, 0);
      expect(unplanned.sets.first.rir, isNull);
      expect(unplanned.prescriptionHint!.reps, 8);
      expect(unplanned.prescriptionHint!.rir, 2.0);
      expect(unplanned.prescriptionHint!.weightKg, isNull);
    });
  });

  group('Replace exercise (#162)', () {
    /// Starts the workout from [_day] over [fake] and returns the controller.
    Future<ActiveWorkoutController> start(FakeMayosApi fake) async {
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
      return controller;
    }

    FakeMayosApi fakeWithBaselines() {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[
        _baselineRow(),
        <String, dynamic>{
          'exercise_id': 'cable_row',
          'sessions_logged': 4,
          'max_weight_kg': 60.0,
          'best_e1rm_kg': 75.0,
          'last_session': <String, dynamic>{
            'performed_date': '2026-09-24',
            'sets': <Map<String, dynamic>>[
              <String, dynamic>{'weight_kg': 55.0, 'reps': 8, 'rir': 2.0},
            ],
          },
        },
      ];
      return fake;
    }

    test('clears the planned exercise in place and adds the replacement',
        () async {
      final ActiveWorkoutController controller =
          await start(fakeWithBaselines());
      await controller.updateCell(0, 0, weightKg: 100, reps: 5, rir: 1);
      await controller.setTicked(0, 0, true);

      await controller.replaceExercise(
        exerciseIndex: 0,
        exerciseId: 'cable_row',
        exerciseName: 'Cable Row',
        imagePath: 'images/cable_row.jpg',
      );

      final ActiveWorkout workout = controller.workout!;
      expect(workout.exercises, hasLength(2));
      // The planned exercise keeps its exact program payload — the program
      // itself is never rewritten — but loses every row and is marked
      // replaced, so it is never a card and never a to-do (#162).
      final ActiveWorkoutExercise planned = workout.exercises[0];
      expect(planned.replaced, isTrue);
      expect(planned.unplanned, isFalse);
      expect(planned.exercise, _day.exercises.single.toJson());
      expect(planned.sets, isEmpty);
      // The replacement sits right after it: unplanned, empty rows, its own
      // catalog picture, no carried-over values.
      final ActiveWorkoutExercise replacement = workout.exercises[1];
      expect(replacement.unplanned, isTrue);
      expect(replacement.replaced, isFalse);
      expect(replacement.exerciseId, 'cable_row');
      expect(replacement.exerciseName, 'Cable Row');
      expect(replacement.imagePath, 'images/cable_row.jpg');
      expect(replacement.sets, hasLength(3));
      for (final ActiveWorkoutSet set in replacement.sets) {
        expect(set.weightKg, 0);
        expect(set.reps, 0);
        expect(set.rir, isNull);
        expect(set.ticked, isFalse);
      }
      // Program version and day are untouched.
      expect(workout.programVersion, 3);
      expect(workout.dayOrder, 2);

      // A restart reads the same two exercises back (#162 persists).
      final ProviderContainer reloaded = _container(
        fake: fakeWithBaselines(),
        tokens: await _tokens(),
        store: InMemoryActiveWorkoutStore()
          ..write(_account, workout),
        cache: InMemoryBaselineCacheStore(),
        drafts: InMemoryDraftStore(),
        workoutCache: InMemoryWorkoutCacheStore(),
      );
      final ActiveWorkoutController restored =
          reloaded.read(activeWorkoutControllerProvider.notifier);
      await restored.syncAccount(_account);
      expect(restored.workout!.exercises, hasLength(2));
      expect(restored.workout!.exercises[0].replaced, isTrue);
      expect(restored.workout!.exercises[1].exerciseId, 'cable_row');
    });

    test('the draft sends the planned exercise as skipped and the '
        'replacement as performed', () async {
      final ActiveWorkoutController controller =
          await start(fakeWithBaselines());
      // Two ticked sets on the planned exercise — the confirmation gate the
      // logger raises before it discards them.
      await controller.updateCell(0, 0, weightKg: 100, reps: 5);
      await controller.setTicked(0, 0, true);
      await controller.updateCell(0, 1, weightKg: 95, reps: 6);
      await controller.setTicked(0, 1, true);

      await controller.replaceExercise(
        exerciseIndex: 0,
        exerciseId: 'cable_row',
        exerciseName: 'Cable Row',
        imagePath: 'images/cable_row.jpg',
      );
      // The replacement's rows start empty, then the player logs one (#162).
      expect(
        controller.workout!.exercises[1].sets.every(
            (ActiveWorkoutSet set) => !set.ticked),
        isTrue,
      );
      await controller.updateCell(1, 0, weightKg: 55, reps: 8, rir: 2);
      await controller.setTicked(1, 0, true);

      final WorkoutDraft draft = controller.workout!.buildWorkoutDraft(
        timezone: 'UTC',
        clientSessionId: '11111111-1111-4111-8111-111111111111',
        now: DateTime.utc(2026, 9, 28, 9),
      )!;

      expect(draft.exercises, hasLength(2));
      // Exactly "planned skipped + unplanned performed": the divergence
      // recording on the service needs nothing else (#162, ADR 018/028).
      final DraftExercise skipped = draft.exercises[0];
      expect(skipped.exerciseId, 'bench_press');
      expect(skipped.skipped, isTrue);
      expect(skipped.sets, isEmpty);
      final DraftExercise performed = draft.exercises[1];
      expect(performed.exerciseId, 'cable_row');
      expect(performed.skipped, isFalse);
      expect(performed.sets, hasLength(1));
      expect(performed.sets.single.weightKg, 55);
      // And the commit body carries only the performed exercise.
      final Map<String, dynamic> body = draft.toCommitBody();
      final List<dynamic> sent = body['sets'] as List<dynamic>;
      expect(sent, hasLength(1));
      expect(
        (sent.single as Map<String, dynamic>)['exercise']['exercise_id'],
        'cable_row',
      );
    });

    test('never touches the program, and the replacement reads its own '
        'frozen baseline', () async {
      final FakeMayosApi fake = fakeWithBaselines();
      final ActiveWorkoutController controller = await start(fake);
      final Map<String, BaselineExercise> frozen =
          Map<String, BaselineExercise>.of(controller.workout!.baselines);
      expect(frozen.keys, containsAll(<String>['bench_press', 'cable_row']));

      await controller.replaceExercise(
        exerciseIndex: 0,
        exerciseId: 'cable_row',
        exerciseName: 'Cable Row',
      );
      final ActiveWorkout workout = controller.workout!;
      // The frozen baselines are exactly what the start resolved: the
      // replacement only *reads* its own entry (#162).
      expect(workout.baselines.keys, frozen.keys);
      final ActiveWorkoutExercise replacement = workout.exercises[1];
      expect(previousSetFor(replacement, 0, workout.baselines),
          frozen['cable_row']!.lastSession.sets.single);
      expect(lastSessionLabel(workout.baselines['cable_row']!.lastSession.sets),
          'Last: 55kg × 8');
      // An exercise with no frozen entry gets none of its own: no hints, no
      // "Last:" line — never the replaced exercise's history (#162).
      await controller.replaceExercise(
        exerciseIndex: 1,
        exerciseId: 'bicep_curl',
        exerciseName: 'Bicep Curl',
      );
      // An unplanned exercise is swapped in place: it was never prescribed,
      // so there is no skipped row to keep.
      expect(controller.workout!.exercises, hasLength(2));
      final ActiveWorkoutExercise second = controller.workout!.exercises[1];
      expect(second.exerciseId, 'bicep_curl');
      expect(previousSetFor(second, 0, controller.workout!.baselines), isNull);
      expect(
        controller.workout!.baselines['bicep_curl'],
        isNull,
      );
      // The planned exercise's payload — the program's own row — is byte for
      // byte what the day carried (#162: the program never changes).
      expect(controller.workout!.exercises[0].exercise,
          _day.exercises.single.toJson());
      expect(controller.workout!.programVersion, 3);
    });

    test('Remove takes an unplanned exercise out and never a planned one',
        () async {
      final ActiveWorkoutController controller = await start(_signedInFake());
      await controller.addUnplannedExercise(
          exerciseId: 'cable_row', exerciseName: 'Cable Row');
      expect(controller.workout!.exercises, hasLength(2));

      // A planned exercise is never removable (#162).
      await controller.removeExercise(0);
      expect(controller.workout!.exercises, hasLength(2));

      // …an unplanned one is, wherever it sits.
      await controller.removeExercise(1);
      expect(controller.workout!.exercises, hasLength(1));
      expect(controller.workout!.exercises.single.exerciseId, 'bench_press');

      // After a replace, the hidden planned row still cannot be removed, but
      // the unplanned replacement can.
      await controller.replaceExercise(
        exerciseIndex: 0,
        exerciseId: 'cable_row',
        exerciseName: 'Cable Row',
      );
      await controller.removeExercise(0);
      expect(controller.workout!.exercises, hasLength(2));
      await controller.removeExercise(1);
      expect(controller.workout!.exercises, hasLength(1));
      expect(controller.workout!.exercises.single.replaced, isTrue);
    });

    test('undo replace brings the planned exercise back as an ordinary card',
        () async {
      final ActiveWorkoutController controller =
          await start(fakeWithBaselines());
      await controller.replaceExercise(
        exerciseIndex: 0,
        exerciseId: 'cable_row',
        exerciseName: 'Cable Row',
        imagePath: 'images/cable_row.jpg',
      );
      expect(controller.workout!.exercises, hasLength(2));
      expect(controller.workout!.exercises[1].unplanned, isTrue);

      await controller.undoReplace(1);

      final ActiveWorkout undone = controller.workout!;
      expect(undone.exercises, hasLength(1));
      final ActiveWorkoutExercise planned = undone.exercises.single;
      expect(planned.exerciseId, 'bench_press');
      expect(planned.replaced, isFalse);
      expect(planned.unplanned, isFalse);
      // Its rows are back — the ones it was seeded with, all empty, so
      // nothing the replace logged survives — and it is a real card again,
      // so the draft carries it exactly like any untouched planned
      // exercise: skipped until a set of it is ticked.
      expect(planned.sets, hasLength(3));
      expect(
        planned.sets.every((ActiveWorkoutSet set) =>
            set.weightKg == 0 && set.reps == 0 && !set.ticked),
        isTrue,
      );
      WorkoutDraft draft() => undone.buildWorkoutDraft(
            timezone: 'UTC',
            clientSessionId: '22222222-2222-4222-8222-222222222222',
            now: DateTime.utc(2026, 9, 28, 9),
          )!;
      expect(draft().exercises.single.skipped, isTrue);
      expect(draft().exercises.single.sets, isEmpty);

      // Logging it makes it performed — no longer skipped (#162 review).
      await controller.updateCell(0, 0, weightKg: 100, reps: 5);
      await controller.setTicked(0, 0, true);
      final WorkoutDraft logged = controller.workout!.buildWorkoutDraft(
        timezone: 'UTC',
        clientSessionId: '33333333-3333-4333-8333-333333333333',
        now: DateTime.utc(2026, 9, 28, 9),
      )!;
      expect(logged.exercises.single.skipped, isFalse);
      expect(logged.exercises.single.sets, hasLength(1));

      // The program row it started from is untouched throughout.
      expect(controller.workout!.exercises.single.exercise,
          _day.exercises.single.toJson());
      expect(controller.workout!.programVersion, 3);

      // Undo is only ever for a replacement: the planned exercise itself is
      // not one, so nothing changes.
      await controller.undoReplace(0);
      expect(controller.workout!.exercises, hasLength(1));
      expect(controller.workout!.exercises.single.replaced, isFalse);
    });

    test('a running rest for the replaced exercise stops like Skip, and one '
        'for another exercise keeps running (#162)', () async {
      final FakeRestAlerts alerts = FakeRestAlerts();
      final InMemoryTokenStore tokens = await _tokens();
      final ProviderContainer container = _container(
        fake: _signedInFake(),
        tokens: tokens,
        store: InMemoryActiveWorkoutStore(),
        cache: InMemoryBaselineCacheStore(),
        drafts: InMemoryDraftStore(),
        workoutCache: InMemoryWorkoutCacheStore(),
        extraOverrides: <Override>[
          restAlertsProvider.overrideWithValue(alerts),
        ],
      );
      final ActiveWorkoutController controller =
          container.read(activeWorkoutControllerProvider.notifier);
      await controller.startFromDay(
          accountId: _account, day: _dayTwo, programVersion: 3);

      // A working tick starts the rest for that exercise (#125).
      await controller.updateCell(0, 0, weightKg: 100, reps: 5);
      await controller.setTicked(0, 0, true);
      expect(controller.workout!.rest, isNotNull);
      expect(controller.workout!.rest!.exerciseId, 'bench_press');
      expect(alerts.shown, hasLength(1));

      // Replacing the *other* exercise leaves the countdown alone.
      await controller.replaceExercise(
        exerciseIndex: 1,
        exerciseId: 'cable_row',
        exerciseName: 'Cable Row',
      );
      expect(controller.workout!.rest, isNotNull);

      // Replacing the exercise the rest belongs to stops it with Skip's own
      // effect: the countdown is gone and the platform alerts with it.
      await controller.replaceExercise(
        exerciseIndex: 0,
        exerciseId: 'cable_row',
        exerciseName: 'Cable Row',
      );
      expect(controller.workout!.rest, isNull);
      expect(alerts.removeCalls, greaterThanOrEqualTo(1));
      expect(alerts.cancelEndCalls, greaterThanOrEqualTo(1));
      expect((await container.read(activeWorkoutStoreProvider).read(_account))!
          .rest,
          isNull);
    });

    test('re-picking the exercise being replaced changes nothing (#162)',
        () async {
      final ActiveWorkoutController controller = await start(_signedInFake());
      await controller.replaceExercise(
        exerciseIndex: 0,
        exerciseId: 'bench_press',
        exerciseName: 'Bench Press',
      );
      expect(controller.workout!.exercises, hasLength(1));
      expect(controller.workout!.exercises.single.replaced, isFalse);
      expect(controller.workout!.exercises.single.sets, hasLength(3));
    });
  });

  group('card lines (#158)', () {
    ActiveWorkoutExercise exerciseOf({
      int targetSets = 3,
      int effectiveSets = 3,
      int minReps = 6,
      int maxReps = 8,
      double targetRpe = 8.0,
      double? projectedWeightKg = 62.5,
      List<ActiveWorkoutSet>? sets,
    }) =>
        ActiveWorkoutExercise(
          exercise: <String, dynamic>{
            'exercise_id': 'hack_squat',
            'exercise_name': 'Hack Squat',
            'target_sets': targetSets,
            'target_reps_min': minReps,
            'target_reps_max': maxReps,
            'target_rpe': targetRpe,
          },
          sets: sets ??
              <ActiveWorkoutSet>[
                for (int i = 0; i < effectiveSets; i++) ActiveWorkoutSet(),
              ],
          effectiveSets: effectiveSets,
          prescriptionHint: PrescriptionHint(
            weightKg: projectedWeightKg,
            reps: minReps,
            rir: rirFromRpe(targetRpe),
          ),
        );

    test('the line uses the effective sets and the frozen projection (#108)',
        () {
      // Three sets prescribed, four seeded: the card says four.
      final ActiveWorkoutExercise exercise =
          exerciseOf(targetSets: 3, effectiveSets: 4);
      expect(exercise.effectiveSetCount, 4);
      expect(
        exercisePrescriptionLine(exercise, restSeconds: 120),
        '4 sets · 6–8 reps · 62.5 kg · RIR ≥ 2 · Rest 2:00',
      );
    });

    test('one set reads "1 set", and Rest Off keeps the chip words', () {
      final ActiveWorkoutExercise exercise = exerciseOf(
        effectiveSets: 1,
        minReps: 8,
        maxReps: 12,
        projectedWeightKg: null,
      );
      expect(
        exercisePrescriptionLine(exercise, restSeconds: 180),
        '1 set · 8–12 reps · RIR ≥ 2 · Rest 3:00',
      );
      expect(
        exercisePrescriptionLine(exercise, restSeconds: 0),
        '1 set · 8–12 reps · RIR ≥ 2 · Rest Off',
      );
    });

    test('a workout stored before effective sets was kept falls back to the '
        'program target', () {
      final ActiveWorkoutExercise legacy = ActiveWorkoutExercise(
        exercise: <String, dynamic>{
          'exercise_id': 'hack_squat',
          'exercise_name': 'Hack Squat',
          'target_sets': 3,
          'target_reps_min': 6,
          'target_reps_max': 8,
          'target_rpe': 8.5,
        },
        sets: <ActiveWorkoutSet>[
          ActiveWorkoutSet(),
          ActiveWorkoutSet(),
          ActiveWorkoutSet(),
        ],
      );
      expect(legacy.effectiveSetCount, 3);
      expect(
        exercisePrescriptionLine(legacy, restSeconds: 120),
        '3 sets · 6–8 reps · RIR ≥ 2 · Rest 2:00',
      );
    });

    test('the caption helper formats every clause, and only those present',
        () {
      expect(
        prescriptionCaption(
          setCount: 4,
          minReps: 6,
          maxReps: 8,
          projectedWeightKg: 62.5,
          rir: 2.0,
        ),
        '4 sets · 6–8 reps · 62.5 kg · RIR ≥ 2',
      );
      // No projection, no rep window: the bare minimum still reads right.
      expect(prescriptionCaption(setCount: 1, minReps: 0, maxReps: 0),
          '1 set');
    });

    test('the Last: line reads a bodyweight set as BW, never 0kg', () {
      expect(
        lastSessionLabel(const <BaselineSet>[
          BaselineSet(weightKg: 60, reps: 6),
          BaselineSet(weightKg: 0, reps: 10),
        ]),
        'Last: 60kg × 6 · BW × 10',
      );
    });
  });

  group('Current set (#158)', () {
    /// Two exercises worth of rows, straight into the model: the Current set
    /// is a pure derivation, so it needs no controller, no store and no API.
    ActiveWorkout workoutOf(List<List<ActiveWorkoutSet>> exercises) =>
        ActiveWorkout(
          id: 'aw-current',
          accountId: _account,
          startedAt: '2026-09-28T08:00:00.000Z',
          dayOrder: 2,
          dayName: 'Upper A',
          programVersion: 3,
          exercises: <ActiveWorkoutExercise>[
            for (int i = 0; i < exercises.length; i++)
              ActiveWorkoutExercise(
                exercise: <String, dynamic>{
                  'exercise_id': 'exercise_$i',
                  'exercise_name': 'Exercise $i',
                },
                sets: exercises[i],
              ),
          ],
          baselines: const <String, BaselineExercise>{},
        );

    test('is the first unticked working set of the first exercise', () {
      final ActiveWorkout workout = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(),
          ActiveWorkoutSet(),
        ],
        <ActiveWorkoutSet>[ActiveWorkoutSet()],
      ]);
      expect(currentSetOf(workout), (exerciseIndex: 0, setIndex: 0));
    });

    test('skips warm-ups and keeps counting past them', () {
      final ActiveWorkout workout = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(isWarmup: true),
          ActiveWorkoutSet(isWarmup: true),
          ActiveWorkoutSet(),
          ActiveWorkoutSet(),
        ],
      ]);
      expect(currentSetOf(workout), (exerciseIndex: 0, setIndex: 2));

      // A ticked warm-up changes nothing: warm-ups are never current.
      final ActiveWorkout ticked = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(isWarmup: true, ticked: true),
          ActiveWorkoutSet(),
        ],
      ]);
      expect(currentSetOf(ticked), (exerciseIndex: 0, setIndex: 1));
    });

    test('follows the ticks down the exercise and across to the next one',
        () {
      final ActiveWorkout workout = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(ticked: true),
          ActiveWorkoutSet(),
          ActiveWorkoutSet(),
        ],
        <ActiveWorkoutSet>[ActiveWorkoutSet()],
      ]);
      expect(currentSetOf(workout), (exerciseIndex: 0, setIndex: 1));

      final ActiveWorkout nextExercise = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(ticked: true),
          ActiveWorkoutSet(ticked: true),
          ActiveWorkoutSet(ticked: true),
        ],
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(isWarmup: true),
          ActiveWorkoutSet(),
        ],
      ]);
      expect(currentSetOf(nextExercise), (exerciseIndex: 1, setIndex: 1));

      // Ticks are reversible: unticking points the highlight back.
      final ActiveWorkout unticked = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[ActiveWorkoutSet()],
        <ActiveWorkoutSet>[ActiveWorkoutSet(ticked: true)],
      ]);
      expect(currentSetOf(unticked), (exerciseIndex: 0, setIndex: 0));
    });

    test('is null once every working set is ticked', () {
      final ActiveWorkout done = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(ticked: true),
          ActiveWorkoutSet(isWarmup: true),
          ActiveWorkoutSet(ticked: true),
        ],
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(ticked: true),
        ],
      ]);
      expect(currentSetOf(done), isNull);
    });

    test('an empty workout has no current set at all', () {
      final ActiveWorkout empty =
          workoutOf(<List<ActiveWorkoutSet>>[<ActiveWorkoutSet>[]]);
      expect(currentSetOf(empty), isNull);
    });
  });

  group('Workout progress (#159)', () {
    /// Straight into the model, like the Current set's group: the counts are
    /// a pure derivation, so they need no controller, store or API.
    ActiveWorkout workoutOf(List<List<ActiveWorkoutSet>> exercises) =>
        ActiveWorkout(
          id: 'aw-progress',
          accountId: _account,
          startedAt: '2026-09-28T08:00:00.000Z',
          dayOrder: 2,
          dayName: 'Upper A',
          programVersion: 3,
          exercises: <ActiveWorkoutExercise>[
            for (int i = 0; i < exercises.length; i++)
              ActiveWorkoutExercise(
                exercise: <String, dynamic>{
                  'exercise_id': 'exercise_$i',
                  'exercise_name': 'Exercise $i',
                },
                sets: exercises[i],
              ),
          ],
          baselines: const <String, BaselineExercise>{},
        );

    test('counts working sets only — warm-ups are excluded on both sides',
        () {
      final ActiveWorkout workout = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          // A ticked warm-up contributes to neither count.
          ActiveWorkoutSet(isWarmup: true, ticked: true),
          ActiveWorkoutSet(),
          ActiveWorkoutSet(ticked: true),
        ],
        <ActiveWorkoutSet>[ActiveWorkoutSet()],
      ]);
      expect(
        workoutProgressOf(workout),
        (
          exercisesCompleted: 0,
          exercisesTotal: 2,
          setsTicked: 1,
          setsTotal: 3,
        ),
      );
    });

    test('an exercise completes only when all its working sets are ticked',
        () {
      final ActiveWorkout oneOfThree = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(ticked: true),
          ActiveWorkoutSet(),
          ActiveWorkoutSet(),
        ],
        <ActiveWorkoutSet>[ActiveWorkoutSet(ticked: true)],
      ]);
      // One of three is not done, but the finished second exercise is.
      expect(
        workoutProgressOf(oneOfThree),
        (
          exercisesCompleted: 1,
          exercisesTotal: 2,
          setsTicked: 2,
          setsTotal: 4,
        ),
      );

      final ActiveWorkout done = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(ticked: true),
          ActiveWorkoutSet(ticked: true),
          ActiveWorkoutSet(ticked: true),
        ],
        <ActiveWorkoutSet>[ActiveWorkoutSet(ticked: true)],
      ]);
      expect(workoutProgressOf(done).exercisesCompleted, 2);
      expect(workoutProgressOf(done).setsTicked, 4);
    });

    test('an exercise with no working rows is excluded from the counts', () {
      final ActiveWorkout workout = workoutOf(<List<ActiveWorkoutSet>>[
        // Every row warm-up: not a to-do, so it is out of the denominator
        // entirely — progress can still reach its N/N (#159).
        <ActiveWorkoutSet>[
          ActiveWorkoutSet(isWarmup: true, ticked: true),
          ActiveWorkoutSet(isWarmup: true, ticked: true),
        ],
        <ActiveWorkoutSet>[ActiveWorkoutSet(ticked: true)],
      ]);
      expect(
        workoutProgressOf(workout),
        (
          exercisesCompleted: 1,
          exercisesTotal: 1,
          setsTicked: 1,
          setsTotal: 1,
        ),
      );
    });

    test('a fresh workout starts at zero', () {
      final ActiveWorkout workout = workoutOf(<List<ActiveWorkoutSet>>[
        <ActiveWorkoutSet>[ActiveWorkoutSet(), ActiveWorkoutSet()],
      ]);
      expect(
        workoutProgressOf(workout),
        (
          exercisesCompleted: 0,
          exercisesTotal: 1,
          setsTicked: 0,
          setsTotal: 2,
        ),
      );
    });
  });

  group('Workout time (#159)', () {
    test('formats as mm:ss, and h:mm:ss once it passes an hour', () {
      expect(formatWorkoutTime(Duration.zero), '00:00');
      expect(formatWorkoutTime(const Duration(seconds: 5)), '00:05');
      expect(formatWorkoutTime(const Duration(seconds: 90)), '01:30');
      expect(formatWorkoutTime(const Duration(minutes: 5)), '05:00');
      expect(formatWorkoutTime(const Duration(minutes: 59, seconds: 30)),
          '59:30');
      expect(formatWorkoutTime(const Duration(hours: 1)), '1:00:00');
      expect(
        formatWorkoutTime(const Duration(hours: 1, minutes: 2, seconds: 3)),
        '1:02:03',
      );
      expect(
        formatWorkoutTime(const Duration(hours: 12, minutes: 4, seconds: 5)),
        '12:04:05',
      );
    });

    test('never reads a negative time', () {
      expect(formatWorkoutTime(const Duration(seconds: -30)), '00:00');
    });

    test('is derived from the start time, so a restart reads the same clock',
        () {
      final ActiveWorkout workout = ActiveWorkout(
        id: 'aw-time',
        accountId: _account,
        startedAt: '2026-09-28T08:00:00.000Z',
        dayOrder: 2,
        dayName: 'Upper A',
        programVersion: 3,
        exercises: const <ActiveWorkoutExercise>[],
        baselines: const <String, BaselineExercise>{},
      );
      expect(
        workoutElapsed(workout,
            now: DateTime.parse('2026-09-28T08:01:30.000Z')),
        const Duration(minutes: 1, seconds: 30),
      );
      // Nothing resets it: an hour on, the same stored start answers.
      expect(
        workoutElapsed(workout, now: DateTime.parse('2026-09-28T09:00:00.000Z')),
        const Duration(hours: 1),
      );
      // A clock behind the start clamps rather than going negative.
      expect(
        workoutElapsed(workout,
            now: DateTime.parse('2026-09-28T07:59:00.000Z')),
        Duration.zero,
      );
    });
  });

  group('store writes are serialized (#123 item 5)', () {
    test('writes land in state order and the latest state wins', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final _LatencyStore store = _LatencyStore(<Duration>[
        const Duration(milliseconds: 40),
        const Duration(milliseconds: 5),
        const Duration(milliseconds: 0),
      ]);
      final ProviderContainer container = ProviderContainer(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(await _tokens()),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          baselineCacheStoreProvider
              .overrideWithValue(InMemoryBaselineCacheStore()),
          activeWorkoutStoreProvider.overrideWithValue(store),
          apiClientProvider.overrideWith(
              (Ref ref) => _api(fake, ref.watch(tokenStoreProvider))),
        ],
      );
      addTearDown(container.dispose);
      final ActiveWorkoutController controller =
          container.read(activeWorkoutControllerProvider.notifier);
      await controller.startFromDay(
          accountId: _account, day: _day, programVersion: 3);

      // Three changes in a row: the first write is the slowest, so an
      // unserialized queue would leave the stored copy at reps 0 or 1.
      await Future.wait(<Future<void>>[
        controller.updateCell(0, 0, reps: 1),
        controller.updateCell(0, 0, reps: 2),
        controller.updateCell(0, 0, reps: 3),
      ]);

      expect(store.landed, <int>[0, 1, 2, 3]);
      expect(store.latest, isNotNull);
      expect(store.latest!.exercises.single.sets.first.reps, 3);
      expect(controller.workout!.exercises.single.sets.first.reps, 3);
    });

    test('discard waits for the pending write and then deletes', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final _LatencyStore store =
          _LatencyStore(<Duration>[const Duration(milliseconds: 60)]);
      final ProviderContainer container = ProviderContainer(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(await _tokens()),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          baselineCacheStoreProvider
              .overrideWithValue(InMemoryBaselineCacheStore()),
          activeWorkoutStoreProvider.overrideWithValue(store),
          apiClientProvider.overrideWith(
              (Ref ref) => _api(fake, ref.watch(tokenStoreProvider))),
        ],
      );
      addTearDown(container.dispose);
      final ActiveWorkoutController controller =
          container.read(activeWorkoutControllerProvider.notifier);
      await controller.startFromDay(
          accountId: _account, day: _day, programVersion: 3);

      // A write is in flight when the player discards: the delete must land
      // after it, never before it.
      final Future<void> inFlight = controller.updateCell(0, 0, reps: 7);
      await controller.discard(accountId: _account);
      await inFlight;

      expect(store.deleted, isTrue);
      expect(store.wroteAfterDelete, isFalse);
      expect(store.latest, isNull);
      expect(controller.hasActive, isFalse);
      expect(await store.read(_account), isNull);
    });

    test('discard only clears the workout it belongs to', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final ProviderContainer container = _container(
        fake: fake,
        tokens: await _tokens(),
        store: store,
        cache: InMemoryBaselineCacheStore(),
        drafts: InMemoryDraftStore(),
        workoutCache: InMemoryWorkoutCacheStore(),
      );
      final ActiveWorkoutController controller =
          container.read(activeWorkoutControllerProvider.notifier);
      await controller.startFromDay(
          accountId: _account, day: _day, programVersion: 3);
      final String id = controller.workout!.id;

      // Wrong account: no-op.
      await controller.discard(accountId: 'account-bob');
      expect(controller.hasActive, isTrue);
      // Wrong workout id: no-op.
      await controller.discard(accountId: _account, workoutId: 'aw-other');
      expect(controller.hasActive, isTrue);
      expect(await store.read(_account), isNotNull);

      // The right account and workout: cleared.
      await controller.discard(accountId: _account, workoutId: id);
      expect(controller.hasActive, isFalse);
      expect(await store.read(_account), isNull);
    });

    test('a start that spans a sign-out aborts and persists nothing', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final ProviderContainer container = _container(
        fake: fake,
        tokens: await _tokens(),
        store: store,
        cache: InMemoryBaselineCacheStore(),
        drafts: InMemoryDraftStore(),
        workoutCache: InMemoryWorkoutCacheStore(),
      );
      final ActiveWorkoutController controller =
          container.read(activeWorkoutControllerProvider.notifier);
      await controller.syncAccount(_account);

      // Pause the baseline fetch the start is waiting on…
      final Completer<void> gate = Completer<void>();
      fake.adapter.beforeRespond = (FakeRequest request) =>
          request.path == '/workouts/baselines'
              ? gate.future
              : Future<void>.value();

      final Future<StartWorkoutOutcome> pending = controller.startFromDay(
          accountId: _account, day: _day, programVersion: 3);
      for (int i = 0; i < 5; i++) {
        await Future<void>.delayed(Duration.zero);
      }

      // …and the account signs out while it is paused.
      await controller.syncAccount(null);
      gate.complete();
      final StartWorkoutOutcome outcome = await pending;

      expect(outcome, StartWorkoutOutcome.aborted);
      expect(controller.hasActive, isFalse);
      expect(controller.workout, isNull);
      expect(controller.state.accountId, isNull);
      expect(await store.read(_account), isNull);
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

    test('falls back to empty when there is neither fetch nor cache', () async {
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

    test('a fresh fetch that never answers falls back within the timeout',
        () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryBaselineCacheStore cache = InMemoryBaselineCacheStore();
      await cache.write(
        _account,
        <BaselineExercise>[BaselineExercise.fromJson(_baselineRow())],
      );
      final BaselinesService service = BaselinesService(
        api: _api(fake, await _tokens()),
        cache: cache,
        drafts: InMemoryDraftStore(),
        freshTimeout: const Duration(milliseconds: 50),
      );
      // The adapter never answers this request: only an overall deadline
      // (connect *and* receive) can end it (#123 item 8).
      fake.adapter.beforeRespond = (FakeRequest request) =>
          request.path == '/workouts/baselines'
              ? Completer<void>().future
              : Future<void>.value();

      final BaselineResolution resolved =
          await service.resolveForStart(_account);

      expect(resolved.source, BaselineSource.cache);
      expect(resolved.baselines.single.exerciseId, 'bench_press');
      // The request was issued (and recorded) but never answered, so only an
      // overall deadline could have ended it.
      expect(
        fake.adapter.requests
            .where(
                (FakeRequest request) => request.path == '/workouts/baselines')
            .length,
        1,
      );
    });

    test('folds the player unsynced drafts into the frozen baseline', () async {
      final FakeMayosApi fake = _signedInFake();
      fake.baselinesBody = <Map<String, dynamic>>[_baselineRow()];
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      await drafts.write(_account, <WorkoutDraft>[
        _unsyncedDraft(sets: const <WorkoutSetLog>[
          WorkoutSetLog(weightKg: 120, reps: 3, rpe: 9.0),
          WorkoutSetLog(weightKg: 40, reps: 10, rpe: 8.0, isWarmup: true),
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

      final BaselineExercise bench = resolved.baselines
          .firstWhere((BaselineExercise b) => b.exerciseId == 'bench_press');
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
      List<ActiveWarmupMovement> warmupMovements =
          const <ActiveWarmupMovement>[],
    }) =>
        ActiveWorkout(
          id: 'aw-1',
          accountId: _account,
          startedAt: '2026-09-28T08:00:00.000Z',
          dayOrder: 2,
          dayName: 'Upper A',
          programVersion: programVersion,
          exercises: exercises,
          warmupMovements: warmupMovements,
          baselines: const <String, BaselineExercise>{},
        );

    test('commits only ticked Warm-up sets separately in direct and draft bodies',
        () {
      final ActiveWorkout workout = workoutWith(
        <ActiveWorkoutExercise>[
          ActiveWorkoutExercise(
            exercise: _plannedExerciseJson,
            sets: <ActiveWorkoutSet>[
              ActiveWorkoutSet(weightKg: 100, reps: 5, ticked: true),
              ActiveWorkoutSet(),
            ],
          ),
        ],
        warmupMovements: <ActiveWarmupMovement>[
          ActiveWarmupMovement(
            exerciseName: 'Cat-Cow',
            sets: const <ActiveWarmupSet>[
              ActiveWarmupSet(reps: 10, ticked: true),
              ActiveWarmupSet(reps: 10),
            ],
          ),
          ActiveWarmupMovement(
            exerciseId: 'band_pull_apart',
            exerciseName: 'Band Pull-Apart',
            sets: const <ActiveWarmupSet>[ActiveWarmupSet(reps: 12)],
          ),
        ],
      );
      final Map<String, dynamic> direct = workout.copyWith(
        clientSessionId: 'fixed-session',
      ).buildCommitBody(
        timezone: 'UTC',
        now: now,
      )!;
      expect(direct['sets'], hasLength(1));
      expect(currentSetOf(workout), (exerciseIndex: 0, setIndex: 1));
      expect(workoutProgressOf(workout).setsTotal, 2);
      expect(workoutProgressOf(workout).setsTicked, 1);
      expect(workoutSummaryStats(workout).workingSets, 1);
      expect(workoutSummaryStats(workout).totalVolumeKg, 500);
      expect(direct['warmup_movements'], <Map<String, dynamic>>[
        <String, dynamic>{
          'exercise_id': null,
          'exercise_name': 'Cat-Cow',
          'sets': <Map<String, dynamic>>[
            <String, dynamic>{'weight_kg': null, 'reps': 10},
          ],
        },
      ]);

      final WorkoutDraft draft = workout.buildWorkoutDraft(
        timezone: 'UTC',
        clientSessionId: 'fixed-session',
        now: now,
      )!;
      expect(draft.toCommitBody()['warmup_movements'], direct['warmup_movements']);
      final WorkoutDraft restored = WorkoutDraft.fromJson(draft.toJson());
      expect(restored.warmupMovements, hasLength(2));
      expect(restored.warmupMovements.first.sets.first.ticked, isTrue);
      expect(restored.warmupMovements.first.sets[1].ticked, isFalse);
      expect(restored.warmupMovements[1].sets.single.ticked, isFalse);
      expect(restored.toCommitBody()['warmup_movements'],
          direct['warmup_movements']);
    });

    test('is identical to what the logger builds for the same input', () {
      // Every set ticked: the same input the current logger would send with
      // its skip checkboxes unticked.
      final ActiveWorkout workout = workoutWith(<ActiveWorkoutExercise>[
        ActiveWorkoutExercise(
          exercise: _plannedExerciseJson,
          targetLabel: '2 × 5–8 @ RIR ≥ 2',
          sets: <ActiveWorkoutSet>[
            ActiveWorkoutSet(weightKg: 100, reps: 5, rir: 1, ticked: true),
            ActiveWorkoutSet(
                weightKg: 40, reps: 10, rir: 2, isWarmup: true, ticked: true),
            ActiveWorkoutSet(weightKg: 100, reps: 5, rir: 1, ticked: true),
          ],
        ),
        ActiveWorkoutExercise(
          exercise: _unplannedExerciseJson,
          unplanned: true,
          sets: <ActiveWorkoutSet>[
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
              WorkoutSetLog(weightKg: 40, reps: 10, rpe: 8.0, isWarmup: true),
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
          sets: <ActiveWorkoutSet>[
            // Unticked with values: never logged.
            ActiveWorkoutSet(weightKg: 100, reps: 5, rir: 1),
            ActiveWorkoutSet(weightKg: 90, reps: 5, rir: 2, ticked: true),
          ],
        ),
        ActiveWorkoutExercise(
          exercise: _unplannedExerciseJson,
          unplanned: true,
          sets: <ActiveWorkoutSet>[
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

    test('an unrated ticked set is committed as rpe null, never a default',
        () {
      final ActiveWorkout workout = workoutWith(<ActiveWorkoutExercise>[
        ActiveWorkoutExercise(
          exercise: _plannedExerciseJson,
          sets: <ActiveWorkoutSet>[
            ActiveWorkoutSet(weightKg: 90, reps: 5, ticked: true),
            ActiveWorkoutSet(weightKg: 90, reps: 5, rir: 5, ticked: true),
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
      final List<WorkoutSetLog> sets = built!.exercises.single.sets;
      expect(sets, hasLength(2));
      // Blank effort stays blank through the draft (#111).
      expect(sets.first.rpe, isNull);
      // RIR 5 is RPE 5 — the old [6, 10] clamp no longer lifts it to 6.
      expect(sets.last.rpe, 5.0);

      // The wire keeps the key and sends null, which the service's optional
      // `WorkoutSetIn.rpe` accepts as "not rated".
      final Map<String, dynamic> body = built.toCommitBody();
      final Map<String, dynamic> exercise =
          (body['sets'] as List<dynamic>).first as Map<String, dynamic>;
      final List<dynamic> payload = exercise['sets'] as List<dynamic>;
      expect((payload.first as Map<String, dynamic>).containsKey('rpe'), isTrue);
      expect((payload.first as Map<String, dynamic>)['rpe'], isNull);
      expect((payload.last as Map<String, dynamic>)['rpe'], 5.0);
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
