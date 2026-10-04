import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/theme/mayos_spacing.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_button.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/features/player/auth/google_auth_gateway.dart';
import 'package:mayos_mobile/src/features/player/auth/google_sign_in_button.dart';
import 'package:mayos_mobile/src/features/player/plan/plan_screen.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_api_adapter.dart';
import 'support/fake_google_auth.dart';
import 'support/fake_mayos_api.dart';

/// Google sign-in and the first-sign-up username picker (#115): the SDK and
/// the service are both faked, so every flow runs offline.

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

Future<ProviderContainer> _pumpAuth(
  WidgetTester tester,
  FakeMayosApi fake, {
  FakeGoogleAuthGateway? google,
  String? initialRoute,
}) async {
  if (initialRoute != null) {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = initialRoute;
    addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue);
  }
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(authApp(
    fake,
    InMemoryTokenStore(),
    extraOverrides: <Override>[
      if (google != null) googleAuthGatewayProvider.overrideWithValue(google),
    ],
  ));
  await _pumpUntilFound(tester, find.text('Log in'));
  return ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
}

/// Drives the login screen into the username picker.
Future<void> _openPicker(WidgetTester tester) async {
  await tester.tap(find.text('Continue with Google'));
  await _pumpUntilFound(
      tester, find.byKey(const Key('google_signup_username')));
}

/// Waits for the debounced availability probe to land.
Future<void> _awaitAvailability(WidgetTester tester) async {
  await _pumpUntilFound(tester, find.text('This username is free.'));
}

