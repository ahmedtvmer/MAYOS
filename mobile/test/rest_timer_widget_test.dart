import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/rest_length.dart';
import 'package:mayos_mobile/src/core/theme/mayos_spacing.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';
import 'package:mayos_mobile/src/features/player/workout/logger_keypad.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';
import 'support/fake_clock.dart';
import 'support/fake_rest_alerts.dart';

const String _account = 'account-alice';

/// Bench, planned with a program rest of 180 (#125's "program value").
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

/// A planned exercise whose program carried no `rest_seconds`: the key is
/// absent, so its prescription line must read the flat 2:00 (#125).
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

/// The frozen baseline bench ticks from, as wire JSON: two working sets, so
/// the first two rows fill from the previous values on tick.
List<Map<String, dynamic>> _baselinesBody() => <Map<String, dynamic>>[
      <String, dynamic>{
        'exercise_id': 'bench_press',
        'sessions_logged': 3,
        'max_weight_kg': 100.0,
        'best_e1rm_kg': 121.67,
        'last_session': <String, dynamic>{
          'performed_date': '2026-09-26',
          'sets': <Map<String, dynamic>>[
            <String, dynamic>{'weight_kg': 100.0, 'reps': 5, 'rir': 1.0},
            <String, dynamic>{'weight_kg': 95.0, 'reps': 6, 'rir': 2.0},
          ],
        },
      },
    ];

ActiveWorkout _workout() => ActiveWorkout(
      id: 'aw-1',
      accountId: _account,
      startedAt: '2026-09-28T08:00:00.000Z',
      dayOrder: 2,
      dayName: 'Upper A',
      programVersion: 3,
      exercises: <ActiveWorkoutExercise>[
        ActiveWorkoutExercise(
          exercise: _benchJson,
          targetLabel: '3 × 5–8 @ RIR ≥ 2',
          sets: <ActiveWorkoutSet>[
            ActiveWorkoutSet(),
            ActiveWorkoutSet(),
            ActiveWorkoutSet(),
          ],
        ),
        ActiveWorkoutExercise(
          exercise: _rowJson,
          sets: <ActiveWorkoutSet>[ActiveWorkoutSet()],
        ),
      ],
      baselines: <String, BaselineExercise>{
        for (final Map<String, dynamic> row in _baselinesBody())
          row['exercise_id'] as String: BaselineExercise.fromJson(row),
      },
    );

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.baselinesBody = _baselinesBody();
  return fake;
}

Future<void> _pumpUntilFound(
  WidgetTester tester,
  Finder finder, {
  int attempts = 40,
}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// The signed-in app with the stored Active workout above, opened through the
/// app-open Resume prompt — the real entry into the table logger.
Future<
    ({
      FakeRestAlerts alerts,
      InMemoryRestLengthStore restLengths,
      InMemoryActiveWorkoutStore store,
      FakeClock clock,
    })> _openLogger(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final FakeMayosApi fake = _signedInFake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
  await store.write(_account, _workout());
  final InMemoryRestLengthStore restLengths = InMemoryRestLengthStore();
  final FakeRestAlerts alerts = FakeRestAlerts();
  final FakeClock clock = FakeClock(DateTime.utc(2026, 9, 29, 10));

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        clockProvider.overrideWithValue(clock.call),
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore()),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        workoutCacheStoreProvider.overrideWithValue(
          InMemoryWorkoutCacheStore(),
        ),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
        baselineCacheStoreProvider.overrideWithValue(
          InMemoryBaselineCacheStore(),
        ),
        activeWorkoutStoreProvider.overrideWithValue(store),
        restLengthStoreProvider.overrideWithValue(restLengths),
        restAlertsProvider.overrideWithValue(alerts),
        // Simulate Flutter's browser visibility lifecycle on the native host.
        webPageVisibilityEnabledProvider.overrideWithValue(true),
        deviceTimezoneProvider.overrideWithValue(Future<String>.value('UTC')),
        deviceTimezoneOrNullProvider.overrideWithValue(
          Future<String?>.value('UTC'),
        ),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.pumpAndSettle();
  expect(find.text('Unfinished workout'), findsOneWidget);
  await tester.tap(find.text('Resume'));
  await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
  await tester.pumpAndSettle();
  return (alerts: alerts, restLengths: restLengths, store: store, clock: clock);
}

