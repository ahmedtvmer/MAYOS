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
  FakeMayosApi? fakeApi,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final FakeMayosApi fake = fakeApi ?? FakeMayosApi();
  fake
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
      ]) {
        await _expectVisible(tester, label);
      }
      expect(find.byKey(const Key('player_notifications_entry')), findsNothing);
      await _expectVisible(tester, 'Expiry and attention alerts');
      expect(find.byKey(const Key('coach_notifications_entry')), findsOneWidget);
      await _expectVisible(tester, 'Account');
      await _expectVisible(tester, 'Password');
    });

    testWidgets('Settings sections in Player mode on $layout',
        (WidgetTester tester) async {
      await _pumpApp(tester, mode: AppMode.player, size: size);

      expect(find.text('Coach profile'), findsNothing);
      expect(find.text('Coach plan'), findsNothing);
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
    expect(find.byKey(const Key('player_notifications_entry')), findsNothing);
    expect(find.text('Notifications'), findsNothing);
  });

  testWidgets('Player Settings opens the Player notifications surface',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..playerNotices.add(<String, dynamic>{
        'notice_id': 'notice-1',
        'assignment_id': 'assignment-1',
        'kind': 'program_published',
        'message': 'Your coach published a new Training program.',
        'created_at': '2026-10-10T12:00:00Z',
        'read_at': null,
      })
      ..playerNotices.add(<String, dynamic>{
        'notice_id': 'notice-2',
        'assignment_id': 'assignment-1',
        'kind': 'program_request',
        'message': 'Your coach responded to your Program request.',
        'created_at': '2026-10-09T12:00:00Z',
        'read_at': null,
      })
      ..checkIns.add(<String, dynamic>{
        'check_in_id': 'check-in-1',
        'assignment_id': 'assignment-1',
        'checked_in_on': '2026-10-10',
        'channel': 'in_app',
        'created_at': '2026-10-10T12:00:00Z',
        'coach_username': 'coach-alice',
        'assignment_status': 'active',
      });
    await _pumpApp(
      tester,
      mode: AppMode.player,
      size: const Size(390, 844),
      fakeApi: fake,
    );

    await _expectVisible(tester, 'Coach updates and Check-ins');
    expect(find.byKey(const Key('player_notifications_entry')), findsOneWidget);
    final Finder entry = find.byKey(const Key('player_notifications_entry'));
    await tester.tap(entry);
    await _pumpUntilFound(
      tester,
      find.text('Your coach published a new Training program.'),
    );

    expect(
      tester
          .widget<Text>(find.byKey(const Key('notice_caption_notice-1')))
          .textSpan!
          .toPlainText(),
      'Training program update · \u20662026-10-10\u2069',
    );
    expect(
      tester
          .widget<Text>(find.byKey(const Key('notice_caption_notice-2')))
          .textSpan!
          .toPlainText(),
      'Program request update · \u20662026-10-09\u2069',
    );
    expect(find.text('2026-10-10 · In app'), findsOneWidget);
    expect(find.text('My coach'), findsNothing);

    final Finder markAllRead = find.text('Mark all read');
    await tester.ensureVisible(markAllRead);
    await tester.tap(markAllRead);
    expect(find.byKey(const Key('player_notifications_surface')), findsOneWidget);
    expect(
      find.text('Your coach published a new Training program.'),
      findsOneWidget,
    );
    await tester.pumpAndSettle();
    expect(fake.markPlayerNoticesReadRequests, 1);
    expect(markAllRead, findsNothing);
  });

  testWidgets('Player notifications use Arabic glossary copy',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..playerNotices.add(<String, dynamic>{
        'notice_id': 'arabic-notice',
        'assignment_id': 'assignment-1',
        'kind': 'program_published',
        'message': 'Coach published an update.',
        'created_at': '2026-10-10T12:00:00Z',
        'read_at': null,
      });
    await _pumpApp(
      tester,
      mode: AppMode.player,
      size: const Size(390, 844),
      displayLanguage: 'ar',
      fakeApi: fake,
    );

    await _expectVisible(tester, 'تحديثات المدرب وسجلات التواصل');
    final Finder entry = find.byKey(const Key('player_notifications_entry'));
    await tester.ensureVisible(entry);
    await tester.tap(entry);
    await _pumpUntilFound(tester, find.text('سجلات التواصل'));

    expect(find.text('الإشعارات'), findsWidgets);
    expect(find.text('لا توجد سجلات تواصل بعد.'), findsOneWidget);
    final Text noticeCaption = tester.widget<Text>(
      find.byKey(const Key('notice_caption_arabic-notice')),
    );
    expect(noticeCaption.textDirection, isNull);
    expect(
      noticeCaption.textSpan!.toPlainText(),
      'تحديث البرنامج التدريبي · \u20662026-10-10\u2069',
    );
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
