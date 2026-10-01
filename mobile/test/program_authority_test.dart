import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_screen.dart';
import 'package:mayos_mobile/src/features/player/profile/profile_screen.dart';
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

Override _apiOverride(FakeMayosApi fake) =>
    apiClientProvider.overrideWith((ref) {
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
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        _apiOverride(fake),
        deviceTimezoneProvider
            .overrideWithValue(Future<String>.value('America/New_York')),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
}

/// Opens the profile editor and changes training days 4 → 3, warranting a rebuild.
Future<void> _changeTrainingDays(WidgetTester tester) async {
  await _openSettings(tester);
  await tester.tap(find.text('Profile'));
  await _pumpUntilFound(tester, find.text('Training profile'));

  await tester.tap(find.byType(DropdownButtonFormField<int>));
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(find.text('3').last);
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> _openProfile(WidgetTester tester) async {
  await _openSettings(tester);
  await tester.tap(find.text('Profile'));
  await _pumpUntilFound(tester, find.text('Training profile'));
}

String _todayIso() {
  final DateTime now = DateTime.now();
  return '${now.year.toString().padLeft(4, '0')}-'
      '${now.month.toString().padLeft(2, '0')}-'
      '${now.day.toString().padLeft(2, '0')}';
}

Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  testWidgets('blocked profile update shows the coach message, not a rebuild',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.profileBlocked = true;
    fake.coachControlsProgram = true;
    await _pumpApp(tester, fake);

    await _changeTrainingDays(tester);
    await tester.tap(find.text('Save profile'));
    expect(find.text('This rebuilds your program'), findsNothing);
    expect(fake.profileUpdateBodies, isEmpty);
    await _pumpUntilFound(tester, find.text(_coachMessage));

    expect(find.text(_coachMessage), findsOneWidget);
    expect(find.text('Program rebuilt.'), findsNothing);
    // The profile update itself still applied.
    expect(fake.weeklyFrequency, 3);
  });

  testWidgets('normal profile update announces the rebuild', (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);

    await _changeTrainingDays(tester);
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('This rebuilds your program'));
    await tester.tap(find.byKey(const Key('profile_rebuild_confirm_button')));
    await _pumpUntilFound(tester, find.text('Program rebuilt.'));

    expect(find.text('Program rebuilt.'), findsOneWidget);
    expect(find.text(_coachMessage), findsNothing);
    expect(fake.weeklyFrequency, 3);
  });

  testWidgets('Training profile pre-fills editable values and saves goal/weight without rebuild',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.currentGoal = 'Build muscle';
    fake.injuriesOrLimitations = 'Right shoulder limitation';
    fake.weightKg = 82.5;
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    expect(find.text('Build muscle'), findsOneWidget);
    expect(find.text('Right shoulder limitation'), findsOneWidget);
    expect(find.text('82.5'), findsOneWidget);

    await tester.enterText(
        find.byKey(const Key('current_goal_field')), 'Get stronger');
    await tester.enterText(find.byKey(const Key('weight_kg_field')), '83');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Profile saved.'));

    expect(fake.currentGoal, 'Get stronger');
    expect(fake.weightKg, 83);
    expect(fake.profileRebuildCalls, 0);
    expect(find.text('This rebuilds your program'), findsNothing);
  });

  testWidgets('saving another fact preserves saved multi-decimal weight',
      (tester) async {
    final FakeMayosApi fake = _playerFake()..weightKg = 82.55;
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    expect(find.text('82.55'), findsOneWidget);
    await tester.enterText(
        find.byKey(const Key('current_goal_field')), 'Build muscle');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Profile saved.'));

    expect(fake.currentGoal, 'Build muscle');
    expect(fake.weightKg, 82.55);
    expect(fake.profileUpdateBodies.single.containsKey('weight_kg'), isFalse);
  });

  testWidgets('offline Training profile save changes nothing', (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);
    await tester.enterText(
        find.byKey(const Key('current_goal_field')), 'Prepare for a marathon');
    fake.failOffline('PUT', '/profile');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text(needsConnectionMessage));

    expect(fake.currentGoal, 'Get stronger');
    expect(fake.profileUpdateBodies, isEmpty);
    expect(find.text(needsConnectionMessage), findsOneWidget);
  });

  testWidgets('offline save after rebuild confirmation changes nothing',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _changeTrainingDays(tester);
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('This rebuilds your program'));
    await tester.tap(find.byKey(const Key('profile_rebuild_confirm_button')));
    fake.failOffline('PUT', '/profile');
    await _pumpUntilFound(tester, find.text(needsConnectionMessage));

    expect(fake.weeklyFrequency, 4);
    expect(fake.profileUpdateBodies, isEmpty);
    expect(find.text(needsConnectionMessage), findsOneWidget);
  });

  testWidgets('empty saved goal is omitted while saving another profile fact',
      (tester) async {
    final FakeMayosApi fake = _playerFake()..currentGoal = '';
    await _pumpApp(tester, fake);
    await _openProfile(tester);
    await tester.enterText(find.byKey(const Key('weight_kg_field')), '80');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Profile saved.'));

    expect(fake.currentGoal, '');
    expect(fake.weightKg, 80);
    expect(
        fake.profileUpdateBodies.single.containsKey('current_goal'), isFalse);
  });

  testWidgets('invalid weight is rejected before rebuild confirmation',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);
    await tester.enterText(find.byKey(const Key('weight_kg_field')), '251');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(
        tester, find.text('Weight must be between 30 and 250 kg.'));

    expect(find.text('This rebuilds your program'), findsNothing);
    expect(find.text('Weight must be between 30 and 250 kg.'), findsOneWidget);
    expect(fake.profileUpdateBodies, isEmpty);
  });

  testWidgets('saving the schedule leaves the training-days setting untouched',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    // The schedule is its own section, seeded from the service's current version.
    expect(find.text('Training schedule'), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('weekday_chip_2')));
    await tester.tap(find.byKey(const Key('weekday_chip_2')));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('timezone_field')));
    await tester.enterText(
        find.byKey(const Key('timezone_field')), 'Europe/Paris');
    await tester.ensureVisible(find.byKey(const Key('save_schedule_button')));
    await tester.tap(find.byKey(const Key('save_schedule_button')));
    await _pumpUntilFound(tester, find.text('Training schedule saved.'));

    expect(fake.scheduleVersions.first['timezone'], 'Europe/Paris');
    expect(fake.scheduleVersions.first['weekdays'], <int>[1, 2, 3, 5]);
    // The program's own setting is not rewritten by a schedule save.
    expect(fake.weeklyFrequency, 4);
    final DropdownButton<int> dropdown = tester.widget<DropdownButton<int>>(
      find.descendant(
        of: find.byType(DropdownButtonFormField<int>),
        matching: find.byType(DropdownButton<int>),
      ),
    );
    expect(dropdown.value, 4);
  });

  testWidgets(
      'the timezone field is prefilled from the device when no schedule exists',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.scheduleVersions = <Map<String, dynamic>>[];
    fake.scheduleEmpty = true;
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    final TextField timezone =
        tester.widget<TextField>(find.byKey(const Key('timezone_field')));
    expect(timezone.controller!.text, 'America/New_York');

    await tester.ensureVisible(find.byKey(const Key('weekday_chip_2')));
    await tester.tap(find.byKey(const Key('weekday_chip_2')));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('save_schedule_button')));
    await tester.tap(find.byKey(const Key('save_schedule_button')));
    await _pumpUntilFound(tester, find.text('Training schedule saved.'));

    expect(fake.scheduleVersions.first['weekdays'], <int>[2]);
    expect(fake.scheduleVersions.first['timezone'], 'America/New_York');
  });

  testWidgets('a non-IANA timezone is refused before submit', (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    await tester.ensureVisible(find.byKey(const Key('timezone_field')));
    await tester.enterText(find.byKey(const Key('timezone_field')), 'London');
    await tester.ensureVisible(find.byKey(const Key('save_schedule_button')));
    await tester.tap(find.byKey(const Key('save_schedule_button')));
    await _pumpUntilFound(tester,
        find.text('Enter an IANA timezone, e.g. Europe/London or UTC.'));

    // The server was never asked to save an invalid timezone.
    expect(fake.scheduleVersions.first['timezone'], 'Europe/London');
  });

  testWidgets('a prospective pause can be scheduled and is listed',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);
    await _pumpUntilFound(tester, find.text('Training pause'));

    final Finder profileScrollables = find.descendant(
      of: find.byType(ProfileScreen),
      matching: find.byType(Scrollable),
    );
    await tester.scrollUntilVisible(
      find.text('Pause: 2026-09-24 → 2026-10-01'),
      250,
      scrollable: profileScrollables.first,
    );
    expect(find.text('Pause: 2026-09-24 → 2026-10-01'), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('schedule_pause_button')));
    await tester.tap(find.byKey(const Key('schedule_pause_button')));
    await _pumpUntilFound(tester, find.textContaining('Pause scheduled'));

    expect(fake.trainingPauses.length, 2);
    expect(fake.trainingPauses.first['starts_on'], _todayIso());
    expect(fake.trainingPauses.first['ends_on'], _todayIso());
  });

  testWidgets('a pause starting before today is refused inline',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);
    await _pumpUntilFound(tester, find.text('Training pause'));

    await tester.drag(find.byType(ListView).first, const Offset(0, -1100));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('pause_start_button')));
    await tester.tap(find.byKey(const Key('pause_start_button')));
    await tester.pump(const Duration(milliseconds: 300));
    // Day 1 of the previous month is always in the past, even on the 1st.
    await tester.tap(find.byTooltip('Previous month'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('1'));
    await tester.pump();
    await tester.tap(find.text('OK'));
    await tester.pump(const Duration(milliseconds: 300));

    await tester.ensureVisible(find.byKey(const Key('schedule_pause_button')));
    await tester.tap(find.byKey(const Key('schedule_pause_button')));
    await _pumpUntilFound(
        tester, find.text('A pause must start today or later.'));

    expect(fake.trainingPauses.length, 1);
  });

  testWidgets(
      'null-program confirmation lands home without a fabricated program',
      (tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    fake.issuedToken = 'token-alice';
    fake.currentUsername = 'alice';
    fake.tokenValid = true;
    fake.profileExists = false;
    fake.nullOnboardingProgram = true;
    fake.intakeDisclosureAcknowledged = true;
    fake.intakeAnswers.addAll(<String, Object>{
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
    });
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final GoRouter router = GoRouter(
      initialLocation: '/onboarding',
      routes: <RouteBase>[
        GoRoute(
          path: '/onboarding',
          builder: (_, __) => const OnboardingScreen(),
        ),
        GoRoute(
          path: '/home',
          builder: (_, __) => const Scaffold(
            body: Center(child: Text('HOME')),
          ),
        ),
      ],
    );
    addTearDown(router.dispose);

    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          _apiOverride(fake),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await _pumpUntilFound(tester, find.text('Create my program'));
    await tester.tap(find.text('Create my program'));
    await _pumpUntilFound(tester, find.text('HOME'));

    expect(find.text('HOME'), findsOneWidget);
    expect(find.text('Upper/Lower 4x'), findsNothing);
    expect(fake.intakeProgram!['program_name'], isNull);
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
