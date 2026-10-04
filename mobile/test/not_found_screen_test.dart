import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/plan/plan_screen.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

/// Pumps frames until [finder] matches, avoiding `pumpAndSettle` (the app can
/// keep scheduling frames while an indicator is on screen).
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
  return fake;
}

void main() {
  testWidgets('an unknown path shows the not-found page',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');

    await tester.pumpWidget(authApp(fake, tokens));
    await _pumpUntilFound(tester, find.text('Home'));

    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    container.read(routerProvider).go('/no-such-page');
    await _pumpUntilFound(tester, find.text('Page not found'));

    expect(find.text('Page not found'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Go to home'), findsOneWidget);

    // The way out asks nothing of the rules: the router places the user.
    await tester.tap(find.widgetWithText(FilledButton, 'Go to home'));
    await _pumpUntilFound(tester, find.text('Program'));
    expect(find.text('Page not found'), findsNothing);
  });

  testWidgets('a cold deep link survives the splash hold in the real router',
      (WidgetTester tester) async {
    // The browser address (or an app link) at launch.
    tester.binding.platformDispatcher.defaultRouteNameTestValue = planPath;
    addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue);
    final FakeMayosApi fake = _signedInFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');

    await tester.pumpWidget(authApp(fake, tokens));
    await _pumpUntilFound(tester, find.byType(PlanScreen));

    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    expect(
        container
            .read(routerProvider)
            .routerDelegate
            .currentConfiguration
            .uri
            .path,
        planPath);
    expect(find.byType(PlanScreen), findsOneWidget);
  });

  testWidgets('a signed-out cold deep link survives password login',
      (WidgetTester tester) async {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = planPath;
    addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue);
    final FakeMayosApi fake = _signedInFake()
      ..passwords['alice'] = 'correct-horse-1';
    final InMemoryTokenStore tokens = InMemoryTokenStore();

    await tester.pumpWidget(authApp(fake, tokens));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));

    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    final Uri loginUri =
        container.read(routerProvider).routerDelegate.currentConfiguration.uri;
    expect(loginUri.path, loginPath);
    expect(loginUri.queryParameters['from'], planPath);

    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('login_submit')));
    await _pumpUntilFound(tester, find.byType(PlanScreen));

    expect(find.byType(PlanScreen), findsOneWidget);
    expect(
      container
          .read(routerProvider)
          .routerDelegate
          .currentConfiguration
          .uri
          .path,
      planPath,
    );
  });

  testWidgets('register and return to login keep the requested page',
      (WidgetTester tester) async {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = planPath;
    addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue);
    await tester.pumpWidget(authApp(FakeMayosApi(), InMemoryTokenStore()));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));

    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.byKey(const Key('register_username')));
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    Uri currentUri() =>
        container.read(routerProvider).routerDelegate.currentConfiguration.uri;
    expect(currentUri().path, registerPath);
    expect(currentUri().queryParameters['from'], planPath);

    await tester.tap(find.text('I already have an account'));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));
    expect(currentUri().path, loginPath);
    expect(currentUri().queryParameters['from'], planPath);
  });

  testWidgets('the recovery-email gate releases a carried page after saving',
      (WidgetTester tester) async {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = planPath;
    addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue);
    final FakeMayosApi fake = _signedInFake()
      ..passwords['alice'] = 'correct-horse-1'
      ..recoveryEmail = null;
    final InMemoryTokenStore tokens = InMemoryTokenStore();

    await tester.pumpWidget(authApp(fake, tokens));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));
    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('login_submit')));
    await _pumpUntilFound(tester, find.byKey(const Key('recovery_email')));

    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    final Uri recoveryUri =
        container.read(routerProvider).routerDelegate.currentConfiguration.uri;
    expect(recoveryUri.path, recoveryEmailPath);
    expect(recoveryUri.queryParameters['from'], planPath);

    await tester.enterText(
        find.byKey(const Key('recovery_email')), 'alice@example.com');
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('recovery_verification_code')));
    await tester.enterText(find.byKey(const Key('recovery_verification_code')),
        fake.currentRecoveryEmailCode!);
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(tester, find.byType(PlanScreen));

    expect(fake.recoveryEmail, 'alice@example.com');
    expect(find.byType(PlanScreen), findsOneWidget);
  });
}
