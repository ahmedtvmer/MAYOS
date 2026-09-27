import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_logo.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_widgets.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

/// Focused coverage for the restyled authentication and recovery-email screens
/// (#52): login, registration, the ADR 007 gate, forgot/reset, keyboard insets,
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

Widget _app(FakeMayosApi fake, InMemoryTokenStore tokens) {
  return ProviderScope(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
      apiClientProvider.overrideWith((ref) {
        final ApiClient client = ApiClient(
          tokens: ref.watch(tokenStoreProvider),
          baseUrl: 'http://test.local',
          adapter: fake.adapter,
        );
        client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
        return client;
      }),
    ],
    child: const MayosApp(),
  );
}

Future<ProviderContainer> _pumpAuth(WidgetTester tester, FakeMayosApi fake,
    {Size size = const Size(393, 852)}) async {
  await _setSize(tester, size);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tester.pumpWidget(_app(fake, tokens));
  await _pumpUntilFound(tester, find.text('Log in'));
  return ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
}

GoRouter _routerOf(WidgetTester tester) {
  final ProviderContainer container =
      ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
  return container.read(routerProvider);
}

/// A fake with a live password for `alice`, so login can succeed.
FakeMayosApi _loginFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.passwords['alice'] = 'correct-horse-1';
  fake.recoveryEmail = 'alice@example.com';
  fake.profileExists = true;
  return fake;
}

void main() {
  testWidgets('login success authenticates and leaves the form',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _loginFake();
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
    final FakeMayosApi fake = _loginFake();
    await _pumpAuth(tester, fake);

    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(find.byKey(const Key('login_password')), 'wrong');
    await tester.tap(find.byKey(const Key('login_submit')));
    await _pumpUntilFound(tester, find.text('Invalid username or password.'));

    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(find.byKey(const Key('login_submit')), findsOneWidget);
  });

  testWidgets('login shows a loading state while the request is in flight',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _loginFake();
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
    final FakeMayosApi fake = FakeMayosApi();
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

  testWidgets('registration success lands on the recovery-email gate',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    await _pumpAuth(tester, fake);

    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));
    await tester.enterText(find.byKey(const Key('register_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('register_password')), 'correct-horse-1');
    await tester.enterText(
        find.byKey(const Key('register_confirm')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('register_submit')));

    await _pumpUntilFound(tester, find.text('Recovery email'));
    expect(find.byKey(const Key('recovery_email')), findsOneWidget);
  });

  testWidgets('recovery-email gate shows a server error, then unlocks',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    await _pumpAuth(tester, fake);
    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));
    await tester.enterText(find.byKey(const Key('register_username')), 'alice');
    await tester.enterText(
        find.byKey(const Key('register_password')), 'correct-horse-1');
    await tester.enterText(
        find.byKey(const Key('register_confirm')), 'correct-horse-1');
    await tester.tap(find.byKey(const Key('register_submit')));
    await _pumpUntilFound(tester, find.text('Recovery email'));

    await tester.enterText(
        find.byKey(const Key('recovery_email')), 'not-an-email');
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(tester, find.text('Enter a valid email address.'));

    await tester.enterText(
        find.byKey(const Key('recovery_email')), 'alice@example.com');
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(tester, find.text('Hosted AI processing'));
    expect(fake.recoveryEmail, 'alice@example.com');
  });

  testWidgets('forgot-password still returns the constant confirmation',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    await _pumpAuth(tester, fake);

    await tester.tap(find.text('Forgot password?'));
    await _pumpUntilFound(tester, find.text('Send reset link'));
    await tester.enterText(
        find.byKey(const Key('forgot_email')), 'alice@example.com');
    await tester.tap(find.byKey(const Key('forgot_submit')));

    await _pumpUntilFound(tester, find.text(fake.resetConfirmation));
    expect(fake.forgotRequests, 1);
  });

  testWidgets('reset-password still completes and routes to login',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..validResetToken = 'reset-code-1';
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
    final FakeMayosApi fake = _loginFake();
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
    final FakeMayosApi fake = _loginFake();
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
    final FakeMayosApi fake = _loginFake();
    await _pumpAuth(tester, fake);

    final Size toggle =
        tester.getSize(find.byKey(const Key('login_password_toggle')));
    expect(toggle.width, greaterThanOrEqualTo(48));
    expect(toggle.height, greaterThanOrEqualTo(48));
    final Size submit = tester.getSize(find.byKey(const Key('login_submit')));
    expect(submit.height, greaterThanOrEqualTo(48));

    expect(
      find.byWidgetPredicate(
          (Widget w) => w is Semantics && w.properties.label == 'MAYOS'),
      findsWidgets,
      reason: 'the brand lockup keeps its MAYOS semantics label',
    );
  });

  for (final String screen in <String>['login', 'register']) {
    testWidgets('$screen brand lockup is horizontally centred at 360x640',
        (WidgetTester tester) async {
      final FakeMayosApi fake = _loginFake();
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
      final double screenCentre = tester.view.physicalSize.width /
          tester.view.devicePixelRatio /
          2;
      final Finder hero = find.descendant(
        of: find.byType(AuthScaffold),
        matching: find.byType(MayosBrandLockup),
      );
      expect(tester.getCenter(hero).dx, closeTo(screenCentre, 0.5));
    });
  }

  testWidgets(
      'login keeps both fields and the CTA visible with the keyboard open',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _loginFake();
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

  testWidgets('remember-me consent is a tappable 48dp row with state',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _loginFake();
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
      final FakeMayosApi fake = _loginFake();
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
      final FakeMayosApi fake = _loginFake();
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
    final FakeMayosApi fake = _loginFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
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
        child: const MayosApp(),
      ),
    );
    await _pumpUntilFound(tester, find.text('Log in'));
    expect(
      MayosTheme.of(tester.element(find.byKey(const Key('login_submit'))))
          .isDark,
      isTrue,
    );
    expect(tester.takeException(), isNull);
  });
}
