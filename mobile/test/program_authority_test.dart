import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

const String _coachMessage =
    'Your assigned coach controls your program. Ask your coach for changes.';

/// Pumps finite frames until [finder] matches, then a few more so transitions
/// settle without depending on `pumpAndSettle` (indeterminate spinners never settle).
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

Override _apiOverride(FakeMayosApi fake) => apiClientProvider.overrideWith((ref) {
      final ApiClient client = ApiClient(
        tokens: ref.watch(tokenStoreProvider),
        baseUrl: 'http://test.local',
        adapter: fake.adapter,
      );
      client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
      return client;
    });

FakeMayosApi _playerFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake) async {
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
        _apiOverride(fake),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Dashboard'));
}

/// Opens the profile editor and changes training days 4 → 3, warranting a rebuild.
Future<void> _changeTrainingDays(WidgetTester tester) async {
  await tester.tap(find.byTooltip('Profile'));
  await _pumpUntilFound(tester, find.text('Training profile'));

  await tester.tap(find.byType(DropdownButtonFormField<int>));
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(find.text('3').last);
  await tester.pump(const Duration(milliseconds: 300));
}

void main() {
  testWidgets('blocked profile update shows the coach message, not a rebuild',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.profileBlocked = true;
    await _pumpApp(tester, fake);

    await _changeTrainingDays(tester);
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text(_coachMessage));

    expect(find.text(_coachMessage), findsOneWidget);
    expect(find.text('Program rebuilt.'), findsNothing);
    // The profile update itself still applied.
    expect(fake.weeklyFrequency, 3);
  });

  testWidgets('normal profile update announces the rebuild',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);

    await _changeTrainingDays(tester);
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Program rebuilt.'));

    expect(find.text('Program rebuilt.'), findsOneWidget);
    expect(find.text(_coachMessage), findsNothing);
    expect(fake.weeklyFrequency, 3);
  });

  testWidgets(
      'null-program onboarding completion finishes without a fabricated program',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.nullOnboardingProgram = true;
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');

    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          _apiOverride(fake),
        ],
        child: const MaterialApp(home: OnboardingScreen()),
      ),
    );

    // Disclosure, then onboarding begins.
    await _pumpUntilFound(tester, find.text('Hosted AI processing'));
    await tester.tap(find.text('Continue'));
    await _pumpUntilFound(tester, find.text('Set up your training'));

    // Answer until the program can be built.
    for (int i = 0;
        i < 4 && find.text('Build my program').evaluate().isEmpty;
        i++) {
      await tester.enterText(find.byType(TextField), 'Four days');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pump(const Duration(milliseconds: 100));
    }
    await tester.tap(find.text('Build my program'));

    await _pumpUntilFound(tester, find.text(_coachMessage));
    expect(find.text(_coachMessage), findsOneWidget);
    expect(find.text('Upper/Lower 4x'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  test('OnboardingCompletion parses null program fields without throwing', () {
    final OnboardingCompletion completion = OnboardingCompletion.fromJson(
        <String, dynamic>{'program_name': null, 'weekly_frequency': null});
    expect(completion.hasProgram, isFalse);
    expect(completion.programName, isNull);
    expect(completion.weeklyFrequency, isNull);
  });
}
