@Tags(<String>['capture'])
library;

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/forgot_password_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/login_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/recovery_email_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/register_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/reset_password_screen.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_screen.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_widgets.dart';
import 'package:mayos_mobile/src/features/shared/splash_screen.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import '../support/fake_mayos_api.dart';

/// Visual review harness for issue #49.
///
/// Skipped by default so the normal test suite stays fast and headless. Run:
///
///   cd mobile
///   CAPTURE=1 flutter test --tags capture test/visual/capture_test.dart
///
/// PNGs are written to `docs/design-review/49/` at the repo root.
final bool _enabled = Platform.environment['CAPTURE'] == '1';
const Key _boundaryKey = Key('mayos.capture');

class _Surface {
  const _Surface(this.name, this.tab);
  final String name;
  final int? tab;
}

Future<void> _loadFonts() async {
  TestWidgetsFlutterBinding.ensureInitialized();
  final FontLoader serif = FontLoader('PlayfairDisplay')
    ..addFont(rootBundle.load('assets/fonts/PlayfairDisplay-Variable.ttf'));
  final FontLoader sans = FontLoader('Inter')
    ..addFont(rootBundle.load('assets/fonts/Inter-Variable.ttf'));
  // The test bundle ships the Material icon font; without it, icons render as
  // Ahem boxes in captures.
  final FontLoader icons = FontLoader('MaterialIcons')
    ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
  await Future.wait<void>(
      <Future<void>>[serif.load(), sans.load(), icons.load()]);
}

FakeMayosApi _fake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  return fake;
}

