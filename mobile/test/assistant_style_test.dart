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
  FakeMayosApi fake, {
  String language = 'en',
}) async {
  fake.displayLanguage = language;
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
  final String landingTitle = language == 'ar'
      ? 'الرئيسية'
      : fake.coach
          ? 'Roster'
          : 'Home';
  await _pumpUntilFound(tester, find.text(landingTitle));
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(
    tester,
    find.text(language == 'ar' ? 'المظهر' : 'Appearance'),
  );
}

Future<void> _openPersonalization(
  WidgetTester tester,
  FakeMayosApi fake, {
  String language = 'en',
}) async {
  await _openSettings(tester, fake, language: language);
  final Finder entry = find.byKey(const Key('personalization_entry'));
  await _pumpUntilFound(tester, entry);
  expect(
    find.text(language == 'ar' ? 'التخصيص' : 'Personalization'),
    findsOneWidget,
  );
  expect(
    find.descendant(
      of: entry,
      matching: find.text(
        language == 'ar' ? 'أسلوب المساعد' : 'Assistant style',
      ),
    ),
    findsOneWidget,
  );
  await tester.tap(entry);
  await _pumpUntilFound(
    tester,
    find.byKey(const Key('assistant_style_direct')),
  );
  await tester.pumpAndSettle();
  expect(
    find.text(language == 'ar' ? 'التخصيص' : 'Personalization'),
    findsOneWidget,
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
  testWidgets('Personalization uses English copy and saves edited style', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake()
      ..assistantStyle = 'scientific'
      ..assistantInstructions = 'Use short examples.';
    await _openPersonalization(tester, fake);

    expect(find.text('Assistant style'), findsOneWidget);
    expect(
      find.text(
        'Choose how your assistant words its chat replies. Facts, training decisions, safety, and reply language stay the same.',
      ),
      findsOneWidget,
    );
    for (final String label in <String>[
      'Direct & pragmatic',
      'Encouraging',
      'Scientific',
      'Tough-love',
      'Concise',
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
      find.text('Evidence and reasoning.'),
      findsOneWidget,
    );
    const Map<String, String> descriptions = <String, String>{
      'Clear and practical.': 'Direct & pragmatic',
      'Recognizes effort.': 'Encouraging',
      'Evidence and reasoning.': 'Scientific',
      'Firm, respectful.': 'Tough-love',
      'Brief, focused replies.': 'Concise',
    };
    for (final MapEntry<String, String> item in descriptions.entries) {
      expect(find.text(item.key), findsOneWidget, reason: item.value);
    }
    expect(find.text('19/500'), findsOneWidget);

    final Finder instructions =
        find.byKey(const Key('assistant_style_instructions'));
    expect(
      tester.widget<TextField>(instructions).controller!.text,
      'Use short examples.',
    );
    expect(find.text('Optional instructions'), findsOneWidget);
    expect(find.text('Used for wording only.'), findsOneWidget);
    await tester.enterText(instructions, '');
    await tester.pump();
    expect(
      find.text('For example: explain terms briefly.'),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const Key('assistant_style_concise')));
    const String arabicInstructions = 'اشرح المصطلحات باختصار.';
    await tester.enterText(instructions, arabicInstructions);
    await tester.pump();
    tester.testTextInput.hide();
    final Finder save = find.byKey(const Key('assistant_style_save'));
    await tester.ensureVisible(save);
    await tester.pumpAndSettle();
    expect(find.text('Save style'), findsOneWidget);
    await tester.tap(save);
    await _pumpUntilFound(tester, find.text('Assistant style saved.'));

    expect(fake.assistantStyle, 'concise');
    expect(fake.assistantInstructions, arabicInstructions);
    expect(
      tester.widget<TextField>(instructions).controller!.text,
      arabicInstructions,
    );
  });

  testWidgets('offline load retries and offline save persists nothing', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake()
      ..failOffline('PUT', '/profile/persona');
    await _openSettings(tester, fake);
    fake.failOffline('GET', '/profile');
    await tester.tap(find.byKey(const Key('personalization_entry')));
    await _pumpUntilFound(tester, find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('Personalization'), findsOneWidget);
    fake.offlineRequests.remove('GET /profile');
    await tester.tap(find.text('Retry'));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('assistant_style_direct')),
    );

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

  testWidgets('preferred name can be edited and cleared from Settings', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake()..preferredName = 'Current Name';
    await _openPersonalization(tester, fake);

    final Finder nameField = find.byKey(const Key('preferred_name_field'));
    expect(tester.widget<TextField>(nameField).controller!.text, 'Current Name');
    await tester.enterText(nameField, 'Edited Name');
    await tester.pump();
    final Finder save = find.byKey(const Key('preferred_name_save'));
    await tester.ensureVisible(save);
    await tester.tap(save);
    await _pumpUntilFound(tester, find.text('Preferred name saved.'));
    expect(fake.preferredName, 'Edited Name');

    final Finder clear = find.byKey(const Key('preferred_name_clear'));
    await tester.ensureVisible(clear);
    await tester.tap(clear);
    await _pumpUntilFound(tester, find.text('Preferred name cleared.'));
    expect(fake.preferredName, isNull);
    expect(tester.widget<TextField>(nameField).controller!.text, isEmpty);
  });

  testWidgets('preferred name can be set from empty in Settings', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake();
    await _openPersonalization(tester, fake);

    final Finder nameField = find.byKey(const Key('preferred_name_field'));
    expect(tester.widget<TextField>(nameField).controller!.text, isEmpty);
    await tester.enterText(nameField, 'Noura');
    await tester.pump();
    final Finder save = find.byKey(const Key('preferred_name_save'));
    await tester.ensureVisible(save);
    await tester.tap(save);
    await _pumpUntilFound(tester, find.text('Preferred name saved.'));

    expect(fake.preferredName, 'Noura');
    expect(tester.widget<TextField>(nameField).controller!.text, 'Noura');
  });

  testWidgets('preferred name validation and Settings copy use Arabic', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake();
    await _openPersonalization(tester, fake, language: 'ar');

    expect(find.text('الاسم المفضّل'), findsWidgets);
    expect(find.text('حفظ الاسم'), findsOneWidget);
    final Finder save = find.byKey(const Key('preferred_name_save'));
    await tester.ensureVisible(save);
    await tester.tap(save);
    await tester.pump();

    expect(find.text('اكتب اسمًا أو امسح الاسم الحالي.'), findsOneWidget);
    expect(fake.preferredName, isNull);
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
