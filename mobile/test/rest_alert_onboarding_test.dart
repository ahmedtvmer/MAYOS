import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/rest_alert_permission_prompt_store.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/onboarding/rest_alert_permission_screen.dart';
import 'package:mayos_mobile/src/features/player/shell/player_shell.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_mayos_api.dart';
import 'support/fake_rest_alert_permission_access.dart';

const Map<String, Object> _answers = <String, Object>{
  'gender': 'female',
  'proportions': 'long_legs',
  'age': 29,
  'height_cm': 168.0,
  'weight_kg': 64.5,
  'training_age_years': 3.0,
  'current_goal': 'build glutes and legs',
  'long_term_goal': 'stronger and more muscular',
  'weekly_frequency': 4,
  'equipment_access': 'Commercial gym',
  'injuries_or_limitations': 'None',
  'stress_and_sleep': 'moderate stress, 7 hours sleep',
};

FakeMayosApi _api({String languageCode = 'en'}) {
  return FakeMayosApi()
    ..issuedToken = 'token-alice'
    ..currentUsername = 'alice'
    ..tokenValid = true
    ..profileExists = false
    ..recoveryEmail = 'alice@example.com'
    ..displayLanguage = languageCode
    ..intakeDisclosureAcknowledged = true
    ..intakeAnswers.addAll(_answers);
}

Override _apiOverride(FakeMayosApi fake) {
  return apiClientProvider.overrideWith((ref) {
    final ApiClient client = ApiClient(
      tokens: ref.watch(tokenStoreProvider),
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );
    client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
    client.onAccountDeleted = ref.watch(accountDeletedEventsProvider).signal;
    return client;
  });
}

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder) async {
  for (int attempt = 0; attempt < 80; attempt++) {
    if (finder.evaluate().isNotEmpty) return;
    await tester.pump(const Duration(milliseconds: 50));
  }
  fail('Did not find $finder');
}

Future<void> _pumpUntilAbsent(WidgetTester tester, Finder finder) async {
  for (int attempt = 0; attempt < 80; attempt++) {
    if (finder.evaluate().isEmpty) return;
    await tester.pump(const Duration(milliseconds: 50));
  }
  fail('Still found $finder');
}

Future<void> _disposeApp(
  WidgetTester tester,
  ProviderContainer container,
) async {
  await tester.pumpWidget(const SizedBox.shrink());
  container.dispose();
  await tester.pump();
}

Future<ProviderContainer> _completeOnboarding(
  WidgetTester tester, {
  required FakeRestAlertPermissionAccess access,
  required InMemoryRestAlertPermissionPromptStore promptStore,
  String languageCode = 'en',
}) async {
  final FakeMayosApi fake = _api(languageCode: languageCode);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final ProviderContainer container = ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
      themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore()),
      draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
      workoutCacheStoreProvider
          .overrideWithValue(InMemoryWorkoutCacheStore()),
      chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
      systemDisplayLanguageProvider.overrideWithValue(languageCode),
      restAlertPermissionAccessProvider.overrideWithValue(access),
      restAlertPermissionPromptStoreProvider.overrideWithValue(promptStore),
      _apiOverride(fake),
    ],
  );
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.byKey(const Key('onboarding_confirm')));
  await tester.tap(find.byKey(const Key('onboarding_confirm')));
  final Finder allowButton =
      find.byKey(const Key('rest_alert_permission_allow'));
  final Finder home = find.byType(PlayerShell);
  for (int attempt = 0; attempt < 80; attempt++) {
    if (allowButton.evaluate().isNotEmpty || home.evaluate().isNotEmpty) break;
    await tester.pump(const Duration(milliseconds: 50));
  }
  expect(
    allowButton.evaluate().isNotEmpty || home.evaluate().isNotEmpty,
    isTrue,
    reason: 'Onboarding should reach either the permission prompt or Home.',
  );
  return container;
}

