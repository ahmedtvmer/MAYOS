import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder) async {
  for (int i = 0; i < 40; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _openSettings(
  WidgetTester tester, {
  String displayLanguage = 'en',
}) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    final Finder settingsLabel =
        find.text(displayLanguage == 'ar' ? 'الإعدادات' : 'Settings');
    await _pumpUntilFound(tester, settingsLabel);
    await tester.tap(settingsLabel);
  }
  await _pumpUntilFound(
    tester,
    find.text(displayLanguage == 'ar' ? 'المظهر' : 'Appearance'),
  );
}

Future<void> _expectVisible(
  WidgetTester tester,
  String label,
) async {
  final Finder text = find.text(label);
  if (text.evaluate().isEmpty) {
    await tester.scrollUntilVisible(
      text,
      250,
      scrollable: find.byType(Scrollable).first,
    );
  }
  if (text.evaluate().isNotEmpty) {
    await tester.ensureVisible(text.first);
    await tester.pump();
  }
  expect(text, findsWidgets);
}

Future<void> _pumpApp(
  WidgetTester tester, {
  required AppMode mode,
  required Size size,
  bool coachCapability = true,
  bool playerCapability = true,
  String displayLanguage = 'en',
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final FakeMayosApi fake = FakeMayosApi()
    ..issuedToken = 'token-alice'
    ..currentUsername = 'alice'
    ..tokenValid = true
    ..coach = coachCapability
    ..playerCapability = playerCapability
    ..profileExists = true
    ..displayLanguage = displayLanguage
    ..recoveryEmail = 'alice@example.com';
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(
          InMemoryAppModeStore(<String, AppMode>{'account-alice': mode}),
        ),
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
  await _pumpUntilFound(
    tester,
    mode == AppMode.coach
        ? find.byKey(const Key('mode_avatar_button'))
        : find.byIcon(Icons.settings_outlined),
  );
  await _openSettings(tester, displayLanguage: displayLanguage);
}

void main() {
  for (final (String layout, Size size) in <(String, Size)>[
    ('Android phone', const Size(390, 844)),
    ('web desktop', const Size(1440, 900)),
  ]) {
    testWidgets('Settings sections in Coach mode on $layout',
        (WidgetTester tester) async {
      await _pumpApp(tester, mode: AppMode.coach, size: size);

      for (final String label in <String>[
        'Training profile',
        'Lifter plan',
        'My coach',
        'Personalization',
        'Assistant style',
        'Assistant',
      ]) {
        expect(find.text(label), findsNothing);
      }
      for (final String label in <String>[
        'Coach profile',
        'Coach plan',
        'Notifications',
        'Account',
      ]) {
        await _expectVisible(tester, label);
      }
      await _expectVisible(tester, 'Password');
    });

    testWidgets('Settings sections in Player mode on $layout',
        (WidgetTester tester) async {
      await _pumpApp(tester, mode: AppMode.player, size: size);

      expect(find.text('Coach profile'), findsNothing);
      expect(find.text('Coach plan'), findsNothing);
      expect(find.text('Notifications'), findsNothing);
      for (final String label in <String>[
        'Training profile',
        'Lifter plan',
        'My coach',
        'Personalization',
        'Assistant style',
        'Assistant',
        'Account',
      ]) {
        await _expectVisible(tester, label);
      }
      await _expectVisible(tester, 'Password');
    });
  }

  for (final (String layout, Size size) in <(String, Size)>[
    ('Android phone', const Size(390, 844)),
    ('web desktop', const Size(1440, 900)),
  ]) {
    for (final (AppMode mode, String label) in <(AppMode, String)>[
      (AppMode.player, 'Player'),
      (AppMode.coach, 'Coach'),
    ]) {
      testWidgets(
          'Account controls are available in $label mode on $layout',
          (WidgetTester tester) async {
        await _pumpApp(tester, mode: mode, size: size);

        for (final String control in <String>[
          'Username',
          'alice',
          'Recovery email',
          'Linked sign-in',
          'Password',
          'Google',
          'Delete account',
          'Display language',
        ]) {
          await _expectVisible(tester, control);
        }
      });
    }
  }

  testWidgets('a non-coach account sees Player Settings including My coach',
      (WidgetTester tester) async {
    await _pumpApp(
      tester,
      mode: AppMode.player,
      size: const Size(390, 844),
      coachCapability: false,
    );

    for (final String label in <String>[
      'Training profile',
      'Lifter plan',
      'My coach',
      'Personalization',
      'Assistant style',
      'Assistant',
    ]) {
      await _expectVisible(tester, label);
    }
    await _expectVisible(tester, 'Password');
    expect(find.text('Coach profile'), findsNothing);
    expect(find.text('Coach plan'), findsNothing);
    expect(find.text('Notifications'), findsNothing);
  });

  testWidgets('My coach remains available without a Player profile capability',
      (WidgetTester tester) async {
    await _pumpApp(
      tester,
      mode: AppMode.player,
      size: const Size(390, 844),
      coachCapability: false,
      playerCapability: false,
    );

    await _expectVisible(tester, 'My coach');
    await _expectVisible(tester, 'Password');
    expect(find.text('Coach profile'), findsNothing);
    expect(find.text('Coach plan'), findsNothing);
  });

  testWidgets('new Settings section labels use the Arabic glossary',
      (WidgetTester tester) async {
    await _pumpApp(
      tester,
      mode: AppMode.player,
      size: const Size(390, 844),
      displayLanguage: 'ar',
    );

    for (final String label in <String>[
      'الملف التدريبي',
      'خطة اللاعب',
      'مدربي',
      'التخصيص',
      'أسلوب المساعد',
      'المساعد',
      'الحساب',
    ]) {
      await _expectVisible(tester, label);
    }
    await _expectVisible(tester, 'كلمة المرور');
    expect(find.text('ملف المدرب'), findsNothing);
    expect(find.text('خطة المدرب'), findsNothing);
    expect(find.text('الإشعارات'), findsNothing);
  });

  testWidgets('Coach Settings sections use the Arabic glossary',
      (WidgetTester tester) async {
    await _pumpApp(
      tester,
      mode: AppMode.coach,
      size: const Size(390, 844),
      displayLanguage: 'ar',
    );

    for (final String label in <String>[
      'ملف المدرب',
      'خطة المدرب',
      'الإشعارات',
      'الحساب',
      'اسم المستخدم',
    ]) {
      await _expectVisible(tester, label);
    }
    await _expectVisible(tester, 'كلمة المرور');
    expect(find.text('الملف التدريبي'), findsNothing);
    expect(find.text('خطة اللاعب'), findsNothing);
    expect(find.text('مدربي'), findsNothing);
  });

  testWidgets('Coach profile entry opens the existing coach profile screen',
      (WidgetTester tester) async {
    await _pumpApp(
      tester,
      mode: AppMode.coach,
      size: const Size(390, 844),
    );

    await tester.tap(find.text('Coach profile'));
    await _pumpUntilFound(tester, find.text('Coach Alice'));
    expect(find.text('Training profile'), findsNothing);
  });

  for (final (AppMode mode, String entry, String plan, String hiddenPlan)
      in <(AppMode, String, String, String)>[
    (AppMode.coach, 'Coach plan', 'Coach Free', 'Lifter Free'),
    (AppMode.player, 'Lifter plan', 'Lifter Free', 'Coach Free'),
  ]) {
    testWidgets('$entry entry shows only its plan',
        (WidgetTester tester) async {
      await _pumpApp(
        tester,
        mode: mode,
        size: const Size(390, 844),
      );
      await tester.tap(find.text(entry));
      await _pumpUntilFound(tester, find.text(plan));
      expect(find.text(hiddenPlan), findsNothing);
    });
  }
}
