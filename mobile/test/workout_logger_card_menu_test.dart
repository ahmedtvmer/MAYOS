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
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/rest_length.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

// The card's ⋮ menu (#162): Replace exercise for every player, Rest time…
// behind the same #125 picker, Remove exercise only for an unplanned one —
// plus the confirmation a replace raises over ticked sets, the search's
// muscle pre-filter, and what the swap does to the workout.

const String _account = 'account-alice';

/// Bench (in the fake's catalog detail, so its muscle is known) and a second
/// planned exercise without one.
const ProgramDay _day = ProgramDay(
  dayName: 'Upper A',
  dayOrder: 2,
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'bench_press',
      exerciseName: 'Bench Press',
      targetSets: 3,
      targetRepsMin: 5,
      targetRepsMax: 8,
      targetRpe: 8.5,
      restSeconds: 180,
    ),
    ProgramExercise(
      exerciseId: 'incline_press',
      exerciseName: 'Incline Press',
      targetSets: 1,
      targetRepsMin: 8,
      targetRepsMax: 12,
      targetRpe: 8.0,
      restSeconds: 120,
    ),
  ],
);

/// Two working sets for bench, so a tick fills from the previous values.
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

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 40}) async {
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

/// Seeds the stored Active workout through the real controller, so the cards
/// render exactly what a player would start with (#123 item 2).
Future<InMemoryActiveWorkoutStore> _seedThroughController(
    {required FakeMayosApi fake}) async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
  final ProviderContainer container = ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      workoutCacheStoreProvider.overrideWithValue(InMemoryWorkoutCacheStore()),
      baselineCacheStoreProvider
          .overrideWithValue(InMemoryBaselineCacheStore()),
      activeWorkoutStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWith((Ref ref) => ApiClient(
            tokens: tokens,
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          )),
    ],
  );
  addTearDown(container.dispose);
  final ActiveWorkoutController controller =
      container.read(activeWorkoutControllerProvider.notifier);
  final StartWorkoutOutcome outcome = await controller.startFromDay(
    accountId: _account,
    day: _day,
    programVersion: 3,
  );
  expect(outcome, StartWorkoutOutcome.started);
  return store;
}

/// The signed-in app over [store], opened through the app-open Resume prompt.
Future<
    ({
      FakeMayosApi fake,
      InMemoryActiveWorkoutStore store,
      InMemoryRestLengthStore restLengths,
    })> _openLogger(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final FakeMayosApi fake = _signedInFake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  // Seeding talks to the (fake) API on real timers, so it runs outside the
  // test's fake-async zone.
  final InMemoryActiveWorkoutStore store = (await tester.runAsync(
    () => _seedThroughController(fake: fake),
  ))!;
  final InMemoryRestLengthStore restLengths = InMemoryRestLengthStore();

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore()),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        workoutCacheStoreProvider
            .overrideWithValue(InMemoryWorkoutCacheStore()),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        activeWorkoutStoreProvider.overrideWithValue(store),
        restLengthStoreProvider.overrideWithValue(restLengths),
        deviceTimezoneProvider.overrideWithValue(Future<String>.value('UTC')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value('UTC')),
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
  return (fake: fake, store: store, restLengths: restLengths);
}

Finder _cardMenu(int exerciseIndex) =>
    find.byKey(ValueKey<String>('logger.cardMenu.$exerciseIndex'));

Finder _replaceItem(int exerciseIndex) =>
    find.byKey(ValueKey<String>('logger.cardMenu.$exerciseIndex.replace'));

Finder _restItem(int exerciseIndex) =>
    find.byKey(ValueKey<String>('logger.cardMenu.$exerciseIndex.rest'));

Finder _removeItem(int exerciseIndex) =>
    find.byKey(ValueKey<String>('logger.cardMenu.$exerciseIndex.remove'));

Finder _row(int exercise, int set) =>
    find.byKey(ValueKey<String>('logger.row.$exercise.$set'));

Finder _tick(int exercise, int set) =>
    find.byKey(ValueKey<String>('logger.tick.$exercise.$set'));

Finder _muscleFilter() =>
    find.byKey(const ValueKey<String>('logger.search.muscleFilter'));

/// Opens a card's ⋮ menu.
Future<void> _openMenu(WidgetTester tester, int exerciseIndex) async {
  await tester.ensureVisible(_cardMenu(exerciseIndex));
  await tester.pump(const Duration(milliseconds: 100));
  await tester.tap(_cardMenu(exerciseIndex));
  await tester.pumpAndSettle();
}

/// Opens the menu and picks one of its entries.
Future<void> _pickMenuItem(
    WidgetTester tester, int exerciseIndex, Finder item) async {
  await _openMenu(tester, exerciseIndex);
  await tester.tap(item);
  await tester.pumpAndSettle();
}