/// A brand-new player with no program, schedule, volume, or records, so the
/// Home empty states can be captured.
FakeMayosApi _emptyPlayerFake() {
  final FakeMayosApi fake = _fake();
  fake.noActiveProgram = true;
  fake.scheduleEmpty = true;
  fake.volumeEmpty = true;
  fake.recordsEmpty = true;
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

void _setSize(WidgetTester tester, Size size) {
  tester.view.physicalSize = size * 2;
  tester.view.devicePixelRatio = 2.0;
}

/// Decodes all bundled brand images before capture so a frame never races the
/// async image decode (which otherwise leaves a logo blank in the PNG).
Future<void> _precacheBrandImages(WidgetTester tester) async {
  final BuildContext context = tester.element(find.byType(MaterialApp));
  const List<String> assets = <String>[
    'assets/brand/mayos-lockup-white.png',
    'assets/brand/mayos-lockup-black.png',
    'assets/brand/mayos-mark-white.png',
    'assets/brand/mayos-mark-black.png',
    'assets/images/gym-wallpaper.jpg',
  ];
  await tester.runAsync(() async {
    for (final String asset in assets) {
      await precacheImage(AssetImage(asset), context);
    }
  });
  await tester.pump();
}

Future<void> _writeCapture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  // Widget tests run under a fake-async zone, so all real IO (directory
  // creation, encoding, file writes) must happen inside runAsync.
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/49');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

/// Writes a #51 onboarding capture to `docs/design-review/51/`.
Future<void> _writeOnboardingCapture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/51');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

/// Writes a #52 auth/recovery capture to `docs/design-review/52/`.
Future<void> _writeAuthCapture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/52');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

/// Writes a #48 Progress capture to `docs/design-review/48/`.
Future<void> _writeProgressCapture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/48');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

/// Writes a #53 Home/Program/exercise-detail capture to
/// `docs/design-review/53/`.
Future<void> _writeRedesignCapture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/53');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

// ---------------------------------------------------------------------------
// #54 cross-screen verification captures
// ---------------------------------------------------------------------------

/// Writes a #54 verification capture to `docs/design-review/54/`.
Future<void> _write54Capture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/54');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

/// Writes a #109 logo-lockup capture to `docs/design-review/109/`.
Future<void> _write109Capture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/109');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

/// Writes a #110 gym-wallpaper capture to `docs/design-review/110/`.
Future<void> _write110Capture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/110');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

/// Overrides shared by every #54 full-app capture.
List<Override> _appOverrides({
  required FakeMayosApi fake,
  required InMemoryTokenStore tokens,
  required ThemeMode mode,
  DraftStore? draftStore,
  WorkoutCacheStore? cacheStore,
  ChatCacheStore? chatCache,
}) {
  return <Override>[
    tokenStoreProvider.overrideWithValue(tokens),
    appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
    themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore(mode)),
    draftStoreProvider.overrideWithValue(draftStore ?? InMemoryDraftStore()),
    workoutCacheStoreProvider
        .overrideWithValue(cacheStore ?? InMemoryWorkoutCacheStore()),
    chatCacheStoreProvider
        .overrideWithValue(chatCache ?? InMemoryChatCacheStore()),
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
}

/// Pumps the app, opens Settings, and taps the given tile to reach a sub-screen.
Future<void> _pumpViaSettings(
  WidgetTester tester,
  Size size,
  ThemeMode mode,
  String tile,
  Finder ready,
  FakeMayosApi fake, {
  DraftStore? draftStore,
}) async {
  _setSize(tester, const Size(1080, 2400));
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: _appOverrides(
          fake: fake,
          tokens: tokens,
          mode: mode,
          draftStore: draftStore,
        ),
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await _pumpUntilFound(tester, find.text('Appearance'));
  await tester.tap(find.text(tile));
  await _pumpUntilFound(tester, ready);
  _setSize(tester, size);
  await tester.pump(const Duration(milliseconds: 200));
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

/// A chat conversation capture: an accepted disclosure and two real messages.
Future<void> _pumpChat54(WidgetTester tester, Size size, ThemeMode mode) async {
  _setSize(tester, const Size(1080, 2400));
  final FakeMayosApi fake = _fake();
  fake.chatHistory.addAll(<Map<String, dynamic>>[
    <String, dynamic>{
      'id': 'chat-1',
      'role': 'user',
      'content': 'How should I warm up for bench press?',
      'created_at': '2026-09-26T12:00:00Z',
    },
    <String, dynamic>{
      'id': 'chat-2',
      'role': 'assistant',
      'content': 'Ramp with the empty bar, then about 60% for five, then your '
          'working weight. Keep your elbows tucked.',
      'created_at': '2026-09-26T12:00:01Z',
    },
  ]);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final InMemoryChatCacheStore chatCache = InMemoryChatCacheStore();
  await chatCache.writeDisclosureAccepted('account-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: _appOverrides(
          fake: fake,
          tokens: tokens,
          mode: mode,
          chatCache: chatCache,
        ),
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.tap(find.byIcon(Icons.chat_bubble_outline));
  await _pumpUntilFound(
      tester, find.text('How should I warm up for bench press?'));
  _setSize(tester, size);
  await tester.pump(const Duration(milliseconds: 200));
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

/// The workout logger for Day 1, reached from the Program tab.
Future<void> _pumpLogger54(
    WidgetTester tester, Size size, ThemeMode mode) async {
  _setSize(tester, const Size(1080, 2400));
  final FakeMayosApi fake = _fake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: _appOverrides(fake: fake, tokens: tokens, mode: mode),
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.tap(find.text('Program'));
  await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));
  await tester.tap(find.text('Log workout'));
  await _pumpUntilFound(tester, find.text('Performed date'));
  _setSize(tester, size);
  await tester.pump(const Duration(milliseconds: 200));
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

/// The workout drafts list with one pending draft, reached from Settings.
Future<void> _pumpDrafts54(
    WidgetTester tester, Size size, ThemeMode mode) async {
  final InMemoryDraftStore draftStore = InMemoryDraftStore();
  await draftStore.write('account-alice', <WorkoutDraft>[
    WorkoutDraft(
      clientSessionId: 'draft-capture-1',
      accountId: 'account-alice',
      performedDate: '2026-09-26',
      performedTimezone: 'UTC',
      programVersion: 1,
      dayOrder: 1,
      dayName: 'Upper 1',
      capturedAt: '2026-09-26T11:00:00.000Z',
      exercises: <DraftExercise>[
        DraftExercise(
          exercise: <String, dynamic>{
            'exercise_id': 'bench_press',
            'exercise_name': 'Bench Press',
            'target_sets': 3,
            'target_reps_min': 5,
            'target_reps_max': 8,
            'target_rpe': 8.5,
            'rest_seconds': 180,
            'notes': null,
          },
          sets: const <WorkoutSetLog>[
            WorkoutSetLog(weightKg: 100, reps: 5, rpe: 8),
          ],
        ),
      ],
      readiness: 4,
      updatedAt: '2026-09-26T11:00:00.000Z',
    ),
  ]);
  await _pumpViaSettings(
    tester,
    size,
    mode,
    'Workout drafts',
    find.textContaining('pending'),
    _fake()..commitFails = true,
    draftStore: draftStore,
  );
}

/// One auth/recovery surface to capture, with an optional interaction.
class _AuthSurface {
  const _AuthSurface(this.name, this.initialLocation, this.heading,
      {this.fieldKey, this.serverError = false});

  final String name;
  final String initialLocation;
  final String heading;
  final String? fieldKey;
  final bool serverError;
}

final List<_AuthSurface> _authSurfaces = <_AuthSurface>[
  const _AuthSurface('login', loginPath, 'Log in', fieldKey: 'login_username'),
  const _AuthSurface('register', registerPath, 'Create account',
      fieldKey: 'register_username'),
  const _AuthSurface('recovery-email', recoveryEmailPath, 'Recovery email',
      fieldKey: 'recovery_email'),
  const _AuthSurface('forgot-password', forgotPasswordPath, 'Forgot password',
      fieldKey: 'forgot_email'),
  const _AuthSurface('reset-password',
      '$resetPasswordPath?token=MAYOS-RESET-CODE', 'Set new password',
      fieldKey: 'reset_password'),
];

GoRouter _authRouter(String initialLocation) {
  return GoRouter(
    initialLocation: initialLocation,
    routes: <RouteBase>[
      GoRoute(
        path: loginPath,
        builder: (BuildContext context, GoRouterState state) =>
            const LoginScreen(),
      ),
      GoRoute(
        path: registerPath,
        builder: (BuildContext context, GoRouterState state) =>
            const RegisterScreen(),
      ),
      GoRoute(
        path: recoveryEmailPath,
        builder: (BuildContext context, GoRouterState state) =>
            const RecoveryEmailScreen(),
      ),
      GoRoute(
        path: forgotPasswordPath,
        builder: (BuildContext context, GoRouterState state) =>
            const ForgotPasswordScreen(),
      ),
      GoRoute(
        path: resetPasswordPath,
        builder: (BuildContext context, GoRouterState state) =>
            ResetPasswordScreen(
          token: state.uri.queryParameters['token'] ?? '',
        ),
      ),
    ],
  );
}

Override _authApiOverride(FakeMayosApi fake) {
  return apiClientProvider.overrideWith((ref) {
    final ApiClient client = ApiClient(
      tokens: ref.watch(tokenStoreProvider),
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );
    client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
    return client;
  });
}

Future<void> _pumpAuthSurface(
  WidgetTester tester,
  _AuthSurface surface,
  Size size,
  ThemeMode mode, {
  bool keyboardInset = false,
}) async {
  _setSize(tester, size);
  final FakeMayosApi fake = FakeMayosApi();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          themeModeStoreProvider
              .overrideWithValue(InMemoryThemeModeStore(mode)),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          _authApiOverride(fake),
        ],
        child: MaterialApp.router(
          debugShowCheckedModeBanner: false,
          theme: MayosTheme.light,
          darkTheme: MayosTheme.dark,
          themeMode: mode,
          routerConfig: _authRouter(surface.initialLocation),
        ),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text(surface.heading));

  if (surface.serverError && surface.fieldKey != null) {
    await tester.enterText(find.byKey(Key('login_username')), 'alice');
    await tester.enterText(find.byKey(Key('login_password')), 'wrong');
    await tester.tap(find.byKey(const Key('login_submit')));
    await _pumpUntilFound(tester, find.text('Invalid username or password.'));
  }

  if (keyboardInset && surface.fieldKey != null) {
    await tester.tap(find.byKey(Key(surface.fieldKey!)));
    await tester.pump(const Duration(milliseconds: 100));
    tester.view.viewInsets =
        FakeViewPadding(bottom: 300 * tester.view.devicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    await tester.pump(const Duration(milliseconds: 200));
  }

  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

// ---------------------------------------------------------------------------
// #51 onboarding captures
// ---------------------------------------------------------------------------

/// One onboarding surface to capture, with the fake intake state that reaches
/// it and an optional interaction (for a selected state).
class _OnboardingSurface {
  const _OnboardingSurface({
    required this.name,
    required this.acknowledged,
    this.answers = const <String, Object>{},
    this.select,
  });

  final String name;
  final bool acknowledged;
  final Map<String, Object> answers;
  final String? select;
}

const Map<String, Object> _throughGender = <String, Object>{'gender': 'female'};

const Map<String, Object> _throughProportions = <String, Object>{
  'gender': 'female',
  'proportions': 'long_legs',
};

const Map<String, Object> _throughTrainingAge = <String, Object>{
  'gender': 'female',
  'proportions': 'long_legs',
  'age': 29,
  'height_cm': 168.0,
  'weight_kg': 64.5,
  'training_age_years': 3.0,
};

const Map<String, Object> _throughLongTerm = <String, Object>{
  ..._throughTrainingAge,
  'current_goal': 'build glutes and legs',
  'long_term_goal': 'stronger and more muscular',
};

const Map<String, Object> _allRequired = <String, Object>{
  ..._throughLongTerm,
  'weekly_frequency': 4,
  'equipment_access': 'commercial gym',
  'injuries_or_limitations': 'None',
  'stress_and_sleep': 'moderate stress, 7 hours sleep',
};

const List<_OnboardingSurface> _onboardingSurfaces = <_OnboardingSurface>[
  _OnboardingSurface(name: 'disclosure', acknowledged: false),
  _OnboardingSurface(name: 'gender', acknowledged: true),
  _OnboardingSurface(
    name: 'proportions',
    acknowledged: true,
    answers: _throughGender,
    select: 'proportions_option_balanced',
  ),
  _OnboardingSurface(
      name: 'age', acknowledged: true, answers: _throughProportions),
  _OnboardingSurface(
      name: 'weekly-frequency', acknowledged: true, answers: _throughLongTerm),
  _OnboardingSurface(
      name: 'text-goal', acknowledged: true, answers: _throughTrainingAge),
  _OnboardingSurface(name: 'review', acknowledged: true, answers: _allRequired),
];

FakeMayosApi _onboardingFake(_OnboardingSurface surface) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = false;
  fake.intakeDisclosureAcknowledged = surface.acknowledged;
  fake.intakeAnswers.addAll(surface.answers);
  return fake;
}

Future<void> _pumpOnboardingSurface(
  WidgetTester tester,
  _OnboardingSurface surface,
  Size size,
  ThemeMode mode,
) async {
  _setSize(tester, size);
  final FakeMayosApi fake = _onboardingFake(surface);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          themeModeStoreProvider
              .overrideWithValue(InMemoryThemeModeStore(mode)),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          apiClientProvider.overrideWith((ref) {
            final ApiClient client = ApiClient(
              tokens: ref.watch(tokenStoreProvider),
              baseUrl: 'http://test.local',
              adapter: fake.adapter,
            );
            client.onUnauthorized =
                ref.watch(unauthorizedEventsProvider).signal;
            return client;
          }),
        ],
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: MayosTheme.light,
          darkTheme: MayosTheme.dark,
          themeMode: mode,
          home: const OnboardingScreen(),
        ),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.byType(OnboardingScaffold));
  final String? select = surface.select;
  if (select != null) {
    // All choices are on screen at these sizes; tap without scrolling so the
    // capture keeps the heading at the top.
    await tester.tap(find.byKey(Key(select)));
    await tester.pump(const Duration(milliseconds: 300));
  }
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> _pumpSplash(WidgetTester tester, Size size, ThemeMode mode) async {
  _setSize(tester, size);
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: MayosTheme.light,
        darkTheme: MayosTheme.dark,
        themeMode: mode,
        home: const SplashScreen(),
      ),
    ),
  );
  await tester.pump(const Duration(milliseconds: 300));
  await _precacheBrandImages(tester);
}

