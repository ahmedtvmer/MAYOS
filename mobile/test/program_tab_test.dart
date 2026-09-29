import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';

import 'support/fake_mayos_api.dart';

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

Future<T> _waitWithPumps<T>(WidgetTester tester, Future<T> operation) async {
  bool completed = false;
  operation.then((_) => completed = true, onError: (Object error) {
    completed = true;
  });
  for (int attempt = 0; attempt < 80 && !completed; attempt++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  return operation;
}

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<void> _pumpProgram(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeMode mode = ThemeMode.light,
  Size size = const Size(1080, 2400),
  ActiveWorkoutStore? activeWorkoutStore,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore(mode)),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        if (activeWorkoutStore != null)
          activeWorkoutStoreProvider.overrideWithValue(activeWorkoutStore),
        workoutCacheStoreProvider
            .overrideWithValue(InMemoryWorkoutCacheStore()),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
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
  await tester.pump(const Duration(milliseconds: 400));
  await tester.tap(find.text('Program'));
  await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));

  // Resize after navigating so the layout is exercised at the target size
  // without depending on bottom-bar hit-testing at the small viewport.
  if (size != const Size(1080, 2400)) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _openSubstitutePicker(WidgetTester tester) async {
  await tester.drag(find.byType(ListView).first, const Offset(0, -180));
  await tester.pumpAndSettle();
  final Finder moreActions = find.byTooltip('More actions for Bench Press');
  await tester.ensureVisible(moreActions);
  await tester.tap(moreActions);
  await tester.pumpAndSettle();
  await tester.tap(find.text('Substitute exercise'));
  await tester.pumpAndSettle();
  await _pumpUntilFound(tester, find.text('Cable Fly'));
  expect(find.text('Muscle: Chest'), findsOneWidget);
  expect(
    find.descendant(
      of: find.byType(AlertDialog),
      matching: find.text('Bench Press'),
    ),
    findsNothing,
  );
}

