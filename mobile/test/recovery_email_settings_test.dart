import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myos_mobile/src/app.dart';
import 'package:myos_mobile/src/core/api_client.dart';
import 'package:myos_mobile/src/core/app_mode.dart';
import 'package:myos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:myos_mobile/src/core/token_store.dart';
import 'package:myos_mobile/src/core/ui/myos_settings_tile.dart';
import 'package:myos_mobile/src/features/shared/mode_switch.dart';
import 'package:myos_mobile/src/providers.dart';

import 'support/fake_myos_api.dart';

Future<void> _pumpSettings(
  WidgetTester tester,
  FakeMyosApi fake, {
  Size size = const Size(360, 2200),
}) async {
  tester.view.physicalSize = size;
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
      child: const MyosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text(fake.displayLanguage == 'ar' ? 'الرئيسية' : 'Home'));
  final String laterLabel = fake.displayLanguage == 'ar' ? 'لاحقًا' : 'Later';
  if (!fake.recoveryEmailVerified) {
    await _pumpUntilFound(tester, find.text(laterLabel));
    await tester.tap(find.text(laterLabel));
    await tester.pump();
  }
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text(fake.displayLanguage == 'ar' ? 'الإعدادات' : 'Settings'));
    await tester.tap(find.text(fake.displayLanguage == 'ar' ? 'الإعدادات' : 'Settings'));
  }
  await _pumpUntilFound(
    tester,
    find.byKey(const Key('recovery_email_settings_entry')),
  );
}

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

FakeMyosApi _signedInFake({String language = 'en'}) {
  return FakeMyosApi()
    ..issuedToken = 'token-alice'
    ..currentUsername = 'alice'
    ..tokenValid = true
    ..profileExists = true
    ..recoveryEmail = 'old@example.com'
    ..recoveryEmailVerified = true
    ..displayLanguage = language;
}