Future<void> _pumpShell(
    WidgetTester tester, _Surface surface, Size size, ThemeMode mode,
    {FakeMayosApi? fake}) async {
  // Navigate at a large viewport (bottom-bar hit-testing is reliable there),
  // then resize to the capture size so the layout is exercised at the target.
  _setSize(tester, const Size(1080, 2400));
  final FakeMayosApi activeFake = fake ?? _fake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          themeModeStoreProvider
              .overrideWithValue(InMemoryThemeModeStore(mode)),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          apiClientProvider.overrideWith((ref) {
            final ApiClient client = ApiClient(
              tokens: ref.watch(tokenStoreProvider),
              baseUrl: 'http://test.local',
              adapter: activeFake.adapter,
            );
            client.onUnauthorized =
                ref.watch(unauthorizedEventsProvider).signal;
            return client;
          }),
        ],
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));

  if (surface.tab == 1) {
    await tester.tap(find.text('Program'));
    await tester.pump(const Duration(milliseconds: 400));
    await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));
  }
  if (surface.tab == 0) {
    await _pumpUntilFound(tester, find.text('This week'));
  }
  if (surface.name == 'settings') {
    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('Appearance'));
  }
  _setSize(tester, size);
  await tester.pump(const Duration(milliseconds: 200));
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

