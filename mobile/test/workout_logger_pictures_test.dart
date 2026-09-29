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
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';
import 'package:mayos_mobile/src/features/player/workout/logger_card_widgets.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_media_http.dart';
import 'support/fake_mayos_api.dart';

/// #161: the catalog picture on every exercise card — loaded, missing and
/// failed pictures through a fake `GET /media` route, all three laid out in
/// the same fixed box so the card never shifts.

const String _account = 'account-alice';

/// Three exercises of identical shape, so their cards must measure the same
/// whatever their picture does: one picture the fake `/media` serves, one it
/// answers 404, and one the program payload carried no image path for. None
/// of the ids is in the fake program's day, so every card builds the same
/// prescription line from the fixture alone.
const ProgramDay _day = ProgramDay(
  dayName: 'Upper A',
  dayOrder: 2,
  exercises: <ProgramExercise>[
    ProgramExercise(
      exerciseId: 'incline_press',
      exerciseName: 'Incline Press',
      targetSets: 3,
      targetRepsMin: 5,
      targetRepsMax: 8,
      targetRpe: 8.5,
      restSeconds: 180,
      imagePath: 'images/incline.jpg',
    ),
    ProgramExercise(
      exerciseId: 'lat_pulldown',
      exerciseName: 'Lat Pulldown',
      targetSets: 3,
      targetRepsMin: 5,
      targetRepsMax: 8,
      targetRpe: 8.5,
      restSeconds: 180,
      imagePath: 'images/gone.jpg',
    ),
    ProgramExercise(
      exerciseId: 'cable_fly',
      exerciseName: 'Cable Fly',
      targetSets: 3,
      targetRepsMin: 5,
      targetRepsMax: 8,
      targetRpe: 8.5,
      restSeconds: 180,
    ),
  ],
);

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

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  // No baselines: every card hides its `Last:` line, so the three cards are
  // laid out from the same facts and only their pictures differ.
  fake.baselinesBody = <Map<String, dynamic>>[];
  return fake;
}

ApiClient _api(FakeMayosApi fake, TokenStore tokens) => ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );

/// Builds the stored Active workout through the real controller, so the
/// cards the test sees carry the payload `ProgramExercise.toJson` wrote —
/// image path included (#161).
Future<InMemoryActiveWorkoutStore> _seedThroughController({
  required FakeMayosApi fake,
}) async {
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
      apiClientProvider.overrideWith((Ref ref) => _api(fake, tokens)),
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

/// The phone canvas: 1080×2400 by default, 360×640 for the small-phone run.
void _usePhoneView(WidgetTester tester,
    {Size size = const Size(1080, 2400)}) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

List<Override> _appOverrides({
  required FakeMayosApi fake,
  required InMemoryTokenStore tokens,
  required InMemoryActiveWorkoutStore store,
  ThemeMode themeMode = ThemeMode.light,
}) =>
    <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
      themeModeStoreProvider
          .overrideWithValue(InMemoryThemeModeStore(themeMode)),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      workoutCacheStoreProvider
          .overrideWithValue(InMemoryWorkoutCacheStore()),
      chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
      baselineCacheStoreProvider
          .overrideWithValue(InMemoryBaselineCacheStore()),
      activeWorkoutStoreProvider.overrideWithValue(store),
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
    ];

Future<void> _pumpApp(WidgetTester tester,
    {required List<Override> overrides}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: overrides,
    child: const MayosApp(),
  ));
}

Future<void> _resumeFromPrompt(WidgetTester tester) async {
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.pumpAndSettle();
  expect(find.text('Unfinished workout'), findsOneWidget);
  await tester.tap(find.text('Resume'));
  await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
  await tester.pumpAndSettle();
}

