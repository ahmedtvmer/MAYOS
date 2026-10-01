import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches, then a few more so route
/// transitions settle without depending on `pumpAndSettle` (indeterminate
/// progress indicators never settle).
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

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake) async {
  // A tall surface keeps the profile form's Save button on screen without
  // scrolling, so the test can focus on behavior rather than scroll plumbing.
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

/// A signed-in, onboarded player with a recovery email, optionally already a coach.
FakeMayosApi _signedInFake({required bool coach}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = coach;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  fake.coachBio = 'Strength coach.';
  fake.coachSpecialization = 'Powerlifting';
  fake.coachCapacity = 12;
  return fake;
}

/// Player mode carries the header Settings icon; Coach mode reaches Settings
/// from the mode sheet (#119).
Future<void> _openSettings(WidgetTester tester) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  testWidgets('coach profile loads, validates, and saves', (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake);

    // The coach shell hosts the profile editor as its Profile tab (#119).
    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(find.text('Coach Alice'), findsOneWidget);
    expect(find.text('Powerlifting'), findsOneWidget);

    final Finder fields = find.byType(TextFormField);

    // Capacity validation rejects 0 with no server write.
    await tester.enterText(fields.at(3), '0');
    await tester.tap(find.text('Save profile'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Capacity must be between 1 and 200.'), findsOneWidget);
    expect(fake.coachCapacity, 12);

    // Display name is required.
    await tester.enterText(fields.at(0), '   ');
    await tester.enterText(fields.at(3), '15');
    await tester.tap(find.text('Save profile'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Enter a display name.'), findsOneWidget);
    expect(fake.coachCapacity, 12);

    // A valid save persists every field.
    await tester.enterText(fields.at(0), 'Coach A');
    await tester.enterText(fields.at(1), 'Hypertrophy');
    await tester.enterText(fields.at(2), 'New bio');
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Coach profile saved.'));
    expect(fake.coachDisplayName, 'Coach A');
    expect(fake.coachSpecialization, 'Hypertrophy');
    expect(fake.coachBio, 'New bio');
    expect(fake.coachCapacity, 15);
  });

  testWidgets('coach profile surfaces a load error and retries',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    fake.coachProfileLoadFails = true;
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('The service is unavailable.'));
    expect(find.text('Retry'), findsOneWidget);

    fake.coachProfileLoadFails = false;
    await tester.tap(find.text('Retry'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(find.text('Coach Alice'), findsOneWidget);
  });

  testWidgets('player uses a MAYOS code to unlock coaching',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.validCoachInviteToken = 'coach-invite-token-123456';
    await _pumpApp(tester, fake);

    // A player has no coach tab until the capability is granted.
    expect(find.byIcon(Icons.groups_outlined), findsNothing);

    await _openSettings(tester);

    expect(find.text('Enable coaching'), findsOneWidget);
    expect(find.text('Redeem an owner-issued coach code'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.workspace_premium_outlined));
    await _pumpUntilFound(tester, find.text('Enter your MAYOS coach code'));
    expect(find.text('Become a coach'), findsOneWidget);
    expect(find.text('MAYOS coach code'), findsOneWidget);
    expect(
      find.textContaining('This code comes from MAYOS'),
      findsOneWidget,
    );
    expect(find.textContaining('owner-issued'), findsNothing);
    expect(find.text('Enable coaching'), findsOneWidget);

    await tester.tap(find.text('Enable coaching'));
    await _pumpUntilFound(tester, find.text('Enter your MAYOS coach code.'));

    // A wrong code shows the generic error and grants nothing.
    await tester.enterText(find.byType(TextField), 'wrong-invite-code-123456');
    await tester.tap(find.text('Enable coaching'));
    await _pumpUntilFound(tester, find.text('Invalid or expired invite code.'));
    expect(fake.coach, isFalse);

    // The valid code grants the capability and routes to the profile editor.
    await tester.enterText(find.byType(TextField), 'coach-invite-token-123456');
    await tester.tap(find.text('Enable coaching'));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(fake.coach, isTrue);
    expect(find.byType(ModeAvatarButton), findsOneWidget);
  });

  testWidgets('an un-onboarded player can become a coach from onboarding',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false)
      ..profileExists = false
      ..validCoachInviteToken = 'coach-invite-token-123456';
    await _pumpApp(tester, fake);

    expect(find.text('Before we begin'), findsOneWidget);
    await tester.tap(find.text("I'm a coach — enter coach code"));
    await _pumpUntilFound(
        tester, find.byKey(const Key('onboarding_coach_code')));

    await tester.enterText(find.byKey(const Key('onboarding_coach_code')),
        'wrong-invite-code-123456');
    await tester.tap(find.byKey(const Key('onboarding_redeem_coach_code')));
    await _pumpUntilFound(tester, find.text('Invalid or expired invite code.'));
    expect(find.text('Before we begin'), findsOneWidget);
    expect(fake.coach, isFalse);

    await tester.enterText(find.byKey(const Key('onboarding_coach_code')),
        'coach-invite-token-123456');
    await tester.tap(find.byKey(const Key('onboarding_redeem_coach_code')));
    await _pumpUntilFound(tester, find.text('Roster'));
    expect(fake.coach, isTrue);
    expect(find.text('Before we begin'), findsNothing);
    expect(find.text('Create my program'), findsNothing);
  });

  testWidgets(
      'a committed grant is not reported as failed when a follow-up read would fail',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.validCoachInviteToken = 'coach-invite-token-123456';
    await _pumpApp(tester, fake);

    await _openSettings(tester);

    await tester.tap(find.byIcon(Icons.workspace_premium_outlined));
    await _pumpUntilFound(tester, find.text('Enter your MAYOS coach code'));

    final int meCallsBefore =
        fake.adapter.requests.where((r) => r.path == '/auth/me').length;
    // Any post-redeem account read would now fail transiently.
    fake.meFails = true;

    await tester.enterText(find.byType(TextField), 'coach-invite-token-123456');
    await tester.tap(find.text('Enable coaching'));

    // The grant stands and the coach surface opens without a follow-up read.
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(fake.coach, isTrue);
    expect(find.text('Invalid or expired invite code.'), findsNothing);
    expect(
      fake.adapter.requests.where((r) => r.path == '/auth/me').length,
      meCallsBefore,
    );
  });

  testWidgets('coach account does not see the Enable coaching setting',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake);

    await _openSettings(tester);

    expect(find.text('Enable coaching'), findsNothing);
  });

  testWidgets('app resume refreshes live capabilities', (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    await _pumpApp(tester, fake);
    await _openSettings(tester);
    // A player has no coach destinations and may still redeem an invite.
    expect(find.text('Enable coaching'), findsOneWidget);
    expect(find.byType(ModeAvatarButton), findsNothing);

    // A grant happened elsewhere while the app was backgrounded: the settings
    // entry flips to the coach state (#119 removed the coach-only tiles).
    fake.coach = true;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    // The rebuild drops the player-only invite entry once the capability lands.
    for (int i = 0;
        i < 40 && find.text('Enable coaching').evaluate().isNotEmpty;
        i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('Enable coaching'), findsNothing);

    // Leaving Settings for Player mode now lands in Coach mode: the account
    // gained the capability and has no stored mode, so it defaults to Coach.
    await tester.tap(find.byTooltip('Back'));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(find.byType(ModeAvatarButton), findsOneWidget);
  });
}