/// Pumps the app, opens Program, and taps the first exercise to reach the
/// read-only exercise detail from a program day (#53).
Future<void> _pumpExerciseDetail(
    WidgetTester tester, Size size, ThemeMode mode) async {
  _setSize(tester, const Size(1080, 2400));
  final FakeMayosApi fake = _fake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          themeModeStoreProvider
              .overrideWithValue(InMemoryThemeModeStore(mode)),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          apiClientProvider.overrideWith((ref) {
            final ApiClient client = ApiClient(
              tokens: ref.watch(tokenStoreProvider),
              baseUrl: 'http://test.local',
              adapter: fake.adapter,
            );
            client.onUnauthorized =
                ref.watch(unauthorizedEventsProvider).signal;
            return client;
          }),
        ],
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.tap(find.text('Program'));
  await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));
  await tester.tap(find.text('Bench Press'));
  await _pumpUntilFound(tester, find.text('Overview'));
  _setSize(tester, size);
  await tester.pump(const Duration(milliseconds: 200));
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

// ---------------------------------------------------------------------------
// #48 Progress captures
// ---------------------------------------------------------------------------

/// Five real-shaped Bench Press sessions for the Strength chart.
List<Map<String, dynamic>> _capturePoints(int count) => <Map<String, dynamic>>[
      <String, dynamic>{
        'date': '2026-06-03',
        'weight_kg': 95.0,
        'reps': 5,
        'rpe': 8.0,
        'e1rm': 110.0,
      },
      <String, dynamic>{
        'date': '2026-06-10',
        'weight_kg': 97.5,
        'reps': 5,
        'rpe': 8.0,
        'e1rm': 112.9,
      },
      <String, dynamic>{
        'date': '2026-06-17',
        'weight_kg': 100.0,
        'reps': 5,
        'rpe': 8.0,
        'e1rm': 115.6,
      },
      <String, dynamic>{
        'date': '2026-06-24',
        'weight_kg': 102.5,
        'reps': 3,
        'rpe': 9.0,
        'e1rm': 116.8,
      },
      <String, dynamic>{
        'date': '2026-07-01',
        'weight_kg': 105.0,
        'reps': 3,
        'rpe': 9.0,
        'e1rm': 119.7,
      },
    ].take(count).toList(growable: false);