/// Ticks one set: the empty cells fill from the frozen baseline (#107).
Future<void> _tickSet(WidgetTester tester, int exercise, int set) async {
  await tester.ensureVisible(_tick(exercise, set));
  await tester.pump(const Duration(milliseconds: 100));
  await tester.tap(_tick(exercise, set));
  await tester.pump(const Duration(milliseconds: 100));
}

/// Drives the catalog search dialog and picks a result.
Future<void> _searchAndPick(WidgetTester tester, String query,
    String result) async {
  await tester.enterText(find.byType(TextField).last, query);
  await tester.tap(find.text('Search'));
  await _pumpUntilFound(tester, find.text(result));
  await tester.tap(find.text(result));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'the card menu offers Replace exercise and Rest time…, and Remove only '
      'for an unplanned exercise (#162)', (WidgetTester tester) async {
    await _openLogger(tester);

    await _openMenu(tester, 0);
    expect(find.text('Replace exercise'), findsOneWidget);
    expect(find.text('Rest time…'), findsOneWidget);
    // Planned exercise: nothing to undo.
    expect(find.text('Remove exercise'), findsNothing);
    expect(_removeItem(0), findsNothing);
    // Every entry is a full-height row: Material's menu items are 48dp.
    expect(tester.getSize(_replaceItem(0)).height, greaterThanOrEqualTo(48));
    await tester.tap(find.text('Replace exercise'));
    // …and it opens the catalog search titled for the action.
    await _pumpUntilFound(tester, find.text('Search the exercise catalog'));
    expect(find.text('Replace exercise'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    // Add an unplanned exercise, whose menu carries Remove.
    final Finder add = find.widgetWithText(OutlinedButton, 'Add exercise');
    await tester.ensureVisible(add);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(add);
    await _pumpUntilFound(tester, find.text('Search the exercise catalog'));
    await _searchAndPick(tester, 'curl', 'Bicep Curl');
    expect(find.text('Unplanned'), findsOneWidget);

    // The day has two planned exercises, so the added one is card 2.
    await _openMenu(tester, 2);
    expect(find.text('Replace exercise'), findsOneWidget);
    expect(find.text('Rest time…'), findsOneWidget);
    expect(find.text('Remove exercise'), findsOneWidget);
    expect(_removeItem(2), findsOneWidget);
  });

  testWidgets(
      'replacing with ticked sets asks first, then clears the rows and swaps '
      'the card (#162)', (WidgetTester tester) async {
    final ({FakeMayosApi fake, InMemoryActiveWorkoutStore store,
        InMemoryRestLengthStore restLengths}) harness =
        await _openLogger(tester);

    // Two ticked sets on Bench: the confirmation gate.
    await _tickSet(tester, 0, 0);
    await _tickSet(tester, 0, 1);
    expect(find.text('2/4 sets'), findsOneWidget);

    await _pickMenuItem(tester, 0, _replaceItem(0));
    expect(
      find.text('Replace and discard 2 logged sets?'),
      findsOneWidget,
    );
    // "Keep logging" leaves everything as it was.
    await tester.tap(find.text('Keep logging'));
    await tester.pumpAndSettle();
    expect(find.text('Bench Press'), findsOneWidget);
    expect(find.text('2/4 sets'), findsOneWidget);

    // Confirming opens the search, and the pick swaps the card.
    await _pickMenuItem(tester, 0, _replaceItem(0));
    expect(
      find.text('Replace and discard 2 logged sets?'),
      findsOneWidget,
    );
    await tester.tap(find.text('Replace'));
    await tester.pumpAndSettle();
    expect(find.text('Search the exercise catalog'), findsOneWidget);
    await _searchAndPick(tester, 'fly', 'Cable Fly');

    // The planned exercise is no longer a card; the replacement is, with its
    // rows starting empty and the Unplanned pill (#162).
    expect(find.text('Bench Press'), findsNothing);
    expect(find.text('Cable Fly'), findsOneWidget);
    expect(find.text('Unplanned'), findsOneWidget);
    expect(_row(0, 0), findsNothing);
    expect(_row(1, 0), findsOneWidget);
    expect(_row(1, 1), findsOneWidget);
    expect(_row(1, 2), findsOneWidget);
    // Nothing of the discarded log survives on the card: the values the
    // first two sets held are gone, and the replacement's rows are empty.
    expect(find.text('100'), findsNothing);
    expect(find.text('95'), findsNothing);
    expect(
      find.descendant(of: _row(1, 0), matching: find.text('–')),
      findsOneWidget,
    );
    // Progress counts the replacement only: the replaced exercise has no
    // working rows left, so it is no longer a to-do (#162).
    expect(find.text('0/2 exercises · 0/4 sets'), findsOneWidget);

    // …and the swap is what the device stored.
    final ActiveWorkout? stored = await harness.store.read(_account);
    expect(stored, isNotNull);
    expect(stored!.exercises, hasLength(3));
    expect(stored.exercises[0].replaced, isTrue);
    expect(stored.exercises[0].sets, isEmpty);
    expect(stored.exercises[1].exerciseId, 'cable_fly');
    expect(stored.exercises[1].unplanned, isTrue);
    // The untouched second planned exercise is exactly where it was.
    expect(stored.exercises[2].exerciseId, 'incline_press');
    expect(stored.exercises[2].replaced, isFalse);
  });

  testWidgets(
      'the Replace search opens pre-filtered to the planned exercise\'s '
      'target muscle, and stays searchable across the catalog (#162)',
      (WidgetTester tester) async {
    await _openLogger(tester);

    await _pickMenuItem(tester, 0, _replaceItem(0));
    await _pumpUntilFound(tester, find.text('Search the exercise catalog'));
    expect(find.text('Replace exercise'), findsOneWidget);
    // Bench's catalog detail says Chest, and the chip opens *on* — the
    // pre-filter is applied before the player types anything.
    expect(find.text('Muscle: Chest'), findsOneWidget);
    expect(_muscleFilter(), findsOneWidget);

    // 'e' matches all three catalog rows; only Chest exercises are offered.
    Finder dialog() => find.byType(AlertDialog);
    Finder inDialog(String text) =>
        find.descendant(of: dialog(), matching: find.text(text));

    await tester.enterText(find.byType(TextField).last, 'e');
    await tester.tap(find.text('Search'));
    await _pumpUntilFound(tester, inDialog('Bench Press'));
    // 'e' matches every catalog row; only the Chest ones are offered.
    expect(inDialog('Cable Fly'), findsOneWidget);
    expect(inDialog('Bicep Curl'), findsNothing);

    // Clearing the filter searches the whole catalog…
    await tester.tap(_muscleFilter());
    await tester.pumpAndSettle();
    expect(inDialog('Bicep Curl'), findsOneWidget);
    expect(inDialog('Cable Fly'), findsOneWidget);
    expect(inDialog('Bench Press'), findsOneWidget);

    // …and turning it back on narrows the same results again.
    await tester.tap(_muscleFilter());
    await tester.pumpAndSettle();
    expect(inDialog('Bicep Curl'), findsNothing);

    // A search no muscle matches says so, and points at the filter.
    await tester.enterText(find.byType(TextField).last, 'curl');
    await tester.tap(find.text('Search'));
    await _pumpUntilFound(
      tester,
      find.textContaining('Tap the muscle filter to search the whole catalog'),
    );
    expect(inDialog('Bicep Curl'), findsNothing);
  });

  testWidgets('Rest time… in the menu opens the #125 picker and writes the '
      'device override (#162)', (WidgetTester tester) async {
    final ({FakeMayosApi fake, InMemoryActiveWorkoutStore store,
        InMemoryRestLengthStore restLengths}) harness =
        await _openLogger(tester);

    await _pickMenuItem(tester, 0, _restItem(0));
    expect(find.text('Off'), findsOneWidget);
    final Finder option = find.byKey(const ValueKey<String>('rest.option.135'));
    if (option.evaluate().isEmpty) {
      await tester.drag(find.byType(ListView), const Offset(0, -800));
      await tester.pumpAndSettle();
    }
    await tester.tap(find.byKey(const ValueKey<String>('rest.option.135')));
    await tester.pumpAndSettle();

    // The rest length stays visible on the prescription line (#162).
    expect(find.textContaining('Rest 2:15'), findsOneWidget);
    expect(harness.restLengths.values[_account]?['bench_press'], 135);
    // The interim chip is gone from the title row: no second "Rest" label.
    expect(find.text('Rest 2:15'), findsNothing);
  });

  testWidgets('Remove exercise takes an unplanned exercise out of the '
      'workout (#162)', (WidgetTester tester) async {
    final ({FakeMayosApi fake, InMemoryActiveWorkoutStore store,
        InMemoryRestLengthStore restLengths}) harness =
        await _openLogger(tester);

    final Finder add = find.widgetWithText(OutlinedButton, 'Add exercise');
    await tester.ensureVisible(add);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(add);
    await _pumpUntilFound(tester, find.text('Search the exercise catalog'));
    await _searchAndPick(tester, 'curl', 'Bicep Curl');
    expect(find.text('Bicep Curl'), findsOneWidget);

    await _pickMenuItem(tester, 2, _removeItem(2));
    expect(find.text('Bicep Curl'), findsNothing);
    expect(find.text('Unplanned'), findsNothing);

    final ActiveWorkout? stored = await harness.store.read(_account);
    expect(stored!.exercises, hasLength(2));
    expect(
      stored.exercises.map((ActiveWorkoutExercise e) => e.exerciseId),
      <String>['bench_press', 'incline_press'],
    );
  });
}