Finder _cell(int exercise, int set, String field) =>
    find.byKey(ValueKey<String>('logger.cell.$exercise.$set.$field'));

Finder _tick(int exercise, int set) =>
    find.byKey(ValueKey<String>('logger.tick.$exercise.$set'));

/// The persistent bottom bar (#160) and #125's rest controls inside it.
Finder _bar() => find.byKey(const ValueKey<String>('logger.bottomBar'));

Finder _restControls() => find.byKey(const ValueKey<String>('rest.controls'));

/// Types [digits] into one cell through the app's own keypad, then hides it.
Future<void> _typeCell(
  WidgetTester tester,
  int exercise,
  int set,
  String field,
  String digits,
) async {
  await tester.tap(_cell(exercise, set, field));
  await tester.pump(const Duration(milliseconds: 100));
  for (final String digit in digits.split('')) {
    await tester.tap(find.byKey(ValueKey<String>('logger.key.$digit')));
  }
  await tester.pump(const Duration(milliseconds: 100));
  await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
  await tester.pump(const Duration(milliseconds: 100));
}

Finder _cardMenu(int exerciseIndex) =>
    find.byKey(ValueKey<String>('logger.cardMenu.$exerciseIndex'));

Finder _restMenuItem(int exerciseIndex) =>
    find.byKey(ValueKey<String>('logger.cardMenu.$exerciseIndex.rest'));

/// Opens the card's ⋮ menu and picks **Rest time…** — the #125 picker lives
/// behind the #162 menu, not on the title row.
Future<void> _openRestPicker(WidgetTester tester, int exerciseIndex) async {
  await tester.tap(_cardMenu(exerciseIndex));
  await tester.pumpAndSettle();
  await tester.tap(_restMenuItem(exerciseIndex));
  await tester.pumpAndSettle();
}