FakeMayosApi _progressFake({int points = 5}) {
  final FakeMayosApi fake = _fake();
  fake.loggedExercises = <Map<String, dynamic>>[
    <String, dynamic>{'id': 'bench_press', 'name': 'Bench Press'},
    <String, dynamic>{'id': 'overhead_press', 'name': 'Overhead Press'},
  ];
  fake.dashboardExerciseHistories = <String, Map<String, dynamic>>{
    'bench_press': <String, dynamic>{
      'history': _capturePoints(points),
      'caption': null,
      'records': <dynamic>[],
    },
  };
  fake.volumeByDays = <int, Map<String, dynamic>>{
    7: <String, dynamic>{'Chest': 12.5, 'Back': 9.0, 'Quads': 6.0},
    28: <String, dynamic>{
      'Chest': 42.5,
      'Back': 36.0,
      'Quads': 30.5,
      'Shoulders': 18.0,
      'Hamstrings & Glutes': 12.0,
    },
    90: <String, dynamic>{
      'Chest': 118.5,
      'Back': 104.0,
      'Quads': 88.5,
      'Shoulders': 61.0,
      'Hamstrings & Glutes': 44.0,
      'Biceps': 30.0,
      'Triceps': 27.5,
    },
  };
  return fake;
}

FakeMayosApi _progressEmptyFake() {
  final FakeMayosApi fake = _fake();
  fake.loggedExercises = <Map<String, dynamic>>[];
  return fake;
}

class _ProgressSurface {
  const _ProgressSurface({
    required this.name,
    required this.fakeBuilder,
    this.volume = false,
    this.empty = false,
  });

  final String name;
  final FakeMayosApi Function() fakeBuilder;
  final bool volume;
  final bool empty;
}

final List<_ProgressSurface> _progressSurfaces = <_ProgressSurface>[
  _ProgressSurface(name: 'strength', fakeBuilder: () => _progressFake()),
  _ProgressSurface(
      name: 'strength-single', fakeBuilder: () => _progressFake(points: 1)),
  _ProgressSurface(
      name: 'volume', fakeBuilder: () => _progressFake(), volume: true),
  _ProgressSurface(name: 'empty', fakeBuilder: _progressEmptyFake, empty: true),
];

