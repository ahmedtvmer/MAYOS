import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/analytics_client.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/display_language/workout_copy.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/performed_date_window.dart';
import 'package:mayos_mobile/src/core/personal_records.dart';
import 'package:mayos_mobile/src/core/theme/mayos_spacing.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/mayos_typography.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_settings_tile.dart';
import 'package:mayos_mobile/src/core/ui/mayos_stat.dart';
import 'package:mayos_mobile/src/core/ui/mayos_player_column.dart';
import 'package:mayos_mobile/src/core/ui/mayos_progress.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';
import 'package:mayos_mobile/src/features/player/exercise/exercise_detail_screen.dart';
import 'package:mayos_mobile/src/features/player/workout/logger_top_bar.dart';
import 'package:mayos_mobile/src/features/player/workout/logger_card_widgets.dart';
import 'package:mayos_mobile/src/features/player/workout/personal_record_badge.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_analytics_client.dart';
import 'support/fake_mayos_api.dart';

const String _account = 'account-alice';

enum _WorkoutSeedVariant { standard, firstExerciseReplaced }

/// The day the tests start from, built for the real controller to seed — the
/// same `ProgramDay` the Program tab hands [ActiveWorkoutController
/// .startFromDay] (#123 item 2).
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

const ProgramDay _warmupDay = ProgramDay(
  dayName: 'Upper A',
  dayOrder: 2,
  warmupExercises: <WarmupExercise>[
    WarmupExercise(exerciseName: 'Cat-Cow', sets: 2, reps: 10),
    WarmupExercise(
      exerciseId: 'band_pull_apart',
      exerciseName: 'Band Pull-Apart',
      sets: 1,
      reps: 12,
    ),
  ],
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

const ProgramDay _prescribedDetailsDay = ProgramDay(
  dayName: 'Upper with details',
  dayOrder: 1,
  warmupExercises: <WarmupExercise>[
    WarmupExercise(
      exerciseName: 'Cat-Cow',
      sets: 1,
      reps: 8,
      restSeconds: 30,
      notes: 'Move smoothly',
    ),
  ],
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'bench_press',
      exerciseName: 'Bench Press',
      targetSets: 2,
      targetRepsMin: 6,
      targetRepsMax: 8,
      targetRpe: 8.5,
      warmupSets: 2,
      restSeconds: 150,
      tempo: '3-1-1',
      notes: 'Pause on the chest',
    ),
  ],
  cardio: 'Cycle for 10 minutes',
);

const ProgramDay _warmupEquipmentDay = ProgramDay(
  dayName: 'Warm-up equipment',
  dayOrder: 1,
  warmupExercises: <WarmupExercise>[
    WarmupExercise(
      exerciseId: 'push_up',
      exerciseName: 'Push-Up',
      equipment: 'body weight',
      sets: 1,
      reps: 10,
    ),
    WarmupExercise(
      exerciseId: 'band_pull_apart',
      exerciseName: 'Band Pull-Apart',
      equipment: 'resistance band',
      sets: 1,
      reps: 12,
    ),
    WarmupExercise(
      exerciseId: 'cat_cow',
      exerciseName: 'Cat-Cow',
      equipment: 'other',
      sets: 1,
      reps: 8,
    ),
  ],
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'bench_press',
      exerciseName: 'Bench Press',
      targetSets: 1,
      targetRepsMin: 5,
      targetRepsMax: 8,
      targetRpe: 8.5,
    ),
  ],
);

const ProgramDay _bodyweightDay = ProgramDay(
  dayName: 'Push',
  dayOrder: 1,
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'push_up',
      exerciseName: 'Push-Up',
      equipment: 'body weight',
      targetSets: 1,
      targetRepsMin: 8,
      targetRepsMax: 15,
      targetRpe: 8.0,
    ),
  ],
);

const ProgramDay _bandDay = ProgramDay(
  dayName: 'Band Work',
  dayOrder: 1,
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'band_pull_apart',
      exerciseName: 'Band Pull-Apart',
      equipment: 'band',
      targetSets: 1,
      targetRepsMin: 8,
      targetRepsMax: 15,
      targetRpe: 8.0,
    ),
  ],
);

final ProgramDay _cardioDay = ProgramDay(
  dayName: 'Upper A',
  dayOrder: 2,
  cardio: 'Steady bike after lifting',
  exercises: _day.exercises,
);

/// Exactly what `ProgramExercise.toJson` writes, which is what the Workout
/// draft carries (#123 item 2: the payload shape is today's).
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

const Map<String, dynamic> _inclineJson = <String, dynamic>{
  'exercise_id': 'incline_press',
  'exercise_name': 'Incline Press',
  'target_sets': 1,
  'target_reps_min': 8,
  'target_reps_max': 12,
  'target_rpe': 8.0,
  'warmup_sets': 0,
  'rest_seconds': 120,
  'notes': null,
};

/// The frozen baseline the fake serves, as wire JSON: two working sets for
/// bench, one unrated set for incline.
List<Map<String, dynamic>> _baselinesBody() => <Map<String, dynamic>>[
      <String, dynamic>{
        'exercise_id': 'bench_press',
        'sessions_logged': 3,
        'performance_sessions_logged': 3,
        'best_zero_load_reps': null,
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
      <String, dynamic>{
        'exercise_id': 'incline_press',
        'sessions_logged': 1,
        'performance_sessions_logged': 1,
        'best_zero_load_reps': null,
        'max_weight_kg': 40.0,
        'best_e1rm_kg': 53.33,
        'last_session': <String, dynamic>{
          'performed_date': '2026-09-26',
          // An unrated previous set: the label drops the `@` part.
          'sets': <Map<String, dynamic>>[
            <String, dynamic>{'weight_kg': 40.0, 'reps': 10, 'rir': null},
          ],
        },
      },
    ];

List<Map<String, dynamic>> _pushUpBaseline({
  required double weightKg,
  required int reps,
}) => <Map<String, dynamic>>[
      <String, dynamic>{
        'exercise_id': 'push_up',
        'sessions_logged': weightKg > 0 ? 1 : 0,
        'performance_sessions_logged': 1,
        'best_zero_load_reps': weightKg == 0 ? reps : null,
        'max_weight_kg': weightKg > 0 ? weightKg : null,
        'best_e1rm_kg': weightKg > 0 ? weightKg * 1.2 : null,
        'last_session': <String, dynamic>{
          'performed_date': '2026-09-26',
          'sets': <Map<String, dynamic>>[
            <String, dynamic>{
              'weight_kg': weightKg,
              'reps': reps,
              'rir': null,
            },
          ],
        },
      },
    ];

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

FakeMayosApi _signedInFake({List<Map<String, dynamic>>? baselines}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.baselinesBody = baselines ?? _baselinesBody();
  return fake;
}

/// Builds the stored Active workout through the real controller — the seeding,
/// the baseline freeze, and the persistence are the app's own, so the rows the
/// table renders are the rows a player would start with (#123 item 2).
Future<InMemoryActiveWorkoutStore> _seedThroughController({
  required FakeMayosApi fake,
  required String startedAt,
  ProgramDay day = _day,
  InMemoryWorkoutCacheStore? workoutCache,
}) async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
  final ProviderContainer container = ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      workoutCacheStoreProvider.overrideWithValue(
        workoutCache ?? InMemoryWorkoutCacheStore(),
      ),
      baselineCacheStoreProvider
          .overrideWithValue(InMemoryBaselineCacheStore()),
      activeWorkoutStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWith((Ref ref) => _api(fake, tokens)),
    ],
  );
  addTearDown(container.dispose);
  final ActiveWorkoutController controller =
      container.read(activeWorkoutControllerProvider.notifier);
  final StartWorkoutOutcome outcome = await controller.startFromDay(
    accountId: _account,
    day: day,
    programVersion: 3,
  );
  expect(outcome, StartWorkoutOutcome.started);
  final ActiveWorkout? seeded = controller.workout;
  expect(seeded, isNotNull);
  // Restamping the start keeps the test's own clock out of the assertions.
  final ActiveWorkout restamped = ActiveWorkout(
    id: seeded!.id,
    accountId: seeded.accountId,
    startedAt: startedAt,
    dayOrder: seeded.dayOrder,
    dayName: seeded.dayName,
    warmupMovements: seeded.warmupMovements,
    cardio: seeded.cardio,
    deload: seeded.deload,
    programVersion: seeded.programVersion,
    exercises: seeded.exercises,
    baselines: seeded.baselines,
  );
  await store.write(_account, restamped);
  return store;
}

ApiClient _api(FakeMayosApi fake, TokenStore tokens) => ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );

/// The 1080×2400 phone canvas every logger test opens on.
void _usePhoneView(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

/// Everything one app instance is pumped with. The same list over the same
/// store is exactly what an app restart rebuilds from (#159), so a test can
/// tear the tree down and open it again against the same storage.
List<Override> _appOverrides({
  required FakeMayosApi fake,
  required InMemoryTokenStore tokens,
  required InMemoryActiveWorkoutStore store,
  InMemoryDraftStore? drafts,
  InMemoryWorkoutCacheStore? workoutCache,
  ThemeMode themeMode = ThemeMode.light,
  DateTime Function()? clock,
  bool webDirectCommit = false,
  FakeAnalyticsClient? analytics,
  String languageCode = 'en',
}) =>
    <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
      themeModeStoreProvider
          .overrideWithValue(InMemoryThemeModeStore(themeMode)),
      systemDisplayLanguageProvider.overrideWithValue(languageCode),
      draftStoreProvider.overrideWithValue(drafts ?? InMemoryDraftStore()),
      workoutCacheStoreProvider
          .overrideWithValue(workoutCache ?? InMemoryWorkoutCacheStore()),
      chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
      baselineCacheStoreProvider
          .overrideWithValue(InMemoryBaselineCacheStore()),
      activeWorkoutStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(
        analytics ?? const NoOpAnalyticsClient(),
      ),
      deviceTimezoneProvider.overrideWithValue(Future<String>.value('UTC')),
      deviceTimezoneOrNullProvider
          .overrideWithValue(Future<String?>.value('UTC')),
      // Workout time and the summary's duration read this clock (#159).
      if (clock != null) clockProvider.overrideWithValue(clock),
      webDirectWorkoutCommitEnabledProvider.overrideWithValue(webDirectCommit),
      apiClientProvider.overrideWith((ref) {
        final ApiClient client = ApiClient(
          tokens: ref.watch(tokenStoreProvider),
          baseUrl: 'http://test.local',
          adapter: fake.adapter,
        );
        client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
        return client;
      }),
    ];

Future<void> _pumpApp(WidgetTester tester,
    {required List<Override> overrides}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: overrides,
    child: const MayosApp(),
  ));
}

/// The app-open Resume prompt, then the logger — the real entry into the
/// table logger (#123).
Future<void> _resumeFromPrompt(
  WidgetTester tester, {
  String languageCode = 'en',
}) async {
  final bool arabic = languageCode == 'ar';
  final String homeLabel = arabic ? 'الرئيسية' : 'Home';
  final String promptTitle = arabic ? 'حصة غير مكتملة' : 'Unfinished workout';
  final String resumeLabel = arabic ? 'استئناف' : 'Resume';
  await _pumpUntilFound(tester, find.text(homeLabel));
  await _pumpUntilFound(tester, find.text(promptTitle));
  expect(find.text(promptTitle), findsOneWidget);
  await tester.tap(find.text(resumeLabel));
  await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
}

