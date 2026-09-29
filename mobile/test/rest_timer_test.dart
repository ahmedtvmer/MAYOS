import 'dart:async';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/baseline_service.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/rest_alerts.dart';
import 'package:mayos_mobile/src/core/rest_length.dart';
import 'package:mayos_mobile/src/core/secure_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';

import 'support/fake_clock.dart';
import 'support/fake_rest_alerts.dart';

const String _account = 'acct-1';
const String _otherAccount = 'acct-2';

/// The exercise payload with a program rest of 180 (#125's "program value").
const Map<String, dynamic> _benchJson = <String, dynamic>{
  'exercise_id': 'bench_press',
  'exercise_name': 'Bench Press',
  'target_sets': 3,
  'target_reps_min': 5,
  'target_reps_max': 8,
  'target_rpe': 8.5,
  'warmup_sets': 0,
  'rest_seconds': 180,
  'notes': null,
};

/// The exercise payload exactly as `ProgramExercise.toJson` writes one whose
/// program carried no `rest_seconds`: the key is absent (#125), so it must
/// resolve to the flat 2:00 rather than a phantom 3:00.
const Map<String, dynamic> _rowJson = <String, dynamic>{
  'exercise_id': 'cable_row',
  'exercise_name': 'Cable Row',
  'target_sets': 3,
  'target_reps_min': 8,
  'target_reps_max': 12,
  'target_rpe': 8.0,
  'warmup_sets': 0,
  'notes': null,
};

ActiveWorkout _workout() => ActiveWorkout(
  id: 'aw-1',
  accountId: _account,
  startedAt: '2026-09-29T08:00:00.000Z',
  dayOrder: 2,
  dayName: 'Upper A',
  programVersion: 3,
  exercises: <ActiveWorkoutExercise>[
    ActiveWorkoutExercise(
      exercise: _benchJson,
      sets: <ActiveWorkoutSet>[ActiveWorkoutSet(), ActiveWorkoutSet()],
    ),
    ActiveWorkoutExercise(
      exercise: _rowJson,
      sets: <ActiveWorkoutSet>[ActiveWorkoutSet()],
    ),
  ],
  baselines: <String, BaselineExercise>{},
);

/// The same workout with the frozen baseline Bench ticks from: two working
/// sets, so "last" in the notification line reads that next set's baseline
/// value (#125).
ActiveWorkout _workoutWithBaselines() => ActiveWorkout(
  id: 'aw-1',
  accountId: _account,
  startedAt: '2026-09-29T08:00:00.000Z',
  dayOrder: 2,
  dayName: 'Upper A',
  programVersion: 3,
  exercises: <ActiveWorkoutExercise>[
    ActiveWorkoutExercise(
      exercise: _benchJson,
      sets: <ActiveWorkoutSet>[ActiveWorkoutSet(), ActiveWorkoutSet()],
    ),
    ActiveWorkoutExercise(
      exercise: _rowJson,
      sets: <ActiveWorkoutSet>[ActiveWorkoutSet()],
    ),
  ],
  baselines: <String, BaselineExercise>{
    'bench_press': const BaselineExercise(
      exerciseId: 'bench_press',
      sessionsLogged: 3,
      maxWeightKg: 100,
      bestE1rmKg: 121.67,
      lastSession: BaselineLastSession(
        performedDate: '2026-09-26',
        sets: <BaselineSet>[
          BaselineSet(weightKg: 100, reps: 5, rir: 1),
          BaselineSet(weightKg: 95, reps: 6, rir: 2),
        ],
      ),
    ),
  },
);

ActiveWorkoutController _controller({
  required ActiveWorkoutStore store,
  required RestLengthStore restLengths,
  required RestAlerts alerts,
  required DateTime Function() now,
}) {
  final ApiClient api = ApiClient(
    tokens: InMemoryTokenStore(),
    baseUrl: 'http://test.local',
  );
  return ActiveWorkoutController(
    store: store,
    baselines: BaselinesService(
      api: api,
      cache: InMemoryBaselineCacheStore(),
      drafts: InMemoryDraftStore(),
    ),
    restLengths: restLengths,
    alerts: alerts,
    now: now,
  );
}