/// Pumps the app, opens Progress, optionally switches to a 28-day Volume view,
/// then captures at [size].
Future<void> _pumpProgressSurface(
  WidgetTester tester,
  _ProgressSurface surface,
  Size size,
  ThemeMode mode,
) async {
  _setSize(tester, const Size(1080, 2400));
  final FakeMayosApi fake = surface.fakeBuilder();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          themeModeStoreProvider
              .overrideWithValue(InMemoryThemeModeStore(mode)),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          apiClientProvider.overrideWith((ref) {
            final ApiClient client = ApiClient(
              tokens: ref.watch(tokenStoreProvider),
              baseUrl: 'http://test.local',
              adapter: fake.adapter,
            );
            client.onUnauthorized =
                ref.watch(unauthorizedEventsProvider).signal;
            return client;
          }),
        ],
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.tap(find.descendant(
    of: find.byType(MayosBottomNavigation),
    matching: find.text('Progress'),
  ));
  await _pumpUntilFound(
    tester,
    surface.empty
        ? find.text('No training history yet')
        : find.text('Estimated 1RM'),
  );
  if (surface.volume) {
    await tester.tap(find.text('Volume'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('28 days'));
    await _pumpUntilFound(tester, find.textContaining('Last 28 days'));
  }
  _setSize(tester, size);
  await tester.pump(const Duration(milliseconds: 200));
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

void main() {
  setUpAll(_loadFonts);

  const List<Size> sizes = <Size>[Size(360, 640), Size(412, 915)];
  const List<ThemeMode> modes = <ThemeMode>[ThemeMode.light, ThemeMode.dark];
  const List<_Surface> surfaces = <_Surface>[
    _Surface('home', 0),
    _Surface('program', 1),
    _Surface('settings', null),
  ];

  // Set CAPTURE=1 (with --tags capture) to render design-review captures.
  final bool skipCapture = !_enabled;

  for (final Size size in sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';

      testWidgets('splash $theme $sizeTag', (WidgetTester tester) async {
        await _pumpSplash(tester, size, mode);
        await _writeCapture(tester, 'splash-$theme-$sizeTag');
      }, skip: skipCapture);

      for (final _Surface surface in surfaces) {
        testWidgets('${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpShell(tester, surface, size, mode);
          await _writeCapture(tester, '${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }
    }
  }

  // #51 onboarding flow captures (docs/design-review/51).
  for (final Size size in sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';
      for (final _OnboardingSurface surface in _onboardingSurfaces) {
        testWidgets('onboarding ${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpOnboardingSurface(tester, surface, size, mode);
          await _writeOnboardingCapture(
              tester, 'onboarding-${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }
    }
  }

  // #52 authentication and recovery-email captures (docs/design-review/52).
  for (final Size size in sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';
      for (final _AuthSurface surface in _authSurfaces) {
        testWidgets('auth ${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpAuthSurface(tester, surface, size, mode);
          await _writeAuthCapture(
              tester, 'auth-${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }
    }
  }

  // Extra login states at the small phone size: a server error and the
  // keyboard inset simulated with a focused field.
  const Size small = Size(360, 640);
  for (final ThemeMode mode in modes) {
    final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
    testWidgets('auth login server error $theme 360x640',
        (WidgetTester tester) async {
      await _pumpAuthSurface(
        tester,
        const _AuthSurface('login', loginPath, 'Log in',
            fieldKey: 'login_username', serverError: true),
        small,
        mode,
      );
      await _writeAuthCapture(tester, 'auth-login-server-error-$theme-360x640');
    }, skip: skipCapture);

    testWidgets('auth login keyboard $theme 360x640',
        (WidgetTester tester) async {
      await _pumpAuthSurface(
        tester,
        const _AuthSurface('login', loginPath, 'Log in',
            fieldKey: 'login_username'),
        small,
        mode,
        keyboardInset: true,
      );
      await _writeAuthCapture(tester, 'auth-login-keyboard-$theme-360x640');
    }, skip: skipCapture);
  }

  // #53 Home/Program/exercise-detail redesign captures (docs/design-review/53).
  // Home with real data and Home for a brand-new player with no data.
  for (final Size size in sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';

      testWidgets('redesign home $theme $sizeTag', (WidgetTester tester) async {
        await _pumpShell(
          tester,
          const _Surface('home', 0),
          size,
          mode,
        );
        await _writeRedesignCapture(tester, 'home-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('redesign home empty $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpShell(
          tester,
          const _Surface('home', 0),
          size,
          mode,
          fake: _emptyPlayerFake(),
        );
        await _writeRedesignCapture(tester, 'home-empty-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('redesign program $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpShell(
          tester,
          const _Surface('program', 1),
          size,
          mode,
        );
        await _writeRedesignCapture(tester, 'program-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('redesign exercise overview $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpExerciseDetail(tester, size, mode);
        await _writeRedesignCapture(
            tester, 'exercise-overview-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('redesign exercise technique $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpExerciseDetail(tester, size, mode);
        await tester.tap(find.text('Technique'));
        // Two pumps: the first builds the new target, the second advances the
        // segmented control's implicit animation to its end state.
        await tester.pump(const Duration(milliseconds: 300));
        await tester.pump(const Duration(milliseconds: 300));
        await _writeRedesignCapture(
            tester, 'exercise-technique-$theme-$sizeTag');
      }, skip: skipCapture);
    }
  }

  // #48 Progress captures (docs/design-review/48): Strength with five real
  // points, a single point, 28-day Volume, and the empty state.
  for (final Size size in sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';
      for (final _ProgressSurface surface in _progressSurfaces) {
        testWidgets('progress ${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpProgressSurface(tester, surface, size, mode);
          await _writeProgressCapture(
              tester, 'progress-${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }
    }
  }

  // -------------------------------------------------------------------------
  // #54 cross-screen verification captures (docs/design-review/54).
  // -------------------------------------------------------------------------
  const List<_AuthSurface> auth54 = <_AuthSurface>[
    _AuthSurface('login', loginPath, 'Log in', fieldKey: 'login_username'),
    _AuthSurface('register', registerPath, 'Create account',
        fieldKey: 'register_username'),
    _AuthSurface('recovery-email', recoveryEmailPath, 'Recovery email',
        fieldKey: 'recovery_email'),
  ];
  const List<_OnboardingSurface> onboarding54 = <_OnboardingSurface>[
    _OnboardingSurface(name: 'disclosure', acknowledged: false),
    _OnboardingSurface(name: 'specialization', acknowledged: true),
    _OnboardingSurface(
      name: 'proportions',
      acknowledged: true,
      answers: _throughGender,
      select: 'proportions_option_balanced',
    ),
    _OnboardingSurface(
        name: 'numeric', acknowledged: true, answers: _throughProportions),
    _OnboardingSurface(
        name: 'review', acknowledged: true, answers: _allRequired),
  ];

  for (final Size size in sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';

      testWidgets('54 splash $theme $sizeTag', (WidgetTester tester) async {
        await _pumpSplash(tester, size, mode);
        await _write54Capture(tester, 'splash-$theme-$sizeTag');
      }, skip: skipCapture);

      for (final _AuthSurface surface in auth54) {
        testWidgets('54 auth ${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpAuthSurface(tester, surface, size, mode);
          await _write54Capture(tester, 'auth-${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }

      for (final _OnboardingSurface surface in onboarding54) {
        testWidgets('54 onboarding ${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpOnboardingSurface(tester, surface, size, mode);
          await _write54Capture(
              tester, 'onboarding-${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }

      for (final _Surface surface in surfaces) {
        testWidgets('54 ${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpShell(tester, surface, size, mode);
          await _write54Capture(tester, '${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }

      testWidgets('54 exercise detail $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpExerciseDetail(tester, size, mode);
        await _write54Capture(tester, 'exercise-detail-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('54 progress strength $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpProgressSurface(tester, _progressSurfaces.first, size, mode);
        await _write54Capture(tester, 'progress-strength-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('54 chat $theme $sizeTag', (WidgetTester tester) async {
        await _pumpChat54(tester, size, mode);
        await _write54Capture(tester, 'chat-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('54 workout logger $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpLogger54(tester, size, mode);
        await _write54Capture(tester, 'workout-logger-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('54 workout drafts $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpDrafts54(tester, size, mode);
        await _write54Capture(tester, 'workout-drafts-$theme-$sizeTag');
      }, skip: skipCapture);
    }
  }

  // Text-scale 2.0 set at 360x640 in Light for the four highest-risk screens.
  testWidgets('54 home text-scale 2.0 360x640 light',
      (WidgetTester tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 2.0;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await _pumpShell(tester, const _Surface('home', 0), small, ThemeMode.light);
    await _write54Capture(tester, 'home-light-360x640-textscale2');
  }, skip: skipCapture);

  testWidgets('54 onboarding proportions text-scale 2.0 360x640 light',
      (WidgetTester tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 2.0;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await _pumpOnboardingSurface(
      tester,
      const _OnboardingSurface(
        name: 'proportions',
        acknowledged: true,
        answers: _throughGender,
        select: 'proportions_option_balanced',
      ),
      small,
      ThemeMode.light,
    );
    await _write54Capture(tester, 'onboarding-proportions-light-360x640-textscale2');
  }, skip: skipCapture);

  testWidgets('54 login text-scale 2.0 360x640 light',
      (WidgetTester tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 2.0;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await _pumpAuthSurface(
      tester,
      const _AuthSurface('login', loginPath, 'Log in',
          fieldKey: 'login_username'),
      small,
      ThemeMode.light,
    );
    await _write54Capture(tester, 'auth-login-light-360x640-textscale2');
  }, skip: skipCapture);

  testWidgets('54 settings text-scale 2.0 360x640 light',
      (WidgetTester tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 2.0;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await _pumpShell(
        tester, const _Surface('settings', null), small, ThemeMode.light);
    await _write54Capture(tester, 'settings-light-360x640-textscale2');
  }, skip: skipCapture);

  // System theme demonstrated by capturing Settings under a dark and a light
  // platform brightness with System selected.
  for (final Brightness brightness in <Brightness>[
    Brightness.dark,
    Brightness.light,
  ]) {
    final String tag = brightness == Brightness.dark ? 'dark' : 'light';
    testWidgets('54 settings system under $tag platform brightness',
        (WidgetTester tester) async {
      tester.platformDispatcher.platformBrightnessTestValue = brightness;
      addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
      await _pumpShell(
          tester, const _Surface('settings', null), small, ThemeMode.system);
      await _write54Capture(tester, 'settings-system-$tag-360x640');
    }, skip: skipCapture);
  }

  // -------------------------------------------------------------------------
  // #109 monochrome logo lockup captures (docs/design-review/109): the splash
  // and the shell header on Home, in both themes at a narrow 320x640 and a
  // common 412x915.
  // -------------------------------------------------------------------------
  const List<Size> logo109Sizes = <Size>[Size(320, 640), Size(412, 915)];
  for (final Size size in logo109Sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';

      testWidgets('109 logo splash $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpSplash(tester, size, mode);
        await _write109Capture(tester, 'splash-$theme-$sizeTag');
      }, skip: skipCapture);

      testWidgets('109 logo home header $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpShell(tester, const _Surface('home', 0), size, mode);
        await _write109Capture(tester, 'home-$theme-$sizeTag');
      }, skip: skipCapture);
    }
  }

  // -------------------------------------------------------------------------
  // #110 gym wallpaper captures (docs/design-review/110): splash, login and
  // register at 320x640 and 412x915 in both app themes, plus a wide web login.
  // -------------------------------------------------------------------------
  const List<_AuthSurface> wallpaper110 = <_AuthSurface>[
    _AuthSurface('login', loginPath, 'Log in', fieldKey: 'login_username'),
    _AuthSurface('register', registerPath, 'Create account',
        fieldKey: 'register_username'),
  ];
  const List<Size> wallpaper110Sizes = <Size>[Size(320, 640), Size(412, 915)];
  for (final Size size in wallpaper110Sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';

      testWidgets('110 wallpaper splash $theme $sizeTag',
          (WidgetTester tester) async {
        await _pumpSplash(tester, size, mode);
        await _write110Capture(tester, 'splash-$theme-$sizeTag');
      }, skip: skipCapture);

      for (final _AuthSurface surface in wallpaper110) {
        testWidgets('110 wallpaper ${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpAuthSurface(tester, surface, size, mode);
          await _write110Capture(tester, '${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }
    }
  }

  testWidgets('110 wallpaper login wide 1280x800 light',
      (WidgetTester tester) async {
    await _pumpAuthSurface(
      tester,
      const _AuthSurface('login', loginPath, 'Log in',
          fieldKey: 'login_username'),
      const Size(1280, 800),
      ThemeMode.light,
    );
    await _write110Capture(tester, 'login-light-1280x800');
  }, skip: skipCapture);
}