/// The signed-in app with a stored Active workout, opened through the
/// app-open Resume prompt — the real entry into the table logger (#123).
/// Returns the shared store, so a test can assert what the app did to it.
Future<InMemoryActiveWorkoutStore> _openLogger(
  WidgetTester tester, {
  String startedAt = '2026-09-28T08:00:00.000Z',
  InMemoryDraftStore? drafts,
  InMemoryWorkoutCacheStore? workoutCache,
  List<Map<String, dynamic>>? baselines,
  ThemeMode themeMode = ThemeMode.light,
  DateTime Function()? clock,
  ProgramDay day = _day,
  _WorkoutSeedVariant workoutSeedVariant = _WorkoutSeedVariant.standard,
  FakeMayosApi? fakeApi,
  bool webDirectCommit = false,
  String? languageCode,
  bool roundTripStoredWorkout = false,
  FakeAnalyticsClient? analytics,
}) async {
  _usePhoneView(tester);

  final FakeMayosApi fake = fakeApi ?? _signedInFake(baselines: baselines);
  final String effectiveLanguage = languageCode ?? fake.displayLanguage;
  if (languageCode != null) fake.displayLanguage = languageCode;
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  // Seeding talks to the (fake) API on real timers, so it runs outside the
  // test's fake-async zone.
  final InMemoryActiveWorkoutStore store = (await tester.runAsync(
    () => _seedThroughController(
      fake: fake,
      startedAt: startedAt,
      day: day,
      workoutCache: workoutCache,
    ),
  ))!;
  if (workoutSeedVariant == _WorkoutSeedVariant.firstExerciseReplaced) {
    final ActiveWorkout seeded = (await store.read(_account))!;
    final ActiveWorkoutExercise replacedExercise =
        seeded.exercises.first.copyWith(
      sets: const <ActiveWorkoutSet>[],
      replaced: true,
    );
    final ActiveWorkoutExercise replacementExercise = ActiveWorkoutExercise(
      exercise: <String, dynamic>{
        ...seeded.exercises.first.exercise,
        'exercise_id': 'cable_fly',
        'exercise_name': 'Cable Fly',
      },
      sets: const <ActiveWorkoutSet>[],
      unplanned: true,
    );
    await store.write(
      _account,
      seeded.copyWith(
        exercises: <ActiveWorkoutExercise>[
          replacedExercise,
          replacementExercise,
          ...seeded.exercises.skip(1),
        ],
      ),
    );
  }
  if (roundTripStoredWorkout) {
    final ActiveWorkout seeded = (await store.read(_account))!;
    await store.write(
      _account,
      ActiveWorkout.fromJson(
        jsonDecode(jsonEncode(seeded.toJson())) as Map<String, dynamic>,
      ),
    );
  }

  await _pumpApp(
    tester,
    overrides: _appOverrides(
      fake: fake,
      tokens: tokens,
      store: store,
      drafts: drafts,
      workoutCache: workoutCache,
      themeMode: themeMode,
      clock: clock,
      webDirectCommit: webDirectCommit,
      analytics: analytics,
      languageCode: effectiveLanguage,
    ),
  );
  await _resumeFromPrompt(tester, languageCode: effectiveLanguage);
  return store;
}

Future<void> _finishAndOpenSummary(WidgetTester tester) async {
  Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
  if (finish.evaluate().isEmpty) {
    finish = find.widgetWithText(FilledButton, 'إنهاء الحصة');
  }
  await tester.tap(finish);
  await tester.pumpAndSettle();
  final Finder discard = find.text('Discard unticked sets and finish');
  if (discard.evaluate().isNotEmpty) {
    await tester.tap(discard);
  }
  await tester.pumpAndSettle();
}

WorkoutDraft _summaryDraft(String id, String performedDate) => WorkoutDraft(
      clientSessionId: id,
      accountId: _account,
      performedDate: performedDate,
      performedTimezone: 'UTC',
      programVersion: 3,
      dayOrder: 2,
      dayName: 'Upper A',
      capturedAt: '${performedDate}T12:00:00Z',
      exercises: const <DraftExercise>[],
      readiness: 4,
      updatedAt: '${performedDate}T12:00:00Z',
    );

Finder _cell(int exercise, int set, String field) =>
    find.byKey(ValueKey<String>('logger.cell.$exercise.$set.$field'));

Finder _tick(int exercise, int set) =>
    find.byKey(ValueKey<String>('logger.tick.$exercise.$set'));

Finder _row(int exercise, int set) =>
    find.byKey(ValueKey<String>('logger.row.$exercise.$set'));

/// The row's own background: null while pending, the Current set's blue wash,
/// or the ticked tint — what the player actually sees (#158).
Color? _rowColor(WidgetTester tester, Finder row) =>
    (tester.widget<Container>(row).decoration as BoxDecoration).color;

Color _textColor(WidgetTester tester, Finder finder) => tester
    .widget<Text>(find.descendant(of: finder, matching: find.byType(Text)))
    .style!
    .color!;

Finder _badge(int exercise, int set, PrRecordKind kind) =>
    find.byKey(ValueKey<String>('logger.pr.$exercise.$set.${kind.name}'));

void _expectWithinColumn(Rect item, Rect column) {
  expect(item.left, greaterThanOrEqualTo(column.left));
  expect(item.right, lessThanOrEqualTo(column.right));
  expect(item.top, greaterThanOrEqualTo(column.top));
  expect(item.bottom, lessThanOrEqualTo(column.bottom));
}

/// Whether the badge under a row is struck through (beaten by a later set).
TextDecoration? _badgeDecoration(WidgetTester tester, Finder badge) => tester
    .widget<Text>(find.descendant(of: badge, matching: find.byType(Text)))
    .style!
    .decoration;

/// Types [digits] into one cell through the app's own keypad, then hides it,
/// leaving the row ready to tick.
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

/// Records every message the app sends on `SystemChannels.platform`, so a
/// test can count its `HapticFeedback` calls.
List<MethodCall> _recordPlatformCalls(WidgetTester tester) {
  final List<MethodCall> calls = <MethodCall>[];
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform, (MethodCall call) async {
    calls.add(call);
    return null;
  });
  addTearDown(() => tester.binding.defaultBinaryMessenger
      .setMockMethodCallHandler(SystemChannels.platform, null));
  return calls;
}

/// How many heavy vibrations the app has fired — the record badge's haptic
/// (#124), as opposed to the selection click every tick also plays.
int _heavyImpacts(List<MethodCall> calls) => calls
    .where((MethodCall call) =>
        call.method == 'HapticFeedback.vibrate' &&
        call.arguments == 'HapticFeedbackType.heavyImpact')
    .length;

/// Opens the logger at 360×640 in [mode] and checks what the #158 review
/// asks of the row: nothing overflows, every control keeps a 48dp target,
/// and the two fixed columns (SET, ✓) are a full 48dp wide.
Future<void> _assertNoOverflowAt360(
  WidgetTester tester, {
  required ThemeMode mode,
}) async {
  await _openLogger(tester, themeMode: mode);
  tester.view.physicalSize = const Size(360, 640);
  tester.view.devicePixelRatio = 1.0;
  await tester.pump(const Duration(milliseconds: 300));
  expect(tester.takeException(), isNull);

  // The fixed columns: SET number and tick, 48dp each at any width (#158).
  expect(
    tester
        .getSize(find.byKey(const ValueKey<String>('logger.setlabel.0.0')))
        .width,
    greaterThanOrEqualTo(48),
  );
  expect(
    tester
        .getSize(find.byKey(const ValueKey<String>('logger.setlabel.0.0')))
        .height,
    kMayosMinTapTarget,
  );
  expect(tester.getSize(_tick(0, 0)).width, greaterThanOrEqualTo(48));
  expect(tester.getSize(_tick(0, 0)).height, kMayosMinTapTarget);

  // The value cells stay 48dp tall wherever their share lands.
  expect(tester.getSize(_cell(0, 0, 'kg')).height, kMayosMinTapTarget);
  expect(tester.getSize(_cell(0, 0, 'rir')).height, kMayosMinTapTarget);

  // The row spans the card rather than a fixed cramped width.
  expect(tester.getSize(_row(0, 0)).width, greaterThan(250));
  expect(tester.getSize(_row(0, 0)).width, lessThan(360));
}

