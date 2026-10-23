import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:myos_mobile/src/app.dart';
import 'package:myos_mobile/src/core/app_mode.dart';
import 'package:myos_mobile/src/core/display_language/controller.dart';
import 'package:myos_mobile/src/core/display_language/store.dart';
import 'package:myos_mobile/src/core/api_client.dart';
import 'package:myos_mobile/src/core/chat_storage.dart';
import 'package:myos_mobile/src/core/theme/myos_spacing.dart';
import 'package:myos_mobile/src/core/theme/myos_theme.dart';
import 'package:myos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:myos_mobile/src/core/token_store.dart';
import 'package:myos_mobile/src/core/install_prompt_store.dart';
import 'package:myos_mobile/src/features/shared/install_prompt.dart';
import 'package:myos_mobile/src/core/ui/myos_logo.dart';
import 'package:myos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:myos_mobile/src/features/player/auth/auth_widgets.dart';
import 'package:myos_mobile/src/features/shared/mode_switch.dart';
import 'package:myos_mobile/src/features/player/auth/google_auth_gateway.dart';
import 'package:myos_mobile/src/features/player/auth/google_sign_in_button.dart';
import 'package:myos_mobile/src/features/player/auth/in_app_browser_hint.dart';
import 'package:myos_mobile/src/providers.dart';
import 'package:myos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_api_adapter.dart';
import 'support/fake_google_auth.dart';
import 'support/fake_myos_api.dart';

class _EligibleInstallPromptStore implements InstallPromptStore {
  @override
  Future<InstallPromptEnvironment> readEnvironment() async =>
      const InstallPromptEnvironment(
        isIosShareBrowser: true,
        hasInstallButton: false,
        isStandalone: false,
        wasDismissed: false,
      );
  @override
  Future<void> rememberDismissal() async {}
  @override
  Future<String> promptInstall() async => 'unavailable';
  @override
  void listenForInstalled(void Function() onInstalled) {}
  @override
  void listenForInstallState(void Function() onInstallStateChanged) {}
  @override
  bool consumeInstalled() => false;
}
/// Focused coverage for the restyled authentication and recovery-email screens
/// (#52): login, registration, recovery email, forgot/reset, keyboard insets,
/// focus traversal, password visibility, and overflow at small sizes/scale.

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
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<ProviderContainer> _pumpAuth(WidgetTester tester, FakeMyosApi fake,
    {Size size = const Size(393, 852),
    List<Override> extraOverrides = const <Override>[]}) async {
  await _setSize(tester, size);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tester
      .pumpWidget(authApp(fake, tokens, extraOverrides: extraOverrides));
  await _pumpUntilFound(tester, find.text('Log in'));
  return ProviderScope.containerOf(tester.element(find.byType(MyosApp)));
}

GoRouter _routerOf(WidgetTester tester) {
  final ProviderContainer container =
      ProviderScope.containerOf(tester.element(find.byType(MyosApp)));
  return container.read(routerProvider);
}

/// A fake with a live password for `alice`, so login can succeed.
FakeMyosApi _loginFake() {
  final FakeMyosApi fake = FakeMyosApi();
  fake.passwords['alice'] = 'correct-horse-1';
  fake.recoveryEmail = 'alice@example.com';
  fake.profileExists = true;
  return fake;
}

const Map<String, String> _inAppBrowserUserAgents = <String, String>{
  'TikTok Android': 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 '
      'Chrome/124.0.6367.82 Mobile Safari/537.36 musical_ly_2023503040 '
      'com.zhiliaoapp.musically',
  'TikTok iOS': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
      'trill_2023503040',
  'TikTok Bytedance WebView': 'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 '
      'Chrome/124.0.6367.82 Mobile Safari/537.36 BytedanceWebview/1.0',
  'Instagram Android': 'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 '
      'Chrome/125.0.6422.165 Mobile Safari/537.36 Instagram 330.0.0.0.90',
  'Instagram iOS': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
      'Instagram 330.0.0.0.90 (iPhone14,5; iOS 17_5; en_US; en; scale=3.00)',
  'Facebook Android': 'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 '
      'Chrome/125.0.6422.165 Mobile Safari/537.36 '
      '[FB_IAB/FB4A;FBAV/466.0.0.47.85;]',
  'Facebook iOS': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
      '[FBAN/FBIOS;FBAV/466.0.0.47.85;FBBV/601234567;]',
  'WhatsApp iOS': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 WhatsApp/24.20.81',
};

