import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

Future<void> _pumpSettings(WidgetTester tester, FakeMayosApi fake) async {
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
  await _pumpUntilFound(tester, find.text(fake.displayLanguage == 'ar' ? 'الرئيسية' : 'Home'));
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

FakeMayosApi _signedInFake({String language = 'en'}) {
  return FakeMayosApi()
    ..issuedToken = 'token-alice'
    ..currentUsername = 'alice'
    ..tokenValid = true
    ..profileExists = true
    ..recoveryEmail = 'old@example.com'
    ..recoveryEmailVerified = true
    ..displayLanguage = language;
}

void main() {
  testWidgets('Settings shows the verified address and completes its change', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake();
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
    final FakeMayosApi fake = _signedInFake(language: 'ar');
    await _pumpSettings(tester, fake);

    expect(find.text('البريد الإلكتروني للاسترداد'), findsOneWidget);
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

  testWidgets('wrong change code keeps the current and pending addresses', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _signedInFake();
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
    final FakeMayosApi fake = _signedInFake()
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
    final FakeMayosApi fake = _signedInFake()
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