void main() {
  for (final String language in <String>['en', 'ar']) {
    testWidgets('About explains MYOS in $language without an action', (
      WidgetTester tester,
    ) async {
      final FakeMyosApi fake = _signedInFake(language: language);
      await _pumpSettings(tester, fake, size: const Size(360, 5000));
      final Finder brandTitle =
          find.text(language == 'ar' ? 'ميوس' : 'MYOS').last;
      final Finder brandSubtitle = find.text(language == 'ar'
          ? 'يعني العضلة باليوناني'
          : 'Greek for muscle · said “meyos”');
      expect(brandTitle, findsOneWidget);
      expect(brandSubtitle, findsOneWidget);
      final Finder aboutTile = find
          .ancestor(
              of: brandTitle, matching: find.byType(MyosSettingsTile))
          .first;
      final SemanticsData aboutSemantics =
          tester.getSemantics(aboutTile).getSemanticsData();
      expect(aboutSemantics.flagsCollection.isButton, isFalse);
      expect(aboutSemantics.hasAction(SemanticsAction.tap), isFalse);
      expect(
          find.descendant(
              of: aboutTile,
              matching: find.byIcon(language == 'ar'
                  ? Icons.chevron_left
                  : Icons.chevron_right)),
          findsNothing);
      final Finder privacy =
          find.text(language == 'ar' ? 'سياسة الخصوصية' : 'Privacy policy');
      expect(privacy, findsOneWidget);
      expect(tester.getTopLeft(brandTitle).dy,
          lessThan(tester.getTopLeft(privacy).dy));
    });
  }

  testWidgets('Settings shows the verified address and completes its change', (
    WidgetTester tester,
  ) async {
    final FakeMyosApi fake = _signedInFake();
    await _pumpSettings(tester, fake);

    expect(find.text('Recovery email'), findsOneWidget);
    expect(find.text('old@example.com · Verified'), findsOneWidget);
    expect(find.text('Change'), findsOneWidget);

    await tester.tap(find.byKey(const Key('recovery_email_settings_entry')));
    await _pumpUntilFound(tester, find.text('Current recovery email'));
    expect(find.text('old@example.com'), findsOneWidget);
    expect(fake.recoveryEmail, 'old@example.com');

    await tester.enterText(
      find.byKey(const Key('recovery_email_change_address')),
      'new@example.com',
    );
    await tester.tap(find.byKey(const Key('recovery_email_change_send')));
    await _pumpUntilFound(tester, find.text('We sent a code to the new recovery email.'));
    expect(find.text('old@example.com'), findsOneWidget);
    expect(find.text('Not set'), findsNothing);
    expect(fake.recoveryEmail, 'old@example.com');
    expect(fake.pendingRecoveryEmail, 'new@example.com');

    await tester.enterText(
      find.byKey(const Key('recovery_email_change_code')),
      fake.currentRecoveryEmailChangeCode!,
    );
    await tester.tap(find.byKey(const Key('recovery_email_change_verify')));
    await _pumpUntilFound(tester, find.text('Recovery email changed.'));

    expect(fake.recoveryEmail, 'new@example.com');
    expect(fake.recoveryEmailVerified, isTrue);
    expect(fake.pendingRecoveryEmail, isNull);
  });

  testWidgets('Recovery-email Settings copy is Arabic', (
    WidgetTester tester,
  ) async {
    final FakeMyosApi fake = _signedInFake(language: 'ar')
      ..recoveryEmailVerified = false;
    await _pumpSettings(tester, fake);

    expect(find.text('البريد الإلكتروني للاسترداد'), findsOneWidget);
    expect(
      find.text(
        'لم يتم التحقق من البريد الإلكتروني للاسترداد. يلزم التحقق منه لاستعادة كلمة المرور.',
      ),
      findsNWidgets(1),
    );
    expect(find.text('تحقق'), findsOneWidget);
    await tester.tap(find.byKey(const Key('recovery_email_settings_entry')));
    await _pumpUntilFound(tester, find.text('البريد الإلكتروني الحالي'));
    expect(find.text('إرسال رمز التحقق'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('recovery_email_change_address')),
      'new@example.com',
    );
    await tester.tap(find.byKey(const Key('recovery_email_change_send')));
    await _pumpUntilFound(tester, find.text('أرسلنا رمزًا إلى البريد الإلكتروني الجديد.'));
    expect(find.text('رمز التحقق المكوّن من 6 أرقام'), findsOneWidget);
    expect(find.text('تأكيد التغيير'), findsOneWidget);
    expect(fake.recoveryEmail, 'old@example.com');
  });

  testWidgets('Settings warning opens verification and clears after success', (
    WidgetTester tester,
  ) async {
    final FakeMyosApi fake = _signedInFake()..recoveryEmailVerified = false;
    await _pumpSettings(tester, fake);

    expect(
      find.text(
        'Recovery email is not verified. Password recovery needs a verified email address.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('recovery_email_verify_action')));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('recovery_verification_code')),
    );
    expect(fake.recoveryEmailCodesSent, 0);

    await tester.tap(find.text('Send code'));
    await _pumpUntilFound(
      tester,
      find.text('We sent a code to your recovery email.'),
    );
    await tester.enterText(
      find.byKey(const Key('recovery_verification_code')),
      fake.currentRecoveryEmailCode!,
    );
    await tester.tap(find.byKey(const Key('recovery_submit')));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('recovery_email_settings_entry')),
    );

    expect(fake.recoveryEmailVerified, isTrue);
    expect(find.text('Not verified'), findsNothing);
    expect(find.text('old@example.com · Verified'), findsOneWidget);
    expect(
      find.text(
        'Recovery email is not verified. Password recovery needs a verified email address.',
      ),
      findsNothing,
    );
  });

  testWidgets('wrong change code keeps the current and pending addresses', (
    WidgetTester tester,
  ) async {
    final FakeMyosApi fake = _signedInFake();
    await _pumpSettings(tester, fake);
    await tester.tap(find.byKey(const Key('recovery_email_settings_entry')));
    await _pumpUntilFound(tester, find.text('Current recovery email'));
    await tester.enterText(
      find.byKey(const Key('recovery_email_change_address')),
      'new@example.com',
    );
    await tester.tap(find.byKey(const Key('recovery_email_change_send')));
    await _pumpUntilFound(tester, find.text('We sent a code to the new recovery email.'));
    await tester.enterText(
      find.byKey(const Key('recovery_email_change_code')),
      '000000',
    );
    await tester.tap(find.byKey(const Key('recovery_email_change_verify')));
    await _pumpUntilFound(
      tester,
      find.text('Could not change the recovery email. Check the address or code and try again.'),
    );

    expect(fake.recoveryEmail, 'old@example.com');
    expect(fake.recoveryEmailVerified, isTrue);
    expect(fake.pendingRecoveryEmail, 'new@example.com');
  });

  testWidgets('Settings resumes the verification step for an existing pending change', (
    WidgetTester tester,
  ) async {
    final FakeMyosApi fake = _signedInFake()
      ..pendingRecoveryEmail = 'pending@example.com'
      ..currentRecoveryEmailChangeCode = '123456';
    await _pumpSettings(tester, fake);
    await tester.tap(find.byKey(const Key('recovery_email_settings_entry')));
    await _pumpUntilFound(tester, find.text('Current recovery email'));

    expect(find.byKey(const Key('recovery_email_change_code')), findsOneWidget);
    expect(find.byKey(const Key('recovery_email_change_address')), findsNothing);
    expect(find.text('pending@example.com'), findsOneWidget);
    expect(fake.recoveryEmail, 'old@example.com');

    await tester.enterText(
      find.byKey(const Key('recovery_email_change_code')),
      fake.currentRecoveryEmailChangeCode!,
    );
    await tester.tap(find.byKey(const Key('recovery_email_change_verify')));
    await _pumpUntilFound(tester, find.text('Recovery email changed.'));
    expect(fake.recoveryEmail, 'pending@example.com');
    expect(fake.recoveryEmailVerified, isTrue);
    expect(fake.pendingRecoveryEmail, isNull);
  });

  testWidgets('linked recovery email shows the server refusal message', (
    WidgetTester tester,
  ) async {
    final FakeMyosApi fake = _signedInFake()
      ..recoveryEmailsLinkedElsewhere.add('taken@example.com');
    await _pumpSettings(tester, fake);
    await tester.tap(find.byKey(const Key('recovery_email_settings_entry')));
    await _pumpUntilFound(tester, find.text('Current recovery email'));
    await tester.enterText(
      find.byKey(const Key('recovery_email_change_address')),
      'taken@example.com',
    );
    await tester.tap(find.byKey(const Key('recovery_email_change_send')));

    await _pumpUntilFound(
      tester,
      find.text('This email is already linked to another account.'),
    );
    expect(fake.recoveryEmail, 'old@example.com');
    expect(fake.pendingRecoveryEmail, isNull);
  });
}
