import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches, then a few more so route
/// transitions settle without depending on `pumpAndSettle`.
Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 30}) async {
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

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake,
    {String languageCode = 'en'}) async {
  fake.displayLanguage = languageCode;
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        systemDisplayLanguageProvider.overrideWithValue(languageCode),
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
      tester, find.text(fake.coach ? 'Roster' : 'Home'));
}

/// A signed-in, onboarded player with a recovery email, optionally a coach.
FakeMayosApi _signedInFake({required bool coach}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = coach;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<void> _openPlan(WidgetTester tester, {String languageCode = 'en'}) async {
  await _openSettings(tester, languageCode: languageCode);
  final Finder coachPlan = find.text(
    languageCode == 'ar' ? 'خطة المدرب' : 'Coach plan',
  );
  if (coachPlan.evaluate().isNotEmpty) {
    await tester.tap(coachPlan);
    await _pumpUntilFound(
      tester,
      find.text(languageCode == 'ar' ? 'المدرب Free' : 'Coach Free'),
    );
  } else {
    await tester.tap(find.text(languageCode == 'ar' ? 'خطة اللاعب' : 'Lifter plan'));
    await _pumpUntilFound(
      tester,
      find.text(languageCode == 'ar' ? 'اللاعب Free' : 'Lifter Free'),
    );
  }
}

/// Player mode carries the header Settings icon; Coach mode reaches Settings
/// from the mode sheet (#119).
Future<void> _openSettings(WidgetTester tester,
    {String languageCode = 'en'}) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    final Finder settings = find.text(languageCode == 'ar' ? 'الإعدادات' : 'Settings');
    await _pumpUntilFound(tester, settings);
    await tester.tap(settings);
  }
  await _pumpUntilFound(
    tester,
    find.text(languageCode == 'ar' ? 'المظهر' : 'Appearance'),
  );
}

