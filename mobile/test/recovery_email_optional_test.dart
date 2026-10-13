import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

Future<void> _pumpSignedIn(
  WidgetTester tester,
  FakeMayosApi fake, {
  InMemoryAppModeStore? modeStore,
}) async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  fake
    ..issuedToken = 'token-alice'
    ..currentUsername = 'alice'
    ..tokenValid = true;
  await tokens.save('token-alice');
  await tester.pumpWidget(authApp(fake, tokens, modeStore: modeStore));
}

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder) async {
  for (int attempt = 0; attempt < 60; attempt++) {
    if (finder.evaluate().isNotEmpty) {
      await tester.pump(const Duration(milliseconds: 100));
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
  final ProviderContainer container = ProviderScope.containerOf(
    tester.element(find.byType(MayosApp)),
    listen: false,
  );
  final GoRouter router = container.read(routerProvider);
  final AuthState auth = container.read(authControllerProvider);
  fail(
      'Timed out waiting for $finder at ${router.routeInformationProvider.value.uri}; '
      'auth=${auth.status}, verified=${auth.session?.account.recoveryEmailVerified}, '
      'overlay=${router.routerDelegate.navigatorKey.currentState?.overlay != null}');
}

GoRouter _router(WidgetTester tester) {
  final ProviderContainer container = ProviderScope.containerOf(
    tester.element(find.byType(MayosApp)),
    listen: false,
  );
  return container.read(routerProvider);
}

void main() {
  testWidgets(
      'account without a recovery email reaches Home and can dismiss the reminder',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = null
      ..recoveryEmailVerified = false;
    await _pumpSignedIn(tester, fake);

    await _pumpUntilFound(tester, find.text('Verify your recovery email'));
    expect(_router(tester).routeInformationProvider.value.uri.path, homePath);
    expect(
      find.text(
        'Your recovery email is not verified. Password recovery needs a verified email address.',
      ),
      findsOneWidget,
    );

    await tester.tap(find.text('Later'));
    await tester.pump();
    _router(tester).go('/no-such-page');
    await _pumpUntilFound(tester, find.text('Page not found'));
    expect(find.text('Verify your recovery email'), findsNothing);
  });

  testWidgets(
      'unverified Coach account lands in Coach mode with Arabic reminder',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..coach = true
      ..displayLanguage = 'ar'
      ..recoveryEmail = null
      ..recoveryEmailVerified = false;
    await _pumpSignedIn(tester, fake);

    await _pumpUntilFound(
        tester, find.text('تحقق من البريد الإلكتروني للاسترداد'));
    expect(
      _router(tester).routeInformationProvider.value.uri.path,
      coachRosterPath,
    );
    expect(
      find.text(
        'لم يتم التحقق من البريد الإلكتروني للاسترداد. يلزم التحقق منه لاستعادة كلمة المرور.',
      ),
      findsOneWidget,
    );
    expect(find.text('لاحقًا'), findsOneWidget);
    expect(find.text('تحقق الآن'), findsOneWidget);
  });

  testWidgets('verified account never sees the launch reminder',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'alice@example.com'
      ..recoveryEmailVerified = true;
    await _pumpSignedIn(tester, fake);

    await _pumpUntilFound(tester, find.text('Home'));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Verify your recovery email'), findsNothing);
  });
}
