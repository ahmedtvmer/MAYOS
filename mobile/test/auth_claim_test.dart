import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

/// Coverage for the "Claim imported account" path (#42): the wire contract of
/// `POST /auth/claim`, signing in on success, the generic 401, the weak-password
/// field error, and the login 403 `claim_required` hand-off with a prefilled
/// username.

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

Future<ProviderContainer> _pumpAuth(WidgetTester tester, FakeMayosApi fake) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tester.pumpWidget(authApp(fake, tokens));
  await _pumpUntilFound(tester, find.text('Log in'));
  return ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
}

/// An importable account whose claim code is `owner-code-1`.
FakeMayosApi _importedFake() {
  return FakeMayosApi()
    ..importedUsernames.add('imported')
    ..claimCodes['imported'] = 'owner-code-1'
    ..recoveryEmail = 'imported@example.com'
    ..profileExists = true;
}

Future<void> _openClaimScreen(WidgetTester tester) async {
  await tester.tap(find.text('Claim imported account'));
  await _pumpUntilFound(tester, find.byKey(const Key('claim_username')));
}

Future<void> _fillClaim(
  WidgetTester tester, {
  String username = 'imported',
  String code = 'owner-code-1',
  String password = 'new-horse-1',
  String? confirm,
}) async {
  await tester.enterText(find.byKey(const Key('claim_username')), username);
  await tester.enterText(find.byKey(const Key('claim_code')), code);
  await tester.enterText(find.byKey(const Key('claim_password')), password);
  await tester.enterText(
      find.byKey(const Key('claim_confirm')), confirm ?? password);
}

void main() {
  test('claim posts the wire contract and signs in with the issued token',
      () async {
    final FakeMayosApi fake = _importedFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final ProviderContainer container = authContainerFor(fake, tokens);
    addTearDown(container.dispose);

    final AuthController auth = container.read(authControllerProvider.notifier);
    await auth.initialize();
    await auth.claim(
      username: 'imported',
      claimCode: 'owner-code-1',
      password: 'new-horse-1',
    );

    final AuthState state = container.read(authControllerProvider);
    expect(state.status, AuthStatus.authenticated);
    final String? token = await tokens.read();
    expect(token, isNotNull);

    final FakeRequest claimRequest = fake.adapter.requests
        .firstWhere((FakeRequest r) => r.path == '/auth/claim');
    expect(claimRequest.method, 'POST');
    expect(claimRequest.body['trainee_id'], 'imported');
    expect(claimRequest.body['claim_code'], 'owner-code-1');
    expect(claimRequest.body['password'], 'new-horse-1');

    final FakeRequest meRequest = fake.adapter.requests
        .firstWhere((FakeRequest r) => r.path == '/auth/me');
    expect(meRequest.headers['Authorization'], 'Bearer $token');
  });

  test('a rejected claim throws the generic 401 and leaves no session',
      () async {
    final FakeMayosApi fake = _importedFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final ProviderContainer container = authContainerFor(fake, tokens);
    addTearDown(container.dispose);

    final AuthController auth = container.read(authControllerProvider.notifier);
    await auth.initialize();

    await expectLater(
      auth.claim(
        username: 'imported',
        claimCode: 'wrong-code',
        password: 'new-horse-1',
      ),
      throwsA(isA<ApiException>()
          .having((ApiException e) => e.statusCode, 'statusCode', 401)
          .having((ApiException e) => e.message, 'message',
              'Invalid or expired claim code.')),
    );
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);
    expect(await tokens.read(), isNull);
  });

  testWidgets('claiming signs in and routes like a successful login',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _importedFake();
    final ProviderContainer container = await _pumpAuth(tester, fake);

    await _openClaimScreen(tester);
    await _fillClaim(tester);
    await tester.tap(find.byKey(const Key('claim_submit')));

    await _pumpUntilFound(tester, find.text('Home'));
    expect(container.read(authControllerProvider).status,
        AuthStatus.authenticated);
  });

  testWidgets('a wrong claim code shows the generic error and stays put',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _importedFake();
    final ProviderContainer container = await _pumpAuth(tester, fake);

    await _openClaimScreen(tester);
    await _fillClaim(tester, code: 'wrong-code');
    await tester.tap(find.byKey(const Key('claim_submit')));

    await _pumpUntilFound(tester, find.text('Invalid or expired claim code.'));
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);
    expect(find.byKey(const Key('claim_username')), findsOneWidget);
  });

  testWidgets('a short password is rejected on the field before any call',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _importedFake();
    await _pumpAuth(tester, fake);

    await _openClaimScreen(tester);
    await _fillClaim(tester, password: 'short', confirm: 'short');
    await tester.tap(find.byKey(const Key('claim_submit')));
    await tester.pump();

    expect(find.text('Use at least 8 characters.'), findsOneWidget);
    expect(
      fake.adapter.requests.any((FakeRequest r) => r.path == '/auth/claim'),
      isFalse,
    );
  });

  testWidgets('a service weak-password refusal is shown on the field',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _importedFake()..claimRejectsWeakPassword = true;
    final ProviderContainer container = await _pumpAuth(tester, fake);

    await _openClaimScreen(tester);
    await _fillClaim(tester);
    await tester.tap(find.byKey(const Key('claim_submit')));

    await _pumpUntilFound(
        tester, find.text('Password does not meet the requirements.'));
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);
  });

  testWidgets('claim_required login offers claim with the username prefilled',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..importedUsernames.add('imported');
    final ProviderContainer container = await _pumpAuth(tester, fake);

    await tester.enterText(
        find.byKey(const Key('login_username')), 'imported');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'anything-1');
    await tester.tap(find.byKey(const Key('login_submit')));

    await _pumpUntilFound(
        tester, find.textContaining('Claim it with the code'));
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);

    await _openClaimScreen(tester);
    final TextField username =
        tester.widget<TextField>(find.byKey(const Key('claim_username')));
    expect(username.controller!.text, 'imported');
  });

  testWidgets('a 403 without the claim_required code is not a claim hand-off',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..loginForbidden = true;
    final ProviderContainer container = await _pumpAuth(tester, fake);

    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('login_password')), 'anything-1');
    await tester.tap(find.byKey(const Key('login_submit')));

    await _pumpUntilFound(tester, find.text('Your account is suspended.'));
    expect(find.textContaining('Claim it with the code'), findsNothing);
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);
  });
}
