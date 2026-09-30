import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_choice_card.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder) async {
  for (int i = 0; i < 40; i++) {
    if (finder.evaluate().isNotEmpty) {
      await tester.pump(const Duration(milliseconds: 300));
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
  fail('Timed out waiting for $finder');
}

Future<void> _openSettings(
  WidgetTester tester,
  FakeMayosApi fake,
) async {
  tester.view.physicalSize = const Size(360, 2200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore()),
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
  await _pumpUntilFound(tester, find.text(fake.coach ? 'Roster' : 'Home'));
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
}

Future<void> _openPersonalization(
  WidgetTester tester,
  FakeMayosApi fake,
) async {
  await _openSettings(tester, fake);
  final Finder entry = find.byKey(const Key('personalization_entry'));
  await _pumpUntilFound(tester, entry);
  await tester.tap(entry);
  await _pumpUntilFound(
    tester,
    find.byKey(const Key('assistant_style_direct')),
  );
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
  testWidgets('Personalization shows bilingual presets and saved selection', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake()
      ..assistantStyle = 'scientific'
      ..assistantInstructions = 'Use short examples.';
    await _openPersonalization(tester, fake);

    for (final String label in <String>[
      'Direct & pragmatic · مباشر وعملي',
      'Encouraging · مشجّع',
      'Scientific · علمي',
      'Tough-love · حازم وداعم',
      'Concise · موجز',
    ]) {
      expect(find.text(label), findsOneWidget);
    }
    expect(
      tester
          .widget<MayosChoiceCard>(
            find.byKey(const Key('assistant_style_scientific')),
          )
          .selected,
      isTrue,
    );
    expect(
      find.text('Evidence and reasoning. · الأدلة والمنطق.'),
      findsOneWidget,
    );
    const Map<String, String> descriptions = <String, String>{
      'Clear and practical. · واضح وعملي.': 'Direct & pragmatic · مباشر وعملي',
      'Recognizes effort. · يقدّر الجهد.': 'Encouraging · مشجّع',
      'Evidence and reasoning. · الأدلة والمنطق.': 'Scientific · علمي',
      'Firm, respectful. · حازم باحترام.': 'Tough-love · حازم وداعم',
      'Brief, focused replies. · ردود موجزة.': 'Concise · موجز',
    };
    for (final MapEntry<String, String> item in descriptions.entries) {
      expect(find.text(item.key), findsOneWidget, reason: item.value);
    }
    expect(find.text('19/500'), findsOneWidget);
  });

  testWidgets('offline save shows the shared message and persists nothing', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake()
      ..failOffline('PUT', '/profile/persona');
    await _openPersonalization(tester, fake);

    await tester.tap(find.byKey(const Key('assistant_style_scientific')));
    await tester.enterText(
      find.byKey(const Key('assistant_style_instructions')),
      'Use short examples.',
    );
    await tester.pump();
    expect(find.text('19/500'), findsOneWidget);
    tester.testTextInput.hide();
    final Finder save = find.byKey(const Key('assistant_style_save'));
    await tester.ensureVisible(save);
    await tester.pumpAndSettle();
    await tester.tap(save);
    await _pumpUntilFound(
      tester,
      find.text('This needs a connection. Nothing was changed.'),
    );

    expect(fake.assistantStyle, 'direct');
    expect(fake.assistantInstructions, '');
  });

  testWidgets('coach-only account does not show Personalization', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake()
      ..coach = true
      ..playerCapability = false;
    await _openSettings(tester, fake);

    expect(find.byKey(const Key('personalization_entry')), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