/// The signed-in app with a stored Active workout, opened through the
/// app-open Resume prompt — the real entry into the card list (#161).
Future<void> _openLogger(
  WidgetTester tester, {
  ThemeMode themeMode = ThemeMode.light,
  Size size = const Size(1080, 2400),
}) async {
  _usePhoneView(tester, size: size);

  final FakeMayosApi fake = _signedInFake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  // Seeding talks to the (fake) API on real timers, so it runs outside the
  // test's fake-async zone.
  final InMemoryActiveWorkoutStore store = (await tester.runAsync(
    () => _seedThroughController(fake: fake),
  ))!;

  await _pumpApp(
    tester,
    overrides: _appOverrides(
      fake: fake,
      tokens: tokens,
      store: store,
      themeMode: themeMode,
    ),
  );
  await _resumeFromPrompt(tester);
}

/// Lets the picture requests, decodes and frames land. The decode runs on
/// the engine's own clock, so real time is spent between the fake-async
/// pumps — the same reason seeding runs outside the test's zone.
Future<void> _settlePictures(WidgetTester tester) async {
  for (int i = 0; i < 5; i++) {
    await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 60)));
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Finder _card(int exercise) => find.byType(ExerciseLoggingCard).at(exercise);

Finder _thumb(int exercise) => find
    .descendant(of: _card(exercise), matching: find.byType(ExerciseCatalogThumbnail))
    .first;

/// The image provider the card is actually loading, unwrapped from the
/// `cacheWidth` resize Flutter adds for a fixed-size thumbnail.
ImageProvider _providerOf(WidgetTester tester, int exercise) {
  ImageProvider provider = tester.widget<Image>(_imageOf(tester, exercise)).image;
  if (provider is ResizeImage) {
    provider = provider.imageProvider;
  }
  return provider;
}

Finder _imageOf(WidgetTester tester, int exercise) => find
    .descendant(of: _card(exercise), matching: find.byType(Image));

bool _hasFallback(WidgetTester tester, int exercise) => find
    .descendant(of: _card(exercise), matching: find.byIcon(Icons.fitness_center))
    .evaluate()
    .isNotEmpty;

