import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_logo.dart';
import 'package:mayos_mobile/src/core/ui/mayos_wallpaper.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/forgot_password_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/login_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/recovery_email_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/register_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/reset_password_screen.dart';
import 'package:mayos_mobile/src/features/shared/splash_screen.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_mayos_api.dart';

/// Issue #110: the gym wallpaper behind the splash and logged-out screens.
///
/// These tests pin its presence on the listed screens (in both app themes),
/// its absence on the recovery-email gate and signed-in screens, the fixed
/// design constants, cover-fit, and the always-white lockup over the photo.

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<void> _setSize(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size * 2;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

FakeMayosApi _fake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

List<Override> _authOverrides(FakeMayosApi fake, InMemoryTokenStore tokens,
    ThemeMode mode) {
  return <Override>[
    tokenStoreProvider.overrideWithValue(tokens),
    chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
    themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore(mode)),
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

GoRouter _authRouter(String initialLocation) {
  return GoRouter(
    initialLocation: initialLocation,
    routes: <RouteBase>[
      GoRoute(
        path: loginPath,
        builder: (_, __) => const LoginScreen(),
      ),
      GoRoute(
        path: registerPath,
        builder: (_, __) => const RegisterScreen(),
      ),
      GoRoute(
        path: recoveryEmailPath,
        builder: (_, __) => const RecoveryEmailScreen(),
      ),
      GoRoute(
        path: forgotPasswordPath,
        builder: (_, __) => const ForgotPasswordScreen(),
      ),
      GoRoute(
        path: resetPasswordPath,
        builder: (_, __) =>
            ResetPasswordScreen(token: 'MAYOS-RESET-CODE'),
      ),
    ],
  );
}

Future<void> _pumpSplash(WidgetTester tester, ThemeMode mode) async {
  await _setSize(tester, const Size(400, 900));
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: MayosTheme.light,
      darkTheme: MayosTheme.dark,
      themeMode: mode,
      home: const SplashScreen(),
    ),
  );
  await tester.pump(const Duration(milliseconds: 200));
}

Future<void> _pumpAuthScreen(
    WidgetTester tester, String location, ThemeMode mode, String heading) async {
  await _setSize(tester, const Size(400, 900));
  final FakeMayosApi fake = _fake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tester.pumpWidget(
    ProviderScope(
      overrides: _authOverrides(fake, tokens, mode),
      child: MaterialApp.router(
        debugShowCheckedModeBanner: false,
        theme: MayosTheme.light,
        darkTheme: MayosTheme.dark,
        themeMode: mode,
        routerConfig: _authRouter(location),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text(heading));
}

/// Pumps the signed-in app and waits for the Home shell.
Future<void> _pumpSignedIn(WidgetTester tester, ThemeMode mode) async {
  await _setSize(tester, const Size(400, 900));
  final FakeMayosApi fake = _fake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        ..._authOverrides(fake, tokens, mode),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        workoutCacheStoreProvider
            .overrideWithValue(InMemoryWorkoutCacheStore()),
        deviceTimezoneProvider.overrideWithValue(Future<String>.value('UTC')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value('UTC')),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('This week'));
  // Let the splash→home route transition finish so the splash (which does use
  // the wallpaper) is no longer mounted.
  for (int i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// The heading each auth surface lands on.
const Map<String, String> _authHeadings = <String, String>{
  loginPath: 'Log in',
  registerPath: 'Create account',
  forgotPasswordPath: 'Forgot password',
  resetPasswordPath: 'Reset password',
};

void main() {
  group('wallpaper design constants', () {
    test('overlay opacity and blur are fixed within the approved bands', () {
      expect(MayosWallpaper.overlayOpacity, inInclusiveRange(0.55, 0.65));
      expect(MayosWallpaper.blurSigma, inInclusiveRange(4, 8));
    });
  });

  for (final ThemeMode mode in const <ThemeMode>[
    ThemeMode.light,
    ThemeMode.dark,
  ]) {
    final String theme = mode == ThemeMode.dark ? 'dark' : 'light';

    testWidgets('splash shows the wallpaper photo ($theme app theme)',
        (WidgetTester tester) async {
      await _pumpSplash(tester, mode);
      expect(find.byKey(MayosWallpaper.photoKey), findsOneWidget);
    });

    testWidgets('splash lockup is white ($theme app theme)',
        (WidgetTester tester) async {
      await _pumpSplash(tester, mode);
      final MayosBrandLockup lockup =
          tester.widget<MayosBrandLockup>(find.byType(MayosBrandLockup));
      expect(lockup.variant, MayosBrandVariant.white);
    });

    for (final MapEntry<String, String> entry in _authHeadings.entries) {
      testWidgets('${entry.key} shows the wallpaper photo ($theme app theme)',
          (WidgetTester tester) async {
        await _pumpAuthScreen(tester, entry.key, mode, entry.value);
        expect(find.byKey(MayosWallpaper.photoKey), findsOneWidget);
      });
    }

    testWidgets('login lockup is white in the light app theme',
        (WidgetTester tester) async {
      await _pumpAuthScreen(
          tester, loginPath, ThemeMode.light, _authHeadings[loginPath]!);
      final MayosBrandLockup lockup =
          tester.widget<MayosBrandLockup>(find.byType(MayosBrandLockup));
      expect(lockup.variant, MayosBrandVariant.white);
    });

    testWidgets('recovery email has no wallpaper ($theme app theme)',
        (WidgetTester tester) async {
      await _pumpAuthScreen(tester, recoveryEmailPath, mode, 'Recovery email');
      expect(find.byKey(MayosWallpaper.photoKey), findsNothing);
    });

    testWidgets('signed-in Home has no wallpaper ($theme app theme)',
        (WidgetTester tester) async {
      await _pumpSignedIn(tester, mode);
      expect(find.text('Home'), findsWidgets);
      expect(find.byKey(MayosWallpaper.photoKey), findsNothing);
    });
  }

  testWidgets('the photo is cover-fit and bundled', (WidgetTester tester) async {
    await _pumpSplash(tester, ThemeMode.dark);
    final Image photo =
        tester.widget<Image>(find.byKey(MayosWallpaper.photoKey));
    expect(photo.image, isA<AssetImage>());
    expect((photo.image as AssetImage).assetName, MayosWallpaper.imageAsset);
    expect(photo.fit, BoxFit.cover);
  });

  testWidgets('recovery email lockup still follows the theme',
      (WidgetTester tester) async {
    await _pumpAuthScreen(
        tester, recoveryEmailPath, ThemeMode.light, 'Recovery email');
    final MayosBrandLockup lockup =
        tester.widget<MayosBrandLockup>(find.byType(MayosBrandLockup));
    expect(lockup.variant, MayosBrandVariant.auto);
  });
}