void main() {
  test('missing server plan state cannot be inferred as Free', () {
    expect(
      () => Account.fromJson(<String, dynamic>{
        'account_id': 'account-alice',
        'trainee_id': 'alice',
        'capabilities': <String, dynamic>{'player': true, 'coach': true},
      }),
      throwsFormatException,
    );
  });

  test('Account parses independent Lifter and Coach plan states', () {
    final Account account = Account.fromJson(<String, dynamic>{
      'account_id': 'account-alice',
      'trainee_id': 'alice',
      'capabilities': <String, dynamic>{'player': true, 'coach': true},
      'plans': <String, dynamic>{
        'lifter': <String, dynamic>{'plan': 'pro', 'status': 'active'},
        'coach': <String, dynamic>{'plan': 'free', 'status': 'active'},
      },
    });

    expect(account.plans.lifter!.isPro, isTrue);
    expect(account.plans.coach!.isFree, isTrue);
    // Dropping the coach capability drops only the Coach plan.
    expect(account.plans.withoutCoach().coach, isNull);
    expect(account.plans.withoutCoach().lifter!.isPro, isTrue);
  });

  test('unknown Lifter allowance status does not break account parsing', () {
    final Account account = Account.fromJson(<String, dynamic>{
      'account_id': 'account-alice',
      'trainee_id': 'alice',
      'capabilities': <String, dynamic>{'player': true, 'coach': false},
      'plans': <String, dynamic>{
        'lifter': <String, dynamic>{'plan': 'free', 'status': 'active'},
      },
      'lifter_ai_allowance': <String, dynamic>{
        'mode': 'launch',
        'status': 'future_allowance_status',
        'request_limit': 5,
        'requests_used': 1,
        'requests_remaining': 4,
        'resource_limit': 1000,
        'resource_used': 200,
        'reset_at': '2026-10-18T00:00:00+00:00',
      },
    });

    expect(account.lifterAiAllowance!.status, 'available');
  });

  test('valid plans with malformed capabilities surfaces ApiException',
      () async {
    final FakeApiAdapter adapter = FakeApiAdapter((FakeRequest request) {
      return FakeResponse(200, <String, dynamic>{
        'account_id': 'account-alice',
        'trainee_id': 'alice',
        'capabilities': 'not-a-map',
        'plans': <String, dynamic>{
          'lifter': <String, dynamic>{'plan': 'free', 'status': 'active'},
        },
      });
    });
    final ApiClient client = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
    );

    await expectLater(
      client.currentAccount(),
      throwsA(isA<ApiException>()),
    );
  });

  testWidgets('single-capability player sees Lifter Free and honest benefits',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    await _pumpApp(tester, fake);
    await _openPlan(tester);

    expect(find.text('Lifter Free'), findsOneWidget);
    expect(find.text('Coach Free'), findsNothing);
    expect(find.text('Ongoing plan — not a trial.'), findsOneWidget);
    for (final String benefit in <String>[
      'Automatic training program',
      'Weekly volume and personal-record dashboard',
      'Coaching assignment with your coach',
    ]) {
      expect(find.text(benefit), findsOneWidget);
    }

    // Truthful core Free: no claim of features still unbuilt.
    expect(find.textContaining('logging'), findsNothing);
    expect(find.textContaining('history'), findsNothing);
    expect(find.textContaining('alert'), findsNothing);
    expect(find.textContaining('publish'), findsNothing);
  });

  testWidgets('Coach mode shows only the Coach plan for a dual-capability account',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake);
    await _openPlan(tester);

    expect(find.text('Coach Free'), findsOneWidget);
    expect(find.text('Coach profile and player invites'), findsOneWidget);
    expect(find.text('Active roster with assignment status'), findsOneWidget);
    expect(find.text('Lifter Free'), findsNothing);
    expect(find.text('Automatic training program'), findsNothing);
  });

  testWidgets('server-owned plan state is displayed, not inferred',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.lifterPlan = 'pro';
    await _pumpApp(tester, fake);
    await _openSettings(tester);
    await tester.tap(find.text('Lifter plan'));
    await _pumpUntilFound(tester, find.text('Lifter Pro'));

    expect(find.text('Lifter Pro'), findsOneWidget);
    expect(find.text('Lifter Free'), findsNothing);
  });

  testWidgets('Lifter plan discloses the same allowance in English and Arabic',
      (WidgetTester tester) async {
    for (final String languageCode in <String>['en', 'ar']) {
      final FakeMayosApi fake = _signedInFake(coach: false);
      fake.lifterAiAllowance = <String, dynamic>{
        'mode': 'launch',
        'status': 'warning',
        'request_limit': 12,
        'requests_used': 3,
        'requests_remaining': 9,
        'resource_limit': 1000,
        'resource_used': 800,
        'reset_at': '2026-10-18T00:00:00+00:00',
      };
      await _pumpApp(tester, fake, languageCode: languageCode);
      await _openPlan(tester, languageCode: languageCode);

      if (languageCode == 'en') {
        expect(find.textContaining('12 complete assistant answers'), findsOneWidget);
        expect(find.textContaining('Longer conversations and Arabic replies'), findsOneWidget);
        expect(find.textContaining('9 assistant requests remain today'), findsOneWidget);
      } else {
        expect(find.textContaining('12'), findsWidgets);
        expect(find.textContaining('إجابة مكتملة من المساعد'), findsOneWidget);
        expect(find.textContaining('الردود بالعربية موارد أكثر'), findsOneWidget);
        expect(find.textContaining('المتبقي من طلبات المساعد اليوم'), findsOneWidget);
      }
      expect(find.textContaining('2026-10-18'), findsWidgets);
      expect(find.textContaining('00:00 UTC'), findsWidgets);
      await tester.pumpWidget(const SizedBox());
    }
  });

  testWidgets('Coach plan shows its own warning and localized cutoff state',
      (WidgetTester tester) async {
    for (final String languageCode in <String>['en', 'ar']) {
      for (final String status in <String>[
        'warning',
        'resource_cutoff',
        'requests_exhausted',
      ]) {
        final FakeMayosApi fake = _signedInFake(coach: true);
        fake.lifterAiAllowance = <String, dynamic>{
          'mode': 'launch',
          'status': 'warning',
          'request_limit': 100,
          'requests_used': 1,
          'requests_remaining': 99,
          'resource_limit': 1000,
          'resource_used': 800,
          'reset_at': '2026-10-18T00:00:00+00:00',
        };
        fake.coachAiAllowance = <String, dynamic>{
          'mode': 'launch',
          'status': status,
          'request_limit': 8,
          'requests_used': status == 'requests_exhausted' ? 8 : 2,
          'requests_remaining': status == 'requests_exhausted' ? 0 : 6,
          'resource_limit': 1000,
          'resource_used': status == 'warning' ? 800 : 1000,
          'reset_at': '2026-10-18T00:00:00+00:00',
        };
        await _pumpApp(tester, fake, languageCode: languageCode);
        await _openPlan(tester, languageCode: languageCode);

        if (languageCode == 'en') {
          expect(find.textContaining('8 complete Coach assistant answers'), findsOneWidget);
          expect(find.textContaining('Longer conversations and Arabic replies'), findsOneWidget);
          expect(
            find.textContaining(
              status == 'requests_exhausted'
                  ? '0 requests remain'
                  : '6 requests remain',
            ),
            findsOneWidget,
          );
          expect(
            find.textContaining(
              status == 'warning'
                  ? 'Coach assistant resources are nearing'
                  : 'today’s Coach assistant resource limit',
            ),
            findsOneWidget,
          );
          expect(find.textContaining('99 assistant requests remain'), findsNothing);
        } else {
          expect(find.textContaining('إجابة مكتملة من مساعد المدرب'), findsOneWidget);
          expect(find.textContaining('الردود بالعربية موارد أكثر'), findsOneWidget);
          expect(find.textContaining('المتبقي من الطلبات'), findsOneWidget);
          expect(
            find.textContaining(
              status == 'warning' ? 'موارد مساعد المدرب تقترب' : 'وصلت إلى حد موارد مساعد المدرب اليومي',
            ),
            findsOneWidget,
          );
        }
        expect(find.textContaining('2026-10-18'), findsWidgets);
        expect(find.textContaining('00:00 UTC'), findsWidgets);
        await tester.pumpWidget(const SizedBox());
      }
    }
  });
}