Future<void> _chooseCableFly(WidgetTester tester) async {
  await _openSubstitutePicker(tester);
  await tester.tap(find.text('Cable Fly'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('program overview shows real days, prescriptions, and provenance',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    await _pumpProgram(tester, fake);

    expect(find.text('Upper/Lower 4x'), findsOneWidget);
    expect(find.text('Upper/Lower · 4 days/week'), findsOneWidget);
    expect(find.text('Version 6'), findsOneWidget);
    expect(find.text('Former coach'), findsOneWidget);

    // The expanded first day sections warm-up, working sets, and cardio.
    expect(find.text('Warm-up'), findsOneWidget);
    expect(find.text('Working sets'), findsOneWidget);
    expect(find.text('Bench Press'), findsOneWidget);
    expect(find.textContaining('3 × 5–8'), findsOneWidget);
    expect(find.text('Cardio'), findsOneWidget);
  });

  for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets('program renders in ${mode.name} theme without overflow',
        (tester) async {
      final FakeMayosApi fake = _signedInFake();
      await _pumpProgram(
        tester,
        fake,
        mode: mode,
        size: const Size(360, 640),
      );

      expect(
        Theme.of(tester.element(find.text('Upper/Lower 4x'))).brightness,
        mode == ThemeMode.dark ? Brightness.dark : Brightness.light,
      );

      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'substitution picker and other-day option fit 360dp in ${mode.name} theme',
        (tester) async {
      final FakeMayosApi fake = _signedInFake()
        ..repeatBenchPressOnOtherDays = true;
      await _pumpProgram(
        tester,
        fake,
        mode: mode,
        size: const Size(360, 640),
      );

      await _chooseCableFly(tester);
      expect(find.text('Also replace on 2 other days'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('Also replace on 2 other days'));
      await tester.pump();
      await tester.tap(find.text('Substitute'));
      await tester.pumpAndSettle();
      await _pumpUntilFound(tester, find.text('Undo'));
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('menu picker substitution refreshes program and exact Undo',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake);

    await _chooseCableFly(tester);
    await _pumpUntilFound(tester, find.text('Cable Fly'));
    expect(fake.programSubstitutionRequests, hasLength(1));
    expect(fake.programSubstitutionRequests.single, <String, dynamic>{
      'day_name': 'Upper 1',
      'exercise_id': 'bench_press',
      'replacement_exercise_id': 'cable_fly',
      'all_occurrences': false,
    });
    expect(find.text('Undo'), findsOneWidget);

    await tester.tap(find.text('Undo'));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Bench Press'));
    expect(fake.programSubstitutionRequests, hasLength(1));
    expect(fake.programSubstitutionUndoRequests, hasLength(1));
    expect(fake.programSubstitutionUndoRequests.single, <String, dynamic>{
      'restore_version': 1,
      'expected_active_version': 2,
    });
  });

  testWidgets(
      'substitution leaves an active workout frozen and seeds the next one',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryActiveWorkoutStore activeWorkouts =
        InMemoryActiveWorkoutStore();
    await _pumpProgram(tester, fake, activeWorkoutStore: activeWorkouts);
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.text('Day 1: Upper 1')),
      listen: false,
    );
    final ApiClient api = container.read(apiClientProvider);
    final TrainingProgram initialProgram =
        (await _waitWithPumps(tester, api.activeProgram()))!;
    final ActiveWorkoutController controller =
        container.read(activeWorkoutControllerProvider.notifier);
    expect(
      await _waitWithPumps(
        tester,
        controller.startFromDay(
          accountId: 'account-alice',
          day: initialProgram.days.first,
          programVersion: initialProgram.version,
        ),
      ),
      StartWorkoutOutcome.started,
    );
    ActiveWorkout? frozenWorkout = await activeWorkouts.read('account-alice');
    expect(frozenWorkout, isNotNull);
    expect(frozenWorkout!.exercises.map((e) => e.exerciseId),
        contains('bench_press'));
    await _chooseCableFly(tester);
    await _pumpUntilFound(tester, find.text('Cable Fly'));

    frozenWorkout = await activeWorkouts.read('account-alice');
    expect(frozenWorkout!.exercises.map((e) => e.exerciseId),
        contains('bench_press'));
    expect(frozenWorkout.exercises.map((e) => e.exerciseId),
        isNot(contains('cable_fly')));

    await _waitWithPumps(
      tester,
      controller.discard(
        accountId: 'account-alice',
        workoutId: frozenWorkout.id,
      ),
    );
    final TrainingProgram updatedProgram =
        (await _waitWithPumps(tester, api.activeProgram()))!;
    expect(
      await _waitWithPumps(
        tester,
        controller.startFromDay(
          accountId: 'account-alice',
          day: updatedProgram.days.first,
          programVersion: updatedProgram.version,
        ),
      ),
      StartWorkoutOutcome.started,
    );
    final ActiveWorkout? nextWorkout =
        await activeWorkouts.read('account-alice');
    expect(nextWorkout, isNotNull);
    expect(
        nextWorkout!.exercises.map((e) => e.exerciseId), contains('cable_fly'));
    expect(nextWorkout.exercises.map((e) => e.exerciseId),
        isNot(contains('bench_press')));
  });

  testWidgets('other-day choice substitutes all occurrences', (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..repeatBenchPressOnOtherDays = true;
    await _pumpProgram(tester, fake);

    await _chooseCableFly(tester);
    expect(find.text('Also replace on 2 other days'), findsOneWidget);
    await tester.tap(find.text('Also replace on 2 other days'));
    await tester.pump();
    await tester.tap(find.text('Substitute'));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Cable Fly'));

    expect(fake.programSubstitutionRequests.single['all_occurrences'], isTrue);
    expect(
      (fake.programDaysOverride ?? <Map<String, dynamic>>[])
          .expand(
              (Map<String, dynamic> day) => day['exercises'] as List<dynamic>)
          .where((dynamic row) =>
              (row as Map<String, dynamic>)['exercise_id'] == 'bench_press'),
      isEmpty,
    );
  });
}