Future<void> _pickRestOption(
  WidgetTester tester,
  int exerciseIndex,
  int seconds,
) async {
  await _openRestPicker(tester, exerciseIndex);
  final Finder option = find.byKey(ValueKey<String>('rest.option.$seconds'));
  if (option.evaluate().isEmpty) {
    // The picker scrolls: walk down to the options below the fold.
    await tester.drag(find.byType(ListView), const Offset(0, -800));
    await tester.pumpAndSettle();
  }
  await tester.tap(find.byKey(ValueKey<String>('rest.option.$seconds')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'the prescription line shows the program rest length and 2:00 '
      'when unset (#125 via the #162 menu)', (WidgetTester tester) async {
    await _openLogger(tester);

    // Bench carries the program's 180 → "Rest 3:00" on the prescription
    // line, which is where the rest length now stays visible (#162)…
    expect(find.textContaining('Rest 3:00'), findsOneWidget);
    // …the exercise with no rest_seconds resolves to the flat 2:00 (#125).
    expect(find.textContaining('Rest 2:00'), findsOneWidget);
    // The picker itself is reached through the card's ⋮ menu (#162), and
    // every card carries its own menu entry point.
    expect(_cardMenu(0), findsOneWidget);
    expect(_cardMenu(1), findsOneWidget);
    await tester.tap(_cardMenu(0));
    await tester.pumpAndSettle();
    expect(find.text('Rest time…'), findsOneWidget);
    expect(_restMenuItem(0), findsOneWidget);
    await tester.tap(_restMenuItem(0));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey<String>('rest.option.60')),
      findsOneWidget,
    );
  });

  testWidgets(
    'the picker offers Off and 1:00–5:00 in 15-second steps and writes a '
    'device override',
    (WidgetTester tester) async {
      final ({
        FakeRestAlerts alerts,
        InMemoryRestLengthStore restLengths,
        InMemoryActiveWorkoutStore store,
        FakeClock clock,
      }) harness = await _openLogger(tester);

      await _openRestPicker(tester, 0);
      expect(find.text('Off'), findsOneWidget);
      expect(find.text('1:00'), findsOneWidget);
      expect(find.text('1:15'), findsOneWidget);
      expect(
        find.byKey(const ValueKey<String>('rest.option.60')),
        findsOneWidget,
      );
      // 2:15 is in the first screenful of the sheet…
      expect(
        find.byKey(const ValueKey<String>('rest.option.135')),
        findsOneWidget,
      );
      // …and 5:00 lives below the fold until the list is scrolled.
      expect(
        find.byKey(const ValueKey<String>('rest.option.300')),
        findsNothing,
      );
      await tester.drag(find.byType(ListView), const Offset(0, -800));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey<String>('rest.option.300')),
        findsOneWidget,
      );
      expect(find.text('5:00'), findsOneWidget);
      await tester.drag(find.byType(ListView), const Offset(0, 800));
      await tester.pumpAndSettle();
      expect(kRestLengthOptions.first, 0);
      expect(kRestLengthOptions.last, 300);
      expect(kRestLengthOptions, hasLength(18));

      await tester.tap(find.byKey(const ValueKey<String>('rest.option.135')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Rest 2:15'), findsOneWidget);
      expect(harness.restLengths.values[_account]?['bench_press'], 135);
      // The other exercise keeps its default: the override is per exercise.
      expect(harness.restLengths.values[_account]?['cable_row'], isNull);
      expect(find.textContaining('Rest 2:00'), findsOneWidget);

      // Off is a first-class choice: the picker reads it back…
      await _pickRestOption(tester, 0, 0);
      expect(find.textContaining('Rest Off'), findsOneWidget);
      expect(harness.restLengths.values[_account]?['bench_press'], 0);
      // …and the sheet reopens with Off as the current value.
      await _openRestPicker(tester, 0);
      expect(
        tester
            .widget<Icon>(
              find.descendant(
                of: find.byKey(const ValueKey<String>('rest.option.0')),
                matching: find.byType(Icon),
              ),
            )
            .icon,
        Icons.check,
      );
    },
  );

  testWidgets(
    'the bottom bar shows #125\'s rest controls on a working tick, only '
    'while the keypad is hidden, and −15/+15/Skip drive the seam',
    (WidgetTester tester) async {
      final ({
        FakeRestAlerts alerts,
        InMemoryRestLengthStore restLengths,
        InMemoryActiveWorkoutStore store,
        FakeClock clock,
      }) harness = await _openLogger(tester);

      // No timer, no rest controls — but the bar itself, with progress and
      // Finish, is there from the first frame (#160).
      expect(_restControls(), findsNothing);
      expect(_bar(), findsOneWidget);
      expect(find.text('0/4 sets'), findsOneWidget);
      expect(
        find.widgetWithText(FilledButton, 'Finish workout'),
        findsOneWidget,
      );

      // A working tick fills from the previous values and starts the rest.
      await tester.tap(_tick(0, 0));
      await tester.pump(const Duration(milliseconds: 100));
      expect(_bar(), findsOneWidget);
      expect(_restControls(), findsOneWidget);
      expect(find.text('Rest · Bench Press'), findsOneWidget);
      expect(find.text('3:00'), findsOneWidget);
      // Resting adds controls to the bar; it never takes Finish away (#160).
      expect(
        find.widgetWithText(FilledButton, 'Finish workout'),
        findsOneWidget,
      );
      expect(find.text('1/4 sets'), findsOneWidget);
      // Every rest action keeps a full 48dp target (#45).
      for (final Finder action in <Finder>[
        find.byKey(const ValueKey<String>('rest.minus')),
        find.byKey(const ValueKey<String>('rest.plus')),
        find.byKey(const ValueKey<String>('rest.skip')),
      ]) {
        expect(tester.getSize(action).height, kMayosMinTapTarget);
        expect(tester.getSize(action).width, greaterThanOrEqualTo(48));
      }
      expect(harness.alerts.ensureReadyCalls, greaterThanOrEqualTo(1));
      expect(harness.alerts.shown, hasLength(1));
      // The line describes the NEXT set to do — Bench's second row, with the
      // baseline's value for it as the "last" — not the row just ticked (#125).
      expect(
        harness.alerts.shown.single.line,
        'Next: Bench Press · set 2 · last 95 × 6 @2',
      );
      expect(harness.alerts.scheduled, hasLength(1));
      expect(harness.alerts.shown.single.totalSeconds, 180);

      // The keypad replaces the whole bar while it is open…
      await tester.tap(_cell(0, 1, 'kg'));
      await tester.pump(const Duration(milliseconds: 100));
      expect(_bar(), findsNothing);
      expect(_restControls(), findsNothing);
      expect(find.text('Hide'), findsOneWidget);
      harness.clock.advance(const Duration(seconds: 1));
      await tester.pump(const Duration(seconds: 1));
      // …and hiding it brings the countdown back at the injected clock time.
      await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
      await tester.pump(const Duration(milliseconds: 100));
      expect(_bar(), findsOneWidget);
      expect(_restControls(), findsOneWidget);
      expect(find.text('2:59'), findsOneWidget);

      // +15 and −15 move the end time and re-post notification + alarm.
      await tester.tap(find.byKey(const ValueKey<String>('rest.plus')));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('3:14'), findsOneWidget);
      expect(harness.alerts.shown, hasLength(2));
      expect(harness.alerts.scheduled, hasLength(2));

      await tester.tap(find.byKey(const ValueKey<String>('rest.minus')));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('2:59'), findsOneWidget);
      expect(harness.alerts.shown, hasLength(3));
      expect(harness.alerts.scheduled, hasLength(3));

      // Skip clears the timer and takes the rest controls away — the bottom
      // bar itself stays put with its progress and Finish — and cancels both
      // platform requests.
      await tester.tap(find.byKey(const ValueKey<String>('rest.skip')));
      await tester.pump(const Duration(milliseconds: 100));
      expect(_restControls(), findsNothing);
      expect(_bar(), findsOneWidget);
      expect(harness.alerts.removeCalls, 1);
      expect(harness.alerts.cancelEndCalls, 1);

      final BuildContext context = tester.element(
        find.byType(WorkoutLoggerScreen),
      );
      final ActiveWorkoutController controller = ProviderScope.containerOf(
        context,
      ).read(activeWorkoutControllerProvider.notifier);
      expect(controller.workout!.rest, isNull);
      expect((await harness.store.read(_account))!.rest, isNull);

      // A second working tick starts another rest. Advance the fake clock and
      // Flutter's timer queue together through its end, without wall time.
      await controller.setRestLength(0, 60);
      await tester.tap(_tick(0, 1));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('1:00'), findsOneWidget);
      harness.clock.advance(const Duration(seconds: 60));
      await tester.pump(const Duration(seconds: 60));
      await tester.pump();
      expect(_restControls(), findsNothing);
      expect(controller.workout!.rest, isNull);
      expect(harness.alerts.playEndCalls, 1);
      expect(harness.alerts.ended, hasLength(1));
    },
  );

  testWidgets('a hidden page catches up silently and keeps real remaining time', (
    WidgetTester tester,
  ) async {
    final harness = await _openLogger(tester);

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    harness.clock.advance(const Duration(seconds: 40));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 1));
    expect(find.text('2:20'), findsOneWidget);
    expect(harness.alerts.playEndCalls, 0);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    harness.clock.advance(const Duration(seconds: 200));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 1));
    expect(_restControls(), findsNothing);
    expect(harness.alerts.playEndCalls, 0);
    expect((await harness.store.read(_account))!.rest, isNull);
  });

  testWidgets('the focused row and keypad stay clear at the Safari viewport', (
    WidgetTester tester,
  ) async {
    await _openLogger(tester);
    tester.view.physicalSize = const Size(390, 664);
    tester.view.viewPadding = const FakeViewPadding(bottom: 34);
    addTearDown(tester.view.resetViewPadding);
    await tester.pump();

    await tester.ensureVisible(_cell(1, 0, 'kg'));
    await tester.pumpAndSettle();
    await tester.tap(_cell(1, 0, 'kg'));
    await tester.pumpAndSettle();

    final Rect row = tester.getRect(
      find.byKey(const ValueKey<String>('logger.row.1.0')),
    );
    final Rect keypad = tester.getRect(find.byType(LoggerKeypad));
    final Rect hideKey = tester.getRect(
      find.byKey(const ValueKey<String>('logger.key.hide')),
    );
    expect(row.bottom, lessThanOrEqualTo(keypad.top));
    expect(row.top, greaterThanOrEqualTo(0));
    expect(hideKey.bottom, lessThanOrEqualTo(664 - 34));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pumpAndSettle();
    final Rect finishButton = tester.getRect(
      find.widgetWithText(FilledButton, 'Finish workout'),
    );
    expect(finishButton.bottom, lessThanOrEqualTo(664 - 34));
    expect(tester.takeException(), isNull);
  });

  testWidgets('tapping a visible row does not recenter the list', (
    WidgetTester tester,
  ) async {
    await _openLogger(tester);
    tester.view.physicalSize = const Size(390, 844);
    await tester.pump();

    final BuildContext cellContext = tester.element(_cell(0, 0, 'kg'));
    final ScrollPosition position = Scrollable.of(cellContext).position;
    final double initialOffset = position.pixels;
    final Rect row = tester.getRect(
      find.byKey(const ValueKey<String>('logger.row.0.0')),
    );
    final Rect list = tester.getRect(
      find.byKey(const ValueKey<String>('logger.list')),
    );
    expect(row.top, greaterThanOrEqualTo(0));
    expect(row.bottom, lessThanOrEqualTo(list.bottom));
    await tester.tap(_cell(0, 0, 'kg'));
    await tester.pumpAndSettle();

    expect(position.pixels, initialOffset);
  });

  testWidgets('a warm-up tick never starts the rest timer', (
    WidgetTester tester,
  ) async {
    final ({
      FakeRestAlerts alerts,
      InMemoryRestLengthStore restLengths,
      InMemoryActiveWorkoutStore store,
      FakeClock clock,
    }) harness = await _openLogger(tester);

    // Give the second row values, then mark it W and tick it: a warm-up is
    // not a working set, so no timer starts (#125).
    await _typeCell(tester, 0, 1, 'kg', '40');
    await _typeCell(tester, 0, 1, 'reps', '10');
    await tester.tap(find.byKey(const ValueKey<String>('logger.setlabel.0.1')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('W'), findsOneWidget);

    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_restControls(), findsNothing);
    expect(_bar(), findsOneWidget);
    expect(harness.alerts.shown, isEmpty);
    expect(harness.alerts.ensureReadyCalls, 0);
  });

  testWidgets('Off rest: a working tick starts no timer', (
    WidgetTester tester,
  ) async {
    final ({
      FakeRestAlerts alerts,
      InMemoryRestLengthStore restLengths,
      InMemoryActiveWorkoutStore store,
      FakeClock clock,
    }) harness = await _openLogger(tester);

    await _pickRestOption(tester, 0, 0);
    expect(find.textContaining('Rest Off'), findsOneWidget);

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_restControls(), findsNothing);
    expect(_bar(), findsOneWidget);
    expect(harness.alerts.shown, isEmpty);
    expect(harness.alerts.ensureReadyCalls, 0);
  });
}