/// Lets a route transition finish so the screen being left is unmounted.
Future<void> _settleRoute(WidgetTester tester) async {
  for (int i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

void main() {
  test('SDK event errors do not close the web authentication stream', () async {
    final StreamController<GoogleSignInAuthenticationEvent> source =
        StreamController<GoogleSignInAuthenticationEvent>();
    final GoogleSdkAuthGateway gateway = GoogleSdkAuthGateway(
      authenticationEventSource: source.stream,
    );
    final List<GoogleAuthOutcome> outcomes = <GoogleAuthOutcome>[];
    final StreamSubscription<GoogleAuthOutcome> subscription =
        gateway.authenticationEvents.listen(outcomes.add);

    source.addError(const GoogleSignInException(
        code: GoogleSignInExceptionCode.uiUnavailable));
    source.add(GoogleSignInAuthenticationEventSignIn(
        user: _FakeGoogleAccount('sdk-event-token')));
    source.addError(
        const GoogleSignInException(code: GoogleSignInExceptionCode.canceled));
    await Future<void>.delayed(Duration.zero);

    expect(outcomes, hasLength(3));
    expect(outcomes[0], isA<GoogleAuthFailed>());
    expect(outcomes[1], isA<GoogleAuthIdToken>());
    expect((outcomes[1] as GoogleAuthIdToken).idToken, 'sdk-event-token');
    expect(outcomes[2], isA<GoogleAuthCanceled>());

    await subscription.cancel();
    await source.close();
  });

  testWidgets('the Google button is hidden without the dart-define',
      (WidgetTester tester) async {
    await _pumpAuth(tester, FakeMayosApi());

    expect(find.text('Continue with Google'), findsNothing);
    expect(find.byType(AuthOrDivider), findsNothing);
    expect(find.byKey(const Key('login_username')), findsOneWidget);
  });

  testWidgets('a configured web gateway renders its fixed button slot',
      (WidgetTester tester) async {
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway(
        buttonStyle: GoogleSignInButtonStyle.webRendered);
    await _pumpAuth(tester, FakeMayosApi(), google: google);

    expect(find.byKey(const Key('fake_google_web_button')), findsOneWidget);
    expect(find.byType(AuthOrDivider), findsOneWidget);
    expect(google.authenticateCalls, 0);
  });

  testWidgets('a non-positive fixed web width skips Google configuration',
      (WidgetTester tester) async {
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway(
        buttonStyle: GoogleSignInButtonStyle.webRendered);
    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          googleAuthGatewayProvider.overrideWithValue(google),
        ],
        child: MaterialApp(
          home: SizedBox(
            child: GoogleWebSignInButton(
              fixedWidth: 0,
              onOutcome: (_) async {},
            ),
          ),
        ),
      ),
    );

    expect(google.webButtonBuildCalls, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a web ID token signs in and keeps the recovery-email gate',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..profileExists = true;
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway(
        buttonStyle: GoogleSignInButtonStyle.webRendered);
    final ProviderContainer container = await _pumpAuth(
      tester,
      fake,
      google: google,
      initialRoute: lifterPlanPath,
    );

    google.emitAuthenticationOutcome(
        GoogleAuthIdToken(fake.googleLinkedIdToken));
    await _pumpUntilFound(tester, find.byKey(const Key('recovery_email')));

    expect(container.read(authControllerProvider).status,
        AuthStatus.authenticated);
    expect(fake.googleSignInRequests, 1);
    expect(google.authenticateCalls, 0);
    expect(
      container
          .read(routerProvider)
          .routerDelegate
          .currentConfiguration
          .uri
          .queryParameters['from'],
      lifterPlanPath,
    );
  });

  testWidgets('a second web ID token is ignored while sign-in is busy',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'alice@example.com';
    final Completer<void> gate = Completer<void>();
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path == '/auth/google') {
        await gate.future;
      }
    };
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway(
        buttonStyle: GoogleSignInButtonStyle.webRendered);
    await _pumpAuth(tester, fake, google: google);

    google.emitAuthenticationOutcome(const GoogleAuthIdToken('first-token'));
    google.emitAuthenticationOutcome(const GoogleAuthIdToken('second-token'));
    for (int i = 0; i < 20 &&
        !fake.adapter.requests
            .any((FakeRequest r) => r.path == '/auth/google'); i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }
    expect(
      fake.adapter.requests.where((FakeRequest r) => r.path == '/auth/google'),
      hasLength(1),
    );

    gate.complete();
    await _pumpUntilFound(tester, find.byKey(const Key('recovery_email')));
    expect(fake.googleSignInRequests, 1);
  });

  testWidgets('a web signup ticket opens the picker with its carried location',
      (WidgetTester tester) async {
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway(
        buttonStyle: GoogleSignInButtonStyle.webRendered);
    final ProviderContainer container = await _pumpAuth(
      tester,
      FakeMayosApi(),
      google: google,
      initialRoute: lifterPlanPath,
    );

    google.emitAuthenticationOutcome(
        const GoogleAuthIdToken('unlinked-web-google-token'));
    await _pumpUntilFound(
        tester, find.byKey(const Key('google_signup_username')));

    final GoRouter router = container.read(routerProvider);
    expect(router.routerDelegate.currentConfiguration.uri.path, googleSignupPath);
    expect(
      router.routerDelegate.currentConfiguration.uri.queryParameters['from'],
      lifterPlanPath,
    );
    expect(google.authenticateCalls, 0);
  });

  testWidgets('a linked Google subject signs in like password login',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..recoveryEmail = 'alice@example.com'
      ..profileExists = true;
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway()
      ..idToken = 'google-linked-id-token';
    final ProviderContainer container =
        await _pumpAuth(tester, fake, google: google);

    expect(find.byKey(const Key('login_google')), findsOneWidget);
    expect(find.text('Continue with Google'), findsOneWidget);
    expect(find.byType(AuthOrDivider), findsOneWidget);

    await tester.tap(find.text('Continue with Google'));
    await _pumpUntilFound(tester, find.text('Home'));

    expect(container.read(authControllerProvider).status,
        AuthStatus.authenticated);
    expect(fake.googleSignInRequests, 1);
    expect(fake.googleCompleteRequests, 0);
    expect(google.authenticateCalls, 1);
  });

  testWidgets('Google signup and sign-in keep a cold deep link',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'alice@example.com';
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    final ProviderContainer container = await _pumpAuth(
      tester,
      fake,
      google: google,
      initialRoute: lifterPlanPath,
    );

    await _openPicker(tester);
    final GoRouter router = container.read(routerProvider);
    expect(
        router.routerDelegate.currentConfiguration.uri.path, googleSignupPath);
    expect(
      router.routerDelegate.currentConfiguration.uri.queryParameters['from'],
      lifterPlanPath,
    );

    await tester.tap(find.byKey(const Key('google_signup_cancel')));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));
    await _settleRoute(tester);
    expect(router.routerDelegate.currentConfiguration.uri.path, loginPath);
    expect(
      router.routerDelegate.currentConfiguration.uri.queryParameters['from'],
      lifterPlanPath,
    );

    google.idToken = fake.googleLinkedIdToken;
    await tester.tap(find.text('Continue with Google'));
    await _pumpUntilFound(tester, find.byType(PlanScreen));
    expect(find.byType(PlanScreen), findsOneWidget);
    expect(router.routerDelegate.currentConfiguration.uri.path, lifterPlanPath);
  });

  testWidgets(
      'a first Google sign-in opens the picker prefilled with the suggestion',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);

    final TextField field = tester
        .widget<TextField>(find.byKey(const Key('google_signup_username')));
    expect(field.controller!.text, 'alice');
    expect(find.text('Create account'), findsOneWidget);
    expect(
      find.byKey(const Key('google_signup_login_link')),
      findsOneWidget,
    );
    expect(fake.googleCompleteRequests, 0);
  });

  testWidgets('a recovery-email hint offers a login route',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..googleExistingAccountHint = true;
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    await _pumpAuth(tester, fake, google: google);

    await tester.tap(find.text('Continue with Google'));
    await _pumpUntilFound(
        tester, find.byKey(const Key('google_existing_account_login')));

    expect(
      find.text('You already have a MAYOS account for this email.'),
      findsOneWidget,
    );
    expect(
      find.text('Log in with your password, then connect Google in Settings.'),
      findsOneWidget,
    );
    expect(
      tester
          .widget<MayosButton>(
              find.byKey(const Key('google_existing_account_login')))
          .variant,
      MayosButtonVariant.primary,
    );
    expect(find.byKey(const Key('google_signup_username')), findsNothing);
    expect(fake.googleCompleteRequests, 0);

    await tester.tap(find.byKey(const Key('google_existing_account_login')));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));
    await _settleRoute(tester);

    expect(google.clearSdkStateCalls, 1);
    expect(fake.googleCompleteRequests, 0);
  });

  testWidgets(
      'system back from the recovery-email hint creates nothing and clears Google state',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..googleExistingAccountHint = true;
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    await _pumpAuth(tester, fake, google: google);

    await tester.tap(find.text('Continue with Google'));
    await _pumpUntilFound(tester,
        find.byKey(const Key('google_existing_account_login')));
    await tester.binding.handlePopRoute();
    await _settleRoute(tester);

    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(find.byKey(const Key('google_signup_username')), findsNothing);
    expect(fake.googleCompleteRequests, 0);
    expect(google.clearSdkStateCalls, 1);
  });

  testWidgets('the recovery-email hint can continue to the picker and leave empty',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..googleExistingAccountHint = true;
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    await _pumpAuth(tester, fake, google: google);

    await tester.tap(find.text('Continue with Google'));
    await _pumpUntilFound(tester,
        find.byKey(const Key('google_existing_account_create_separate')));
    expect(
      tester
          .widget<MayosButton>(find.byKey(
              const Key('google_existing_account_create_separate')))
          .variant,
      MayosButtonVariant.secondary,
    );
    await tester.tap(
        find.byKey(const Key('google_existing_account_create_separate')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('google_signup_username')));
    await _awaitAvailability(tester);

    expect(find.text('Create account'), findsOneWidget);
    expect(fake.usernameAvailableRequests, greaterThan(0));
    expect(fake.googleCompleteRequests, 0);

    await tester.tap(find.byKey(const Key('google_signup_cancel')));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));
    await _settleRoute(tester);

    expect(google.clearSdkStateCalls, 1);
    expect(fake.googleCompleteRequests, 0);
  });

  testWidgets('a taken username shows a live error and blocks the submit',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..googleTakenUsernames.add('alice');
    await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);
    await _pumpUntilFound(tester, find.text('That username is taken.'));

    expect(fake.usernameAvailableRequests, greaterThan(0));
    expect(
      tester
          .widget<MayosButton>(find.byKey(const Key('google_signup_submit')))
          .onPressed,
      isNull,
    );

    await tester.enterText(
        find.byKey(const Key('google_signup_username')), 'alice2');
    await _pumpUntilFound(tester, find.text('This username is free.'));
    expect(
      tester
          .widget<MayosButton>(find.byKey(const Key('google_signup_submit')))
          .onPressed,
      isNotNull,
    );
  });

  testWidgets('an expired signup ticket returns to sign-in with an explanation',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    await _pumpAuth(tester, fake, google: google);

    await _openPicker(tester);
    await _awaitAvailability(tester);
    fake.googleTicketExpired = true;

    await tester.tap(find.byKey(const Key('google_signup_submit')));
    await _pumpUntilFound(
        tester, find.text('Your Google sign-up expired. Please try again.'));

    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(fake.googleCompleteRequests, 1);
    expect(fake.googleCompletedUsernames, isEmpty);
    expect(google.clearSdkStateCalls, 1);
  });

  testWidgets('an invalid username never reaches the availability check',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);
    final int probed = fake.usernameAvailableRequests;

    await tester.enterText(
        find.byKey(const Key('google_signup_username')), 'ab');
    await tester.pump(const Duration(milliseconds: 600));

    expect(fake.usernameAvailableRequests, probed);
    expect(find.textContaining('3–30 characters'), findsOneWidget);
    expect(
      tester
          .widget<MayosButton>(find.byKey(const Key('google_signup_submit')))
          .onPressed,
      isNull,
    );
    expect(fake.googleCompleteRequests, 0);
  });

  testWidgets(
      'submitting the picked username signs in and keeps the ADR 007 gate',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final ProviderContainer container =
        await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);
    await _awaitAvailability(tester);

    await tester.tap(find.byKey(const Key('google_signup_submit')));
    await _pumpUntilFound(tester, find.text('Recovery email'));

    expect(fake.googleCompletedUsernames, <String>['alice']);
    expect(container.read(authControllerProvider).status,
        AuthStatus.authenticated);
    expect(find.byKey(const Key('recovery_email')), findsOneWidget);
  });

  testWidgets('verified Google signup skips the recovery-email gate',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..googleCompleteRecoveryEmailVerified = true;
    final ProviderContainer container =
        await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);
    await _awaitAvailability(tester);
    await tester.tap(find.byKey(const Key('google_signup_submit')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('onboarding_disclosure_continue')));

    expect(
      container.read(authControllerProvider).session?.account.recoveryEmailVerified,
      isTrue,
    );
    expect(find.byKey(const Key('recovery_email')), findsNothing);
    expect(fake.googleCompletedIdTokens, <String>['fake-google-id-token']);
  });

  testWidgets(
      'leaving the picker creates nothing and clears the Google SDK state',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    await _pumpAuth(tester, fake, google: google);

    await _openPicker(tester);
    await tester.tap(find.byKey(const Key('google_signup_cancel')));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));

    expect(fake.googleCompleteRequests, 0);
    expect(fake.googleSignInRequests, 1);
    expect(google.clearSdkStateCalls, 1);
  });

  testWidgets('a cancelled Google sheet leaves the sign-in screen alone',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway()
      ..idToken = null;
    await _pumpAuth(tester, fake, google: google);

    await tester.tap(find.text('Continue with Google'));
    await tester.pump();

    expect(fake.googleSignInRequests, 0);
    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(find.byKey(const Key('google_signup_username')), findsNothing);
  });

  testWidgets('a Google SDK failure is explained on the sign-in screen',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway()
      ..scriptedOutcome = const GoogleAuthFailed(
          'Google sign-in is not configured for this build.');
    await _pumpAuth(tester, fake, google: google);

    await tester.tap(find.text('Continue with Google'));
    await _pumpUntilFound(
        tester, find.text('Google sign-in is not configured for this build.'));

    expect(fake.googleSignInRequests, 0);
    expect(find.byKey(const Key('login_username')), findsOneWidget);
  });

  testWidgets('a slow answer about an older username never relabels the field',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..googleTakenUsernames.add('alice');
    final Completer<void> gate = Completer<void>();
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path == '/auth/username-available') {
        await gate.future;
      }
    };
    await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);
    // Let the prefilled "alice" probe go out and stall on the gate.
    await tester.pump(const Duration(milliseconds: 450));
    expect(find.text('Checking availability…'), findsOneWidget);

    // Move on before it answers; "bob" is free, "alice" is not.
    await tester.enterText(
        find.byKey(const Key('google_signup_username')), 'bob');
    await tester.pump(const Duration(milliseconds: 450));
    expect(find.text('Checking availability…'), findsOneWidget);

    gate.complete();
    await _pumpUntilFound(tester, find.text('This username is free.'));

    expect(fake.usernameAvailableRequests, 2);
    expect(find.text('This username is free.'), findsOneWidget);
    expect(find.text('That username is taken.'), findsNothing);
  });

  testWidgets('logout signs the Google SDK out', (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..recoveryEmail = 'alice@example.com'
      ..profileExists = true;
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway()
      ..idToken = 'google-linked-id-token';
    final ProviderContainer container =
        await _pumpAuth(tester, fake, google: google);

    await tester.tap(find.text('Continue with Google'));
    await _pumpUntilFound(tester, find.text('Home'));
    expect(google.clearSdkStateCalls, 0);

    // The request chain runs on the test's fake clock, so drive frames while
    // the logout is in flight.
    final Future<void> logout =
        container.read(authControllerProvider.notifier).logout();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await logout;

    expect(google.clearSdkStateCalls, 1);
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);
  });

  testWidgets(
      'a username taken between the check and the submit is an inline error',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);
    await _awaitAvailability(tester);
    fake.googleTakenUsernames.add('alice');

    await tester.tap(find.byKey(const Key('google_signup_submit')));
    await _pumpUntilFound(tester, find.text('That username is taken.'));

    expect(find.byKey(const Key('google_signup_username')), findsOneWidget);
    expect(fake.googleCompletedUsernames, isEmpty);
    expect(
      tester
          .widget<MayosButton>(find.byKey(const Key('google_signup_submit')))
          .onPressed,
      isNull,
    );
  });

  testWidgets('a 409 for an already-linked Google account goes back to sign-in',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..googleCompleteAlreadyLinked = true;
    await _pumpAuth(tester, fake, google: FakeGoogleAuthGateway());

    await _openPicker(tester);
    await _awaitAvailability(tester);

    await tester.tap(find.byKey(const Key('google_signup_submit')));
    await _pumpUntilFound(tester, find.text(kGoogleAlreadyLinkedMessage));

    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(find.byKey(const Key('google_signup_username')), findsNothing);
    expect(fake.googleCompletedUsernames, isEmpty);
  });

  testWidgets('a 401 on the availability check exits like an expired ticket',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..googleTicketExpired = true;
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    await _pumpAuth(tester, fake, google: google);

    await _openPicker(tester);
    await _pumpUntilFound(tester, find.text(kGoogleSignupExpiredMessage));
    await _settleRoute(tester);

    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(find.byKey(const Key('google_signup_username')), findsNothing);
    expect(fake.googleCompleteRequests, 0);
    expect(google.clearSdkStateCalls, 1);
  });

  testWidgets('the register screen offers Continue with Google above the form',
      (WidgetTester tester) async {
    await _pumpAuth(tester, FakeMayosApi(), google: FakeGoogleAuthGateway());

    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.byKey(const Key('register_username')));
    await _settleRoute(tester);

    expect(find.text('Continue with Google'), findsOneWidget);
    expect(find.byKey(const Key('register_google')), findsOneWidget);
    expect(find.byType(AuthOrDivider), findsOneWidget);
    expect(find.byKey(const Key('login_username')), findsNothing);
    final Offset section =
        tester.getTopLeft(find.byKey(const Key('register_google')));
    final Offset field =
        tester.getTopLeft(find.byKey(const Key('register_username')));
    expect(section.dy, lessThan(field.dy));
  });

  testWidgets('the Google button takes Google\u2019s dark theme in a dark app',
      (WidgetTester tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: MayosTheme.dark,
      home: Scaffold(
        body: GoogleSignInButton(onPressed: () async {}),
      ),
    ));

    final Material material = tester.widget<Material>(find.descendant(
      of: find.byType(GoogleSignInButton),
      matching: find.byType(Material),
    ));
    expect(material.color, GoogleBrand.darkFill);
    expect(
      (material.shape! as RoundedRectangleBorder).side.color,
      GoogleBrand.darkStroke,
    );
    expect(find.text('Continue with Google'), findsOneWidget);
    expect(
      tester.widget<Text>(find.text('Continue with Google')).style!.color,
      GoogleBrand.darkLabel,
    );
    expect(
      tester.getSize(find.byType(GoogleSignInButton)).height,
      kMayosMinTapTarget,
    );
  });
}

class _FakeGoogleAccount implements GoogleSignInAccount {
  _FakeGoogleAccount(String idToken)
      : authentication = GoogleSignInAuthentication(idToken: idToken);

  @override
  final GoogleSignInAuthentication authentication;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
