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
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
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
    'assets/brand/mayos-lockup-blue.png',
    'assets/brand/mayos-lockup-black.png',
    'assets/brand/mayos-mark-white.png',
    'assets/brand/mayos-mark-blue.png',
    'assets/brand/mayos-mark-black.png',
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

// ---------------------------------------------------------------------------
// #52 authentication and recovery-email captures
// ---------------------------------------------------------------------------

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
    WidgetTester tester, _Surface surface, Size size, ThemeMode mode) async {
  _setSize(tester, size);
  final FakeMayosApi fake = _fake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
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

  if (surface.tab != null) {
    await tester.tap(find.text(surface.tab == 0 ? 'Home' : 'Program'));
    await tester.pump(const Duration(milliseconds: 400));
    await _pumpUntilFound(
        tester,
        surface.tab == 0
            ? find.text('Weekly weighted sets')
            : find.text('Upper/Lower 4x'));
  }
  if (surface.name == 'settings') {
    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('Appearance'));
  }
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
}