const String _chromeAndroidUserAgent = 'Mozilla/5.0 (Linux; Android 14; '
    'Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 '
    'Mobile Safari/537.36';
const String _safariIosUserAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 '
    'like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
    'Version/17.5 Mobile/15E148 Safari/604.1';

void main() {
  for (final MapEntry<String, String> browser in
      _inAppBrowserUserAgents.entries) {
    test('shows hint on web for ${browser.key}', () {
      expect(
        shouldShowInAppBrowserGoogleHint(
            isWeb: true, userAgent: browser.value),
        isTrue,
      );
    });
    test('does not show hint off web for ${browser.key}', () {
      expect(
        shouldShowInAppBrowserGoogleHint(
            isWeb: false, userAgent: browser.value),
        isFalse,
      );
    });
  }
  test('does not show hint in Chrome on Android', () {
    expect(
      shouldShowInAppBrowserGoogleHint(
          isWeb: true, userAgent: _chromeAndroidUserAgent),
      isFalse,
    );
  });
  test('does not show hint in Safari on iOS', () {
    expect(
      shouldShowInAppBrowserGoogleHint(
          isWeb: true, userAgent: _safariIosUserAgent),
      isFalse,
    );
  });

  for (final String language in <String>['en', 'ar']) {
    testWidgets('login shows localized Google hint in TikTok webview ($language)',
        (WidgetTester tester) async {
      await _pumpAuth(
        tester,
        _loginFake(),
        extraOverrides: <Override>[
          googleAuthGatewayProvider.overrideWithValue(FakeGoogleAuthGateway()),
          showInAppBrowserGoogleHintProvider.overrideWith((ref) =>
              shouldShowInAppBrowserGoogleHint(
                  isWeb: true,
                  userAgent: _inAppBrowserUserAgents['TikTok Android']!)),
          displayLanguageProvider.overrideWith((ref) =>
              DisplayLanguageController(InMemoryDisplayLanguageStore(),
                  systemLanguage: language)),
        ],
      );
      final String hint = language == 'ar'
          ? 'لتسجيل الدخول بحساب Google، افتح هذه الصفحة في متصفحك.'
          : 'To sign in with Google, open this page in your browser.';
      expect(find.text(hint), findsOneWidget);
      expect(find.byKey(const Key('login_username')), findsOneWidget);
    });

    testWidgets('login omits Google hint for Chrome Android ($language)',
        (WidgetTester tester) async {
      await _pumpAuth(
        tester,
        _loginFake(),
        extraOverrides: <Override>[
          googleAuthGatewayProvider
              .overrideWithValue(FakeGoogleAuthGateway()),
          showInAppBrowserGoogleHintProvider.overrideWith((ref) =>
              shouldShowInAppBrowserGoogleHint(
                  isWeb: true, userAgent: _chromeAndroidUserAgent)),
          displayLanguageProvider.overrideWith((ref) =>
              DisplayLanguageController(InMemoryDisplayLanguageStore(),
                  systemLanguage: language)),
        ],
      );
      expect(find.byKey(const Key('login_google_in_app_browser_hint')),
          findsNothing);
    });
  }

  testWidgets('login screen has no install prompt', (tester) async {
    await _pumpAuth(tester, _loginFake(), extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(_EligibleInstallPromptStore()),
    ]);
    expect(find.text('Install MYOS'), findsNothing);
    expect(find.textContaining('Add to Home Screen'), findsNothing);
    await tester.tap(find.text('Create an account'));
    await tester.pumpAndSettle();
    expect(find.text('Create account'), findsWidgets);
    expect(find.text('Install MYOS'), findsNothing);
    expect(find.textContaining('Add to Home Screen'), findsNothing);
  });

  testWidgets('login success authenticates and leaves the form',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    final ProviderContainer container = await _pumpAuth(tester, fake);

    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('login_submit')));
    await tester.pump();

    await _pumpUntilFound(tester, find.text('Home'));
    expect(container.read(authControllerProvider).status,
        AuthStatus.authenticated);
  });

  testWidgets('login failure shows the server message and stays put',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    await _pumpAuth(tester, fake);

    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(find.byKey(const Key('login_password')), 'wrong');
    await tester.tap(find.byKey(const Key('login_submit')));
    await _pumpUntilFound(tester, find.text('Invalid username or password.'));

    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(find.byKey(const Key('login_submit')), findsOneWidget);
  });

  testWidgets('login offers no claim-account entry (#151)',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    await _pumpAuth(tester, fake);

    // The claim surface is gone: no link mentions claiming an account.
    expect(find.text('Claim imported account'), findsNothing);
    expect(
      find.byWidgetPredicate((Widget w) =>
          w is AuthLink && w.label.toLowerCase().contains('claim')),
      findsNothing,
    );
    // The remaining links still fill the action bar (no empty slot left).
    expect(find.text('Create an account'), findsOneWidget);
    expect(find.text('Forgot password?'), findsOneWidget);
    expect(find.text('Privacy policy'), findsOneWidget);
  });

  testWidgets('login shows a loading state while the request is in flight',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    final Completer<void> gate = Completer<void>();
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path == '/auth/login') {
        await gate.future;
      }
    };

    await _pumpAuth(tester, fake);
    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('login_submit')));
    await tester.pump();

    expect(find.byType(CircularProgressIndicator), findsWidgets);
    final FilledButton button = tester.widget<FilledButton>(find.descendant(
      of: find.byKey(const Key('login_submit')),
      matching: find.byType(FilledButton),
    ));
    expect(button.onPressed, isNull);

    gate.complete();
    await _pumpUntilFound(tester, find.text('Home'));
  });

  testWidgets('registration rejects mismatched passwords before any call',
      (WidgetTester tester) async {
    final FakeMyosApi fake = FakeMyosApi();
    await _pumpAuth(tester, fake);

    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));
    await tester.enterText(find.byKey(const Key('register_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('register_password')), 'correct-horse-1');
    await tester.enterText(
        find.byKey(const Key('register_confirm')), 'different-horse');
    await tester.tap(find.byKey(const Key('register_submit')));
    await tester.pump();

    expect(find.text('Passwords do not match.'), findsOneWidget);
    expect(
      fake.adapter.requests.any((FakeRequest r) => r.path == '/auth/register'),
      isFalse,
    );
  });

  testWidgets('registration reaches onboarding and shows the optional reminder',
      (WidgetTester tester) async {
    final FakeMyosApi fake = FakeMyosApi();
    await _pumpAuth(tester, fake);

    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));
    await tester.enterText(find.byKey(const Key('register_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('register_password')), 'correct-horse-1');
    await tester.enterText(
        find.byKey(const Key('register_confirm')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('register_submit')));

    await _pumpUntilFound(tester, find.text('Verify your recovery email'));
    expect(_routerOf(tester).routeInformationProvider.value.uri.path,
        onboardingPath);
    expect(find.byKey(const Key('recovery_email')), findsNothing);
  });

  testWidgets('coach code registration opens Coach mode without verification',
      (WidgetTester tester) async {
    final FakeMyosApi fake = FakeMyosApi()
      ..validNewAccountCoachInviteCode = 'coach-code-123456';
    await _pumpAuth(tester, fake);
    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));

    final Finder toggle = find.byKey(const Key('register_coach_invite_toggle'));
    expect(find.byKey(const Key('register_coach_invite_code')), findsNothing);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('register_coach_invite_code')), findsOneWidget);
    expect(find.text('temporary-code'), findsNothing);
    await tester.enterText(
        find.byKey(const Key('register_coach_invite_code')), 'temporary-code');
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('register_coach_invite_code')), findsNothing);
    await tester.tap(toggle);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('register_username')), 'coach');
    await tester.enterText(
        find.byKey(const Key('register_password')), 'correct-horse-1');
    await tester.enterText(
        find.byKey(const Key('register_confirm')), 'correct-horse-1');
    await tester.enterText(find.byKey(const Key('register_coach_invite_code')),
        'coach-code-123456');
    await tester.tap(find.byKey(const Key('register_submit')));
    await _pumpUntilFound(tester, find.text('Verify your recovery email'));
    expect(fake.lastRegistrationCoachInviteCode, 'coach-code-123456');
    await _pumpUntilFound(tester, find.text('Roster'));
    expect(_routerOf(tester).routeInformationProvider.value.uri.path,
        coachRosterPath);
    expect(find.text('Before we begin'), findsNothing);
    await tester.tap(find.text('Later'));
    await tester.pump();

    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Player mode'));
    await tester.tap(find.text('Player mode'));
    await _pumpUntilFound(tester, find.text('Set up your own training'));
  });

  testWidgets('invalid coach code shows service error and stays at sign-up',
      (WidgetTester tester) async {
    final FakeMyosApi fake = FakeMyosApi()
      ..validNewAccountCoachInviteCode = 'valid-code-123456';
    await _pumpAuth(tester, fake);
    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));
    await tester.tap(find.byKey(const Key('register_coach_invite_toggle')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('register_username')), 'coach');
    await tester.enterText(
        find.byKey(const Key('register_password')), 'correct-horse-1');
    await tester.enterText(
        find.byKey(const Key('register_confirm')), 'correct-horse-1');
    await tester.enterText(find.byKey(const Key('register_coach_invite_code')),
        'wrong-code-123456');
    await tester.tap(find.byKey(const Key('register_submit')));
    await _pumpUntilFound(tester,
        find.text("This coach invite code isn't valid for this username"));
    expect(find.byKey(const Key('register_username')), findsOneWidget);
    expect(find.byKey(const Key('recovery_email')), findsNothing);
  });

  testWidgets('the optional recovery flow shows errors and verifies an address',
      (WidgetTester tester) async {
    final FakeMyosApi fake = FakeMyosApi();
    await _pumpAuth(tester, fake);
    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));
    await tester.enterText(find.byKey(const Key('register_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('register_password')), 'correct-horse-1');
    await tester.enterText(
        find.byKey(const Key('register_confirm')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('register_submit')));
    await _pumpUntilFound(tester, find.text('Verify your recovery email'));
    await tester.tap(find.text('Verify now'));
    await _pumpUntilFound(tester, find.text('Recovery email'));

    await tester.enterText(
        find.byKey(const Key('recovery_email')), 'not-an-email');
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(tester, find.text('Enter a valid email address.'));

    await tester.enterText(
        find.byKey(const Key('recovery_email')), 'alice@example.com');
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('recovery_verification_code')));
    await tester.enterText(find.byKey(const Key('recovery_verification_code')),
        fake.currentRecoveryEmailCode!);
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(tester, find.text('Your answers and privacy'));
    expect(fake.recoveryEmail, 'alice@example.com');
  });

  testWidgets('the reminder opens code entry and an unverified email can be corrected',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake()..recoveryEmailVerified = false;
    await _pumpAuth(tester, fake);
    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('login_submit')));

    await _pumpUntilFound(tester, find.text('Verify your recovery email'));
    await tester.tap(find.text('Verify now'));
    await _pumpUntilFound(
        tester, find.byKey(const Key('recovery_verification_code')));
    expect(fake.recoveryEmailCodesSent, 0);
    expect(find.text('Send code'), findsOneWidget);
    await tester.tap(find.text('Change email'));
    await _pumpUntilFound(tester, find.byKey(const Key('recovery_email')));
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('recovery_email')))
          .controller
          ?.text,
      'alice@example.com',
    );

    await tester.enterText(
        find.byKey(const Key('recovery_email')), 'corrected@example.com');
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('recovery_verification_code')));

    expect(fake.recoveryEmail, 'corrected@example.com');
    expect(fake.recoveryEmailVerified, isFalse);
    expect(fake.recoveryEmailCodesSent, 1);
  });

  testWidgets('verification code sends only after the person requests it',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake()..recoveryEmailVerified = false;
    await _pumpAuth(tester, fake);
    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('login_submit')));

    await _pumpUntilFound(tester, find.text('Verify your recovery email'));
    await tester.tap(find.text('Verify now'));
    await _pumpUntilFound(
        tester, find.byKey(const Key('recovery_verification_code')));
    expect(fake.recoveryEmailCodesSent, 0);
    await tester.tap(find.text('Send code'));
    await _pumpUntilFound(tester, find.text('We sent a code to your recovery email.'));
    expect(fake.recoveryEmailCodesSent, 1);
    expect(find.text('Resend code'), findsOneWidget);

    await tester.tap(find.text('Resend code'));
    await _pumpUntilFound(tester, find.text('We sent a code to your recovery email.'));
    expect(fake.recoveryEmailCodesSent, 2);
  });

  testWidgets('the verification screen leaves after the email becomes verified',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake()..recoveryEmailVerified = false;
    await _pumpAuth(tester, fake);
    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('login_submit')));
    await _pumpUntilFound(tester, find.text('Verify your recovery email'));
    await tester.tap(find.text('Verify now'));
    await _pumpUntilFound(
        tester, find.byKey(const Key('recovery_verification_code')));
    expect(fake.recoveryEmailCodesSent, 0);

    fake.recoveryEmailVerified = true;
    await tester.tap(find.text('Change email'));
    await _pumpUntilFound(tester, find.byKey(const Key('recovery_email')));
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await tester.pumpAndSettle();

    expect(fake.recoveryEmailVerified, isTrue);
    expect(fake.recoveryEmailCodesSent, 0);
    expect(_routerOf(tester).routeInformationProvider.value.uri.path, homePath);
    expect(find.byKey(const Key('recovery_verification_code')), findsNothing);
  });

  testWidgets('forgot-password still returns the constant confirmation',
      (WidgetTester tester) async {
    final FakeMyosApi fake = FakeMyosApi();
    await _pumpAuth(tester, fake);

    await tester.tap(find.text('Forgot password?'));
    await _pumpUntilFound(tester, find.text('Send reset link'));
    await tester.enterText(
        find.byKey(const Key('forgot_email')), 'alice@example.com');
    await tester.tap(find.byKey(const Key('forgot_submit')));

    await _pumpUntilFound(tester, find.text(fake.resetConfirmation));
    expect(
        find.text("Didn't get an email? Check the address,"), findsOneWidget);
    expect(find.text('or log in and add a recovery email in Settings.'),
        findsOneWidget);
    expect(find.text('sign up'), findsOneWidget);
    expect(fake.forgotRequests, 1);

    await tester.tap(find.byKey(const Key('forgot_signup')));
    await _pumpUntilFound(tester, find.text('Create account'));
  });

  testWidgets('reset-password still completes and routes to login',
      (WidgetTester tester) async {
    final FakeMyosApi fake = FakeMyosApi()..validResetToken = 'reset-code-1';
    await _pumpAuth(tester, fake);

    _routerOf(tester).go('$resetPasswordPath?token=reset-code-1');
    await _pumpUntilFound(tester, find.text('Set new password'));
    await tester.enterText(
        find.byKey(const Key('reset_password')), 'new-horse-123');
    await tester.enterText(
        find.byKey(const Key('reset_confirm')), 'new-horse-123');
    await tester.tap(find.byKey(const Key('reset_submit')));

    await _pumpUntilFound(
        tester, find.text('Password changed. Sign in with your new password.'));
  });

  testWidgets('password visibility toggle flips obscure and its label',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    await _pumpAuth(tester, fake);

    EditableText passwordField() => tester.widget<EditableText>(find.descendant(
          of: find.byKey(const Key('login_password')),
          matching: find.byType(EditableText),
        ));
    expect(passwordField().obscureText, isTrue);
    expect(find.byTooltip('Show password'), findsOneWidget);

    await tester.tap(find.byKey(const Key('login_password_toggle')));
    await tester.pump();

    expect(passwordField().obscureText, isFalse);
    expect(find.byTooltip('Hide password'), findsOneWidget);
  });

  testWidgets('focus traversal next then done submits the login',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    final ProviderContainer container = await _pumpAuth(tester, fake);

    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.testTextInput.receiveAction(TextInputAction.next);
    await tester.pump();

    FocusNode focused() => tester
        .widget<EditableText>(find.descendant(
          of: find.byKey(const Key('login_password')),
          matching: find.byType(EditableText),
        ))
        .focusNode;
    expect(focused().hasFocus, isTrue);

    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.testTextInput.receiveAction(TextInputAction.done);

    await _pumpUntilFound(tester, find.text('Home'));
    expect(container.read(authControllerProvider).status,
        AuthStatus.authenticated);
  });

  testWidgets('meets 48dp touch targets and labelled password toggle',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    await _pumpAuth(tester, fake);

    final Size toggle =
        tester.getSize(find.byKey(const Key('login_password_toggle')));
    expect(toggle.width, greaterThanOrEqualTo(48));
    expect(toggle.height, greaterThanOrEqualTo(48));
    final Size submit = tester.getSize(find.byKey(const Key('login_submit')));
    expect(submit.height, greaterThanOrEqualTo(48));

    expect(
      find.byWidgetPredicate(
          (Widget w) => w is Semantics && w.properties.label == 'MYOS'),
      findsWidgets,
      reason: 'the brand lockup keeps its MYOS semantics label',
    );
  });

  for (final String screen in <String>['login', 'register']) {
    testWidgets('$screen brand lockup is horizontally centred at 360x640',
        (WidgetTester tester) async {
      final FakeMyosApi fake = _loginFake();
      await _pumpAuth(tester, fake, size: const Size(360, 640));
      if (screen == 'register') {
        await tester.tap(find.text('Create an account'));
        await _pumpUntilFound(tester, find.text('Create account'));
      }
      // Let the route transition settle so only the destination AuthScaffold
      // remains mounted and it is not measured mid-slide.
      for (int i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      final double screenCentre =
          tester.view.physicalSize.width / tester.view.devicePixelRatio / 2;
      final Finder hero = find.descendant(
        of: find.byType(AuthScaffold),
        matching: find.byType(MyosBrandLockup),
      );
      expect(tester.getCenter(hero).dx, closeTo(screenCentre, 0.5));
    });
  }

  testWidgets(
      'login keeps both fields and the CTA visible with the keyboard open',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    await _pumpAuth(tester, fake, size: const Size(360, 640));

    await tester.tap(find.byKey(const Key('login_username')));
    await tester.pump();
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.resetViewInsets);
    await tester.pump(const Duration(milliseconds: 200));

    expect(tester.takeException(), isNull);
    expect(
        find.byKey(const Key('login_username')).hitTestable(), findsOneWidget);
    expect(
        find.byKey(const Key('login_password')).hitTestable(), findsOneWidget);
    expect(find.byKey(const Key('login_submit')).hitTestable(), findsOneWidget);
    // The tertiary links move into the scroll body while the keyboard is open.
    expect(find.text('Create an account'), findsOneWidget);
  });

  testWidgets(
      'opening the keyboard keeps the focused field alive with Google present',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    final FakeGoogleAuthGateway google =
        FakeGoogleAuthGateway(buttonStyle: GoogleSignInButtonStyle.webRendered);
    await _pumpAuth(
      tester,
      fake,
      size: const Size(360, 640),
      extraOverrides: <Override>[
        googleAuthGatewayProvider.overrideWithValue(google),
      ],
    );
    final Finder editable = find.descendant(
        of: find.byKey(const Key('login_username')),
        matching: find.byType(EditableText));

    await tester.tap(find.byKey(const Key('login_username')));
    await tester.pump();
    final State<EditableText> before = tester.state(editable);
    final int buttonBuildsBeforeKeyboard = google.webButtonBuildCalls;
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.resetViewInsets);
    await tester.pump(const Duration(milliseconds: 200));

    // The hero dropping out on short screens must not rebuild the fields: a
    // recreated field loses focus, which closes the keyboard, which brings the
    // hero back — an open/close loop on mobile Safari.
    expect(tester.state<State<EditableText>>(editable), same(before));
    expect(tester.widget<EditableText>(editable).focusNode.hasFocus, isTrue);
    expect(find.byKey(const Key('fake_google_web_button')), findsOneWidget);
    expect(google.webButtonBuildCalls, buttonBuildsBeforeKeyboard);
  });

  testWidgets('on a desktop window the sign-in form keeps a phone-width column',
      (WidgetTester tester) async {
    await _pumpAuth(tester, _loginFake(), size: const Size(1280, 800));

    final Rect field = tester.getRect(find.byKey(const Key('login_username')));
    expect(field.width, lessThanOrEqualTo(MyosLayout.playerColumnMaxWidth));
    // Inside the column centred in the 1280 window, not stretched across it.
    const double half = MyosLayout.playerColumnMaxWidth / 2;
    expect(field.left, greaterThanOrEqualTo(640 - half));
    expect(field.right, lessThanOrEqualTo(640 + half));
  });

  testWidgets(
      'web Google button is centred and capped at the configured maximum',
      (WidgetTester tester) async {
    final FakeGoogleAuthGateway google =
        FakeGoogleAuthGateway(buttonStyle: GoogleSignInButtonStyle.webRendered);
    await _pumpAuth(
      tester,
      _loginFake(),
      size: const Size(1280, 800),
      extraOverrides: <Override>[
        googleAuthGatewayProvider.overrideWithValue(google),
      ],
    );

    final Rect button =
        tester.getRect(find.byKey(const Key('fake_google_web_button')));
    final Rect slot = tester.getRect(find.byType(GoogleWebSignInButton));
    expect(google.renderedButtonWidth, MyosLayout.googleButtonMaxWidth);
    expect(button.width, MyosLayout.googleButtonMaxWidth);
    expect(button.center.dx, closeTo(slot.center.dx, 0.5));
  });

  testWidgets('remember-me consent is a tappable 48dp row with state',
      (WidgetTester tester) async {
    final FakeMyosApi fake = _loginFake();
    await _pumpAuth(tester, fake);

    Finder consent() => find.byWidgetPredicate((Widget w) =>
        w is Semantics && w.properties.label == 'Keep me signed in');
    expect(consent(), findsOneWidget);
    expect(tester.widget<Semantics>(consent()).properties.checked, isFalse);
    expect(tester.getSize(find.byType(AuthConsentRow)).height,
        greaterThanOrEqualTo(48));

    await tester.tap(find.text('Keep me signed in'));
    await tester.pump();
    expect(tester.widget<Semantics>(consent()).properties.checked, isTrue);
  });

  for (final String screen in <String>['login', 'register', 'recovery']) {
    testWidgets('$screen has no overflow at 360x640 with the keyboard open',
        (WidgetTester tester) async {
      final FakeMyosApi fake = _loginFake();
      await _pumpAuth(tester, fake, size: const Size(360, 640));
      if (screen == 'register') {
        await tester.tap(find.text('Create an account'));
        await _pumpUntilFound(tester, find.text('Create account'));
      }
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      addTearDown(tester.view.resetViewInsets);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });

    testWidgets('$screen has no overflow at 360x640 and 2.0x text',
        (WidgetTester tester) async {
      final FakeMyosApi fake = _loginFake();
      await _pumpAuth(tester, fake, size: const Size(360, 640));
      if (screen == 'register') {
        await tester.tap(find.text('Create an account'));
        await _pumpUntilFound(tester, find.text('Create account'));
      }
      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('dark theme renders the auth composition',
      (WidgetTester tester) async {
    await _setSize(tester, const Size(393, 852));
    final FakeMyosApi fake = _loginFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          themeModeStoreProvider
              .overrideWithValue(InMemoryThemeModeStore(ThemeMode.dark)),
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
        child: const MyosApp(),
      ),
    );
    await _pumpUntilFound(tester, find.text('Log in'));
    expect(
      MyosTheme.of(tester.element(find.byKey(const Key('login_submit'))))
          .isDark,
      isTrue,
    );
    expect(tester.takeException(), isNull);
  });
}