void main() {
  testWidgets('logger shows Coach exercise details without opening library details',
      (WidgetTester tester) async {
    const ProgramDay day = ProgramDay(
      dayName: 'Upper A',
      dayOrder: 1,
      exercises: <ProgramExercise>[
        ProgramExercise(
          exerciseId: 'coach:pin-squat',
          exerciseName: 'Pin Squat',
          targetSets: 2,
          targetRepsMin: 5,
          targetRepsMax: 8,
          targetRpe: 8,
          note: 'Pause on the pins.',
          videoUrl: 'https://example.com/pin-squat',
          isCoachExercise: true,
        ),
      ],
    );
    await _openLogger(tester, day: day);

    expect(find.text('Pause on the pins.'), findsOneWidget);
    expect(find.text('Watch exercise video'), findsOneWidget);
    await tester.tap(find.text('Pin Squat'));
    await tester.pumpAndSettle();

    expect(find.byType(ExerciseDetailScreen), findsNothing);
    expect(find.byKey(const Key('logger_coach_exercise_video_coach:pin-squat')),
        findsOneWidget);
  });

  testWidgets('workout logger shows the applied deload and opens the assistant',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()..prescriptionOffline = true;
    final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
    await cache.writePrescription(
      _account,
      _day.dayOrder,
      const Prescription(
        deload: DeloadDecision(
          state: DeloadState.applied,
          reason: 'Rolling readiness crash across the last 3 sessions.',
          volumeMultiplier: 0.5,
          intensityCapRpe: 7.0,
        ),
        targets: <PrescriptionTarget>[],
      ),
    );
    await _openLogger(tester, fakeApi: fake, workoutCache: cache);

    expect(find.byKey(const ValueKey<String>('logger.deload')), findsOneWidget);
    expect(find.text('Deload applied'), findsOneWidget);
    expect(
      find.text(
        'Applied: sets scaled to 50% of plan · RPE capped at 7.',
      ),
      findsOneWidget,
    );
    expect(
      (await cache.readPrescription(_account, _day.dayOrder))?.deload.state,
      DeloadState.applied,
    );
    await tester.tap(find.byKey(const ValueKey<String>('deload_banner.chat')));
    await _pumpUntilFound(tester, find.text('Assistant'));

    expect(find.byKey(const Key('chat_composer')), findsOneWidget);
  });

  testWidgets(
      'warm-up movements show prescribed rows and stay outside work progress',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store =
        await _openLogger(tester, day: _warmupDay);

    expect(find.byKey(const ValueKey<String>('logger.warmup.section')),
        findsOneWidget);
    final Finder exercisesSection =
        find.byKey(const ValueKey<String>('logger.exercises.section'));
    expect(exercisesSection, findsOneWidget);
    expect(find.text('Exercises'), findsOneWidget);
    expect(find.byType(WarmupMovementLoggingCard), findsNWidgets(2));
    expect(
      tester.getRect(exercisesSection).top,
      greaterThanOrEqualTo(
        tester.getRect(find.byType(WarmupMovementLoggingCard).last).bottom,
      ),
    );
    expect(
      tester.getRect(exercisesSection).bottom,
      lessThanOrEqualTo(
        tester.getRect(find.byType(ExerciseLoggingCard).first).top,
      ),
    );
    expect(
      tester
          .widget<TextFormField>(
              find.byKey(const ValueKey<String>('logger.warmup.0.0.kg')))
          .initialValue,
      isEmpty,
    );
    expect(
      tester
          .widget<TextFormField>(
              find.byKey(const ValueKey<String>('logger.warmup.0.0.reps')))
          .initialValue,
      '10',
    );
    expect(
      tester
          .widget<TextFormField>(
              find.byKey(const ValueKey<String>('logger.warmup.1.0.reps')))
          .initialValue,
      '12',
    );

    await tester
        .tap(find.byKey(const ValueKey<String>('logger.warmup.0.0.tick')));
    await tester.pumpAndSettle();
    final ActiveWorkout persisted = (await store.read(_account))!;
    expect(persisted.warmupMovements[0].sets[0].ticked, isTrue);
    expect(persisted.warmupMovements[0].sets[0].weightKg, isNull);
    expect(persisted.warmupMovements[0].sets[1].ticked, isFalse);
    expect(currentSetOf(persisted), (exerciseIndex: 0, setIndex: 0));
    expect(workoutProgressOf(persisted).setsTotal, 4);
    expect(workoutProgressOf(persisted).setsTicked, 0);

    await tester.tap(find.text('Finish workout'));
    await tester.pumpAndSettle();
    expect(find.text('Workout summary'), findsNothing);
    expect(find.text('Log at least one set'), findsOneWidget);
  });

  testWidgets('logger carries tempo, notes, warm-up sets, and day blocks',
      (tester) async {
    final InMemoryActiveWorkoutStore store = await _openLogger(
      tester,
      day: _prescribedDetailsDay,
    );

    expect(find.byKey(const ValueKey<String>('logger.warmup.section')),
        findsOneWidget);
    expect(find.text('Cycle for 10 minutes'), findsOneWidget);
    expect(find.text('1 × 8 · rest 30s'), findsOneWidget);
    expect(find.text('Exercise notes: Move smoothly'), findsOneWidget);
    final ActiveWorkout activeWorkout = (await store.read(_account))!;
    expect(
      find.textContaining('2 ramped warm-up sets · 3 sets · 6–8 reps'),
      findsOneWidget,
    );
    expect(find.text('Tempo: 3-1-1'), findsOneWidget);
    expect(find.text('Exercise notes: Pause on the chest'), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('logger.row.0.0')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('logger.row.0.1')), findsOneWidget);
    expect(
      tester
          .widget<Text>(find.descendant(
            of: find.byKey(const ValueKey<String>('logger.setlabel.0.0')),
            matching: find.byType(Text),
          ))
          .data,
      '1',
    );
    expect(
      tester
          .widget<Text>(find.descendant(
            of: find.byKey(const ValueKey<String>('logger.setlabel.0.1')),
            matching: find.byType(Text),
          ))
          .data,
      '2',
    );
    expect(
      tester
          .widget<Text>(find.descendant(
            of: find.byKey(const ValueKey<String>('logger.setlabel.0.2')),
            matching: find.byType(Text),
          ))
          .data,
      '3',
    );
    expect(
      activeWorkout.exercises.first.sets
          .where((ActiveWorkoutSet set) => set.isWarmup)
          .length,
      0,
    );
    expect(workoutProgressOf(activeWorkout).setsTotal, 3);
  });

  for (final String languageCode in <String>['en', 'ar']) {
    testWidgets(
        '$languageCode workout without Warm-up has no section headers',
        (WidgetTester tester) async {
      await _openLogger(tester, languageCode: languageCode);

      expect(find.byKey(const ValueKey<String>('logger.warmup.section')),
          findsNothing);
      expect(find.byKey(const ValueKey<String>('logger.exercises.section')),
          findsNothing);
      expect(
        find.text(languageCode == 'ar' ? 'التمارين' : 'Exercises'),
        findsNothing,
      );
      expect(find.byType(WarmupMovementLoggingCard), findsNothing);
      expect(find.byType(CardioLoggingCard), findsNothing);
    });
  }

  testWidgets('Arabic section headers render with right-to-left direction',
      (WidgetTester tester) async {
    await _openLogger(tester, day: _warmupDay, languageCode: 'ar');

    final Finder exercisesSection =
        find.byKey(const ValueKey<String>('logger.exercises.section'));
    expect(exercisesSection, findsOneWidget);
    expect(find.text('التمارين'), findsOneWidget);
    expect(
      Directionality.of(tester.element(exercisesSection)),
      TextDirection.rtl,
    );
    expect(
      tester
          .renderObject<RenderParagraph>(find.text('التمارين'))
          .textDirection,
      TextDirection.rtl,
    );
    expect(
      tester.renderObject<RenderParagraph>(find.text('التمارين')).textAlign,
      TextAlign.start,
    );

    expect(find.byKey(const ValueKey<String>('logger.warmup.section')),
        findsOneWidget);
    expect(find.text('الإحماء'), findsOneWidget);
  });

  testWidgets('Exercises header precedes the first visible card after replace',
      (WidgetTester tester) async {
    await _openLogger(
      tester,
      day: _warmupDay,
      workoutSeedVariant: _WorkoutSeedVariant.firstExerciseReplaced,
    );

    expect(find.text('Bench Press'), findsNothing);
    expect(find.text('Cable Fly'), findsOneWidget);
    expect(find.text('Incline Press'), findsOneWidget);
    final Finder exercisesSection =
        find.byKey(const ValueKey<String>('logger.exercises.section'));
    expect(
      tester.getRect(exercisesSection).bottom,
      lessThanOrEqualTo(
        tester.getRect(find.byType(ExerciseLoggingCard).first).top,
      ),
    );
  });

  testWidgets(
      'prescribed Cardio needs valid minutes and stays outside set progress',
      (WidgetTester tester) async {
    final InMemoryDraftStore drafts = InMemoryDraftStore();
    final InMemoryActiveWorkoutStore store =
        await _openLogger(tester, day: _cardioDay, drafts: drafts);

    expect(find.byType(CardioLoggingCard), findsOneWidget);
    expect(find.text('Steady bike after lifting'), findsOneWidget);
    expect(
      tester
          .widget<IconButton>(find.byKey(
            const ValueKey<String>('logger.cardio.tick'),
          ))
          .onPressed,
      isNull,
    );

    await tester.enterText(
      find.byKey(const ValueKey<String>('logger.cardio.minutes')),
      '601',
    );
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<IconButton>(find.byKey(
            const ValueKey<String>('logger.cardio.tick'),
          ))
          .onPressed,
      isNull,
    );
    await tester.enterText(
      find.byKey(const ValueKey<String>('logger.cardio.minutes')),
      '25',
    );
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<IconButton>(find.byKey(
            const ValueKey<String>('logger.cardio.tick'),
          ))
          .onPressed,
      isNotNull,
    );
    await tester.tap(find.byKey(const ValueKey<String>('logger.cardio.tick')));
    await tester.pumpAndSettle();

    final ActiveWorkout afterCardio = (await store.read(_account))!;
    expect(afterCardio.cardio!.ticked, isTrue);
    expect(afterCardio.cardio!.minutes, 25);
    expect(workoutProgressOf(afterCardio).setsTicked, 0);
    expect(workoutProgressOf(afterCardio).setsTotal, 4);
    expect(currentSetOf(afterCardio), (exerciseIndex: 0, setIndex: 0));

    await tester.tap(_tick(0, 0));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('logger.summary.cardio')),
        findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Save workout'));
    await _pumpUntilFound(tester, find.text('Workouts'));
    final WorkoutDraft draft = (await drafts.read(_account)).single;
    expect(draft.cardio!.prescription, 'Steady bike after lifting');
    expect(draft.cardio!.minutes, 25);
    expect(draft.cardio!.ticked, isTrue);
    expect(draft.toCommitBody()['cardio'], <String, dynamic>{
      'prescription': 'Steady bike after lifting',
      'minutes': 25,
    });
  });

  testWidgets('a linked warm-up name opens library detail without prescription',
      (WidgetTester tester) async {
    await _openLogger(tester, day: _warmupDay);

    final SemanticsNode exerciseName =
        tester.getSemantics(find.text('Band Pull-Apart'));
    expect(exerciseName.flagsCollection.isButton, isTrue);
    await tester.tap(find.text('Band Pull-Apart'));
    await _pumpUntilFound(tester, find.text('Overview'));

    expect(find.text('Band Pull-Apart'), findsOneWidget);
    expect(find.text('Sets × reps'), findsNothing);
  });

  testWidgets('warm-up weight cells label body weight and band zero loads',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store =
        await _openLogger(tester, day: _warmupEquipmentDay);

    TextFormField weightField(int movementIndex) => tester.widget<TextFormField>(
          find.byKey(
            ValueKey<String>('logger.warmup.$movementIndex.0.kg'),
          ),
        );
    InputDecorator weightDecorator(int movementIndex) =>
        tester.widget<InputDecorator>(
          find.descendant(
            of: find.byKey(
              ValueKey<String>('logger.warmup.$movementIndex.0.kg'),
            ),
            matching: find.byType(InputDecorator),
          ),
        );

    expect(weightDecorator(0).decoration.hintText, 'BW');
    expect(weightDecorator(1).decoration.hintText, 'Band');
    expect(weightDecorator(2).decoration.hintText, '—');
    expect(
      find.descendant(
        of: find.byKey(const ValueKey<String>('logger.warmup.0.0.kg')),
        matching: find.text('BW'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const ValueKey<String>('logger.warmup.1.0.kg')),
        matching: find.text('Band'),
      ),
      findsOneWidget,
    );

    await tester.enterText(
      find.byKey(const ValueKey<String>('logger.warmup.0.0.kg')),
      '0',
    );
    await tester.pumpAndSettle();
    expect(weightField(0).controller!.text, '0');
    await tester.tap(
        find.byKey(const ValueKey<String>('logger.warmup.0.0.tick')));
    await tester.pumpAndSettle();
    expect(weightField(0).controller!.text, isEmpty);
    expect(weightDecorator(0).decoration.hintText, 'BW');
    expect(
      (await store.read(_account))!.warmupMovements[0].sets.single.weightKg,
      0,
    );

    await tester.enterText(
      find.byKey(const ValueKey<String>('logger.warmup.1.0.kg')),
      '0',
    );
    await tester.pumpAndSettle();
    await tester.tap(
        find.byKey(const ValueKey<String>('logger.warmup.1.0.tick')));
    await tester.pumpAndSettle();
    expect(weightField(1).controller!.text, isEmpty);
    expect(weightDecorator(1).decoration.hintText, 'Band');
    expect(
      (await store.read(_account))!.warmupMovements[1].sets.single.weightKg,
      0,
    );

    await tester.enterText(
      find.byKey(const ValueKey<String>('logger.warmup.1.0.kg')),
      '20',
    );
    await tester.pumpAndSettle();
    expect(weightField(1).controller!.text, '20');
  });

  testWidgets('warm-up movement sets remain tickable with no weight',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store =
        await _openLogger(tester, day: _warmupEquipmentDay);

    await tester.tap(find.byKey(const ValueKey<String>('logger.warmup.0.0.tick')));
    await tester.pumpAndSettle();

    final ActiveWarmupSet set =
        (await store.read(_account))!.warmupMovements[0].sets.single;
    expect(set.ticked, isTrue);
    expect(set.weightKg, isNull);
    expect(find.text('Push-Up · set 1 · Reps'), findsNothing);
  });

  testWidgets('clearing a warm-up weight commits null',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _openLogger(tester, day: _warmupDay, fakeApi: fake);

    final Finder weight =
        find.byKey(const ValueKey<String>('logger.warmup.0.0.kg'));
    await tester.enterText(weight, '25');
    await tester.pumpAndSettle();
    await tester.enterText(weight, '');
    await tester.pumpAndSettle();
    await tester
        .tap(find.byKey(const ValueKey<String>('logger.warmup.0.0.tick')));
    await tester.tap(_tick(0, 0));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Save workout'));
    await _pumpUntilFound(tester, find.text('Workouts'));

    final FakeRequest commit = fake.adapter.requests.lastWhere(
      (FakeRequest request) =>
          request.method == 'POST' && request.path == '/workouts/sessions',
    );
    expect(commit.body['warmup_movements'], <Map<String, dynamic>>[
      <String, dynamic>{
        'exercise_id': null,
        'exercise_name': 'Cat-Cow',
        'sets': <Map<String, dynamic>>[
          <String, dynamic>{'weight_kg': null, 'reps': 10},
        ],
      },
    ]);
  });

  testWidgets(
      'the table is SET · KG · REPS · RIR · ✓ and the baseline rides on the '
      'card as the Last: line (#158)', (WidgetTester tester) async {
    await _openLogger(tester);
    final MayosThemeExtension c = MayosThemeExtension.light;

    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);

    // Header columns: the PREVIOUS column is gone (#158).
    for (final String label in <String>['SET', 'KG', 'REPS', 'RIR', '✓']) {
      expect(find.text(label), findsWidgets);
    }
    expect(find.text('PREVIOUS'), findsNothing);
    expect(find.text('100 × 5 @1'), findsNothing);

    // The frozen baseline's last session, working sets in logged order, is
    // one line per card…
    expect(find.text('Last: 100kg × 5 · 95kg × 6'), findsOneWidget);
    expect(find.text('Last: 40kg × 10'), findsOneWidget);

    // …and it is matched set by set as the faded hint in every empty cell:
    // bench's first working set…
    expect(_textColor(tester, _cell(0, 0, 'kg')), c.textDisabled);
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('100')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 0, 'reps'), matching: find.text('5')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('1')),
      findsOneWidget,
    );
    // …its second…
    expect(
      find.descendant(of: _cell(0, 1, 'kg'), matching: find.text('95')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 1, 'reps'), matching: find.text('6')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 1, 'rir'), matching: find.text('2')),
      findsOneWidget,
    );
    // …and the third bench set has no previous working set, so its hint is
    // the prescription target (#107/#108).
    expect(
      find.descendant(of: _cell(0, 2, 'kg'), matching: find.text('60')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 2, 'rir'), matching: find.text('≥ 2')),
      findsOneWidget,
    );
    // The prescription line the card now carries, rest included (#158).
    expect(
      find.text('3 sets · 5–8 reps · 60 kg · RIR ≥ 2 · Rest 3:00'),
      findsOneWidget,
    );
    // Incline carries no projection in this fixture, so its line has no
    // weight clause — and one seeded row reads "1 set".
    expect(
      find.text('1 set · 8–12 reps · RIR ≥ 2 · Rest 2:00'),
      findsOneWidget,
    );
    // The Unplanned tag only where it applies: none of the planned cards.
    expect(find.text('Unplanned'), findsNothing);
  });

  testWidgets(
      'the Last: line is hidden entirely when there is no history '
      '(#158)', (WidgetTester tester) async {
    await _openLogger(tester, baselines: <Map<String, dynamic>>[]);

    expect(find.textContaining('Last:'), findsNothing);
    // The rest of the card is unchanged: the prescription is always there.
    expect(
      find.text('3 sets · 5–8 reps · 60 kg · RIR ≥ 2 · Rest 3:00'),
      findsOneWidget,
    );
    // Without a baseline there is nothing to hint from either: the cells
    // fall back to the prescription target.
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('60')),
      findsOneWidget,
    );
  });

  testWidgets(
      'the exercise card names the movement in primary colour and '
      'adds a full-width + Add set (#158)', (WidgetTester tester) async {
    await _openLogger(tester);
    final MayosThemeExtension c = MayosThemeExtension.light;

    // Blue is reserved for what the player must act on (#157).
    expect(tester.widget<Text>(find.text('Bench Press')).style!.color,
        c.textPrimary);
    expect(tester.widget<Text>(find.text('Incline Press')).style!.color,
        c.textPrimary);

    final Finder addSet = find.widgetWithText(OutlinedButton, '+ Add set');
    expect(addSet, findsNWidgets(2));
    // Full-width inside the card, not a quiet text link (#158).
    expect(tester.getSize(addSet.first).width, greaterThan(200));
  });

  testWidgets(
      'a warm-up row has no previous to borrow and is never filled from one',
      (WidgetTester tester) async {
    await _openLogger(tester);
    final MayosThemeExtension c = MayosThemeExtension.light;

    // Set 2 becomes a warm-up: the baseline's second working set is no longer
    // its "previous" — warm-ups count for nothing in the match (#123 item 1).
    await tester.tap(find.byKey(const ValueKey<String>('logger.setlabel.0.1')));
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('W'), findsOneWidget);
    // The warm-up row falls back to the prescription target…
    expect(
      find.descendant(of: _cell(0, 1, 'kg'), matching: find.text('60')),
      findsOneWidget,
    );
    // …and the rows below it renumber: working row 3 is now the *second*
    // working set, so it takes the baseline's second previous working set,
    // while row 1 keeps the first.
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('100')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 2, 'kg'), matching: find.text('95')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 2, 'rir'), matching: find.text('2')),
      findsOneWidget,
    );

    // With no previous to borrow, the tick cannot fill the row: it opens the
    // keypad instead, and the prescription target is the faded hint.
    expect(
      find.descendant(of: _cell(0, 1, 'kg'), matching: find.text('60')),
      findsOneWidget,
    );
    expect(_textColor(tester, _cell(0, 1, 'kg')), c.textDisabled);
    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 2 · Weight (kg)'), findsOneWidget);
    expect(_textColor(tester, _cell(0, 1, 'kg')), c.textDisabled);
  });

  testWidgets('ticking an empty row fills it from the previous values',
      (WidgetTester tester) async {
    await _openLogger(tester);

    final MayosThemeExtension c = MayosThemeExtension.light;
    // Before the tick the cells are empty hints (muted): the previous value
    // where there is one…
    expect(_textColor(tester, _cell(0, 0, 'kg')), c.textDisabled);
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('100')),
      findsOneWidget,
    );

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('100')),
        findsOneWidget);
    expect(find.descendant(of: _cell(0, 0, 'reps'), matching: find.text('5')),
        findsOneWidget);
    expect(find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('1')),
        findsOneWidget);
    // Filled, not hinted: the values now read as real values.
    expect(_textColor(tester, _cell(0, 0, 'kg')), c.textPrimary);
    // No keypad was needed.
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets('ticking with no value and no previous opens the keypad there',
      (WidgetTester tester) async {
    await _openLogger(tester);

    // Bench set 3 has no previous working set, so the tick cannot fill it.
    await tester.tap(_tick(0, 2));
    await tester.pump(const Duration(milliseconds: 100));

    expect(
      find.text('Bench Press · set 3 · Weight (kg)'),
      findsOneWidget,
    );
    // The row was not ticked.
    expect(_textColor(tester, _cell(0, 2, 'kg')),
        MayosThemeExtension.light.textDisabled);

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets(
      'body-weight sets need reps only, show BW, and save 0 kg in an Android draft',
      (WidgetTester tester) async {
    final InMemoryDraftStore drafts = InMemoryDraftStore();
    final InMemoryActiveWorkoutStore store = await _openLogger(
      tester,
      day: _bodyweightDay,
      drafts: drafts,
      roundTripStoredWorkout: true,
    );

    final ActiveWorkout restored = (await store.read(_account))!;
    expect(restored.exercises.single.equipment, 'body weight');
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('BW')),
      findsOneWidget,
    );

    // With no reps, the tick opens the reps keypad directly despite the
    // exercise's zero added load.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Push-Up · set 1 · Reps'), findsOneWidget);
    await _typeCell(tester, 0, 0, 'reps', '12');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    final ActiveWorkout logged = (await store.read(_account))!;
    expect(logged.exercises.single.sets.single.ticked, isTrue);
    expect(logged.exercises.single.sets.single.weightKg, 0);
    expect(find.text('Hide'), findsNothing);

    await _finishAndOpenSummary(tester);
    await tester.tap(find.byKey(const ValueKey<String>('logger.save')));
    await _pumpUntilFound(tester, find.text('Workouts'));

    final List<WorkoutDraft> saved = await drafts.read(_account);
    expect(saved, hasLength(1));
    expect(saved.single.exercises.single.sets.single.weightKg, 0);
  });

  testWidgets('an added load on a body-weight exercise stays numeric',
      (WidgetTester tester) async {
    await _openLogger(tester, day: _bodyweightDay);
    await _typeCell(tester, 0, 0, 'kg', '20');
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('20')),
      findsOneWidget,
    );
  });

  testWidgets('an untouched BW row shows and autofills its previous added load',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = await _openLogger(
      tester,
      day: _bodyweightDay,
      baselines: _pushUpBaseline(weightKg: 20, reps: 10),
    );

    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('20')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('BW')),
      findsNothing,
    );

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    final ActiveWorkoutSet set =
        (await store.read(_account))!.exercises.single.sets.single;
    expect(set.ticked, isTrue);
    expect(set.weightKg, 20);
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets('an entered BW zero overrides a positive previous added load',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = await _openLogger(
      tester,
      day: _bodyweightDay,
      baselines: _pushUpBaseline(weightKg: 20, reps: 10),
    );

    await _typeCell(tester, 0, 0, 'kg', '0');
    final ActiveWorkout stored = (await store.read(_account))!;
    final ActiveWorkout restored = ActiveWorkout.fromJson(
      jsonDecode(jsonEncode(stored.toJson())) as Map<String, dynamic>,
    );
    expect(
      restored.exercises.single.sets.single.weightExplicitlyEntered,
      isTrue,
    );
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('BW')),
      findsOneWidget,
    );
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    final ActiveWorkoutSet set =
        (await store.read(_account))!.exercises.single.sets.single;
    expect(set.ticked, isTrue);
    expect(set.weightKg, 0);
  });

  testWidgets('a BW row with previous zero shows BW and autofills zero',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = await _openLogger(
      tester,
      day: _bodyweightDay,
      baselines: _pushUpBaseline(weightKg: 0, reps: 10),
    );

    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('BW')),
      findsOneWidget,
    );
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    final ActiveWorkoutSet set =
        (await store.read(_account))!.exercises.single.sets.single;
    expect(set.ticked, isTrue);
    expect(set.weightKg, 0);
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets('the logger and summary show localized most-reps records',
      (WidgetTester tester) async {
    for (final String language in <String>['en', 'ar']) {
      await _openLogger(
        tester,
        day: _bodyweightDay,
        languageCode: language,
        baselines: _pushUpBaseline(weightKg: 0, reps: 10),
      );

      await _typeCell(tester, 0, 0, 'reps', '12');
      await tester.tap(_tick(0, 0));
      await tester.pump(const Duration(milliseconds: 100));
      expect(_badge(0, 0, PrRecordKind.mostReps), findsOneWidget);
      expect(
        find.text(language == 'ar' ? 'أكبر عدد من التكرارات' : 'Most reps'),
        findsOneWidget,
      );

      await _finishAndOpenSummary(tester);
      if (language == 'ar') {
        final Finder celebration =
            find.textContaining('أكبر عدد من التكرارات');
        expect(celebration, findsOneWidget);
        expect(
          tester.widget<Text>(celebration).data,
          contains('\u206612\u2069 تكرارًا'),
        );
      } else {
        expect(find.text('Push-Up · Most reps 12 reps'), findsOneWidget);
      }
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets(
      'the logger does not badge the first zero-load session after weighted history',
      (WidgetTester tester) async {
    final List<Map<String, dynamic>> baseline =
        _pushUpBaseline(weightKg: 20, reps: 10);
    baseline.single['performance_sessions_logged'] = 3;
    baseline.single['best_zero_load_reps'] = null;
    await _openLogger(
      tester,
      day: _bodyweightDay,
      baselines: baseline,
    );

    await _typeCell(tester, 0, 0, 'kg', '0');
    await _typeCell(tester, 0, 0, 'reps', '12');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    expect(_badge(0, 0, PrRecordKind.mostReps), findsNothing);
  });

  testWidgets(
      'a previous 0 kg band set autofills and displays the localized Band label',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..displayLanguage = 'ar'
      ..baselinesBody = <Map<String, dynamic>>[
        <String, dynamic>{
          'exercise_id': 'band_pull_apart',
          'sessions_logged': 1,
          'max_weight_kg': 0.0,
          'best_e1rm_kg': 0.0,
          'last_session': <String, dynamic>{
            'performed_date': '2026-09-26',
            'sets': <Map<String, dynamic>>[
              <String, dynamic>{
                'weight_kg': 0.0,
                'reps': 12,
                'rir': null,
              },
            ],
          },
        },
      ];
    final InMemoryActiveWorkoutStore store = await _openLogger(
      tester,
      day: _bandDay,
      fakeApi: fake,
      languageCode: 'ar',
      roundTripStoredWorkout: true,
    );

    expect(find.textContaining('مطاط'), findsNWidgets(2));
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    final ActiveWorkout logged = (await store.read(_account))!;
    expect(logged.exercises.single.sets.single.ticked, isTrue);
    expect(logged.exercises.single.sets.single.weightKg, 0);
    expect(logged.exercises.single.sets.single.reps, 12);
    expect(find.text('Hide'), findsNothing);
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('مطاط')),
      findsOneWidget,
    );
  });

  testWidgets('web commits a body-weight set at 0 kg',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _openLogger(
      tester,
      day: _bodyweightDay,
      fakeApi: fake,
      webDirectCommit: true,
    );

    await _typeCell(tester, 0, 0, 'reps', '10');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await _finishAndOpenSummary(tester);
    await tester.tap(find.byKey(const ValueKey<String>('logger.save')));
    await _pumpUntilFound(tester, find.text('Workouts'));

    final FakeRequest commit = fake.adapter.requests.lastWhere(
      (FakeRequest request) =>
          request.method == 'POST' && request.path == '/workouts/sessions',
    );
    final Map<String, dynamic> exercise =
        (commit.body['sets'] as List<dynamic>).single as Map<String, dynamic>;
    final Map<String, dynamic> set =
        (exercise['sets'] as List<dynamic>).single as Map<String, dynamic>;
    expect(set['weight_kg'], 0);
    expect(set['reps'], 10);
  });

  testWidgets('the keypad Next order is kg → reps → RIR → the next set',
      (WidgetTester tester) async {
    await _openLogger(tester);

    await tester.tap(_cell(0, 0, 'kg'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 1 · Weight (kg)'), findsOneWidget);
    expect(find.text('.'), findsOneWidget); // kg keypad carries the dot

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 1 · Reps'), findsOneWidget);
    expect(find.text('.'), findsNothing); // …reps does not

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 1 · Reps in reserve'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 2 · Weight (kg)'), findsOneWidget);

    // Walk the remaining order: set 2 reps/rir, set 3 kg/reps/rir, then the
    // final Next hides the keypad.
    for (int i = 0; i < 6; i++) {
      await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('Bench Press · set 3 · Reps in reserve'), findsNothing);
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets(
      'the RIR keypad is one-tap chips 0–5+ and Unrated, and a chip advances',
      (WidgetTester tester) async {
    await _openLogger(tester);

    await tester.tap(_cell(0, 0, 'rir'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Unrated'), findsOneWidget);
    expect(find.text('.'), findsNothing);

    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.2')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('2')),
      findsOneWidget,
    );
    expect(_textColor(tester, _cell(0, 0, 'rir')),
        MayosThemeExtension.light.textPrimary);
    // The chip sets the value AND walks on to the next set's kg (#123 item 10).
    expect(find.text('Bench Press · set 2 · Weight (kg)'), findsOneWidget);

    // Unrated clears the effort back to the previous-value hint, and also
    // advances.
    await tester.tap(_cell(0, 0, 'rir'));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.unrated')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('1')),
      findsOneWidget,
    );
    expect(_textColor(tester, _cell(0, 0, 'rir')),
        MayosThemeExtension.light.textDisabled);
    expect(find.text('Bench Press · set 2 · Weight (kg)'), findsOneWidget);

    // The top choice is 5+ — RIR 5, the service's RPE 5 floor — and effort is
    // chips only: no free decimal field anywhere (#111).
    await tester.tap(_cell(0, 0, 'rir'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('5+'), findsOneWidget);
    expect(find.text('.'), findsNothing);
    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.5')));
    await tester.pump(const Duration(milliseconds: 100));
    // RIR 5 reads 5+ in the cell too (#111).
    expect(
      find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('5+')),
      findsOneWidget,
    );
    expect(_textColor(tester, _cell(0, 0, 'rir')),
        MayosThemeExtension.light.textPrimary);
  });

  testWidgets('tapping the SET number cycles N ↔ W and mutes the row',
      (WidgetTester tester) async {
    await _openLogger(tester);

    final Finder label =
        find.byKey(const ValueKey<String>('logger.setlabel.0.0'));
    expect(_textColor(tester, label), MayosThemeExtension.light.textPrimary);

    await tester.tap(label);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('W'), findsOneWidget);
    expect(_textColor(tester, label), MayosThemeExtension.light.textMuted);

    await tester.tap(label);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('W'), findsNothing);
    expect(_textColor(tester, label), MayosThemeExtension.light.textPrimary);
  });

  testWidgets(
      'the Current set is the first unticked working set and moves across '
      'exercises, skipping warm-ups (#158)', (WidgetTester tester) async {
    await _openLogger(tester);
    final MayosThemeExtension c = MayosThemeExtension.light;

    // A fresh workout: bench's first working set is next, everyone else
    // neutral.
    expect(_rowColor(tester, _row(0, 0)), c.accentSubtle);
    expect(_rowColor(tester, _row(0, 1)), isNull);
    expect(_rowColor(tester, _row(0, 2)), isNull);
    expect(_rowColor(tester, _row(1, 0)), isNull);

    // Ticking it moves the highlight on to the next row…
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_rowColor(tester, _row(0, 0)), c.successTint);
    expect(_rowColor(tester, _row(0, 1)), c.accentSubtle);

    // …and turning that row into a warm-up makes the highlight skip it,
    // because warm-ups are never the next working set (#158).
    await tester.tap(find.byKey(const ValueKey<String>('logger.setlabel.0.1')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_rowColor(tester, _row(0, 1)), isNull);
    expect(_rowColor(tester, _row(0, 2)), c.accentSubtle);

    // Ticking the third row carries the Current set across to the next
    // exercise — it is never confined to one card.
    await _typeCell(tester, 0, 2, 'kg', '80');
    await _typeCell(tester, 0, 2, 'reps', '6');
    await tester.tap(_tick(0, 2));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_rowColor(tester, _row(0, 2)), c.successTint);
    expect(_rowColor(tester, _row(1, 0)), c.accentSubtle);

    // Every working set ticked: there is no Current set left to point at.
    await tester.tap(_tick(1, 0));
    await tester.pump(const Duration(milliseconds: 100));
    for (final Finder row in <Finder>[
      _row(0, 0),
      _row(0, 1),
      _row(0, 2),
      _row(1, 0),
    ]) {
      expect(_rowColor(tester, row), isNot(c.accentSubtle));
    }
  });

  testWidgets(
      'row states: a pending check is outlined, a ticked row is '
      'filled, tinted and still editable (#158)', (WidgetTester tester) async {
    await _openLogger(tester);
    final MayosThemeExtension c = MayosThemeExtension.light;

    BoxDecoration tickDecoration(WidgetTester tester) => tester
        .widget<DecoratedBox>(find.descendant(
            of: _tick(0, 1), matching: find.byType(DecoratedBox)))
        .decoration as BoxDecoration;

    // Set 2 is pending: neutral row, outlined check.
    final BoxDecoration pending = tickDecoration(tester);
    expect(pending.color, isNull);
    expect(pending.border, isNotNull);
    expect(_rowColor(tester, _row(0, 1)), isNull);

    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));

    final BoxDecoration done = tickDecoration(tester);
    expect(done.color, c.accent);
    expect(done.border, isNull);
    expect(_rowColor(tester, _row(0, 1)), c.successTint);

    // Ticked values stay editable: the keypad still opens on them (#158).
    await tester.tap(_cell(0, 1, 'reps'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 2 · Reps'), findsOneWidget);
  });

  testWidgets(
      'RIR in the row is a compact selector that opens the existing '
      'chips (#158)', (WidgetTester tester) async {
    await _openLogger(tester);

    // The chevron says it opens…
    expect(
      find.descendant(
          of: _cell(0, 0, 'rir'), matching: find.byIcon(Icons.expand_more)),
      findsOneWidget,
    );
    // …and it opens exactly the keypad's own chips: 0–4, 5+ and Unrated,
    // with no free numeric field anywhere (#111/#158).
    await tester.tap(_cell(0, 0, 'rir'));
    await tester.pump(const Duration(milliseconds: 100));
    for (final int value in <int>[0, 1, 2, 3, 4, 5]) {
      expect(find.byKey(ValueKey<String>('logger.rir.$value')), findsOneWidget);
    }
    expect(find.byKey(const ValueKey<String>('logger.rir.unrated')),
        findsOneWidget);
    expect(find.text('.'), findsNothing);

    // One tap sets the effort and walks on to the next set (#123 item 10).
    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.3')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('3')),
      findsOneWidget,
    );
    expect(find.text('Bench Press · set 2 · Weight (kg)'), findsOneWidget);
  });

  testWidgets(
      'no overflow at 360dp (light) and the row keeps its 48dp '
      'targets (#158)', (WidgetTester tester) async {
    await _assertNoOverflowAt360(tester, mode: ThemeMode.light);
  });

  testWidgets(
      'no overflow at 360dp (dark) and the row keeps its 48dp '
      'targets (#158)', (WidgetTester tester) async {
    await _assertNoOverflowAt360(tester, mode: ThemeMode.dark);
    // The sweep really is dark: the card's title reads the dark token.
    expect(tester.widget<Text>(find.text('Bench Press')).style!.color,
        MayosThemeExtension.dark.textPrimary);
  });

  testWidgets('swiping a middle set row deletes that row only',
      (WidgetTester tester) async {
    await _openLogger(tester);

    final Finder rows = find.byType(Dismissible);
    expect(rows, findsNWidgets(3)); // three bench rows; incline has one
    final List<String> keysBefore = rows
        .evaluate()
        .map(
            (Element element) => (element.widget as Dismissible).key.toString())
        .toList();

    await tester.drag(rows.at(1), const Offset(-600, 0));
    await tester.pumpAndSettle();

    final List<Element> remaining = rows.evaluate().toList();
    expect(remaining, hasLength(2));
    // The survivors keep their own identities: the first and the last row.
    final List<String> keysAfter = remaining
        .map(
            (Element element) => (element.widget as Dismissible).key.toString())
        .toList();
    expect(keysAfter, <String>[keysBefore.first, keysBefore.last]);
  });

  testWidgets(
      'logger keypad backspace has a localized semantic label and deletes one digit',
      (WidgetTester tester) async {
    final SemanticsHandle semantics = tester.ensureSemantics();

    for (final (String language, String label) in <(String, String)>[
      ('en', 'Backspace'),
      ('ar', 'حذف آخر رقم'),
    ]) {
      await tester.pumpWidget(const SizedBox.shrink());
      final InMemoryActiveWorkoutStore store = await _openLogger(
        tester,
        languageCode: language,
        clock: () => DateTime.parse('2026-09-28T08:12:34.000Z'),
      );
      await tester.tap(_cell(0, 0, 'kg'));
      await tester.pump(const Duration(milliseconds: 100));
      for (final String key in <String>['2', '7', 'dot', '5']) {
        await tester.tap(find.byKey(ValueKey<String>('logger.key.$key')));
      }
      await tester.pump(const Duration(milliseconds: 100));

      final Finder backspace = find.bySemanticsLabel(label);
      expect(backspace, findsOneWidget);
      expect(find.text('⌫'), findsNothing);
      await tester.tap(backspace);
      await tester.pump(const Duration(milliseconds: 100));
      final ActiveWorkout updated = (await store.read(_account))!;
      expect(updated.exercises.first.sets.first.weightKg, 27);
    }
    semantics.dispose();
  });

  testWidgets(
      'Arabic keypad persists 27.5 and RIR before an end-to-start swipe deletes the set',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = await _openLogger(
      tester,
      languageCode: 'ar',
      clock: () => DateTime.parse('2026-09-28T08:12:34.000Z'),
    );
    tester.view.physicalSize = const Size(824, 1830);
    tester.view.devicePixelRatio = 2;
    await tester.pump(const Duration(milliseconds: 100));

    expect(
      Directionality.of(tester.element(find.byType(WorkoutLoggerScreen))),
      TextDirection.rtl,
    );

    await tester.tap(_cell(0, 0, 'kg'));
    await tester.pump(const Duration(milliseconds: 100));
    final List<Offset> keypadCenters = <Offset>[
      for (final String key in <String>[
        '1', '2', '3', '4', '5', '6', '7', '8', '9', 'dot', '0', 'backspace',
      ])
        tester.getCenter(
          find.byKey(ValueKey<String>('logger.key.$key')),
        ),
    ];
    for (int row = 0; row < 4; row++) {
      final List<double> x = <double>[
        for (int column = 0; column < 3; column++)
          keypadCenters[row * 3 + column].dx,
      ];
      expect(x, orderedEquals(x.toList()..sort()));
    }
    for (int row = 0; row < 3; row++) {
      expect(
        keypadCenters[row * 3].dy,
        lessThan(keypadCenters[(row + 1) * 3].dy),
      );
    }
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.2')));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.7')));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.dot')));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.5')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('27.5')),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pump(const Duration(milliseconds: 100));

    final ActiveWorkout entered = (await store.read(_account))!;
    final ActiveWorkoutSet enteredSet = entered.exercises.first.sets.first;
    expect(enteredSet.weightKg, 27.5);
    expect(enteredSet.weightExplicitlyEntered, isTrue);

    await tester.tap(_cell(0, 0, 'rir'));
    await tester.pump(const Duration(milliseconds: 100));
    final List<double> rirCenters = <double>[
      for (int value = 0; value <= 5; value++)
        tester.getCenter(find.byKey(ValueKey<String>('logger.rir.$value'))).dx,
    ];
    expect(rirCenters, orderedEquals(rirCenters.toList()..sort()));
    expect(find.text('5+'), findsOneWidget);

    final Finder firstSwipe = find.byType(Dismissible).first;
    final Dismissible row = tester.widget<Dismissible>(firstSwipe);
    expect(row.direction, DismissDirection.endToStart);
    final Container deleteBackground = row.background! as Container;
    expect(deleteBackground.alignment, AlignmentDirectional.centerEnd);
    expect(
      deleteBackground.alignment!.resolve(TextDirection.rtl),
      Alignment.centerLeft,
    );

    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.5')));
    await tester.pump(const Duration(milliseconds: 100));
    final ActiveWorkout rated = (await store.read(_account))!;
    expect(rated.exercises.first.sets.first.weightKg, 27.5);
    expect(rated.exercises.first.sets.first.rir, 5);
    final String removedSetId = rated.exercises.first.sets.first.id;

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('logger.key.hide')), findsNothing);
    await tester.ensureVisible(_row(0, 0));
    await tester.pumpAndSettle();
    await tester.drag(firstSwipe, const Offset(700, 0));
    await tester.pumpAndSettle();
    final ActiveWorkout deleted = (await store.read(_account))!;
    expect(deleted.exercises.first.sets, hasLength(2));
    expect(
      deleted.exercises.first.sets.any((ActiveWorkoutSet set) =>
          set.id == removedSetId),
      isFalse,
    );
  });

  testWidgets('Finish with nothing ticked is blocked by Log at least one set',
      (WidgetTester tester) async {
    await _openLogger(tester);

    final Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
    await tester.tap(finish);
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Log at least one set'), findsOneWidget);
    expect(find.text('Performed date'), findsNothing);
  });

  testWidgets('the unticked-sets sheet offers Keep logging and Discard',
      (WidgetTester tester) async {
    await _openLogger(tester);

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();

    // Four rows, one ticked.
    expect(find.text("3 sets aren't ticked"), findsOneWidget);

    await tester.tap(find.text('Keep logging'));
    await tester.pumpAndSettle();
    expect(find.text("3 sets aren't ticked"), findsNothing);
    expect(find.text('Performed date'), findsNothing);

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();
    expect(find.text('Performed date'), findsOneWidget);
    expect(find.text('Save workout'), findsWidgets);

    // Back from the summary returns to the Active workout.
    await tester.tap(find.byKey(const ValueKey<String>('logger.save.back')));
    await tester.pumpAndSettle();
    expect(find.text('Performed date'), findsNothing);
    expect(find.widgetWithText(FilledButton, 'Finish workout'), findsOneWidget);
  });

  testWidgets(
      'the saved draft matches today\'s shape: ticked sets, warm-up flag, skipped exercise',
      (WidgetTester tester) async {
    final InMemoryDraftStore drafts = InMemoryDraftStore();
    await _openLogger(tester, drafts: drafts);

    // Bench set 1 ticked from the previous values; bench set 2 turned into a
    // warm-up, which has no previous to borrow, so its numbers come from the
    // keypad before it is ticked.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.setlabel.0.1')));
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(_cell(0, 1, 'kg'));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.4')));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.0')));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.1')));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.0')));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.2')));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      find.descendant(of: _cell(0, 1, 'kg'), matching: find.text('40')),
      findsOneWidget,
    );

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    // bench set 3 + the incline exercise are unticked.
    expect(find.text("2 sets aren't ticked"), findsOneWidget);
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'felt strong');
    await tester.tap(find.widgetWithText(FilledButton, 'Save workout'));
    await _pumpUntilFound(tester, find.text('Workouts'));

    final List<WorkoutDraft> saved = await drafts.read(_account);
    expect(saved, hasLength(1));
    final WorkoutDraft draft = saved.single;

    // The scalar shape the logger has always written.
    expect(draft.dayOrder, 2);
    expect(draft.dayName, 'Upper A');
    expect(draft.programVersion, 3);
    expect(draft.performedTimezone, 'UTC');
    // The default is the day the workout started, held to the allowed window.
    expect(
      draft.performedDate,
      formatPerformedDate(performedDateWindow()
          .clamp(DateTime.parse('2026-09-28T08:00:00.000Z').toLocal())),
    );
    expect(draft.readiness, 4);
    expect(draft.notes, 'felt strong');

    // Only ticked sets are logged; the warm-up flag travels with its set; an
    // exercise with no ticked set is `skipped`.
    final List<Map<String, dynamic>> expected = <Map<String, dynamic>>[
      DraftExercise(
        exercise: _benchJson,
        sets: const <WorkoutSetLog>[
          WorkoutSetLog(weightKg: 100, reps: 5, rpe: 9.0),
          WorkoutSetLog(weightKg: 40, reps: 10, rpe: 8.0, isWarmup: true),
        ],
      ).toJson(),
      DraftExercise(
              exercise: _inclineJson,
              sets: const <WorkoutSetLog>[],
              skipped: true)
          .toJson(),
    ];
    expect(
      jsonEncode(draft.exercises
          .map((DraftExercise exercise) => exercise.toJson())
          .toList()),
      jsonEncode(expected),
    );
  });

  testWidgets('an out-of-window start day is clamped and the player is told',
      (WidgetTester tester) async {
    final DateTime tenDaysAgo =
        DateTime.now().subtract(const Duration(days: 10));
    await _openLogger(tester, startedAt: tenDaysAgo.toUtc().toIso8601String());

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();

    // The default lands on the first day the window allows, not the start day.
    final PerformedDateWindow window = performedDateWindow();
    expect(
      find.descendant(
        of: find.widgetWithText(MayosSettingsTile, 'Performed date'),
        matching: find.text(formatPerformedDate(window.first)),
      ),
      findsOneWidget,
    );
    // …and the player is told why.
    expect(
      find.textContaining('outside the allowed entry window'),
      findsWidgets,
    );
  });

  testWidgets(
      'a record badge is solid on the current best, then struck through '
      'when a later set beats it', (WidgetTester tester) async {
    await _openLogger(tester);

    // 105 kg × 5 @RIR 1 beats both of bench's frozen aggregates
    // (100 kg, 121.67 e1RM), so the ticked row earns both badges solid.
    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    final Finder weight = _badge(0, 0, PrRecordKind.weight);
    final Finder e1rm = _badge(0, 0, PrRecordKind.e1rm);
    expect(weight, findsOneWidget);
    expect(e1rm, findsOneWidget);
    expect(tester.widget<PersonalRecordBadge>(weight).beaten, isFalse);
    expect(tester.widget<PersonalRecordBadge>(e1rm).beaten, isFalse);
    expect(_badgeDecoration(tester, weight), isNull);
    expect(_textColor(tester, weight), MayosThemeExtension.light.onWarning);
    expect(find.text('PR kg'), findsOneWidget);
    expect(find.text('PR e1RM'), findsOneWidget);

    // 110 kg × 6 @RIR 2 takes both records over: the earlier badges stay on
    // their row, struck through and muted, while the new best is solid.
    await _typeCell(tester, 0, 1, 'kg', '110');
    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));

    expect(
      tester
          .widget<PersonalRecordBadge>(_badge(0, 1, PrRecordKind.weight))
          .beaten,
      isFalse,
    );
    expect(tester.widget<PersonalRecordBadge>(weight).beaten, isTrue);
    expect(_badgeDecoration(tester, weight), TextDecoration.lineThrough);
    expect(_textColor(tester, weight), MayosThemeExtension.light.textMuted);
    expect(_badgeDecoration(tester, e1rm), TextDecoration.lineThrough);
    // One solid and one struck badge of each kind are on screen.
    expect(find.text('PR kg'), findsNWidgets(2));
    expect(find.text('PR e1RM'), findsNWidgets(2));
  });

  testWidgets('unticking a record-earning set clears its badges (#124)',
      (WidgetTester tester) async {
    await _openLogger(tester);

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_badge(0, 0, PrRecordKind.weight), findsOneWidget);
    expect(_badge(0, 0, PrRecordKind.e1rm), findsOneWidget);

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_badge(0, 0, PrRecordKind.weight), findsNothing);
    expect(_badge(0, 0, PrRecordKind.e1rm), findsNothing);

    // Ticking again earns them back: the badges are recomputed from the rows.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_badge(0, 0, PrRecordKind.weight), findsOneWidget);
    expect(_badge(0, 0, PrRecordKind.e1rm), findsOneWidget);
  });

  testWidgets('the summary lists the current records and the stats (#124)',
      (WidgetTester tester) async {
    await _openLogger(tester);

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await _typeCell(tester, 0, 1, 'kg', '110');
    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    // bench set 3 and the incline exercise are unticked.
    expect(find.text("2 sets aren't ticked"), findsOneWidget);
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();

    expect(find.text('Workout summary'), findsOneWidget);
    expect(find.text('Personal records'), findsOneWidget);
    // Only the current bests celebrate: 105's badges were taken over by 110.
    expect(find.text('Bench Press · PR 110 kg'), findsOneWidget);
    expect(find.text('Bench Press · PR e1RM 139.3 kg'), findsOneWidget);
    expect(find.textContaining('PR 105 kg'), findsNothing);

    // Exercises done, ticked working sets, total volume (105×5 + 110×6).
    expect(find.widgetWithText(MayosStat, '1'), findsOneWidget);
    expect(find.widgetWithText(MayosStat, '2'), findsOneWidget);
    expect(find.widgetWithText(MayosStat, '1185'), findsOneWidget);
    expect(find.text('Exercises done'), findsOneWidget);
    expect(find.text('Ticked working sets'), findsOneWidget);
    expect(find.text('Total volume'), findsOneWidget);

    // Back returns to the Active workout with its badges still there.
    await tester.tap(find.byKey(const ValueKey<String>('logger.save.back')));
    await tester.pumpAndSettle();
    expect(find.text('Workout summary'), findsNothing);
    expect(_badge(0, 0, PrRecordKind.weight), findsOneWidget);
  });

  testWidgets(
      'the online summary freezes projected Weekly streak and Checkpoint',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..trainingStatusBody = <String, dynamic>{
        'weekly_streak': 2,
        'week_start': '2026-09-26',
        'week_done': 1,
        'week_target': 2,
        'mayos_workouts': 8,
        'next_checkpoint': 10,
        'workouts_to_next': 2,
      };
    await _openLogger(
      tester,
      fakeApi: fake,
      clock: () => DateTime(2026, 9, 30, 12),
    );
    expect(fake.trainingStatusRequests, greaterThan(0));

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await _finishAndOpenSummary(tester);

    expect(find.text('Weekly streak: 3 weeks'), findsOneWidget);
    expect(find.text('This week: 2 of 2 done'), findsOneWidget);
    expect(find.text('1 workout to your 10th'), findsOneWidget);

    final BuildContext context =
        tester.element(find.byType(WorkoutLoggerScreen));
    final controller = ProviderScope.containerOf(context)
        .read(trainingStatusProvider.notifier);
    await controller.acceptCommit(_account, <String, dynamic>{
      'training_status': <String, dynamic>{
        'weekly_streak': 99,
        'week_start': '2026-10-03',
        'week_done': 0,
        'week_target': 4,
        'mayos_workouts': 9,
        'next_checkpoint': 10,
        'workouts_to_next': 1,
      },
    });
    await tester.pump();
    expect(find.text('Weekly streak: 3 weeks'), findsOneWidget);
    expect(find.text('This week: 2 of 2 done'), findsOneWidget);
    expect(find.text('1 workout to your 10th'), findsOneWidget);
  });

  testWidgets(
      'an offline summary projects pending drafts from its cached status',
      (WidgetTester tester) async {
    final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
    await cache.writeTrainingStatus(
      _account,
      const TrainingStatus(
        weeklyStreak: 2,
        weekStart: '2026-09-26',
        weekDone: 1,
        weekTarget: 3,
        mayosWorkouts: 7,
        nextCheckpoint: 10,
        workoutsToNext: 3,
      ),
    );
    final InMemoryDraftStore drafts = InMemoryDraftStore();
    await drafts.write(_account, <WorkoutDraft>[
      _summaryDraft('pending-this-week', '2026-09-29'),
      _summaryDraft('pending-last-week', '2026-09-20'),
    ]);
    final FakeMayosApi fake = _signedInFake()
      ..trainingStatusFails = true
      ..commitFails = true;
    await _openLogger(
      tester,
      fakeApi: fake,
      drafts: drafts,
      workoutCache: cache,
      clock: () => DateTime(2026, 9, 30, 12),
    );

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await _finishAndOpenSummary(tester);

    expect(find.text('Weekly streak: 3 weeks'), findsOneWidget);
    expect(find.text('This week: 3 of 3 done'), findsOneWidget);
    expect(find.text('Your 10th workout!'), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('logger.summary.checkpoint')),
        findsOneWidget);
    expect(
        find.text('Your review will appear on your dashboard'), findsOneWidget);
  });

  testWidgets('a committed Checkpoint shows its review and computed ratings',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..trainingStatusBody = <String, dynamic>{
        'weekly_streak': 0,
        'week_start': '2026-09-26',
        'week_done': 0,
        'week_target': 3,
        'mayos_workouts': 9,
        'next_checkpoint': 10,
        'workouts_to_next': 1,
      }
      ..programVersion = 3
      ..checkpointOnCommit = <String, dynamic>{'number': 10, 'reached': true}
      ..checkpointReviewRows = <Map<String, dynamic>>[
        <String, dynamic>{
          'checkpoint': 10,
          'period_start': '2026-09-01',
          'period_end': '2026-09-30',
          'rating': <Map<String, dynamic>>[
            <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
          ],
          'opened': false,
        },
      ]
      ..checkpointReviewDetails[10] = <String, dynamic>{
        'checkpoint': 10,
        'period_start': '2026-09-01',
        'period_end': '2026-09-30',
        'facts': <String, dynamic>{'workouts_in_period': 10},
        'rating': <Map<String, dynamic>>[
          <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
        ],
        'text':
            'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
        'text_is_template': true,
      };
    await _openLogger(
      tester,
      fakeApi: fake,
      webDirectCommit: true,
      clock: () => DateTime(2026, 9, 30, 12),
    );

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await _finishAndOpenSummary(tester);
    expect(
        find.text('Your review will appear on your dashboard'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey<String>('logger.save')));
    await _pumpUntilFound(tester, find.text('Consistency: Strong'));

    expect(find.textContaining('Checkpoint 10:'), findsOneWidget);
    expect(find.text('Consistency: Strong'), findsOneWidget);
  });

  testWidgets(
      'a stale cached week hides streak lines but keeps Checkpoint progress',
      (WidgetTester tester) async {
    final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
    await cache.writeTrainingStatus(
      _account,
      const TrainingStatus(
        weeklyStreak: 4,
        weekStart: '2026-09-19',
        weekDone: 3,
        weekTarget: 3,
        mayosWorkouts: 9,
        nextCheckpoint: 10,
        workoutsToNext: 1,
      ),
    );
    final FakeMayosApi fake = _signedInFake()..trainingStatusFails = true;
    await _openLogger(
      tester,
      fakeApi: fake,
      workoutCache: cache,
      clock: () => DateTime(2026, 9, 30, 12),
    );

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await _finishAndOpenSummary(tester);

    expect(find.textContaining('Weekly streak:'), findsNothing);
    expect(find.textContaining('This week:'), findsNothing);
    expect(find.text('Your 10th workout!'), findsOneWidget);
    expect(
        find.text('Your review will appear on your dashboard'), findsOneWidget);
  });

  testWidgets('records and workout summary fit phone and desktop columns', (
    WidgetTester tester,
  ) async {
    for (final Size size in const <Size>[
      Size(390, 664),
      Size(1280, 800),
    ]) {
      await _openLogger(tester);
      tester.view.physicalSize = size;
      await tester.pump();
      await _typeCell(tester, 0, 0, 'kg', '105');
      await tester.ensureVisible(_tick(0, 0));
      await tester.pumpAndSettle();
      await tester.tap(_tick(0, 0));
      await tester.pumpAndSettle();

      expect(_badge(0, 0, PrRecordKind.weight), findsOneWidget);
      expect(_badge(0, 0, PrRecordKind.e1rm), findsOneWidget);
      final Rect? playerColumn = size.width >= 1024
          ? tester.getRect(find.byKey(MayosPlayerColumn.contentKey))
          : null;
      if (playerColumn != null) {
        expect(playerColumn.width, MayosLayout.playerColumnMaxWidth);
        expect(playerColumn.center.dx, size.width / 2);
        _expectWithinColumn(
          tester.getRect(_badge(0, 0, PrRecordKind.weight)),
          playerColumn,
        );
        _expectWithinColumn(
          tester.getRect(_badge(0, 0, PrRecordKind.e1rm)),
          playerColumn,
        );
      }
      await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Discard unticked sets and finish'));
      await tester.pumpAndSettle();
      expect(find.text('Workout summary'), findsOneWidget);
      expect(find.text('Bench Press · PR 105 kg'), findsOneWidget);
      expect(find.text('Bench Press · PR e1RM 126 kg'), findsOneWidget);
      if (playerColumn != null) {
        for (final Finder content in <Finder>[
          find.text('Workout summary'),
          find.text('Personal records'),
          find.text('Bench Press · PR 105 kg'),
          find.text('Bench Press · PR e1RM 126 kg'),
        ]) {
          _expectWithinColumn(tester.getRect(content), playerColumn);
        }
      }
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('Arabic workout summary keeps server names and Western digits',
      (WidgetTester tester) async {
    await _openLogger(
      tester,
      languageCode: 'ar',
      clock: () => DateTime(2026, 9, 28, 8, 20),
    );

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.ensureVisible(_tick(0, 0));
    for (int i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    await tester.tap(_tick(0, 0));
    await _pumpUntilFound(tester, _badge(0, 0, PrRecordKind.weight));
    await _pumpUntilFound(tester, _badge(0, 0, PrRecordKind.e1rm));

    final Finder finish = find.widgetWithText(FilledButton, 'إنهاء الحصة');
    await tester.ensureVisible(finish);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(finish);
    // Let the unticked-sets sheet finish opening before tapping its action.
    await tester.pump(const Duration(milliseconds: 500));
    final Finder discardUnticked =
        find.widgetWithText(FilledButton, 'حذف غير المحدد وإنهاء الحصة');
    expect(discardUnticked, findsOneWidget);
    await tester.ensureVisible(discardUnticked);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(discardUnticked, warnIfMissed: true);
    await tester.pump(const Duration(milliseconds: 100));
    await _pumpUntilFound(tester, find.text('ملخص الحصة'));

    const WorkoutCopy copy = WorkoutCopy('ar');
    final Finder recordsHeading = find.text(copy.personalRecords);
    await _pumpUntilFound(tester, recordsHeading);
    expect(recordsHeading, findsOneWidget);
    await tester.ensureVisible(recordsHeading);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('التمارين المكتملة'), findsOneWidget);
    expect(find.text('مجموعات التدريب المحددة'), findsOneWidget);
    expect(find.text('إجمالي الوزن المرفوع'), findsOneWidget);
    expect(find.text('المدة'), findsOneWidget);
    expect(
      find.text(
        '\u2066Bench Press\u2069 · رقم قياسي \u2066105 kg\u2069',
      ),
      findsOneWidget,
    );
    final MayosSettingsTile dateTile =
        tester.widget<MayosSettingsTile>(find.byType(MayosSettingsTile).first);
    expect(dateTile.subtitle, matches(RegExp(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')));
    expect(dateTile.subtitleTextDirection, TextDirection.ltr);
    expect(
      Directionality.of(tester.element(find.text('ملخص الحصة'))),
      TextDirection.rtl,
    );
    final String renderedText = find
        .byType(Text)
        .evaluate()
        .map((Element element) => (element.widget as Text).data ?? '')
        .join('\n');
    expect(renderedText, isNot(matches(RegExp(r'[٠-٩۰-۹]'))));
    expect(tester.takeException(), isNull);
  });

  testWidgets('the summary omits the celebration when nothing earned a record',
      (WidgetTester tester) async {
    await _openLogger(tester);

    // A plain tick from the previous values is exactly bench's baseline
    // (100 kg × 5 @RIR 1): a tie is not a record, so no badge ever shows.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_badge(0, 0, PrRecordKind.weight), findsNothing);
    expect(_badge(0, 0, PrRecordKind.e1rm), findsNothing);

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();

    expect(find.text('Workout summary'), findsOneWidget);
    expect(find.text('Personal records'), findsNothing);
    expect(find.textContaining('· PR '), findsNothing);
    // The stats are still there: one exercise done, one working set, 500 kg,
    // and the duration the summary snapshot holds (#159).
    expect(find.byType(MayosStat), findsNWidgets(4));
    expect(find.text('Exercises done'), findsOneWidget);
    expect(find.text('Ticked working sets'), findsOneWidget);
    expect(find.widgetWithText(MayosStat, '500'), findsOneWidget);
  });

  testWidgets(
      'a newly earned record vibrates heavily once, and an untick '
      'never vibrates', (WidgetTester tester) async {
    final List<MethodCall> calls = _recordPlatformCalls(tester);
    await _openLogger(tester);

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 1);
    expect(_badge(0, 0, PrRecordKind.weight), findsOneWidget);

    // Unticking only recalculates the badges away.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 1);
    expect(_badge(0, 0, PrRecordKind.weight), findsNothing);

    // Tick it again: a record is earned anew, so it vibrates again.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 2);
    expect(_badge(0, 0, PrRecordKind.weight), findsOneWidget);
  });

  testWidgets('a cell edit vibrates when it settles, never per keystroke',
      (WidgetTester tester) async {
    final List<MethodCall> calls = _recordPlatformCalls(tester);
    await _openLogger(tester);

    // Ticking with the previous values only ties bench's baseline: 100 × 5
    // @1 beats nothing, so the tick itself is silent.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 0);

    // Edit the reps cell of the ticked set: each keystroke takes the e1RM
    // past the baseline, but nothing settles until the player leaves.
    await tester.tap(_cell(0, 0, 'reps'));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.5')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 0);

    // Next commits the edit: exactly one heavy vibration.
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 1);

    // Leaving the next cell, which earned nothing new, stays silent.
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 1);
  });

  testWidgets('turning a ticked warm-up into a working set vibrates (#124)',
      (WidgetTester tester) async {
    final List<MethodCall> calls = _recordPlatformCalls(tester);
    await _openLogger(tester);

    // 105 kg × 5 would beat both aggregates — but the row is a warm-up.
    await _typeCell(tester, 0, 0, 'kg', '105');
    await _typeCell(tester, 0, 0, 'reps', '5');
    await tester.tap(find.byKey(const ValueKey<String>('logger.setlabel.0.0')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('W'), findsOneWidget);

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(_heavyImpacts(calls), 0);
    expect(_badge(0, 0, PrRecordKind.weight), findsNothing);

    // The same ticked row becomes a working set: the record appears now.
    await tester.tap(find.byKey(const ValueKey<String>('logger.setlabel.0.0')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('W'), findsNothing);
    expect(_badge(0, 0, PrRecordKind.weight), findsOneWidget);
    expect(_heavyImpacts(calls), 1);
  });

  testWidgets('the summary snapshot never changes after the rows change (#124)',
      (WidgetTester tester) async {
    await _openLogger(tester);

    await _typeCell(tester, 0, 0, 'kg', '105');
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await _typeCell(tester, 0, 1, 'kg', '110');
    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();

    expect(find.text('Bench Press · PR 110 kg'), findsOneWidget);
    expect(find.widgetWithText(MayosStat, '1185'), findsOneWidget);

    // Rows change under the open summary: a heavier record and more volume
    // land in the Active workout (and reach the store, like any sync would).
    final BuildContext context =
        tester.element(find.byType(WorkoutLoggerScreen));
    final ActiveWorkoutController controller =
        ProviderScope.containerOf(context)
            .read(activeWorkoutControllerProvider.notifier);
    await controller.updateCell(0, 2, weightKg: 200, reps: 5);
    await controller.setTicked(0, 2, true);
    await tester.pumpAndSettle();

    // The summary is still the snapshot taken at Finish.
    expect(find.text('Bench Press · PR 110 kg'), findsOneWidget);
    expect(find.widgetWithText(MayosStat, '1185'), findsOneWidget);
    expect(find.textContaining('PR 200 kg'), findsNothing);
    expect(find.widgetWithText(MayosStat, '2185'), findsNothing);
  });

  testWidgets(
      'the top bar shows Workout time from the start, ticking every '
      'second (#159)', (WidgetTester tester) async {
    DateTime now = DateTime.parse('2026-09-28T08:00:42.000Z');
    await _openLogger(
      tester,
      startedAt: '2026-09-28T08:00:00.000Z',
      clock: () => now,
    );

    // `Log workout · mm:ss`, derived from the workout's own start (#159).
    final Finder label = find.text('Log workout · 00:42');
    expect(label, findsOneWidget);
    // Sans: the serif display role belongs to the day heading alone (#157).
    expect(
        tester.widget<Text>(label).style!.fontFamily, MayosTypography.forLanguage('en').interfaceFamily);

    // The bar redraws once a second off the clock — derived, never counted,
    // so nothing pauses and nothing has to be stored.
    now = DateTime.parse('2026-09-28T08:01:07.000Z');
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Log workout · 01:07'), findsOneWidget);
  });

  testWidgets('Arabic logger header isolates its workout time after the title',
      (WidgetTester tester) async {
    await _openLogger(
      tester,
      languageCode: 'ar',
      startedAt: '2026-09-28T08:00:00.000Z',
      clock: () => DateTime.parse('2026-09-28T08:00:42.000Z'),
    );

    expect(
      find.text('تسجيل حصة تدريبية · \u206600:42\u2069'),
      findsOneWidget,
    );
    expect(
      Directionality.of(tester.element(find.byType(LoggerTopBar))),
      TextDirection.rtl,
    );
  });

  testWidgets('Workout time stays correct across a simulated restart (#159)',
      (WidgetTester tester) async {
    _usePhoneView(tester);
    DateTime now = DateTime.parse('2026-09-28T08:01:30.000Z');
    final FakeMayosApi fake = _signedInFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    // Seeding runs outside the test's fake-async zone, like every open.
    final InMemoryActiveWorkoutStore store = (await tester.runAsync(
      () => _seedThroughController(
        fake: fake,
        startedAt: '2026-09-28T08:00:00.000Z',
      ),
    ))!;
    await _pumpApp(
      tester,
      overrides: _appOverrides(
        fake: fake,
        tokens: tokens,
        store: store,
        clock: () => now,
      ),
    );
    await _resumeFromPrompt(tester);
    expect(find.text('Log workout · 01:30'), findsOneWidget);

    // Close the app completely, then open it again on the same storage an
    // hour later: the time is the workout's, not the screen's, so nothing
    // resets on a restart (#159).
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    now = DateTime.parse('2026-09-28T09:00:00.000Z');
    await _pumpApp(
      tester,
      overrides: _appOverrides(
        fake: fake,
        tokens: tokens,
        store: store,
        clock: () => now,
      ),
    );
    await _resumeFromPrompt(tester);
    expect(find.text('Log workout · 1:00:00'), findsOneWidget);
  });

  testWidgets(
      'the ⋮ menu discards the workout behind its own confirmation '
      '(#159)', (WidgetTester tester) async {
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final InMemoryActiveWorkoutStore store =
        await _openLogger(tester, analytics: analytics);

    await tester.tap(find.byKey(LoggerTopBar.menuKey));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(LoggerTopBar.discardKey));
    await tester.pumpAndSettle();

    // Its own dialog, not the Resume prompt's: the player is told what will
    // be lost before anything is thrown away (#159).
    expect(find.text('Discard this workout?'), findsOneWidget);
    expect(
      find.text("The sets you've logged in this workout will be lost."),
      findsOneWidget,
    );
    expect(find.text('Unfinished workout'), findsNothing);

    // Keep logging dismisses it: the workout is untouched.
    await tester.tap(find.text('Keep logging'));
    await tester.pumpAndSettle();
    expect(find.text('Discard this workout?'), findsNothing);
    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);
    expect(await store.read(_account), isNotNull);
    expect(
      analytics.events.where((Map<String, Object> event) =>
          event['event'] == 'workout_draft_discarded'),
      isEmpty,
    );

    // This time Discard: the same effect Discard has in the Resume prompt —
    // the Active workout is gone and the player leaves the logger.
    await tester.tap(find.byKey(LoggerTopBar.menuKey));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(LoggerTopBar.discardKey));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsNothing);
    expect(await store.read(_account), isNull);
    expect(find.text('Discard this workout?'), findsNothing);
    expect(
      analytics.events.where((Map<String, Object> event) =>
          event['event'] == 'workout_draft_discarded'),
      hasLength(1),
    );
  });

  testWidgets(
      'the day heading is the one serif line and the progress line '
      'counts exercises and sets (#159)', (WidgetTester tester) async {
    await _openLogger(tester);

    // The training day's name carries the screen's only serif heading.
    expect(
      tester.widget<Text>(find.text('Upper A')).style!.fontFamily,
      MayosTypography.displayFamily,
    );

    final Finder progress =
        find.byKey(const ValueKey<String>('logger.progress'));
    final Text line = tester.widget<Text>(progress);
    expect(line.style!.fontFamily, MayosTypography.forLanguage('en').interfaceFamily);
    // Two exercises, four working rows, nothing ticked yet.
    expect(line.data, '0/2 exercises · 0/4 sets');

    // Ticking moves the set count…
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.widget<Text>(progress).data, '0/2 exercises · 1/4 sets');
    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.widget<Text>(progress).data, '0/2 exercises · 2/4 sets');

    // …and a warm-up leaves the counts while completing bench, because the
    // line uses the Current set's working-set rule (#158/#159): bench's two
    // working rows are now both ticked, and its third row is a warm-up.
    await tester.tap(find.byKey(const ValueKey<String>('logger.setlabel.0.2')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.widget<Text>(progress).data, '1/2 exercises · 2/3 sets');

    // The last exercise finishes the line off.
    await tester.tap(_tick(1, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.widget<Text>(progress).data, '2/2 exercises · 3/3 sets');
  });

  testWidgets(
      'the summary shows the workout\'s total duration, frozen at '
      'Finish, with no overflow at 360dp (#159)', (WidgetTester tester) async {
    DateTime now = DateTime.parse('2026-09-28T08:32:10.000Z');
    await _openLogger(
      tester,
      startedAt: '2026-09-28T08:00:00.000Z',
      clock: () => now,
    );

    // The narrow phone, light theme: the four stats have to fit (#159).
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.takeException(), isNull);

    final Finder tick = _tick(0, 0);
    await tester.ensureVisible(tick);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(tick);
    await tester.pump(const Duration(milliseconds: 100));

    final Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
    await tester.ensureVisible(finish);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(finish);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();

    final Finder duration =
        find.byKey(const ValueKey<String>('logger.summary.duration'));
    expect(find.descendant(of: duration, matching: find.text('32:10')),
        findsOneWidget);
    expect(find.widgetWithText(MayosStat, 'Duration'), findsOneWidget);
    expect(tester.takeException(), isNull);

    // The top bar freezes on the snapshot while the summary is open: the
    // clock running on must not tick beside the frozen "Duration" stat
    // (#124/#159).
    now = DateTime.parse('2026-09-28T09:00:00.000Z');
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Log workout · 32:10'), findsOneWidget);
    expect(find.text('Log workout · 1:00:00'), findsNothing);
    expect(find.descendant(of: duration, matching: find.text('32:10')),
        findsOneWidget);
    expect(find.descendant(of: duration, matching: find.text('1:27:50')),
        findsNothing);
    expect(tester.takeException(), isNull);

    // Back to the logger: the live tick resumes from the same clock.
    final Finder back = find.byKey(const ValueKey<String>('logger.save.back'));
    await tester.ensureVisible(back);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(back);
    await tester.pumpAndSettle();

    expect(find.text('Workout summary'), findsNothing);
    expect(find.text('Log workout · 1:00:00'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'the bottom bar keeps sets progress and Finish in reach while '
      'the list scrolls (#160)', (WidgetTester tester) async {
    await _openLogger(tester);
    // The narrow phone, where the list really does scroll (#160).
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.takeException(), isNull);

    final Finder bar = find.byKey(const ValueKey<String>('logger.bottomBar'));
    final Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
    final Finder list = find.byKey(const ValueKey<String>('logger.list'));

    // Progress and Finish are there from the first frame, with the same
    // counts the header's line shows (#159/#160)…
    expect(bar, findsOneWidget);
    expect(find.text('0/4 sets'), findsOneWidget);
    expect(finish, findsOneWidget);
    expect(
      tester
          .widget<MayosProgressIndicator>(
            find.descendant(
                of: bar, matching: find.byType(MayosProgressIndicator)),
          )
          .value,
      moreOrLessEquals(0),
    );
    // …and the bar is fixed at the bottom of the screen, above the system
    // navigation (the frame's SafeArea).
    expect(
      tester.getBottomRight(bar).dy,
      moreOrLessEquals(
          tester.view.physicalSize.height / tester.view.devicePixelRatio,
          epsilon: 0.5),
    );

    // A tick moves the counts and the progress bar, wherever the list is.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('1/4 sets'), findsOneWidget);
    expect(
      tester
          .widget<MayosProgressIndicator>(
            find.descendant(
                of: bar, matching: find.byType(MayosProgressIndicator)),
          )
          .value,
      moreOrLessEquals(0.25),
    );

    // Scroll the list to its end: the bar does not move, hide or shrink.
    final Offset barTop = tester.getTopLeft(bar);
    for (int i = 0; i < 4; i++) {
      await tester.drag(list, const Offset(0, -400));
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(tester.getTopLeft(bar), barTop);
    expect(find.text('1/4 sets'), findsOneWidget);
    expect(finish, findsOneWidget);
    expect(tester.takeException(), isNull);

    // Finish runs its usual flow straight from the bar — no scrolling first:
    // the unticked-sets sheet, then back from Keep logging.
    await tester.tap(finish);
    await tester.pumpAndSettle();
    expect(find.text("3 sets aren't ticked"), findsOneWidget);
    await tester.tap(find.text('Keep logging'));
    await tester.pumpAndSettle();
    expect(finish, findsOneWidget);
    expect(bar, findsOneWidget);
  });

  testWidgets(
      'the bottom bar steps aside for the keypad and the last card '
      'scrolls clear of it (#160)', (WidgetTester tester) async {
    await _openLogger(tester);
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.takeException(), isNull);

    final Finder bar = find.byKey(const ValueKey<String>('logger.bottomBar'));
    expect(bar, findsOneWidget);

    // The keypad takes the bottom bar's place while a cell is edited, so the
    // keypad never covers it (#160)…
    await tester.tap(_cell(0, 0, 'kg'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(bar, findsNothing);
    expect(
        find.byKey(const ValueKey<String>('logger.key.hide')), findsOneWidget);
    // …and hiding it brings the bar straight back.
    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(bar, findsOneWidget);
    expect(tester.takeException(), isNull);

    // To the end of the list: the last card and Add exercise both land above
    // the bar, with the list's own bottom padding under them (#160).
    final Finder list = find.byKey(const ValueKey<String>('logger.list'));
    for (int i = 0; i < 4; i++) {
      await tester.drag(list, const Offset(0, -400));
      await tester.pump(const Duration(milliseconds: 50));
    }
    final Finder add = find.byKey(const ValueKey<String>('logger.addExercise'));
    expect(add, findsOneWidget);
    // Finish was the list's last action; Add exercise now ends it (#160).
    expect(find.widgetWithText(FilledButton, 'Finish workout'), findsOneWidget);

    // _row(1, 0) is checked because it is the LAST row of the LAST card —
    // incline's only row — not merely a row that happens to be first: the
    // row keys in tree order end there, so nothing follows it in the list.
    final Finder allRows = find.byWidgetPredicate(
      (Widget widget) =>
          widget.key is ValueKey<String> &&
          (widget.key as ValueKey<String>).value.startsWith('logger.row.'),
    );
    expect(
      allRows
          .evaluate()
          .map((Element row) => (row.widget.key! as ValueKey<String>).value)
          .last,
      'logger.row.1.0',
    );

    // That last row must be scrolled INTO the visible list and clear of the
    // bar: a row scrolled off the top of the viewport would sit above
    // barTop for free, so being on screen is the part that proves the end of
    // the list is reachable (#160).
    final Finder lastRow = _row(1, 0);
    final Rect listRect = tester.getRect(list);
    final Rect rowRect = tester.getRect(lastRow);
    final double barTop = tester.getTopLeft(bar).dy;
    expect(rowRect.top, greaterThanOrEqualTo(listRect.top));
    expect(rowRect.bottom, lessThanOrEqualTo(listRect.bottom));
    expect(rowRect.bottom, lessThanOrEqualTo(barTop));
    expect(tester.getBottomRight(add).dy, lessThanOrEqualTo(barTop));
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'the bottom bar takes the system-nav inset inside its surface '
      'and keeps its content above it (#160)', (WidgetTester tester) async {
    // A gesture-nav phone: the bottom 48dp of the screen belongs to the
    // system navigation.
    tester.view.padding = const FakeViewPadding(bottom: 48);
    tester.view.viewPadding = const FakeViewPadding(bottom: 48);
    addTearDown(tester.view.resetPadding);
    addTearDown(tester.view.resetViewPadding);
    await _openLogger(tester);

    final Finder bar = find.byKey(const ValueKey<String>('logger.bottomBar'));
    final Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
    final Finder counts =
        find.byKey(const ValueKey<String>('logger.bottomBar.progress'));
    final double screenBottom =
        tester.view.physicalSize.height / tester.view.devicePixelRatio;

    // The bar's surface runs to the physical screen bottom — the inset is
    // inside it, so no page background shows as a seam under the bar…
    expect(bar, findsOneWidget);
    expect(
      tester.getBottomRight(bar).dy,
      moreOrLessEquals(screenBottom, epsilon: 0.5),
    );
    // …while every part of it the player touches or reads sits above the
    // inset.
    expect(
      tester.getBottomRight(finish).dy,
      lessThanOrEqualTo(screenBottom - 48),
    );
    expect(
      tester.getBottomRight(counts).dy,
      lessThanOrEqualTo(screenBottom - 48),
    );
    expect(tester.getTopLeft(bar).dy, lessThan(screenBottom - 48));
    expect(tester.takeException(), isNull);

    // It is still the bar: Finish runs from there, above the system nav.
    await tester.tap(finish);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Log at least one set'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a tick clears the Finish nudge and no other message (#160)',
      (WidgetTester tester) async {
    // A workout started outside the entry window: its notice rides in the
    // same slot above the bar and must survive the tick.
    final DateTime tenDaysAgo =
        DateTime.now().subtract(const Duration(days: 10));
    await _openLogger(tester, startedAt: tenDaysAgo.toUtc().toIso8601String());

    final Finder notice =
        find.textContaining('outside the allowed entry window');
    final Finder nudge = find.text('Log at least one set');

    // Finish with nothing ticked raises its own nudge beside the notice…
    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(nudge, findsOneWidget);
    expect(notice, findsOneWidget);

    // …and the next tick takes the nudge away — and only that message.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    expect(nudge, findsNothing);
    expect(notice, findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