/// Lets the detached microtasks the Android seam schedules (permission ask,
/// secure flag write) run to completion before a test asserts on them.
Future<void> _flush() async {
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
}

/// A [SecureStore] that never touches the platform channel: the permission
/// policy test drives the ask-once flag through plain memory.
class _MemorySecureStore extends SecureStore {
  final Map<String, String> values = <String, String>{};

  @override
  Future<String?> readString(String key) async => values[key];

  @override
  Future<void> writeString(String key, String value) async {
    values[key] = value;
  }
}

void main() {
  group('rest length resolution (#125)', () {
    test('a missing rest_seconds in ProgramExercise is unset, not 180', () {
      final ProgramExercise missing = ProgramExercise.fromJson(
        <String, dynamic>{
          'exercise_id': 'cable_row',
          'exercise_name': 'Cable Row',
        },
      );
      expect(missing.restSeconds, isNull);
      expect(missing.restSecondsOrDefault, kDefaultRestSeconds);
      // Unset stays unset through the round trip: no phantom 180 is written
      // back into the Active workout or the draft.
      expect(missing.toJson().containsKey('rest_seconds'), isFalse);
      expect(missing.restLabel, 'rest ${kDefaultRestSeconds}s');

      // A program that did carry a value keeps it, key and all.
      final ProgramExercise given = ProgramExercise.fromJson(<String, dynamic>{
        'exercise_id': 'bench_press',
        'exercise_name': 'Bench Press',
        'rest_seconds': 180,
      });
      expect(given.restSeconds, 180);
      expect(given.restSecondsOrDefault, 180);
      expect(given.toJson()['rest_seconds'], 180);
      expect(given.restLabel, 'rest 180s');
    });

    test('resolution: program value, missing → 2:00, device override per '
        'account', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final InMemoryRestLengthStore restLengths = InMemoryRestLengthStore();
      await store.write(_account, _workout());

      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: restLengths,
        alerts: FakeRestAlerts(),
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
      );
      await controller.syncAccount(_account);

      // Program value for the planned exercise…
      expect(controller.restLengthFor(0), 180);
      // …the flat 2:00 when the program carried none…
      expect(controller.restLengthFor(1), kDefaultRestSeconds);
      expect(restMmSs(controller.restLengthFor(1)), '2:00');

      // …and the device override wins over both, for that exercise only.
      await controller.setRestLength(1, 75);
      expect(controller.restLengthFor(1), 75);
      expect(controller.restLengthFor(0), 180);

      // Remembered per account on this device: another account sharing the
      // store never inherits it…
      final ActiveWorkoutController other = _controller(
        store: store,
        restLengths: restLengths,
        alerts: FakeRestAlerts(),
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
      );
      await other.syncAccount(_otherAccount);
      expect(other.restLengthFor(1), kDefaultRestSeconds);

      // …and a fresh controller for the same account reads it back (the
      // override outlives a restart). The device store loads beside the
      // restore, so the test gives that detached read a turn to land.
      final ActiveWorkoutController restarted = _controller(
        store: store,
        restLengths: restLengths,
        alerts: FakeRestAlerts(),
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
      );
      await restarted.syncAccount(_account);
      await Future<void>.delayed(Duration.zero);
      expect(restarted.restLengthFor(1), 75);

      // Off is a device override like any other, and it wins outright.
      await controller.setRestLength(1, 0);
      expect(controller.restLengthFor(1), 0);
    });
  });

  group('rest timer start (#125)', () {
    test(
      'ticking a working set starts the timer and alerts the seam',
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final FakeRestAlerts alerts = FakeRestAlerts();
        DateTime now = DateTime.utc(2026, 9, 29, 10);
        await store.write(_account, _workout());
        final ActiveWorkoutController controller = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: () => now,
        );
        await controller.syncAccount(_account);

        await controller.updateCell(0, 0, weightKg: 100, reps: 5, rir: 1);
        await controller.setTicked(0, 0, true);

        final ActiveRestTimer? rest = controller.workout!.rest;
        expect(rest, isNotNull);
        expect(rest!.totalSeconds, 180);
        expect(
          rest.endsAt,
          now.add(const Duration(seconds: 180)).toUtc().toIso8601String(),
        );
        expect(rest.exerciseName, 'Bench Press');
        expect(rest.setNumber, 1);
        expect(rest.lastLabel, '100 × 5 @1');

        // The end time is stored in the Active workout (it survives a restart).
        final ActiveWorkout? stored = await store.read(_account);
        expect(stored!.rest, isNotNull);
        expect(stored.rest!.endsAt, rest.endsAt);

        // The seam was prepared and got the notification + alarm to post.
        expect(alerts.ensureReadyCalls, 1);
        expect(alerts.shown, hasLength(1));
        // The line describes the NEXT set to do — Bench's second row, with no
        // baseline for this workout — not the row just ticked (#125).
        expect(alerts.shown.single.line, 'Next: Bench Press · set 2');
        expect(alerts.scheduled, hasLength(1));
        expect(alerts.scheduled.single.endsAt, rest.endsAtClock(now));
      },
    );

    test('a later tick restarts it with the new end time', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final FakeRestAlerts alerts = FakeRestAlerts();
      DateTime now = DateTime.utc(2026, 9, 29, 10);
      await store.write(_account, _workout());
      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: InMemoryRestLengthStore(),
        alerts: alerts,
        now: () => now,
      );
      await controller.syncAccount(_account);

      await controller.setTicked(0, 0, true);
      expect(
        controller.workout!.rest!.endsAt,
        now.add(const Duration(seconds: 180)).toUtc().toIso8601String(),
      );

      // Thirty seconds later another working set ticks: the timer restarts
      // from *then*, and the notification and alarm are posted again.
      now = now.add(const Duration(seconds: 30));
      await controller.updateCell(0, 1, weightKg: 90, reps: 6);
      await controller.setTicked(0, 1, true);

      final ActiveRestTimer rest = controller.workout!.rest!;
      expect(
        rest.endsAt,
        now.add(const Duration(seconds: 180)).toUtc().toIso8601String(),
      );
      expect(rest.setNumber, 2);
      expect(rest.lastLabel, '90 × 6');
      expect(alerts.shown, hasLength(2));
      expect(alerts.scheduled, hasLength(2));
      expect(alerts.shown.last.endsAt, rest.endsAtClock(now));
      expect(alerts.scheduled.last.endsAt, rest.endsAtClock(now));
    });

    test('a warm-up tick and an Off rest never start the timer', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final FakeRestAlerts alerts = FakeRestAlerts();
      await store.write(_account, _workout());
      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: InMemoryRestLengthStore(),
        alerts: alerts,
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
      );
      await controller.syncAccount(_account);

      // A warm-up row is not a working set (#125): no timer, no alerts.
      await controller.toggleWarmup(0, 0);
      await controller.setTicked(0, 0, true);
      expect(controller.workout!.exercises[0].sets[0].ticked, isTrue);
      expect(controller.workout!.rest, isNull);
      expect(alerts.shown, isEmpty);
      expect(alerts.ensureReadyCalls, 0);

      // Off (0) for the second exercise: the tick still lands, the timer
      // still does not start.
      await controller.setRestLength(1, 0);
      await controller.setTicked(1, 0, true);
      expect(controller.workout!.exercises[1].sets[0].ticked, isTrue);
      expect(controller.workout!.rest, isNull);
      expect(alerts.shown, isEmpty);
      expect(alerts.ensureReadyCalls, 0);
    });

    test(
      'the alert line describes the NEXT set, not the one just ticked',
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final FakeRestAlerts alerts = FakeRestAlerts();
        final DateTime now = DateTime.utc(2026, 9, 29, 10);
        await store.write(_account, _workoutWithBaselines());
        final ActiveWorkoutController controller = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: () => now,
        );
        await controller.syncAccount(_account);

        // Ticking Bench set 1: the next thing to do is Bench set 2, whose
        // "last" is that set's own baseline value — not the row just ticked.
        await controller.setTicked(0, 0, true);
        expect(
          alerts.shown.single.line,
          'Next: Bench Press · set 2 · last 95 × 6 @2',
        );
        // The rest itself still remembers the row that started it.
        expect(controller.workout!.rest!.setNumber, 1);

        // The last row of Bench is ticked: the next set is the following
        // exercise's first, and with no baseline for it the "last" part is
        // omitted rather than guessed.
        await controller.setTicked(0, 1, true);
        expect(alerts.shown.last.line, 'Next: Cable Row · set 1');
      },
    );
  });

  group('rest timer adjust and end (#125)', () {
    test('−15 and +15 reschedule the notification and the alarm', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final FakeRestAlerts alerts = FakeRestAlerts();
      final DateTime now = DateTime.utc(2026, 9, 29, 10);
      await store.write(_account, _workout());
      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: InMemoryRestLengthStore(),
        alerts: alerts,
        now: () => now,
      );
      await controller.syncAccount(_account);
      await controller.setTicked(0, 0, true);
      expect(alerts.shown, hasLength(1));
      expect(alerts.scheduled, hasLength(1));

      await controller.adjustRest(const Duration(seconds: -15));
      expect(
        controller.workout!.rest!.endsAt,
        now.add(const Duration(seconds: 165)).toUtc().toIso8601String(),
      );
      expect(alerts.shown, hasLength(2));
      expect(alerts.scheduled, hasLength(2));
      expect(
        alerts.scheduled.last.endsAt,
        controller.workout!.rest!.endsAtClock(now),
      );

      await controller.adjustRest(const Duration(seconds: 15));
      expect(
        controller.workout!.rest!.endsAt,
        now.add(const Duration(seconds: 180)).toUtc().toIso8601String(),
      );
      expect(alerts.shown, hasLength(3));
      expect(alerts.scheduled, hasLength(3));

      // −15 past zero clamps to now instead of a backwards end time.
      await controller.adjustRest(const Duration(seconds: -600));
      expect(controller.workout!.rest!.remainingSeconds(now), 0);
    });

    test(
      'Skip clears the timer and cancels the notification and alarm',
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final FakeRestAlerts alerts = FakeRestAlerts();
        await store.write(_account, _workout());
        final ActiveWorkoutController controller = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
        );
        await controller.syncAccount(_account);
        await controller.setTicked(0, 0, true);
        expect(controller.workout!.rest, isNotNull);

        await controller.skipRest();
        expect(controller.workout!.rest, isNull);
        expect(alerts.removeCalls, 1);
        expect(alerts.cancelEndCalls, 1);
        // Nothing was re-posted after the skip.
        expect(alerts.shown, hasLength(1));
        expect(alerts.scheduled, hasLength(1));
        // …and the cleared timer is what the store keeps.
        expect((await store.read(_account))!.rest, isNull);
      },
    );

    test('the end of a rest clears it and plays the in-app alert', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final FakeRestAlerts alerts = FakeRestAlerts();
      await store.write(_account, _workout());
      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: InMemoryRestLengthStore(),
        alerts: alerts,
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
      );
      await controller.syncAccount(_account);
      await controller.setTicked(0, 0, true);

      await controller.completeRest();
      expect(controller.workout!.rest, isNull);
      expect(alerts.playEndCalls, 1);
      expect(alerts.removeCalls, 1);
      expect(alerts.cancelEndCalls, 1);
      expect((await store.read(_account))!.rest, isNull);
    });

    test('Finish suspends the alerts and Back restores them', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final FakeRestAlerts alerts = FakeRestAlerts();
      await store.write(_account, _workout());
      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: InMemoryRestLengthStore(),
        alerts: alerts,
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
      );
      await controller.syncAccount(_account);
      await controller.setTicked(0, 0, true);

      // The Finish summary replaces the workout: the lock-screen
      // notification and the end alarm come off (#125).
      await controller.suspendRestAlerts();
      expect(controller.workout!.rest, isNotNull);
      expect(alerts.removeCalls, 1);
      expect(alerts.cancelEndCalls, 1);

      // An adjustment made while suspended re-posts nothing…
      await controller.adjustRest(const Duration(seconds: 15));
      expect(alerts.shown, hasLength(1));
      // …and Back to the workout brings the alerts back for the running rest.
      await controller.restoreRestAlerts();
      expect(alerts.shown, hasLength(2));
      expect(alerts.scheduled, hasLength(2));
    });

    test('Discard cancels the notification and the alarm', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final FakeRestAlerts alerts = FakeRestAlerts();
      await store.write(_account, _workout());
      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: InMemoryRestLengthStore(),
        alerts: alerts,
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
      );
      await controller.syncAccount(_account);
      await controller.setTicked(0, 0, true);

      await controller.discard(accountId: _account);
      expect(controller.hasActive, isFalse);
      expect(alerts.removeCalls, 1);
      expect(alerts.cancelEndCalls, 1);
      expect(await store.read(_account), isNull);
    });

    test(
      'the end of a rest alerts exactly once, however it is reached',
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final FakeRestAlerts alerts = FakeRestAlerts();
        final DateTime now = DateTime.utc(2026, 9, 29, 10);
        await store.write(_account, _workout());
        final ActiveWorkoutController controller = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: () => now,
        );
        await controller.syncAccount(_account);
        await controller.setTicked(0, 0, true);

        // The ticker and a second, late call both reach this rest's end.
        await controller.completeRest();
        await controller.completeRest();

        expect(controller.workout!.rest, isNull);
        expect(alerts.playEndCalls, 1);
        expect(alerts.ended, hasLength(1));
        expect(alerts.ended.single.line, 'Next: Bench Press · set 2');
        expect(alerts.removeCalls, 1);
        expect(alerts.cancelEndCalls, 1);
        expect((await store.read(_account))!.rest, isNull);
      },
    );

    test('a rest that ended while the app was away clears silently', () async {
      final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
      final FakeRestAlerts alerts = FakeRestAlerts();
      DateTime now = DateTime.utc(2026, 9, 29, 10);
      await store.write(_account, _workout());
      final ActiveWorkoutController controller = _controller(
        store: store,
        restLengths: InMemoryRestLengthStore(),
        alerts: alerts,
        now: () => now,
      );
      await controller.syncAccount(_account);
      await controller.setTicked(0, 0, true);
      final DateTime endsAt = controller.workout!.rest!.endsAtClock(now);

      // The logger comes back minutes after the scheduled alarm fired: the
      // bar clears without a second vibration/sound.
      now = endsAt.add(const Duration(minutes: 3));
      await controller.completeRest();
      expect(controller.workout!.rest, isNull);
      expect(alerts.playEndCalls, 0);
      expect(alerts.ended, isEmpty);
      // The stale platform artefacts are still taken down exactly once.
      expect(alerts.removeCalls, 1);
      expect(alerts.cancelEndCalls, 1);

      await controller.completeRest();
      expect(alerts.playEndCalls, 0);
      expect(alerts.removeCalls, 1);
    });

    test(
      'the foreground end drops the alarm a second before it fires',
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final FakeRestAlerts alerts = FakeRestAlerts();
        DateTime now = DateTime.utc(2026, 9, 29, 10);
        await store.write(_account, _workout());
        final ActiveWorkoutController controller = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: () => now,
        );
        await controller.syncAccount(_account);
        await controller.setTicked(0, 0, true);
        final DateTime endsAt = controller.workout!.rest!.endsAtClock(now);

        // A long way from the end: the alarm the player may background into is
        // still needed.
        await controller.dropImminentEndAlarm();
        expect(alerts.cancelEndCalls, 0);

        // Inside the last second the ticker owns the end: dropped once, and a
        // repeat tick does not cancel a second time.
        now = endsAt.subtract(const Duration(milliseconds: 400));
        await controller.dropImminentEndAlarm();
        await controller.dropImminentEndAlarm();
        expect(alerts.cancelEndCalls, 1);

        // +15 re-posts the alarm, which re-arms the drop for the new end time.
        await controller.adjustRest(const Duration(seconds: 15));
        expect(alerts.scheduled, hasLength(2));
        now = controller.workout!.rest!
            .endsAtClock(now)
            .subtract(const Duration(milliseconds: 400));
        await controller.dropImminentEndAlarm();
        expect(alerts.cancelEndCalls, 2);
      },
    );

    test(
      "switching A→B takes A's countdown and alarm off the screen",
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final FakeRestAlerts alerts = FakeRestAlerts();
        final DateTime now = DateTime.utc(2026, 9, 29, 10);
        await store.write(_account, _workout());
        final ActiveWorkoutController controller = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: () => now,
        );
        await controller.syncAccount(_account);
        await controller.setTicked(0, 0, true);
        expect(alerts.shown, hasLength(1));

        // Straight to another account, with no signed-out moment in between:
        // A's lock-screen notification and alarm go exactly like sign-out's.
        await controller.syncAccount(_otherAccount);
        expect(alerts.removeCalls, 1);
        expect(alerts.cancelEndCalls, 1);
        expect(controller.workout, isNull);
        // B has no stored workout, so nothing of A's is re-posted for it.
        expect(alerts.shown, hasLength(1));

        // Back to A: its still-running rest posts again, and nothing that
        // belongs to B is left behind to cancel.
        await controller.syncAccount(_account);
        expect(alerts.shown, hasLength(2));
        expect(alerts.removeCalls, 1);
        expect(alerts.cancelEndCalls, 1);
      },
    );
  });

  group('rest timer restore (#125)', () {
    test(
      'a stored future end time survives a restart and re-posts the alerts',
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final DateTime now = DateTime.utc(2026, 9, 29, 10);
        await store.write(
          _account,
          _workout().copyWith(
            rest: ActiveRestTimer(
              endsAt: now
                  .add(const Duration(seconds: 90))
                  .toUtc()
                  .toIso8601String(),
              totalSeconds: 180,
              exerciseId: 'bench_press',
              exerciseName: 'Bench Press',
              setNumber: 2,
              lastLabel: '90 × 5 @2',
            ),
          ),
        );

        // A simulated restart: a fresh controller over the same device storage.
        final FakeRestAlerts alerts = FakeRestAlerts();
        final ActiveWorkoutController restored = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: () => now,
        );
        await restored.syncAccount(_account);

        final ActiveRestTimer? rest = restored.workout!.rest;
        expect(rest, isNotNull);
        expect(
          rest!.endsAt,
          now.add(const Duration(seconds: 90)).toUtc().toIso8601String(),
        );
        expect(rest.totalSeconds, 180);
        expect(rest.lastLabel, '90 × 5 @2');
        // The countdown notification and the alarm are re-posted for it, but
        // the one-time permission ask is not repeated.
        expect(alerts.shown, hasLength(1));
        expect(alerts.scheduled, hasLength(1));
        expect(alerts.ensureReadyCalls, 0);
      },
    );

    test(
      'a rest that ended while the app was closed clears without alerting',
      () async {
        final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
        final DateTime now = DateTime.utc(2026, 9, 29, 10);
        await store.write(
          _account,
          _workout().copyWith(
            rest: ActiveRestTimer(
              endsAt: now
                  .subtract(const Duration(seconds: 5))
                  .toUtc()
                  .toIso8601String(),
              totalSeconds: 180,
              exerciseId: 'bench_press',
              exerciseName: 'Bench Press',
              setNumber: 2,
            ),
          ),
        );

        final FakeRestAlerts alerts = FakeRestAlerts();
        final ActiveWorkoutController restored = _controller(
          store: store,
          restLengths: InMemoryRestLengthStore(),
          alerts: alerts,
          now: () => now,
        );
        await restored.syncAccount(_account);

        expect(restored.workout!.rest, isNull);
        // No second vibration/sound, but any stale platform artefact is gone.
        expect(alerts.playEndCalls, 0);
        expect(alerts.removeCalls, 1);
        expect(alerts.cancelEndCalls, 1);
        expect((await store.read(_account))!.rest, isNull);
      },
    );
  });

  group('exact-alarm permission policy (#125)', () {
    test('asked once with one line, and a refusal falls back to inexact and '
        'is never re-asked', () async {
      final _MemorySecureStore store = _MemorySecureStore();
      final List<String> explanations = <String>[];
      int notificationAsks = 0;
      int exactAsks = 0;
      bool granted = false;
      final AndroidRestAlerts alerts = AndroidRestAlerts(
        store: store,
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
        explain: explanations.add,
        requestNotificationsPermission: () async {
          notificationAsks += 1;
          return true;
        },
        requestExactAlarmsPermission: () async {
          exactAsks += 1;
          return granted;
        },
        canScheduleExactNotifications: () async => granted,
      );

      // First rest start: one-line explanation, one ask of each permission.
      await alerts.ensureReady();
      await _flush();
      expect(explanations, hasLength(1));
      expect(explanations.single, isNotEmpty);
      expect(notificationAsks, 1);
      expect(exactAsks, 1);
      // Refused → the end alarm runs inexact while idle.
      expect(
        await alerts.endScheduleMode(),
        AndroidScheduleMode.inexactAllowWhileIdle,
      );
      expect(store.values['rest_alerts.asked'], '1');

      // A later start never asks again — even if the answer would differ.
      granted = true;
      await alerts.ensureReady();
      await _flush();
      expect(exactAsks, 1);
      expect(notificationAsks, 1);
      expect(explanations, hasLength(1));
      // The live capability is still read per schedule, so a grant made in
      // system settings upgrades the next alarm to exact without a re-ask.
      expect(
        await alerts.endScheduleMode(),
        AndroidScheduleMode.exactAllowWhileIdle,
      );
    });

    test(
      'two quick ticks share one ask, with the flag written first',
      () async {
        final _MemorySecureStore store = _MemorySecureStore();
        int notificationAsks = 0;
        int exactAsks = 0;
        bool flaggedFirst = false;
        final AndroidRestAlerts alerts = AndroidRestAlerts(
          store: store,
          now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
          requestNotificationsPermission: () async {
            notificationAsks += 1;
            flaggedFirst = store.values['rest_alerts.asked'] == '1';
            return true;
          },
          requestExactAlarmsPermission: () async {
            exactAsks += 1;
            flaggedFirst =
                flaggedFirst && store.values['rest_alerts.asked'] == '1';
            return true;
          },
          canScheduleExactNotifications: () async => true,
        );

        // Two starts a tick apart: the second must not race the flag the first
        // one is about to write.
        unawaited(alerts.ensureReady());
        await alerts.ensureReady();
        await _flush();

        expect(notificationAsks, 1);
        expect(exactAsks, 1);
        // The "already asked" flag is on disk before either prompt shows.
        expect(flaggedFirst, isTrue);
        expect(store.values['rest_alerts.asked'], '1');
      },
    );

    test('every entry point waits for ONE init before it runs', () async {
      final _MemorySecureStore store = _MemorySecureStore();
      final Completer<void> gate = Completer<void>();
      int initCalls = 0;
      int notificationAsks = 0;
      int exactAsks = 0;
      final AndroidRestAlerts alerts = AndroidRestAlerts(
        store: store,
        now: FakeClock(DateTime.utc(2026, 9, 29, 10)).call,
        initialize: () {
          initCalls += 1;
          return gate.future;
        },
        requestNotificationsPermission: () async {
          notificationAsks += 1;
          return true;
        },
        requestExactAlarmsPermission: () async {
          exactAsks += 1;
          return true;
        },
        canScheduleExactNotifications: () async => true,
      );
      final RestAlertInfo info = RestAlertInfo(
        endsAt: DateTime.utc(2026, 9, 29, 10, 3),
        totalSeconds: 180,
        exerciseName: 'Bench Press',
        setNumber: 2,
      );

      // The first rest's entry points, all at once.
      await alerts.ensureReady();
      await alerts.ensureReady();
      unawaited(alerts.showRest(info));
      unawaited(alerts.scheduleEnd(info));
      await _flush();

      // ONE shared init is still in flight — and nothing that runs after it,
      // not even the permission ask, has happened yet.
      expect(initCalls, 1);
      expect(notificationAsks, 0);
      expect(exactAsks, 0);

      gate.complete();
      await _flush();

      // Init finished once for all four calls, and the two quick
      // ensureReady calls shared the single ask it was gating.
      expect(initCalls, 1);
      expect(notificationAsks, 1);
      expect(exactAsks, 1);
    });
  });
}
