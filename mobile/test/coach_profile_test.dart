import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';
import 'support/coach_layout_harness.dart';

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
  expect(finder, findsWidgets, reason: 'Timed out waiting for $finder');
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  Size logicalSize = const Size(540, 1200),
  String language = 'en',
}) async {
  // A tall surface keeps the profile form's Save button on screen without
  // scrolling, so the test can focus on behavior rather than scroll plumbing.
  tester.view.physicalSize = Size(logicalSize.width * 2, logicalSize.height * 2);
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
        systemDisplayLanguageProvider.overrideWithValue(language),
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
  final String startupLanguage = fake.displayLanguage;
  final Finder initialScreen = !fake.profileExists
      ? find.text(startupLanguage == 'ar' ? 'قبل أن نبدأ' : 'Before we begin')
      : fake.coach
          ? find.text(startupLanguage == 'ar' ? 'علاقات التدريب النشطة' : 'Active assignments')
          : find.text(startupLanguage == 'ar' ? 'الرئيسية' : 'Home');
  await _pumpUntilFound(tester, initialScreen);
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
  testWidgets('Arabic coach notice reader resolves cached request notices',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true)
      ..displayLanguage = 'ar';
    fake.assignmentNotices.add(<String, dynamic>{
      'notice_id': 'request-received',
      'kind': 'program_request',
      'message': 'bob requested a program change. Review it in your roster.',
      'message_code': 'assignment_notice.program_request_received.v1',
      'message_params': <String, dynamic>{'player_name': 'bob'},
      'message_fallback':
          'bob requested a program change. Review it in your roster.',
      'created_at': '2026-10-01T12:00:00Z',
      'read_at': null,
    });
    await _pumpApp(tester, fake);

    await tester.tap(find.text('الملف الشخصي'));
    await _pumpUntilFound(tester, find.text('الملف الشخصي للمدرب'));

    expect(
      find.textContaining('طلبًا لتغيير البرنامج التدريبي.'),
      findsOneWidget,
    );
    expect(
      find.text('bob requested a program change. Review it in your roster.'),
      findsNothing,
    );
  });

  testWidgets(
      'coach notice reader switches cached structured copy and retains fallbacks',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    fake.assignmentNotices.addAll(<Map<String, dynamic>>[
      <String, dynamic>{
        'notice_id': 'request-received',
        'kind': 'program_request',
        'message': 'bob requested a program change. Review it in your roster.',
        'message_code': 'assignment_notice.program_request_received.v1',
        'message_params': <String, dynamic>{'player_name': 'bob'},
        'message_fallback':
            'bob requested a program change. Review it in your roster.',
        'created_at': '2026-10-01T12:00:00Z',
        'read_at': null,
      },
      <String, dynamic>{
        'notice_id': 'legacy',
        'kind': 'legacy_notice',
        'message': 'Legacy coach text stays in English.',
        'created_at': '2026-09-01T12:00:00Z',
        'read_at': '2026-09-02T12:00:00Z',
      },
      <String, dynamic>{
        'notice_id': 'unusable',
        'kind': 'program_request',
        'message': 'Safe fallback for unusable metadata.',
        'message_code': 'assignment_notice.program_request_received.v1',
        'message_params': <String, dynamic>{},
        'message_fallback': 'Safe fallback for unusable metadata.',
        'created_at': '2026-08-01T12:00:00Z',
      },
    ]);
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    await tester.scrollUntilVisible(
      find.text('bob requested a program change. Review it in your roster.'),
      300,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.text('Legacy coach text stays in English.'), findsOneWidget);
    expect(find.text('Safe fallback for unusable metadata.'), findsOneWidget);

    final int noticeReads = fake.adapter.requests
        .where((request) => request.path == '/coach/assignments/notices')
        .length;
    final container = ProviderScope.containerOf(
      tester.element(
        find.text('bob requested a program change. Review it in your roster.'),
      ),
    );
    await container.read(displayLanguageProvider.notifier).choose('ar');
    await tester.pump();

    expect(
      find.textContaining('طلبًا لتغيير البرنامج التدريبي.'),
      findsOneWidget,
    );
    expect(find.text('Legacy coach text stays in English.'), findsOneWidget);
    expect(find.text('Safe fallback for unusable metadata.'), findsOneWidget);
    expect(
      fake.adapter.requests
          .where((request) => request.path == '/coach/assignments/notices')
          .length,
      noticeReads,
    );
  });

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

  testWidgets('Coach code redemption fits a phone in both languages',
      (tester) async {
    FakeMayosApi? usedFake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) {
        usedFake = fake;
        fake.coach = false;
        fake.validCoachInviteToken = 'coach-invite-token-123456';
      },
      prepare: (WidgetTester tester, String language) async {
        final Finder settings = find.byIcon(Icons.settings_outlined);
        await _pumpUntilFound(tester, settings);
        expect(settings, findsOneWidget);
        await tester.tap(settings);
        await tester.pumpAndSettle();
        final Finder inviteEntry = find.byIcon(Icons.workspace_premium_outlined);
        await _pumpUntilFound(tester, inviteEntry);
        expect(inviteEntry, findsOneWidget);
        await tester.tap(inviteEntry);
        await _pumpUntilFound(
          tester,
          find.byKey(const Key('coach_invite_screen_body')),
        );
      },
      ready: (String language) =>
          find.byKey(const Key('coach_invite_screen_body')),
      pageScrollable: (String language) => find.descendant(
        of: find.byKey(const Key('coach_invite_screen_body')),
        matching: find.byType(Scrollable),
      ).first,
      allowedInnerStrips: (String language) =>
          find.byKey(const Key('settings_coach_code')),
      assertions: (WidgetTester tester, String language) async {
        final Finder code = find.byKey(const Key('settings_coach_code'));
        await _pumpUntilFound(tester, code);
        expect(code, findsOneWidget);
        await tester.enterText(code, 'coach-invite-token-123456');
        await tester.tap(find.text(language == 'ar' ? 'تفعيل التدريب' : 'Enable coaching'));
        final Finder landing = find.text(
          language == 'ar' ? 'علاقات التدريب النشطة' : 'Active assignments',
        );
        await _pumpUntilFound(tester, landing);
        expect(landing, findsOneWidget);
        expect(usedFake!.coach, isTrue);
        expect(tester.takeException(), isNull);
      },
    );
  });

  testWidgets('phone invite can be created and copied in both languages',
      (tester) async {
    String? clipboardText;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform, (MethodCall call) async {
      if (call.method == 'Clipboard.setData') {
        clipboardText = (call.arguments as Map<Object?, Object?>)['text'] as String?;
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));

    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) {
        fake.coachBio = 'Strength coach.';
      },
      ready: (String language) => find.byKey(const ValueKey<String>('mayos_scaffold_body')),
      pageScrollable: (String language) => find.byType(Scrollable).first,
      assertions: (WidgetTester tester, String language) async {
        final String profileLabel = language == 'ar' ? 'الملف الشخصي' : 'Profile';
        final String profileTitle = language == 'ar' ? 'الملف الشخصي للمدرب' : 'Coach profile';
        await tester.tap(find.text(profileLabel).hitTestable());
        await _pumpUntilFound(tester, find.text(profileTitle));
        await _pumpUntilFound(tester, find.byType(TextFormField));
        final Finder createInvite = find.byKey(
          const Key('coach_create_player_invite'),
        );
        final Finder profileList = find.byType(ListView).last;
        for (int attempt = 0; attempt < 8 && createInvite.evaluate().isEmpty; attempt++) {
          await tester.drag(profileList, const Offset(0, -500));
          await tester.pumpAndSettle();
        }
        expect(createInvite, findsOneWidget, reason: 'language=$language');
        await tester.ensureVisible(createInvite);
        await tester.pumpAndSettle();
        await tester.tap(createInvite.hitTestable());
        await tester.pumpAndSettle();
        final Finder copy = find.byKey(const Key('coach_invite_share'));
        expect(copy, findsOneWidget);
        expect(find.byIcon(Icons.copy_outlined), findsOneWidget);
        expect(find.text(language == 'ar' ? 'نسخ كود الدعوة' : 'Copy invite code'), findsOneWidget);
        expect(find.text('assignment-invite-token-123456'), findsOneWidget);
        await tester.ensureVisible(copy);
        await tester.tap(copy);
        await tester.pumpAndSettle();
        expect(clipboardText, 'assignment-invite-token-123456');
        expect(tester.takeException(), isNull);
      },
    );
  });

  testWidgets('desktop profile keeps invite controls in its existing layout',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake, logicalSize: const Size(1280, 900));
    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    final Finder createInvite = find.text('Create player invite');
    await tester.scrollUntilVisible(
      createInvite,
      320,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.tap(createInvite);
    await tester.pumpAndSettle();

    expect(find.text('assignment-invite-token-123456'), findsOneWidget);
    expect(find.byKey(const Key('coach_invite_share')), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('coach stall threshold is editable from Coach settings',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake);
    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Coach profile'));

    final Finder threshold = find.byKey(const Key('coach_stall_threshold'));
    await tester.scrollUntilVisible(
      threshold,
      300,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    expect(find.text('Coach settings'), findsOneWidget);
    expect(find.text('Stall threshold'), findsOneWidget);
    await tester.tap(threshold);
    await tester.pumpAndSettle();
    await tester.tap(find.text('6 weeks').last);
    await tester.pumpAndSettle();

    expect(fake.stallThresholdWeeks, 6);
    expect(find.text('Stall threshold saved.'), findsOneWidget);
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
