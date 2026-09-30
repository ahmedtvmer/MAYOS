import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/browser_key_value_store.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/web_active_workout_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';
import 'support/in_memory_browser_key_value_store.dart';

const String _account = 'account-alice';
const String _sessionId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

ActiveWorkout _workout({
  String accountId = _account,
  bool commitAttempted = false,
}) =>
    ActiveWorkout(
      id: 'aw-web-test',
      accountId: accountId,
      clientSessionId: _sessionId,
      commitAttempted: commitAttempted,
      startedAt: '2026-09-28T08:00:00.000Z',
      dayOrder: 1,
      dayName: 'Upper 1',
      programVersion: 3,
      exercises: <ActiveWorkoutExercise>[
        ActiveWorkoutExercise(
          exercise: <String, dynamic>{
            'exercise_id': 'bench_press',
            'exercise_name': 'Bench Press',
            'target_sets': 1,
            'target_reps_min': 5,
            'target_reps_max': 8,
            'target_rpe': 8.0,
            'warmup_sets': 0,
            'rest_seconds': 180,
            'notes': null,
          },
          sets: <ActiveWorkoutSet>[
            ActiveWorkoutSet(
              weightKg: 80,
              reps: 5,
              ticked: true,
            ),
          ],
        ),
      ],
      baselines: <String, BaselineExercise>{},
    );

FakeMayosApi _fake() => FakeMayosApi()
  ..issuedToken = 'token-alice'
  ..currentUsername = 'alice'
  ..tokenValid = true
  ..profileExists = true
  ..recoveryEmail = 'alice@example.com'
  ..programVersion = 3;