void main() {
  for (final String languageCode in <String>['en', 'ar']) {
    testWidgets(
        'the rest-alert explanation appears after onboarding before Home ($languageCode)',
        (WidgetTester tester) async {
      final FakeRestAlertPermissionAccess access =
          FakeRestAlertPermissionAccess();
      final InMemoryRestAlertPermissionPromptStore store =
          InMemoryRestAlertPermissionPromptStore();
      final ProviderContainer container = await _completeOnboarding(
        tester,
        access: access,
        promptStore: store,
        languageCode: languageCode,
      );

      final bool arabic = languageCode == 'ar';
      expect(find.byType(RestAlertPermissionScreen), findsOneWidget);
      expect(find.byType(PlayerShell), findsNothing);
      expect(
        find.text(arabic ? 'تنبيهات مؤقت الراحة' : 'Rest timer alerts'),
        findsOneWidget,
      );
      expect(
        find.text(arabic
            ? 'يصلك تنبيه عند انتهاء الراحة، حتى عندما تكون الشاشة مطفأة.'
            : 'Get an alert when your rest ends, even with the screen off.'),
        findsOneWidget,
      );
      expect(find.text(arabic ? 'السماح' : 'Allow'), findsOneWidget);
      expect(find.text(arabic ? 'ليس الآن' : 'Not now'), findsOneWidget);
      expect(store.shownAccounts, contains('account-alice'));
      await _disposeApp(tester, container);
    });
  }

  testWidgets('Allow requests notifications before exact alarms and opens Home',
      (WidgetTester tester) async {
    final FakeRestAlertPermissionAccess access =
        FakeRestAlertPermissionAccess();
    final ProviderContainer container = await _completeOnboarding(
      tester,
      access: access,
      promptStore: InMemoryRestAlertPermissionPromptStore(),
    );

    await tester.tap(find.byKey(const Key('rest_alert_permission_allow')));
    await _pumpUntilAbsent(tester, find.byType(RestAlertPermissionScreen));
    await _pumpUntilFound(tester, find.byType(PlayerShell));

    expect(access.requests, <String>['notifications', 'exact_alarm']);
    expect(find.byType(RestAlertPermissionScreen), findsNothing);
    await _disposeApp(tester, container);
  });

  testWidgets('Not now requests nothing and opens Home',
      (WidgetTester tester) async {
    final FakeRestAlertPermissionAccess access =
        FakeRestAlertPermissionAccess();
    final ProviderContainer container = await _completeOnboarding(
      tester,
      access: access,
      promptStore: InMemoryRestAlertPermissionPromptStore(),
    );

    await tester.tap(find.byKey(const Key('rest_alert_permission_not_now')));
    await _pumpUntilAbsent(tester, find.byType(RestAlertPermissionScreen));
    await _pumpUntilFound(tester, find.byType(PlayerShell));

    expect(access.requests, isEmpty);
    expect(find.byType(RestAlertPermissionScreen), findsNothing);
    await _disposeApp(tester, container);
  });

  testWidgets('a shown explanation is not displayed again for the account',
      (WidgetTester tester) async {
    final FakeRestAlertPermissionAccess access =
        FakeRestAlertPermissionAccess();
    final InMemoryRestAlertPermissionPromptStore store =
        InMemoryRestAlertPermissionPromptStore();
    final ProviderContainer container = await _completeOnboarding(
      tester,
      access: access,
      promptStore: store,
    );

    await tester.tap(find.byKey(const Key('rest_alert_permission_not_now')));
    await _pumpUntilAbsent(tester, find.byType(RestAlertPermissionScreen));
    await _pumpUntilFound(tester, find.byType(PlayerShell));
    container.read(routerProvider).go(restAlertPermissionPath);
    await _pumpUntilAbsent(tester, find.byType(RestAlertPermissionScreen));
    await _pumpUntilFound(tester, find.byType(PlayerShell));

    expect(find.byType(RestAlertPermissionScreen), findsNothing);
    expect(access.requests, isEmpty);
    await _disposeApp(tester, container);
  });

  testWidgets('the explanation is skipped when both permissions are granted',
      (WidgetTester tester) async {
    final FakeRestAlertPermissionAccess access =
        FakeRestAlertPermissionAccess(granted: true);
    final InMemoryRestAlertPermissionPromptStore store =
        InMemoryRestAlertPermissionPromptStore();
    final ProviderContainer container = await _completeOnboarding(
      tester,
      access: access,
      promptStore: store,
    );
    await _pumpUntilFound(tester, find.byType(PlayerShell));
    await _pumpUntilAbsent(tester, find.byType(RestAlertPermissionScreen));

    expect(access.grantedChecks, 1);
    expect(access.requests, isEmpty);
    expect(find.byType(RestAlertPermissionScreen), findsNothing);
    expect(store.shownAccounts, isEmpty);
    await _disposeApp(tester, container);
  });

  testWidgets('unsupported platforms continue to Home without the prompt',
      (WidgetTester tester) async {
    final FakeRestAlertPermissionAccess access =
        FakeRestAlertPermissionAccess(supported: false);
    final ProviderContainer container = await _completeOnboarding(
      tester,
      access: access,
      promptStore: InMemoryRestAlertPermissionPromptStore(),
    );

    await _pumpUntilFound(tester, find.byType(PlayerShell));
    await _pumpUntilAbsent(tester, find.byType(RestAlertPermissionScreen));
    expect(find.byType(RestAlertPermissionScreen), findsNothing);
    expect(access.grantedChecks, 0);
    expect(access.requests, isEmpty);
    await _disposeApp(tester, container);
  });
}
