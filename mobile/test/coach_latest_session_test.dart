import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language/coach_copy.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/features/coach/coach_history_segment.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

Future<void> _pumpUntilFound(
  WidgetTester tester,
  Finder finder, {
  int attempts = 40,
}) async {
  for (int index = 0; index < attempts; index++) {
    if (finder.evaluate().isNotEmpty) {
      for (int frame = 0; frame < 4; frame++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

FakeMayosApi _coachFake({String language = 'en'}) {
  final FakeMayosApi fake = FakeMayosApi()
    ..issuedToken = 'token-history-coach'
    ..currentUsername = 'coach'
    ..tokenValid = true
    ..coach = true
    ..profileExists = true
    ..recoveryEmail = 'coach@example.com'
    ..displayLanguage = language
    ..coachDisplayName = 'Coach';
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-history',
    'player_username': 'bob',
    'started_at': '2026-09-24T10:00:00Z',
    'status': 'active',
  });
  return fake;
}

Map<String, dynamic> _latestSession(FakeMayosApi fake) =>
    fake.coachPlayerSummary['latest_session'] as Map<String, dynamic>;

void _setExercise(
  FakeMayosApi fake, {
  String? imagePath = 'images/bench-press.jpg',
  String? primaryMuscle = 'Chest',
  String? primaryAction = 'Shoulder Horizontal Adduction',
}) {
  _latestSession(fake)['exercises'] = <Map<String, dynamic>>[
    <String, dynamic>{
      'exercise_id': 'bench_press',
      'name': 'Bench Press',
      'sets': 3,
      'reps': 15,
      'volume_kg': 2000.0,
      'image_path': imagePath,
      'primary_muscle': primaryMuscle,
      'primary_action': primaryAction,
    },
  ];
}

void _setSessionFlags(FakeMayosApi fake) {
  final Map<String, dynamic> latest = _latestSession(fake)
    ..['warmup_movements'] = <Map<String, dynamic>>[
      <String, dynamic>{
        'exercise_name': 'Band Pull Apart',
        'sets': <Map<String, dynamic>>[
          <String, dynamic>{'reps': 12},
        ],
      },
    ]
    ..['cardio'] = <String, dynamic>{'prescription': 'Bike', 'minutes': 25}
    ..['program_version'] = 4
    ..['active_program_version_at_sync'] = 5
    ..['is_historical_program'] = true
    ..['corrections'] = <Map<String, dynamic>>[
      <String, dynamic>{
        'previous_date': '2026-09-26',
        'corrected_date': '2026-09-25',
        'corrected_at': '2026-09-26T12:00:00Z',
      },
    ];
  latest['divergences'] = <Map<String, dynamic>>[
    <String, dynamic>{
      'kind': 'skipped',
      'exercise_id': 'squat',
      'exercise_name': 'Squat',
    },
    <String, dynamic>{
      'kind': 'unplanned',
      'exercise_id': 'row',
      'exercise_name': 'Cable Row',
    },
  ];
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  Size logicalSize = const Size(1440, 1600),
  ThemeMode? themeMode,
}) async {
  tester.view.physicalSize = Size(
    logicalSize.width * 2,
    logicalSize.height * 2,
  );
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save(fake.issuedToken!);
  await tester.pumpWidget(
    authApp(
      fake,
      tokens,
      extraOverrides: <Override>[
        if (themeMode != null)
          themeModeStoreProvider.overrideWithValue(
            InMemoryThemeModeStore(themeMode),
          ),
      ],
    ),
  );
  final String rosterLabel = fake.displayLanguage == 'ar'
      ? 'علاقات التدريب النشطة'
      : 'Active assignments';
  await _pumpUntilFound(tester, find.text(rosterLabel));
  await tester.tap(find.text('bob'));
  await _pumpUntilFound(
    tester,
    find.text(
      fake.displayLanguage == 'ar' ? 'أحدث حصة تدريبية' : 'Latest session',
    ),
  );
}

void main() {
  test('volume formatter groups thousands and omits a zero decimal', () {
    const CoachCopy english = CoachCopy('en');
    const CoachCopy arabic = CoachCopy('ar');

    expect(english.formatVolume(1840), '1,840');
    expect(english.formatVolume(1842.5), '1,842.5');
    expect(arabic.formatVolume(1840), '\u20661,840\u2069');
  });

  testWidgets(
    'desktop Latest session shows enriched table and all flags in dark theme',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _coachFake();
      _setExercise(fake);
      _setSessionFlags(fake);
      await _pumpApp(tester, fake, themeMode: ThemeMode.dark);

      expect(find.text('Upper 1 · 2026-09-25'), findsOneWidget);
      expect(find.text('Exercise'), findsOneWidget);
      expect(find.text('Action'), findsOneWidget);
      expect(find.text('Sets'), findsOneWidget);
      expect(find.text('Reps'), findsOneWidget);
      expect(find.text('Volume (kg)'), findsOneWidget);
      expect(find.text('Bench Press'), findsOneWidget);
      expect(find.text('Chest'), findsWidgets);
      expect(find.text('Shoulder Horizontal Adduction'), findsOneWidget);
      expect(find.text('2,000'), findsOneWidget);
      expect(find.text('2,000 kg'), findsNothing);
      expect(find.text('12 sets · 4,200 kg'), findsOneWidget);
      expect(find.text('Skipped: Squat'), findsOneWidget);
      expect(find.text('Unplanned: Cable Row'), findsOneWidget);
      expect(find.textContaining('Warm-up:'), findsOneWidget);
      expect(find.text('Cardio: 25 min'), findsOneWidget);
      expect(find.text('Readiness 4/5'), findsOneWidget);
      expect(
        find.text('Logged against program v4 (current v5)'),
        findsOneWidget,
      );
      expect(
        find.text('Date corrected from 2026-09-26 to 2026-09-25'),
        findsOneWidget,
      );
      expect(
        Theme.of(tester.element(find.text('Bench Press'))).brightness,
        Brightness.dark,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'phone Latest session wraps flags and shows compact exercise values',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _coachFake();
      _setExercise(fake);
      _setSessionFlags(fake);
      await _pumpApp(tester, fake, logicalSize: const Size(360, 1200));

      expect(find.text('3 sets · 15 reps · 2,000 kg'), findsOneWidget);
      expect(
        find.text('Action: Shoulder Horizontal Adduction'),
        findsOneWidget,
      );
      expect(find.text('Skipped: Squat'), findsOneWidget);
      expect(find.text('Unplanned: Cable Row'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('Arabic Latest session localizes compact rows and uses RTL', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _coachFake(language: 'ar');
    _setExercise(fake);
    _setSessionFlags(fake);
    await _pumpApp(tester, fake, logicalSize: const Size(540, 1200));

    final Finder compactVolume =
        find.textContaining('تكرارًا · إجمالي الوزن المرفوع');
    expect(find.text('أحدث حصة تدريبية'), findsOneWidget);
    expect(find.textContaining('الحركة:'), findsOneWidget);
    expect(find.textContaining('الاستعداد'), findsOneWidget);
    expect(compactVolume, findsOneWidget);
    expect(Directionality.of(tester.element(compactVolume)), TextDirection.rtl);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'missing exercise labels hide muscle and show an em dash action',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _coachFake();
      _setExercise(
        fake,
        imagePath: null,
        primaryMuscle: null,
        primaryAction: null,
      );
      _latestSession(fake)
        ..['readiness_score'] = null
        ..['warmup_movements'] = <dynamic>[]
        ..['cardio'] = null
        ..['program_version'] = null
        ..['active_program_version_at_sync'] = null
        ..['is_historical_program'] = false
        ..['corrections'] = <dynamic>[]
        ..['divergences'] = <dynamic>[];
      fake.coachPlayerSummary['volume'] = <String, dynamic>{};
      await _pumpApp(tester, fake);

      expect(find.text('Chest'), findsNothing);
      expect(find.text('Shoulder Horizontal Adduction'), findsNothing);
      expect(find.text('—'), findsOneWidget);
      expect(find.textContaining('Skipped:'), findsNothing);
      expect(find.textContaining('Unplanned:'), findsNothing);
      expect(find.textContaining('Warm-up:'), findsNothing);
      expect(find.textContaining('Cardio:'), findsNothing);
      expect(find.textContaining('Readiness'), findsNothing);
      expect(find.textContaining('Logged against program'), findsNothing);
      expect(find.textContaining('Date corrected'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('Arabic History segment renders desktop table and localized flags', (
    WidgetTester tester,
  ) async {
    tester.view.physicalSize = const Size(2880, 3200);
    tester.view.devicePixelRatio = 2;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final CoachPlayerLatestSession latest = CoachPlayerLatestSession(
      sessionDate: '2026-10-05',
      splitName: 'Full A',
      setsCount: 3,
      totalVolumeKg: 1840,
      readinessScore: 4,
      programVersion: 4,
      activeProgramVersionAtSync: 5,
      isHistoricalProgram: true,
      corrections: const <PerformedDateCorrection>[
        PerformedDateCorrection(
          previousDate: '2026-10-04',
          correctedDate: '2026-10-05',
          correctedAt: '2026-10-05T12:00:00Z',
        ),
      ],
      exercises: const <CoachPlayerSessionExercise>[
        CoachPlayerSessionExercise(
          exerciseId: 'bench_press',
          name: 'Bench Press',
          sets: 3,
          reps: 24,
          volumeKg: 1840,
          primaryMuscle: 'Chest',
          primaryAction: 'Shoulder Horizontal Adduction',
        ),
      ],
      divergences: const <CoachPlayerDivergence>[
        CoachPlayerDivergence(
          kind: 'skipped',
          exerciseId: 'squat',
          exerciseName: 'Squat',
        ),
        CoachPlayerDivergence(
          kind: 'unplanned',
          exerciseId: 'row',
          exerciseName: 'Cable Row',
        ),
      ],
      warmupMovements: const <WarmupMovementLog>[
        WarmupMovementLog(
          exerciseName: 'Band Pull Apart',
          sets: <WarmupSetLog>[],
        ),
      ],
      cardio: const WorkoutCardio(prescription: 'Bike', minutes: 25),
    );
    final CoachHistorySegment segment = CoachHistorySegment(
      data: CoachHistorySegmentData(
        summary: CoachPlayerSummary(
          playerUsername: 'player',
          startedAt: '2026-09-24T10:00:00Z',
          status: 'active',
          volume: const <String, double>{},
          latestSession: latest,
        ),
        records: const <PersonalRecord>[],
        checkpointReviews: const <CheckpointReviewListItem>[],
        exercises: const <CoachPlayerExercise>[],
        histories: const <String, CoachExerciseHistory>{},
        openExerciseId: null,
        loadingHistory: false,
        expandedSections: const <CoachHistorySection, bool>{},
      ),
      onToggleSection: (_) {},
      onExerciseToggle: (_) {},
      onCheckpointTap: (_) {},
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ar'),
        supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        theme: MayosTheme.lightForLanguage('ar'),
        home: MediaQuery(
          data: const MediaQueryData(size: Size(1440, 1600)),
          child: SingleChildScrollView(child: segment),
        ),
      ),
    );

    const CoachCopy copy = CoachCopy('ar');
    for (final String header in <String>[
      copy.programExerciseColumn,
      copy.programActionColumn,
      copy.programSetsColumn,
      copy.programRepsColumn,
      copy.sessionVolumeColumn,
    ]) {
      expect(find.text(header), findsOneWidget);
    }
    for (final String flag in <String>[
      copy.divergence('Skipped', 'Squat'),
      copy.divergence('Unplanned', 'Cable Row'),
      copy.warmupMovements(1),
      copy.cardioMinutes(25),
      copy.readiness(4),
      copy.historicalProgram(4, 5),
      copy.correctedDate('2026-10-04', '2026-10-05'),
    ]) {
      expect(find.text(flag), findsOneWidget);
    }
    expect(find.text(copy.latestSessionTotals(3, 1840)), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.text(copy.sessionVolumeColumn))),
      TextDirection.rtl,
    );
    expect(tester.takeException(), isNull);
  });
}
