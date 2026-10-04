import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_failure.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/display_language/coach_copy.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_spacing.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/settings/settings_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_google_auth.dart';
import 'support/fake_mayos_api.dart';

void main() {
  testWidgets('login failure follows the selected display language',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..loginNetworkFails = true;
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore()..value = 'en';
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login_username')), 'alice');
    await tester.enterText(
      find.byKey(const Key('login_password')),
      'password-123',
    );
    await tester.tap(find.byKey(const Key('login_submit')));
    await tester.pumpAndSettle();

    const AppFailureMessage connectionFailure = AppFailureMessage(
      AppFailureId.cannotReachService,
      'Cannot reach the service. Check your connection.',
    );
    expect(find.text('Cannot reach the service. Check your connection.'),
        findsOneWidget);

    await _selectArabicOnAuth(tester);
    expect(
      find.text(const MayosCopy('ar').failureMessage(connectionFailure)),
      findsOneWidget,
    );
    expect(find.text('Cannot reach the service. Check your connection.'),
        findsNothing);

    fake.loginNetworkFails = false;
    await tester.tap(find.byKey(const Key('login_submit')));
    await tester.pumpAndSettle();
    expect(find.text('Invalid username or password.'), findsOneWidget);
  });

  testWidgets('Arabic auth screen keeps password-length digits Western',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore()..value = 'ar';
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    expect(
        tester
            .getSize(find.byKey(const Key('display_language_selector')))
            .height,
        greaterThanOrEqualTo(kMayosMinTapTarget));
    await tester.tap(find.text('إنشاء حساب'));
    await tester.pumpAndSettle();
    expect(find.text('8 أحرف على الأقل'), findsOneWidget);
    expect(find.text('٨ أحرف على الأقل'), findsNothing);
  });

  testWidgets('disabling coaching preserves Arabic account language',
      (WidgetTester tester) async {
    final String activeAssignments = const CoachCopy('ar').activeAssignments;
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'coach@example.com'
      ..coach = true
      ..displayLanguage = 'ar';
    fake.passwords['coach'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await _signIn(tester, 'coach');
    expect(find.text(activeAssignments), findsOneWidget);
    expect(Directionality.of(tester.element(find.text(activeAssignments))),
        TextDirection.rtl);

    const CoachCopy coachCopy = CoachCopy('ar');
    await tester.ensureVisible(find.text(coachCopy.disableCoaching));
    await tester.tap(find.text(coachCopy.disableCoaching).first);
    await tester.pumpAndSettle();
    expect(find.text(coachCopy.disableCoachingQuestion), findsOneWidget);
    await tester.tap(find.text(coachCopy.disableCoaching).last);
    for (var i = 0;
        i < 30 && find.text(const MayosCopy('ar').home).evaluate().isEmpty;
        i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    final Finder home = find.text(const MayosCopy('ar').home);
    expect(home, findsOneWidget);
    expect(Directionality.of(tester.element(home)), TextDirection.rtl);
    expect(fake.coach, isFalse);
  });

  testWidgets(
      'Arabic account recovery-email gate has no logged-out language selector',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..displayLanguage = 'ar';
    fake.passwords['alice'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();

    await _signIn(tester, 'alice');

    expect(find.byKey(const Key('recovery_email')), findsOneWidget);
    expect(find.byKey(const Key('display_language_selector')), findsNothing);
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('recovery_email')))),
        TextDirection.rtl);
    expect(await languageStore.readAccount('account-alice'), 'ar');
  });

  testWidgets('Arabic account stays Arabic after redeeming a Coach invite',
      (WidgetTester tester) async {
    final String activeAssignments = const CoachCopy('ar').activeAssignments;
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com'
      ..displayLanguage = 'ar'
      ..validCoachInviteToken = 'coach-invite-token-abcdef';
    fake.passwords['alice'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await _signIn(tester, 'alice');
    expect(
        Directionality.of(
            tester.element(find.text(const MayosCopy('ar').home))),
        TextDirection.rtl);

    // Settings UI path is covered by coach_profile_test.
    final container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    bool redemptionCompleted = false;
    final Future<void> redemption = container
        .read(authControllerProvider.notifier)
        .redeemCoachInvite('coach-invite-token-abcdef');
    unawaited(redemption.then((_) {
      redemptionCompleted = true;
    }, onError: (Object error, StackTrace stackTrace) {
      redemptionCompleted = true;
    }));
    for (var i = 0;
        i < 40 &&
            (!redemptionCompleted ||
                find.text(activeAssignments).evaluate().isEmpty);
        i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(redemptionCompleted, isTrue,
        reason: 'the fake Coach-invite API request should complete');
    await redemption;

    expect(find.text(activeAssignments), findsOneWidget);
    expect(Directionality.of(tester.element(find.text(activeAssignments))),
        TextDirection.rtl);
    expect(fake.displayLanguage, 'ar');
    expect(await languageStore.readAccount('account-alice'), 'ar');
  });

  testWidgets(
      'forgot-password confirmation uses Arabic for known and unknown emails',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..recoveryEmail = 'known@example.com';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore()..value = 'ar';
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await tester.tap(find.text('نسيت كلمة المرور؟'));
    await tester.pumpAndSettle();

    const String confirmation =
        'إذا كان هذا البريد الإلكتروني مرتبطًا بحساب، فسيصلك رابط إعادة التعيين قريبًا.';
    for (final String email in <String>[
      'known@example.com',
      'unknown@example.com',
    ]) {
      await _enter(tester, const Key('forgot_email'), email);
      await tester.tap(find.byKey(const Key('forgot_submit')));
      await tester.pumpAndSettle();
      expect(find.text(confirmation), findsOneWidget);
      expect(
          find.text(
              'If this email is linked to a ledger, a reset link is on its way.'),
          findsNothing);
    }
    expect(fake.forgotRequests, 2);
  });

  testWidgets(
      'system locale changes affect only an unsigned manual-free choice',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();

    tester.platformDispatcher.localesTestValue = const <Locale>[Locale('ar')];
    await tester.pump();
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('display_language_selector')))),
        TextDirection.rtl);
    expect(
        find.descendant(
            of: find.byKey(const Key('display_language_selector')),
            matching: find.text('العربية')),
        findsOneWidget);

    await tester.tap(find.byKey(const Key('display_language_selector')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('الإنجليزية').last);
    await tester.pumpAndSettle();
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('display_language_selector')))),
        TextDirection.ltr);

    tester.platformDispatcher.localesTestValue = const <Locale>[Locale('en')];
    await tester.pump();
    tester.platformDispatcher.localesTestValue = const <Locale>[Locale('ar')];
    await tester.pump();
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('display_language_selector')))),
        TextDirection.ltr);
    expect(
        find.descendant(
            of: find.byKey(const Key('display_language_selector')),
            matching: find.text('English')),
        findsOneWidget);
    tester.platformDispatcher.clearLocalesTestValue();
    await tester.pump();
  });

  testWidgets(
      'system locale changes do not replace a signed-in account language',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com'
      ..displayLanguage = 'en';
    fake.passwords['alice'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await _signIn(tester, 'alice');
    expect(Directionality.of(tester.element(find.text('Home'))),
        TextDirection.ltr);

    tester.platformDispatcher.localesTestValue = const <Locale>[Locale('ar')];
    await tester.pump();
    expect(Directionality.of(tester.element(find.text('Home'))),
        TextDirection.ltr);
    tester.platformDispatcher.clearLocalesTestValue();
    await tester.pump();
  });

  testWidgets('offline session restoration reads only that account cache',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..meFails = true;
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    await tokens.saveAccountId('account-alice');
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore()..value = 'en';
    languageStore.accountValues['account-alice'] = 'ar';
    languageStore.accountValues['account-bob'] = 'en';

    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('العربية'), findsOneWidget);
    expect(find.text('الإنجليزية'), findsNothing);
    expect(find.text('إنشاء حساب'), findsOneWidget);
  });

  testWidgets(
      'late startup token-store failure cannot replace account language',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com'
      ..displayLanguage = 'ar';
    fake.passwords['alice'] = 'password-123';
    final _LateTokenReadFailure tokens = _LateTokenReadFailure();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();

    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    expect(tokens.delayedRead.isCompleted, isFalse);

    await _signIn(tester, 'alice');
    final Finder home = find.text(const MayosCopy('ar').home);
    expect(Directionality.of(tester.element(home)), TextDirection.rtl);
    tokens.delayedRead.completeError(StateError('storage unavailable'));
    await tester.pumpAndSettle();
    expect(Directionality.of(tester.element(home)), TextDirection.rtl);
  });

  testWidgets(
      'late successful startup account read cannot replace signed-in language',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com'
      ..displayLanguage = 'ar';
    fake.passwords['alice'] = 'password-123';
    final _LateTokenAccountIdRead tokens = _LateTokenAccountIdRead();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    languageStore.accountValues['account-alice'] = 'en';

    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    expect(tokens.delayedAccountId.isCompleted, isFalse);

    await _signIn(tester, 'alice');
    final Finder home = find.text(const MayosCopy('ar').home);
    expect(Directionality.of(tester.element(home)), TextDirection.rtl);

    tokens.delayedAccountId.complete('account-alice');
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(Directionality.of(tester.element(home)), TextDirection.rtl);
  });

  testWidgets(
      'rejected startup session restores logged-out language and locale behavior',
      (WidgetTester tester) async {
    final FakeMayosApi rejectedFake = FakeMayosApi();
    final Completer<void> allowRejectedMe = Completer<void>();
    rejectedFake.adapter.beforeRespond = (request) async {
      if (request.path.endsWith('/auth/me')) await allowRejectedMe.future;
    };
    final InMemoryTokenStore rejectedTokens = InMemoryTokenStore();
    await rejectedTokens.save('expired-token');
    await rejectedTokens.saveAccountId('account-alice');
    final _ObservedDisplayLanguageStore rejectedLanguageStore =
        _ObservedDisplayLanguageStore(initialValue: 'en')
          ..accountValues['account-alice'] = 'ar';

    await tester.pumpWidget(
        authApp(rejectedFake, rejectedTokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(rejectedLanguageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    for (var i = 0;
        i < 20 && !rejectedLanguageStore.accountRead.isCompleted;
        i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(rejectedLanguageStore.accountRead.isCompleted, isTrue);
    allowRejectedMe.complete();
    for (var i = 0;
        i < 30 && find.byKey(const Key('login_submit')).evaluate().isEmpty;
        i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(find.byKey(const Key('login_submit')), findsOneWidget);
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('display_language_selector')))),
        TextDirection.ltr);
    Finder loggedOutLanguage(String value) => find.descendant(
        of: find.byKey(const Key('display_language_selector')),
        matching: find.text(value));
    expect(loggedOutLanguage('English'), findsOneWidget);

    tester.platformDispatcher.localesTestValue = const <Locale>[Locale('ar')];
    await tester.pump();
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('display_language_selector')))),
        TextDirection.ltr);
    expect(loggedOutLanguage('English'), findsOneWidget);
    tester.platformDispatcher.clearLocalesTestValue();
    await tester.pump();

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    final FakeMayosApi noManualFake = FakeMayosApi();
    final Completer<void> allowNoManualMe = Completer<void>();
    noManualFake.adapter.beforeRespond = (request) async {
      if (request.path.endsWith('/auth/me')) await allowNoManualMe.future;
    };
    final InMemoryTokenStore noManualTokens = InMemoryTokenStore();
    await noManualTokens.save('expired-token');
    await noManualTokens.saveAccountId('account-alice');
    final _ObservedDisplayLanguageStore noManualLanguageStore =
        _ObservedDisplayLanguageStore()..accountValues['account-alice'] = 'ar';
    await tester.pumpWidget(
        authApp(noManualFake, noManualTokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(noManualLanguageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    for (var i = 0;
        i < 20 && !noManualLanguageStore.accountRead.isCompleted;
        i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(noManualLanguageStore.accountRead.isCompleted, isTrue);
    allowNoManualMe.complete();
    for (var i = 0;
        i < 30 && find.byKey(const Key('login_submit')).evaluate().isEmpty;
        i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(find.byKey(const Key('login_submit')), findsOneWidget);
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('display_language_selector')))),
        TextDirection.ltr);

    tester.platformDispatcher.localesTestValue = const <Locale>[Locale('ar')];
    await tester.pump();
    expect(
        Directionality.of(
            tester.element(find.byKey(const Key('display_language_selector')))),
        TextDirection.rtl);
    expect(
        find.descendant(
            of: find.byKey(const Key('display_language_selector')),
            matching: find.text('العربية')),
        findsOneWidget);
    tester.platformDispatcher.clearLocalesTestValue();
    await tester.pump();
  });

  testWidgets('confirmed Settings language survives an older account refresh',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com';
    fake.passwords['alice'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await _signIn(tester, 'alice');
    await _openSettings(tester);

    final Completer<void> refreshStarted = Completer<void>();
    final Completer<void> allowRefresh = Completer<void>();
    fake.currentAccountDisplayLanguageOverride = 'en';
    fake.adapter.beforeRespond = (request) async {
      if (request.path.endsWith('/auth/me')) {
        if (!refreshStarted.isCompleted) refreshStarted.complete();
        await allowRefresh.future;
      }
    };
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    for (var i = 0; i < 20 && !refreshStarted.isCompleted; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(refreshStarted.isCompleted, isTrue);

    final Finder selector =
        find.byKey(const Key('account_display_language_en-0'));
    await tester.scrollUntilVisible(selector, 250,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(selector);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Arabic').last);
    await tester.pump(const Duration(milliseconds: 500));
    for (var i = 0; i < 20 && fake.displayLanguage != 'ar'; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(fake.displayLanguage, 'ar');
    expect(Directionality.of(tester.element(find.byType(SettingsScreen))),
        TextDirection.rtl);

    allowRefresh.complete();
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(Directionality.of(tester.element(find.byType(SettingsScreen))),
        TextDirection.rtl);
    expect(languageStore.accountValues['account-alice'], 'ar');
    expect(fake.displayLanguage, 'ar');
  });

  testWidgets(
      'confirmed Settings language remains visible while save is pending',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com';
    fake.passwords['alice'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    final Completer<void> updateStarted = Completer<void>();
    final Completer<void> allowUpdate = Completer<void>();
    fake.adapter.beforeRespond = (request) async {
      if (request.path.endsWith('/auth/display-language')) {
        if (!updateStarted.isCompleted) updateStarted.complete();
        await allowUpdate.future;
      }
    };
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await _signIn(tester, 'alice');
    await _openSettings(tester);
    final Finder selector =
        find.byKey(const Key('account_display_language_en-0'));
    await tester.scrollUntilVisible(selector, 250,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(selector);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Arabic').last);
    // Let the dropdown route finish closing without settling the active save
    // indicator animation.
    await tester.pump(const Duration(milliseconds: 500));
    Finder settingsLanguageDropdown() => find.descendant(
        of: find.byType(SettingsScreen),
        matching: find.byType(DropdownButton<String>));

    Finder settingsLanguageText(String value) => find.descendant(
        of: settingsLanguageDropdown(), matching: find.text(value));

    // Pump bounded frames while the request is deliberately held by the test.
    // Waiting on pumpAndSettle here would never settle while the progress
    // indicator is animating.
    for (var i = 0; i < 20 && !updateStarted.isCompleted; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    try {
      expect(updateStarted.isCompleted, isTrue,
          reason: 'the language update request should reach the fake API');
      expect(settingsLanguageText('English'), findsOneWidget);
      expect(settingsLanguageText('Arabic'), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      final DropdownButton<String> pendingSelector =
          tester.widget(find.byKey(const Key('account_display_language_en-0')));
      expect(pendingSelector.value, 'en');
      expect(pendingSelector.onChanged, isNull);
      expect(fake.displayLanguage, 'en');

      allowUpdate.complete();
      for (var i = 0;
          i < 20 && settingsLanguageText('العربية').evaluate().isEmpty;
          i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(fake.displayLanguage, 'ar');
      expect(settingsLanguageText('العربية'), findsOneWidget);
      expect(Directionality.of(tester.element(find.byType(SettingsScreen))),
          TextDirection.rtl);
    } finally {
      if (!allowUpdate.isCompleted) allowUpdate.complete();
    }
  });

  testWidgets('late Settings save after logout preserves logged-out choice',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com';
    fake.passwords['alice'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore()..value = 'en';
    final Completer<void> updateStarted = Completer<void>();
    final Completer<void> allowUpdate = Completer<void>();
    fake.adapter.beforeRespond = (request) async {
      if (request.path.endsWith('/auth/display-language')) {
        if (!updateStarted.isCompleted) updateStarted.complete();
        await allowUpdate.future;
      }
    };

    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await _signIn(tester, 'alice');
    await _openSettings(tester);
    final Finder selector =
        find.byKey(const Key('account_display_language_en-0'));
    await tester.scrollUntilVisible(selector, 250,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(selector);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Arabic').last);
    await tester.pump(const Duration(milliseconds: 500));
    for (var i = 0; i < 20 && !updateStarted.isCompleted; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }

    try {
      expect(updateStarted.isCompleted, isTrue);
      final Finder logout = find.text('Log out');
      await tester.scrollUntilVisible(logout, 250,
          scrollable: find.byType(Scrollable).first);
      await tester.tap(logout);
      // The save spinner is still active until logout removes Settings, so
      // use bounded frames rather than pumpAndSettle.
      for (var i = 0;
          i < 20 && find.byKey(const Key('login_submit')).evaluate().isEmpty;
          i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      // Let any auth-route transition finish using a bounded pump while the
      // held save indicator may still be active in the previous route.
      await tester.pump(const Duration(milliseconds: 500));
      Finder loggedOutLanguageText(String value) => find.descendant(
          of: find.byKey(const Key('display_language_selector')),
          matching: find.text(value));
      expect(find.byKey(const Key('login_submit')), findsOneWidget);
      expect(loggedOutLanguageText('English'), findsOneWidget);
      expect(loggedOutLanguageText('العربية'), findsNothing);

      allowUpdate.complete();
      for (var i = 0; i < 20; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(find.byKey(const Key('login_submit')), findsOneWidget);
      expect(loggedOutLanguageText('English'), findsOneWidget);
      expect(loggedOutLanguageText('العربية'), findsNothing);
      expect(fake.displayLanguage, 'ar');
      expect(await languageStore.readAccount('account-alice'), 'ar');
    } finally {
      if (!allowUpdate.isCompleted) allowUpdate.complete();
    }
  });

  testWidgets('password registration sends the selected Arabic language',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]));
    await tester.pumpAndSettle();
    await _selectArabicOnAuth(tester);
    await tester.tap(find.text('إنشاء حساب'));
    await tester.pumpAndSettle();
    await _enter(tester, const Key('register_username'), 'arabic_player');
    await _enter(tester, const Key('register_password'), 'password-123');
    await _enter(tester, const Key('register_confirm'), 'password-123');
    await tester.tap(find.byKey(const Key('register_submit')));
    await tester.pumpAndSettle();

    expect(fake.registeredDisplayLanguage, 'ar');
    final request = fake.adapter.requests
        .singleWhere((request) => request.path == '/auth/register');
    expect(request.body['display_language'], 'ar');
    expect(Directionality.of(tester.element(find.byType(Scaffold).first)),
        TextDirection.rtl);
  });

  testWidgets('Google signup sends the selected Arabic language',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore();
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      systemDisplayLanguageProvider.overrideWithValue('en'),
      googleAuthGatewayProvider.overrideWithValue(google),
    ]));
    await tester.pumpAndSettle();
    await _selectArabicOnAuth(tester);
    await tester.tap(find.text('المتابعة باستخدام Google'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('google_signup_username')), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('google_signup_submit')));
    await tester.pumpAndSettle();

    final request = fake.adapter.requests
        .singleWhere((request) => request.path == '/auth/google/complete');
    expect(request.body['display_language'], 'ar');
    expect(fake.displayLanguage, 'ar');
    expect(Directionality.of(tester.element(find.byType(Scaffold).first)),
        TextDirection.rtl);
  });

  testWidgets(
      'saved account language wins; logout restores local choice and account switch isolates cache',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()
      ..profileExists = true
      ..recoveryEmail = 'player@example.com'
      ..displayLanguage = 'ar';
    fake.passwords['alice'] = 'password-123';
    fake.passwords['bob'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryDisplayLanguageStore languageStore =
        InMemoryDisplayLanguageStore()..value = 'en';

    await tester.pumpWidget(authApp(fake, tokens, extraOverrides: <Override>[
      displayLanguageStoreProvider.overrideWithValue(languageStore),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      systemDisplayLanguageProvider.overrideWithValue('fr'),
    ]));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('display_language_selector')), findsOneWidget);
    expect(find.text('English'), findsOneWidget);

    await _signIn(tester, 'alice');
    final Finder arabicHome = find.text(const MayosCopy('ar').home);
    expect(arabicHome, findsOneWidget);
    expect(Directionality.of(tester.element(arabicHome)), TextDirection.rtl);
    expect(await languageStore.readAccount('account-alice'), 'ar');

    await _logout(tester);
    expect(find.byKey(const Key('display_language_selector')), findsOneWidget);
    expect(find.text('English'), findsOneWidget);
    expect(languageStore.accountValues, containsPair('account-alice', 'ar'));

    fake.displayLanguage = 'en';
    await _signIn(tester, 'bob');
    expect(find.text('Home'), findsOneWidget);
    expect(Directionality.of(tester.element(find.text('Home'))),
        TextDirection.ltr);
    expect(await languageStore.readAccount('account-bob'), 'en');
    expect(await languageStore.readAccount('account-alice'), 'ar');
  });
}

