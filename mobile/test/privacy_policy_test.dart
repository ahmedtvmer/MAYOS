import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/privacy_policy.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

/// The privacy policy is served by the API at `/privacy` (ADR 046); the app
/// only ever hands that URL to the system browser, from the signed-out auth
/// screens and from Settings (#43).

class _RecordingLauncher {
  final List<String> urls = <String>[];
  bool result = true;

  Future<bool> open(String url) async {
    urls.add(url);
    return result;
  }
}

Override _launcherOverride(_RecordingLauncher launcher) =>
    privacyUrlLauncherProvider.overrideWithValue(launcher.open);

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

Future<void> _setSize(WidgetTester tester) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _pumpAuth(WidgetTester tester, _RecordingLauncher launcher) async {
  await _setSize(tester);
  await tester.pumpWidget(authApp(
    FakeMayosApi(),
    InMemoryTokenStore(),
    extraOverrides: <Override>[_launcherOverride(launcher)],
  ));
  await _pumpUntilFound(tester, find.text('Log in'));
}

Future<void> _pumpSignedIn(WidgetTester tester, _RecordingLauncher launcher) async {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.passwords['alice'] = 'correct-horse-1';

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        _launcherOverride(launcher),
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
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
}

void main() {
  test('the policy URL is the API privacy route', () {
    expect(privacyPolicyUrl, endsWith('/privacy'));
    expect(Uri.parse(privacyPolicyUrl).hasScheme, isTrue);
  });

  testWidgets('the signed-out login screen offers the privacy policy',
      (WidgetTester tester) async {
    final _RecordingLauncher launcher = _RecordingLauncher();
    await _pumpAuth(tester, launcher);

    await tester.tap(find.byKey(const Key('login_privacy_policy')));
    await tester.pumpAndSettle();

    expect(launcher.urls, <String>[privacyPolicyUrl]);
    // Opening the policy must never disturb the login form.
    expect(find.byKey(const Key('login_submit')), findsOneWidget);
  });

  testWidgets('the register screen links the policy next to consent',
      (WidgetTester tester) async {
    final _RecordingLauncher launcher = _RecordingLauncher();
    await _pumpAuth(tester, launcher);
    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.byKey(const Key('register_submit')));

    final Finder consent = find.text('Keep me signed in');
    final Finder policy = find.byKey(const Key('register_privacy_policy'));
    expect(consent, findsOneWidget);
    expect(policy, findsOneWidget);
    // "Near consent": the disclosure sits directly under the consent row.
    expect(
      tester.getTopLeft(policy).dy,
      greaterThan(tester.getBottomRight(consent).dy),
    );
    expect(
      tester.getTopLeft(policy).dy - tester.getBottomRight(consent).dy,
      lessThan(120),
    );

    await tester.tap(policy);
    await tester.pumpAndSettle();
    expect(launcher.urls, <String>[privacyPolicyUrl]);
  });

  testWidgets('settings offers the privacy policy to a signed-in account',
      (WidgetTester tester) async {
    final _RecordingLauncher launcher = _RecordingLauncher();
    await _pumpSignedIn(tester, launcher);

    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('Appearance'));

    // The About section sits below the fold on this viewport.
    await tester.drag(find.byType(ListView), const Offset(0, -800));
    await _pumpUntilFound(tester, find.text('Privacy policy'));

    await tester.tap(find.text('Privacy policy'));
    await tester.pumpAndSettle();
    expect(launcher.urls, <String>[privacyPolicyUrl]);
  });

  testWidgets('a refused launch is reported instead of failing silently',
      (WidgetTester tester) async {
    final _RecordingLauncher launcher = _RecordingLauncher()..result = false;
    await _pumpAuth(tester, launcher);

    await tester.tap(find.byKey(const Key('login_privacy_policy')));
    await tester.pumpAndSettle();

    expect(launcher.urls, <String>[privacyPolicyUrl]);
    expect(find.textContaining('Could not open the privacy policy'),
        findsOneWidget);
  });
}
