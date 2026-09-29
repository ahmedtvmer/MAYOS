import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_button.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/features/player/auth/google_auth_gateway.dart';
import 'package:mayos_mobile/src/features/player/auth/google_sign_in_button.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
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
}) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(authApp(
    fake,
    InMemoryTokenStore(),
    extraOverrides: <Override>[
      if (google != null)
        googleAuthGatewayProvider.overrideWithValue(google),
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

void main() {
  testWidgets('the Google button is hidden without the dart-define',
      (WidgetTester tester) async {
    await _pumpAuth(tester, FakeMayosApi());

    expect(find.text('Continue with Google'), findsNothing);
    expect(find.byType(AuthOrDivider), findsNothing);
    expect(find.byKey(const Key('login_username')), findsOneWidget);
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

  testWidgets('a first Google sign-in opens the picker prefilled with the suggestion',
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

  testWidgets('a taken username shows a live error and blocks the submit',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..googleTakenUsernames.add('alice');
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

  testWidgets('submitting the picked username signs in and keeps the ADR 007 gate',
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

  testWidgets('leaving the picker creates nothing and clears the Google SDK state',
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
}
