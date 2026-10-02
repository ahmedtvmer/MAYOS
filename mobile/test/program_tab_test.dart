import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
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
  WorkoutCacheStore? workoutCacheStore,
  String languageCode = 'en',
}) async {
  fake.displayLanguage = languageCode;
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
        systemDisplayLanguageProvider.overrideWithValue(languageCode),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore(mode)),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        if (activeWorkoutStore != null)
          activeWorkoutStoreProvider.overrideWithValue(activeWorkoutStore),
        workoutCacheStoreProvider.overrideWithValue(
          workoutCacheStore ?? InMemoryWorkoutCacheStore(),
        ),
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
  await _pumpUntilFound(
      tester, find.text(languageCode == 'ar' ? 'الرئيسية' : 'Home'));
  await tester.pump(const Duration(milliseconds: 400));
  await tester
      .tap(find.text(languageCode == 'ar' ? 'البرنامج التدريبي' : 'Program'));
  await _pumpUntilFound(tester,
      find.text(languageCode == 'ar' ? 'اليوم 1: Upper 1' : 'Day 1: Upper 1'));

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
  testWidgets(
      'Arabic program labels translate while split and exercise names remain',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake, languageCode: 'ar');
    expect(find.text('اليوم 1: Upper 1'), findsOneWidget);
    expect(find.text('مجموعات التدريب'), findsOneWidget);
    expect(find.text('Bench Press'), findsOneWidget);
    expect(find.textContaining('4 أيام في الأسبوع'), findsOneWidget);
    final Finder warmupPrescription = find.text('2 × 15 · راحة 45 ثانية');
    expect(warmupPrescription, findsOneWidget);
    expect(
      Directionality.of(tester.element(warmupPrescription)),
      TextDirection.ltr,
    );
    expect(find.text('2 × 15 · rest 45s'), findsNothing);
    expect(Directionality.of(tester.element(find.text('مجموعات التدريب'))),
        TextDirection.rtl);
  });

  testWidgets('Arabic Program translates app-composed deload labels',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()..prescriptionOffline = true;
    final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
    await cache.writePrescription(
      'account-alice',
      1,
      const Prescription(
        deload: DeloadDecision(
          state: DeloadState.suggested,
          reason: 'Acute readiness floor (1/5 logged).',
          volumeMultiplier: 0.5,
          intensityCapRpe: 7.0,
        ),
        targets: <PrescriptionTarget>[],
      ),
    );
    await _pumpProgram(
      tester,
      fake,
      languageCode: 'ar',
      workoutCacheStore: cache,
    );
    await _pumpUntilFound(tester, find.text('اقتُرح تخفيف التدريب'));

    expect(find.text('اقتُرح تخفيف التدريب'), findsOneWidget);
    expect(find.text('Acute readiness floor (1/5 logged).'), findsOneWidget);
    expect(
      find.text(
        'عند التطبيق: خُفضت المجموعات إلى 50% من البرنامج · '
        'ضُبط الجهد عند RIR ≥ 3. أُبلغ مدربك.',
      ),
      findsOneWidget,
    );
    expect(
      tester
          .widget<Text>(
            find.textContaining('RIR ≥ 3'),
          )
          .textDirection,
      TextDirection.ltr,
    );
    expect(find.text('اسأل المساعد'), findsOneWidget);
  });

  testWidgets('program shows a suggested deload and opens the assistant',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..prescriptionOffline = true;
    final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
    await cache.writePrescription(
      'account-alice',
      1,
      const Prescription(
        deload: DeloadDecision(
          state: DeloadState.suggested,
          reason: 'Acute readiness floor (1/5 logged).',
          volumeMultiplier: 0.5,
          intensityCapRpe: 7.0,
        ),
        targets: <PrescriptionTarget>[],
      ),
    );
    await _pumpProgram(tester, fake, workoutCacheStore: cache);
    await _pumpUntilFound(tester, find.text('Deload suggested'));

    expect(find.text('Acute readiness floor (1/5 logged).'), findsOneWidget);
    expect(
      find.text(
        'If applied: sets scaled to 50% of plan · RPE capped at 7. '
        'Your coach has been told.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('deload_banner.chat')));
    await _pumpUntilFound(tester, find.text('Assistant'));

    expect(find.byKey(const Key('chat_composer')), findsOneWidget);
  });

  testWidgets('program overview shows real days, prescriptions, and provenance',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    await _pumpProgram(tester, fake);

    expect(find.text('Upper/Lower 4x'), findsOneWidget);
    expect(find.text('Upper/Lower · 4 days/week'), findsOneWidget);
    expect(find.text('Version 6'), findsNothing);
    expect(find.text('Former coach'), findsOneWidget);

    // The expanded first day sections warm-up, working sets, and cardio.
    expect(find.text('Warm-up'), findsOneWidget);
    expect(find.text('Working sets'), findsOneWidget);
    expect(find.text('Bench Press'), findsOneWidget);
    expect(
        find.text('Suggested substitutes: Incline DB Press'), findsOneWidget);
    expect(find.textContaining('3 × 5–8'), findsOneWidget);
    expect(find.textContaining('2 warm-up sets · rest 180s'), findsOneWidget);
    expect(find.text('Band Pull-Apart'), findsOneWidget);
    expect(find.text('2 × 15 · rest 45s'), findsOneWidget);
    expect(find.text('Pause on the chest.'), findsNothing);
    expect(find.text('Squeeze at the top.'), findsNothing);
    expect(find.text('Cardio'), findsOneWidget);
  });

  testWidgets('exercise detail keeps notes and technique available',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake);

    expect(find.text('Pause on the chest.'), findsNothing);
    await tester.tap(find.text('Bench Press'));
    await _pumpUntilFound(tester, find.text('Pause on the chest.'));

    expect(find.text('Notes'), findsOneWidget);
    expect(find.text('Pause on the chest.'), findsOneWidget);
    expect(find.text('Technique'), findsOneWidget);

    await tester.tap(find.text('Technique'));
    await _pumpUntilFound(tester, find.textContaining('Lie on a flat bench'));
    expect(find.textContaining('Lie on a flat bench'), findsOneWidget);
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

  testWidgets(
      'issue 170: previous coach publication leaves the new assignment in direct control',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..programPublishedByCoachAccountId = 'account-former-coach';
    await _pumpProgram(tester, fake);

    await _chooseCableFly(tester);
    await _pumpUntilFound(tester, find.text('Cable Fly'));
    expect(fake.programSubstitutionRequests, hasLength(1));
    expect(fake.programRequests, isEmpty);
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

  for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets(
        'coach substitution requests are prefilled and fit 360dp in ${mode.name} theme',
        (tester) async {
      final FakeMayosApi fake = _signedInFake()
        ..activeAssignmentId = 'assignment-1'
        ..activeCoachDisplayName = 'Coach Alice'
        ..programPublishedByCoachAccountId = 'account-coach-1'
        ..coachControlsProgram = true;
      await _pumpProgram(
        tester,
        fake,
        mode: mode,
        size: const Size(360, 640),
      );

      await _openSubstitutePicker(tester);
      await tester.tap(find.text('Cable Fly'));
      await tester.pumpAndSettle();

      final Finder requestDialog = find.byType(AlertDialog);
      expect(
        find.descendant(of: requestDialog, matching: find.text('Upper 1')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: requestDialog, matching: find.text('Bench Press')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: requestDialog, matching: find.text('Cable Fly')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('program_request_day_field')), findsNothing);
      expect(find.byKey(const Key('program_request_exercise_field')),
          findsNothing);
      expect(find.byKey(const Key('program_request_replacement_field')),
          findsNothing);
      expect(
        find.descendant(of: requestDialog, matching: find.text('bench_press')),
        findsNothing,
      );

      await tester.tap(find.byKey(const Key('program_request_submit_button')));
      await tester.pumpAndSettle();
      expect(find.text('A reason is required.'), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('program_request_reason_field')),
        'The current movement hurts my shoulder.',
      );
      await tester.tap(find.byKey(const Key('program_request_submit_button')));
      await tester.pumpAndSettle();
      await _pumpUntilFound(
        tester,
        find.textContaining('Your coach has been asked to replace'),
      );

      expect(fake.programRequests, hasLength(1));
      expect(fake.programRequests.single,
          containsPair('kind', 'exercise_substitution'));
      expect(fake.programRequests.single, containsPair('day_name', 'Upper 1'));
      expect(fake.programRequests.single,
          containsPair('exercise_id', 'bench_press'));
      expect(fake.programRequests.single,
          containsPair('replacement_exercise_id', 'cable_fly'));
      expect(fake.programRequests.single,
          containsPair('reason', 'The current movement hurts my shoulder.'));
      expect(fake.programSubstitutionRequests, isEmpty);
      expect(find.text('Bench Press'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('stale request authority refreshes into direct substitution',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..programPublishedByCoachAccountId = 'account-coach-1'
      ..coachControlsProgram = true;
    await _pumpProgram(tester, fake);

    await _openSubstitutePicker(tester);
    await tester.tap(find.text('Cable Fly'));
    await tester.pumpAndSettle();
    fake.coachControlsProgram = false;
    await tester.enterText(
      find.byKey(const Key('program_request_reason_field')),
      'The current movement hurts my shoulder.',
    );
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Undo'));

    expect(fake.programRequests, isEmpty);
    expect(fake.programSubstitutionRequests, hasLength(1));
    expect(
      find.textContaining(
          'Program authority changed. Continuing with direct substitution.'),
      findsOneWidget,
    );
    expect(find.text('Cable Fly'), findsOneWidget);
  });

  testWidgets('stale direct authority refreshes into a coach request',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake);

    await _openSubstitutePicker(tester);
    fake.coachControlsProgram = true;
    await tester.tap(find.text('Cable Fly'));
    await tester.pumpAndSettle();

    expect(
        find.byKey(const Key('program_request_reason_field')), findsOneWidget);
    expect(fake.programSubstitutionRequests, isEmpty);
    await tester.enterText(
      find.byKey(const Key('program_request_reason_field')),
      'The current movement hurts my shoulder.',
    );
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await tester.pumpAndSettle();

    expect(fake.programRequests, hasLength(1));
    expect(fake.programRequests.single['replacement_exercise_id'], 'cable_fly');
    expect(fake.programSubstitutionRequests, isEmpty);
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