Future<void> _pumpUntil(
  WidgetTester tester,
  Finder finder, {
  int attempts = 50,
}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) return;
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<_WebHarness> _pumpWebApp(
  WidgetTester tester, {
  required FakeMayosApi fake,
  required InMemoryBrowserKeyValueStore browser,
  required WebActiveWorkoutStore store,
  ActiveWorkout? initialWorkout,
  bool unexpectedCommitError = false,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  if (initialWorkout != null) {
    await store.write(initialWorkout.accountId, initialWorkout);
  }
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tokens.saveAccountId(_account);
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider
            .overrideWithValue(InMemoryThemeModeStore(ThemeMode.light)),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        workoutCacheStoreProvider
            .overrideWithValue(InMemoryWorkoutCacheStore()),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        browserKeyValueStoreProvider.overrideWithValue(browser),
        activeWorkoutStoreProvider.overrideWithValue(store),
        offlineWorkoutDraftsEnabledProvider.overrideWithValue(false),
        deviceTimezoneProvider.overrideWithValue(Future<String>.value('UTC')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value('UTC')),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = unexpectedCommitError
              ? _UnexpectedCommitApi(
                  tokens: ref.watch(tokenStoreProvider),
                  baseUrl: 'http://test.local',
                  adapter: fake.adapter,
                )
              : ApiClient(
                  tokens: ref.watch(tokenStoreProvider),
                  baseUrl: 'http://test.local',
                  adapter: fake.adapter,
                );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          client.onAccountDeleted =
              ref.watch(accountDeletedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntil(tester, find.text('Home'));
  await tester.pumpAndSettle();
  final ProviderContainer container =
      ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
  await container
      .read(activeWorkoutControllerProvider.notifier)
      .syncAccount(_account);
  await tester.pumpAndSettle();
  return _WebHarness(fake, browser, store, tokens);
}

Future<void> _resumeLogger(WidgetTester tester) async {
  await _pumpUntil(tester, find.text('Unfinished workout'));
  expect(find.text('Unfinished workout'), findsOneWidget);
  await tester.tap(find.text('Resume'));
  await _pumpUntil(tester, find.byType(WorkoutLoggerScreen));
  await tester.pumpAndSettle();
}

Future<void> _finishToSummary(WidgetTester tester) async {
  await tester.tap(find.text('Finish workout'));
  await tester.pumpAndSettle();
  expect(find.text('Workout summary'), findsOneWidget);
}

class _WebHarness {
  const _WebHarness(this.fake, this.browser, this.store, this.tokens);

  final FakeMayosApi fake;
  final InMemoryBrowserKeyValueStore browser;
  final WebActiveWorkoutStore store;
  final InMemoryTokenStore tokens;
}

class _UnexpectedCommitApi extends ApiClient {
  _UnexpectedCommitApi({
    required super.tokens,
    required super.baseUrl,
    required super.adapter,
  });

  @override
  Future<WorkoutCommitResult> commitWorkoutSession(
    Map<String, dynamic> body,
  ) async {
    throw StateError('unexpected commit error');
  }
}

class _DeniedBrowserStorage implements BrowserKeyValueStore {
  Never _deny() => throw UnsupportedError('Browser storage is unavailable.');

  @override
  String? getItem(String key) => _deny();

  @override
  void setItem(String key, String value) => _deny();

  @override
  void removeItem(String key) => _deny();
}

void main() {
  test('web store restores across instances and isolates account keys',
      () async {
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore first = WebActiveWorkoutStore(storage: browser);
    await first.write(
      _account,
      _workout().copyWith(
        warmupMovements: <ActiveWarmupMovement>[
          ActiveWarmupMovement(
            exerciseName: 'Cat-Cow',
            sets: const <ActiveWarmupSet>[
              ActiveWarmupSet(reps: 10, ticked: true),
              ActiveWarmupSet(reps: 10),
            ],
          ),
        ],
        cardio: const WorkoutCardio(
          prescription: 'Steady bike after lifting',
          minutes: 25,
        ),
      ),
    );

    final WebActiveWorkoutStore afterReload =
        WebActiveWorkoutStore(storage: browser);
    final ActiveWorkout? restored = await afterReload.read(_account);
    expect(restored?.clientSessionId, _sessionId);
    expect(restored!.warmupMovements.single.sets.first.ticked, isTrue);
    expect(restored.warmupMovements.single.sets[1].ticked, isFalse);
    expect(restored.cardio!.prescription, 'Steady bike after lifting');
    expect(restored.cardio!.minutes, 25);
    expect(restored.cardio!.ticked, isFalse);
    expect(await afterReload.read('account-bob'), isNull);
  });

  testWidgets('web commit sends ticked Warm-up movement rows and Cardio',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    final ActiveWorkout workout = _workout().copyWith(
      warmupMovements: <ActiveWarmupMovement>[
        ActiveWarmupMovement(
          exerciseId: 'arm_circles',
          exerciseName: 'Arm Circles',
          sets: const <ActiveWarmupSet>[
            ActiveWarmupSet(reps: 10),
            ActiveWarmupSet(reps: 10),
          ],
        ),
      ],
      cardio: const WorkoutCardio(prescription: 'Bike intervals'),
    );
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: workout,
    );
    await _resumeLogger(tester);
    expect(find.text('Arm Circles'), findsOneWidget);

    await tester.tap(
        find.byKey(const ValueKey<String>('logger.warmup.0.0.tick')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey<String>('logger.cardio.minutes')),
      '30',
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey<String>('logger.cardio.tick')));
    await tester.pumpAndSettle();
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await _pumpUntil(tester, find.text('Workout saved to your training history.'));

    final Map<String, dynamic> sent = fake.adapter.requests
        .firstWhere((request) =>
            request.method == 'POST' && request.path == '/workouts/sessions')
        .body;
    expect(sent['warmup_movements'], <Map<String, dynamic>>[
      <String, dynamic>{
        'exercise_id': 'arm_circles',
        'exercise_name': 'Arm Circles',
        'sets': <Map<String, dynamic>>[
          <String, dynamic>{'weight_kg': null, 'reps': 10},
        ],
      },
    ]);
    expect(sent['cardio'], <String, dynamic>{
      'prescription': 'Bike intervals',
      'minutes': 30,
    });
  });

  test('storage denial falls back to in-memory logging for this tab', () async {
    final WebActiveWorkoutStore store =
        WebActiveWorkoutStore(storage: _DeniedBrowserStorage());
    await store.write(_account, _workout());
    expect((await store.read(_account))?.clientSessionId, _sessionId);
    await store.markWorkoutStartNoticeSeen(_account);
    expect(await store.hasSeenWorkoutStartNotice(_account), isTrue);
  });

  testWidgets('restored browser workout is offered after rebuilding the app',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore first = WebActiveWorkoutStore(storage: browser);
    final _WebHarness harness = await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: first,
      initialWorkout: _workout(),
    );
    await _pumpUntil(tester, find.text('Unfinished workout'));
    expect(find.text('Unfinished workout'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());

    final WebActiveWorkoutStore afterReload =
        WebActiveWorkoutStore(storage: harness.browser);
    await _pumpWebApp(
      tester,
      fake: harness.fake,
      browser: harness.browser,
      store: afterReload,
    );
    await _pumpUntil(tester, find.text('Unfinished workout'));
    expect(find.text('Upper 1'), findsOneWidget);
    await tester.tap(find.text('Resume'));
    await _pumpUntil(tester, find.byType(WorkoutLoggerScreen));
    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);
  });

  testWidgets('retry keeps the original id and commits after a 5xx',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..commitFails = true;
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await tester.pumpAndSettle();

    expect(find.text('MAYOS is busy. Your workout is kept in this browser.'),
        findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    expect((await store.read(_account))?.clientSessionId, _sessionId);
    final Map<String, dynamic> firstPost = fake.adapter.requests
        .firstWhere((request) =>
            request.method == 'POST' && request.path == '/workouts/sessions')
        .body;
    expect(firstPost['client_session_id'], _sessionId);

    fake.commitFails = false;
    await tester.tap(find.text('Retry'));
    await _pumpUntil(
        tester, find.text('Workout saved to your training history.'));
    final List<String> sentIds = fake.adapter.requests
        .where((request) =>
            request.method == 'POST' && request.path == '/workouts/sessions')
        .map((request) => request.body['client_session_id'] as String)
        .toList();
    expect(sentIds, <String>[_sessionId, _sessionId]);
    expect(
      fake.adapter.requests.where((request) =>
          request.method == 'GET' &&
          request.path == '/workouts/sessions/by-client-id/$_sessionId'),
      hasLength(1),
    );
    expect(await store.read(_account), isNull);
    expect(
        find.text('Workout saved to your training history.'), findsOneWidget);
    expect(find.text('Workout summary'), findsOneWidget);
  });

  testWidgets('Back after a successful web commit leaves the logger',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await _pumpUntil(
        tester, find.text('Workout saved to your training history.'));
    expect(await store.read(_account), isNull);

    await tester.tap(find.byTooltip('Back to workout'));
    await tester.pumpAndSettle();
    expect(find.byType(WorkoutLoggerScreen), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('retry reconciles a lost response without posting twice',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..commitResponseLost = true;
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await tester.pumpAndSettle();
    expect(find.text('Retry'), findsOneWidget);
    expect(fake.committedSessions, hasLength(1));

    await tester.tap(find.text('Retry'));
    await _pumpUntil(
        tester, find.text('Workout saved to your training history.'));
    expect(
      fake.adapter.requests.where((request) =>
          request.method == 'POST' && request.path == '/workouts/sessions'),
      hasLength(1),
    );
    expect(await store.read(_account), isNull);
    expect(
        find.text('Workout saved to your training history.'), findsOneWidget);
  });

  testWidgets('reload after a failed commit reconciles before another POST',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..commitResponseLost = true;
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    final _WebHarness harness = await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await tester.pumpAndSettle();
    expect((await store.read(_account))?.commitAttempted, isTrue);
    expect(fake.committedSessions, hasLength(1));

    await tester.pumpWidget(const SizedBox.shrink());
    final WebActiveWorkoutStore afterReload =
        WebActiveWorkoutStore(storage: harness.browser);
    await _pumpWebApp(
      tester,
      fake: harness.fake,
      browser: harness.browser,
      store: afterReload,
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Retry'));
    await _pumpUntil(
        tester, find.text('Workout saved to your training history.'));

    final List<FakeRequest> requests = fake.adapter.requests
        .where((request) =>
            request.path == '/workouts/sessions' ||
            request.path == '/workouts/sessions/by-client-id/$_sessionId')
        .toList();
    expect(requests.where((request) => request.method == 'POST'), hasLength(1));
    expect(requests.last.method, 'GET');
    expect(requests.last.path, '/workouts/sessions/by-client-id/$_sessionId');
    expect(await afterReload.read(_account), isNull);
  });

  testWidgets('network failure keeps the workout and exposes Retry',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()
      ..offlineRequests.add('POST /workouts/sessions');
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await _pumpUntil(tester, find.text('Retry'));

    expect(find.textContaining("Couldn't reach MAYOS"), findsOneWidget);
    expect((await store.read(_account))?.clientSessionId, _sessionId);
    fake.offlineRequests.clear();
    await tester.tap(find.text('Retry'));
    await _pumpUntil(
        tester, find.text('Workout saved to your training history.'));
    expect(
      fake.adapter.requests.where((request) =>
          request.method == 'POST' && request.path == '/workouts/sessions'),
      hasLength(2),
    );
  });

  testWidgets('401 keeps the workout and never offers Discard',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()
      ..commitRefusalStatusCode = 401
      ..commitRefusalMessage = 'Please sign in again.';
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await tester.pumpAndSettle();

    expect(await store.read(_account), isNotNull);
    expect(find.text('Discard workout'), findsNothing);
  });

  testWidgets('429 keeps the workout and offers Retry',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()
      ..commitRefusalStatusCode = 429
      ..commitRefusalMessage = 'Please slow down.';
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await tester.pumpAndSettle();

    expect(find.text('Retry'), findsOneWidget);
    expect(find.text('Discard workout'), findsNothing);
    expect(await store.read(_account), isNotNull);
    fake.commitRefusalStatusCode = null;
    await tester.tap(find.text('Retry'));
    await _pumpUntil(
        tester, find.text('Workout saved to your training history.'));
  });

  testWidgets('unexpected Save error keeps the workout and offers Retry',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
      unexpectedCommitError: true,
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await _pumpUntil(tester, find.text('Retry'));

    expect(
        find.text(
            "Couldn't reach MAYOS. Your workout is kept in this browser."),
        findsOneWidget);
    expect(find.text('Discard workout'), findsNothing);
    expect((await store.read(_account))?.commitAttempted, isTrue);
  });

  testWidgets('4xx shows the server detail and allows discarding',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()
      ..commitRefusalStatusCode = 422
      ..commitRefusalMessage = 'The workout cannot be recorded.';
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    await tester.pumpAndSettle();

    expect(find.text('The workout cannot be recorded.'), findsOneWidget);
    expect(find.text('Discard workout'), findsOneWidget);
    expect(find.text('Retry'), findsNothing);
    await tester.tap(find.text('Discard workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard').last);
    await tester.pumpAndSettle();
    expect(await store.read(_account), isNull);
  });

  testWidgets('first web start notice is remembered for the account',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
    );
    final Finder start = find.text('Log workout');
    await tester.ensureVisible(start);
    await tester.tap(start);
    await tester.pumpAndSettle();
    expect(find.text('Logging workouts on web'), findsOneWidget);
    expect(find.textContaining('need a connection to finish saving'),
        findsOneWidget);
    expect(find.textContaining('only in this browser'), findsOneWidget);

    await tester.tap(find.text('Continue logging'));
    await _pumpUntil(tester, find.byType(WorkoutLoggerScreen));
    expect(await store.hasSeenWorkoutStartNotice(_account), isTrue);
    expect(
      RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
          .hasMatch((await store.read(_account))!.clientSessionId!),
      isTrue,
    );

    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    await container
        .read(activeWorkoutControllerProvider.notifier)
        .discard(accountId: _account);
    await tester.pump();
    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();
    final Finder startAgain = find.text('Log workout');
    await tester.ensureVisible(startAgain);
    await tester.tap(startAgain);
    await _pumpUntil(tester, find.byType(WorkoutLoggerScreen));
    expect(find.text('Logging workouts on web'), findsNothing);
  });

  testWidgets('web logout warns and discards the unfinished workout',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntil(tester, find.text('Appearance'));
    await tester.tap(find.text('Log out'));
    await tester.pumpAndSettle();

    expect(find.text('Discard unfinished workout?'), findsOneWidget);
    expect(find.text('Discard and log out'), findsOneWidget);
    expect(find.textContaining('from this browser'), findsOneWidget);
    await tester.tap(find.text('Discard and log out'));
    await _pumpUntil(tester, find.text('Log in'));
    expect(await store.read(_account), isNull);
  });

  testWidgets('account_deleted response erases the browser workout',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()
      ..commitRefusalStatusCode = 401
      ..commitRefusalErrorCode = 'account_deleted';
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await store.markWorkoutStartNoticeSeen(_account);
    await _pumpWebApp(
      tester,
      fake: fake,
      browser: browser,
      store: store,
      initialWorkout: _workout(),
    );
    await _resumeLogger(tester);
    await _finishToSummary(tester);
    await tester.tap(find.text('Save workout'));
    for (int i = 0; i < 20; i++) {
      if (await store.read(_account) == null) break;
      await tester.pump(const Duration(milliseconds: 50));
    }

    expect(await store.read(_account), isNull);
    expect(await store.hasSeenWorkoutStartNotice(_account), isFalse);
    expect(find.text('Discard workout'), findsNothing);
  });

  test('account deletion erases browser Active workout and notice flag',
      () async {
    final FakeMayosApi fake = _fake()..passwords['alice'] = 'correct-horse';
    final InMemoryBrowserKeyValueStore browser = InMemoryBrowserKeyValueStore();
    final WebActiveWorkoutStore store = WebActiveWorkoutStore(storage: browser);
    await store.write(_account, _workout());
    await store.markWorkoutStartNoticeSeen(_account);
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    await tokens.saveAccountId(_account);
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        offlineWorkoutDraftsEnabledProvider.overrideWithValue(false),
        browserKeyValueStoreProvider.overrideWithValue(browser),
        activeWorkoutStoreProvider.overrideWithValue(store),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          client.onAccountDeleted =
              ref.watch(accountDeletedEventsProvider).signal;
          return client;
        }),
      ],
    );
    addTearDown(container.dispose);

    await container.read(authRepositoryProvider).deleteAccount('correct-horse');

    expect(await store.read(_account), isNull);
    expect(await store.hasSeenWorkoutStartNotice(_account), isFalse);
  });
}