void main() {
  /// Wraps one widget test in a cold fake `/media`: the hook is installed
  /// for the body and removed before the test framework checks the painting
  /// debug variables it owns.
  void mediaTest(
    String description,
    Future<void> Function(WidgetTester tester, FakeMediaCatalog media) body,
  ) {
    testWidgets(description, (WidgetTester tester) async {
      final FakeMediaCatalog media = FakeMediaCatalog();
      media.install();
      // The one picture the fake route serves; `images/gone.jpg` stays
      // unregistered so `/media` answers 404 for it.
      media.serve('images/incline.jpg');
      try {
        await body(tester, media);
      } finally {
        FakeMediaCatalog.uninstall();
      }
    });
  }

  mediaTest(
      'loaded, failed and missing pictures keep one fixed card layout (#161)',
      (WidgetTester tester, FakeMediaCatalog media) async {
    await _openLogger(tester);
    await _settlePictures(tester);

    expect(find.byType(ExerciseLoggingCard), findsNWidgets(3));

    // Loaded: the public /media address, and no fallback showing.
    final ImageProvider loaded = _providerOf(tester, 0);
    expect(loaded, isA<NetworkImage>());
    expect((loaded as NetworkImage).url,
        'http://10.0.2.2:8000/media/images/incline.jpg');
    expect(_hasFallback(tester, 0), isFalse);
    // The loading placeholder is gone: the frame itself arrived.
    expect(
      find.descendant(
          of: _card(0), matching: find.byIcon(Icons.image_outlined)),
      findsNothing,
    );

    // Failed: the picture widget is there, the 404 showed the fallback.
    expect(_imageOf(tester, 1), findsOneWidget);
    expect(_hasFallback(tester, 1), isTrue);
    expect(media.requestCount('images/gone.jpg'), 1);

    // Missing: the program payload carried no image path, so no picture is
    // ever requested and the same fallback sits in the same box.
    expect(_imageOf(tester, 2), findsNothing);
    expect(_hasFallback(tester, 2), isTrue);
    expect(media.requests.any((FakeMediaRequest r) => r.uri.path.contains('cable_fly')), isFalse);

    // The three states measure identically: a fixed thumbnail box…
    final Size box = tester.getSize(_thumb(0));
    expect(box, const Size(48, 48));
    expect(tester.getSize(_thumb(1)), box);
    expect(tester.getSize(_thumb(2)), box);
    // …and the same card height, so nothing shifts when a picture arrives.
    final double height = tester.getSize(_card(0)).height;
    expect(tester.getSize(_card(1)).height, height);
    expect(tester.getSize(_card(2)).height, height);
    expect(tester.takeException(), isNull);
  });

  mediaTest('the picture loads once and is reused on rebuild (#161)',
      (WidgetTester tester, FakeMediaCatalog media) async {
    await _openLogger(tester);
    await _settlePictures(tester);

    expect(media.requestCount('images/incline.jpg'), 1);

    // Rebuild the card: ticking a row goes through the logger's own setState
    // and the picture must come from the image cache, not the network.
    await tester.tap(find.byKey(const ValueKey<String>('logger.tick.0.0')));
    await tester.pump(const Duration(milliseconds: 200));
    await _settlePictures(tester);

    expect(media.requestCount('images/incline.jpg'), 1);
    expect(_hasFallback(tester, 0), isFalse);
    expect(tester.takeException(), isNull);
  });

  mediaTest(
      'the picture request is public: /media with no bearer token (#161)',
      (WidgetTester tester, FakeMediaCatalog media) async {
    await _openLogger(tester);
    await _settlePictures(tester);

    expect(media.requests, isNotEmpty);
    for (final FakeMediaRequest request in media.requests) {
      expect(request.uri.path, startsWith('/media/'));
      expect(request.header('Authorization'), isFalse);
      expect(request.header('Cookie'), isFalse);
    }
    expect(tester.takeException(), isNull);
  });

  mediaTest('no overflow at 360dp, light and dark, pictures settled (#161)',
      (WidgetTester tester, FakeMediaCatalog media) async {
    for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
      await _openLogger(tester, themeMode: mode, size: const Size(360, 640));
      await _settlePictures(tester);

      expect(tester.takeException(), isNull);
      expect(tester.getSize(_thumb(0)), const Size(48, 48));
      // Every card still fits the narrow phone with its picture.
      expect(_card(0), findsOneWidget);
      expect(_card(2), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
    }
  });

  mediaTest(
      'an exercise added from the search gets its catalog picture (#53)',
      (WidgetTester tester, FakeMediaCatalog media) async {
    // The picture the fake `/media` serves for the exercise the search picks.
    media.serve('images/bicep_curl.jpg');
    await _openLogger(tester);
    await _settlePictures(tester);

    await tester.tap(find.byKey(const ValueKey<String>('logger.addExercise')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'bicep');
    await tester.tap(find.text('Search'));
    await _pumpUntilFound(tester, find.text('Bicep Curl'));
    await tester.tap(find.text('Bicep Curl'));
    await tester.pumpAndSettle();

    // The card carries the picture the catalog search returned for it: the
    // `/media` request went out and no fallback is standing in.
    expect(find.byType(ExerciseLoggingCard), findsNWidgets(4));
    final Finder added = find
        .ancestor(
            of: find.text('Bicep Curl'),
            matching: find.byType(ExerciseLoggingCard))
        .first;
    await _settlePictures(tester);
    expect(media.requestCount('images/bicep_curl.jpg'), 1);
    expect(
      find.descendant(of: added, matching: find.byIcon(Icons.fitness_center)),
      findsNothing,
    );
    expect(tester.takeException(), isNull);
  });

  mediaTest(
      'media kill switch: the thumbnail falls back and never asks (#53)',
      (WidgetTester tester, FakeMediaCatalog media) async {
    await tester.pumpWidget(MaterialApp(
      theme: MayosTheme.light,
      home: const Scaffold(
        body: ExerciseCatalogThumbnail(
          imagePath: 'images/incline.jpg',
          enabled: false,
        ),
      ),
    ));

    expect(find.byType(ExerciseCatalogThumbnail), findsOneWidget);
    expect(find.byIcon(Icons.fitness_center), findsOneWidget);
    expect(find.byType(Image), findsNothing);
    await _settlePictures(tester);
    expect(media.totalRequests, 0);
    expect(tester.takeException(), isNull);
  });
}
