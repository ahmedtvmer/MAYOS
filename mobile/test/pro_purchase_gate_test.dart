import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/external_url_launcher.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/settings/settings_screen.dart';
import 'package:mayos_mobile/src/features/player/plan/plan_screen.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

/// A test double that records every URL the app asks to open.
class _RecordingLauncher {
  final List<String> urls = <String>[];

  Future<bool> open(String url) async {
    urls.add(url);
    return true;
  }
}

/// A purchase CTA in any language would match one of these.
final RegExp _bannedCtaPattern = RegExp(
  r'\b(buy|subscribe|purchase|upgrade|free trial|start trial)\b',
  caseSensitive: false,
);

Finder _purchaseCtaFinder() {
  return find.byWidgetPredicate((Widget widget) {
    if (widget is Text) {
      final String content =
          widget.data ?? widget.textSpan?.toPlainText() ?? '';
      return _bannedCtaPattern.hasMatch(content);
    }
    if (widget is RichText) {
      return _bannedCtaPattern.hasMatch(widget.text.toPlainText().trim());
    }
    return false;
  });
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

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<void> _pumpSignedInApp(
  WidgetTester tester,
  _RecordingLauncher launcher,
) async {
  final FakeMayosApi fake = _signedInFake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(authApp(
    fake,
    tokens,
    extraOverrides: <Override>[
      externalUrlLauncherProvider.overrideWithValue(launcher.open),
    ],
  ));
  await _pumpUntilFound(tester, find.text('Home'));
}

void main() {
  // Pins the Play-launch purchase gate (#750): the first Android release is
  // free only. Until Play Billing lands (#740), no plan or settings surface
  // may offer a purchase, a subscription, or an upgrade link, and nothing on
  // those screens may launch an external URL.
  //
  // The web/PWA build shares this codebase and these screens verbatim, so the
  // same assertions hold for it; widget tests always run with `kIsWeb ==
  // false`, hence the default-platform group below instead of a web override.
  // One gate for every platform: the screens below have no platform branch,
  // so pinning both keeps a future #740 gate honest on Android and leaves the
  // shared web/PWA build untouched.
  group('on Android', () {
    testWidgets(
      'the Lifter plan screen shows the plan without a purchase CTA',
      (WidgetTester tester) async {
        final _RecordingLauncher launcher = _RecordingLauncher();
        await _pumpSignedInApp(tester, launcher);

        ProviderScope.containerOf(
          tester.element(find.byType(MayosApp)),
          listen: false,
        ).read(routerProvider).go(lifterPlanPath);
        await _pumpUntilFound(tester, find.byType(PlanScreen));

        expect(find.byType(PlanScreen), findsOneWidget);
        expect(_purchaseCtaFinder(), findsNothing);
        expect(launcher.urls, isEmpty);
      },
      variant: TargetPlatformVariant.only(TargetPlatform.android),
    );

    testWidgets(
      'the settings screen has no purchase CTA or external link',
      (WidgetTester tester) async {
        final _RecordingLauncher launcher = _RecordingLauncher();
        await _pumpSignedInApp(tester, launcher);

        ProviderScope.containerOf(
          tester.element(find.byType(MayosApp)),
          listen: false,
        ).read(routerProvider).go(settingsPath);
        await _pumpUntilFound(tester, find.byType(SettingsScreen));

        expect(find.byType(SettingsScreen), findsOneWidget);
        expect(_purchaseCtaFinder(), findsNothing);
        expect(launcher.urls, isEmpty);
      },
      variant: TargetPlatformVariant.only(TargetPlatform.android),
    );
  });

  group('with the default test platform (shared web/PWA code path)', () {
    testWidgets('the Lifter plan screen shows the plan without a purchase CTA',
        (WidgetTester tester) async {
      final _RecordingLauncher launcher = _RecordingLauncher();
      await _pumpSignedInApp(tester, launcher);

      ProviderScope.containerOf(
        tester.element(find.byType(MayosApp)),
        listen: false,
      ).read(routerProvider).go(lifterPlanPath);
      await _pumpUntilFound(tester, find.byType(PlanScreen));

      expect(find.byType(PlanScreen), findsOneWidget);
      expect(_purchaseCtaFinder(), findsNothing);
      expect(launcher.urls, isEmpty);
    });

    testWidgets('the settings screen has no purchase CTA or external link',
        (WidgetTester tester) async {
      final _RecordingLauncher launcher = _RecordingLauncher();
      await _pumpSignedInApp(tester, launcher);

      ProviderScope.containerOf(
        tester.element(find.byType(MayosApp)),
        listen: false,
      ).read(routerProvider).go(settingsPath);
      await _pumpUntilFound(tester, find.byType(SettingsScreen));

      expect(find.byType(SettingsScreen), findsOneWidget);
      expect(_purchaseCtaFinder(), findsNothing);
      expect(launcher.urls, isEmpty);
    });
  });
}