Future<void> _signIn(WidgetTester tester, String username) async {
  await tester.enterText(find.byKey(const Key('login_username')), username);
  await tester.enterText(
      find.byKey(const Key('login_password')), 'password-123');
  await tester.tap(find.byKey(const Key('login_submit')));
  await tester.pumpAndSettle();
}

Future<void> _selectArabicOnAuth(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('display_language_selector')));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Arabic').last);
  await tester.pumpAndSettle();
}

Future<void> _enter(WidgetTester tester, Key key, String value) async {
  final Finder field = find.byKey(key);
  await tester.ensureVisible(field);
  await tester.enterText(field, value);
}

Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await tester.pumpAndSettle();
}

Future<void> _logout(WidgetTester tester) async {
  final Finder settings = find.byIcon(Icons.settings_outlined);
  if (settings.evaluate().isNotEmpty) {
    await tester.tap(settings);
  } else {
    await tester.tap(find.byKey(const Key('mode_avatar_button')));
    await tester.pumpAndSettle();
    final Finder settingsLabel = find.text('Settings').evaluate().isNotEmpty
        ? find.text('Settings')
        : find.text('الإعدادات');
    await tester.tap(settingsLabel);
  }
  await tester.pumpAndSettle();
  final Finder settingsList = find.byKey(const Key('settings_section_list'));
  final Finder logOut = find.byWidgetPredicate(
    (Widget widget) =>
        widget is Text &&
        (widget.data == 'Log out' || widget.data == 'تسجيل الخروج'),
  );
  await tester.scrollUntilVisible(
    logOut,
    250,
    scrollable: find.descendant(
      of: settingsList,
      matching: find.byType(Scrollable),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(logOut);
  await tester.pumpAndSettle();
}

class _LateTokenReadFailure extends InMemoryTokenStore {
  final Completer<String?> delayedRead = Completer<String?>();
  int _reads = 0;

  @override
  Future<String?> read() {
    _reads++;
    if (_reads == 2) return delayedRead.future;
    return super.read();
  }
}

class _LateTokenAccountIdRead extends InMemoryTokenStore {
  final Completer<String?> delayedAccountId = Completer<String?>();

  @override
  Future<String?> readAccountId() => delayedAccountId.future;
}

class _ObservedDisplayLanguageStore extends InMemoryDisplayLanguageStore {
  _ObservedDisplayLanguageStore({String? initialValue}) {
    value = initialValue;
  }

  final Completer<void> accountRead = Completer<void>();

  @override
  Future<String?> readAccount(String accountId) async {
    final String? cached = await super.readAccount(accountId);
    if (!accountRead.isCompleted) accountRead.complete();
    return cached;
  }
}
