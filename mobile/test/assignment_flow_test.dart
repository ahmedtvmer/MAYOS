import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

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
      find.text(fake.displayLanguage == 'ar'
          ? 'الرئيسية'
          : fake.coach
              ? 'Roster'
              : 'Home'));
}

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
  fake.coachCapacity = 10;
  return fake;
}

Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  testWidgets(
      'Arabic settings and assignment surfaces keep server text and Western dates',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false)
      ..displayLanguage = 'ar'
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..activeCoachSpecialization = 'Powerlifting';
    fake.playerNotices.add(<String, dynamic>{
      'notice_id': 'notice-1',
      'assignment_id': 'assignment-1',
      'kind': 'program_published',
      'message': 'Coach note: keep the current program this week.',
      'created_at': '2026-09-26T12:00:00Z',
      'read_at': null,
    });
    fake.checkIns.add(<String, dynamic>{
      'check_in_id': 'check-in-1',
      'assignment_id': 'assignment-1',
      'checked_in_on': '2026-09-26',
      'channel': 'in_app',
      'note': 'Discuss sleep at the next check-in.',
      'created_at': '2026-09-26T12:00:00Z',
      'coach_username': 'alice',
      'assignment_status': 'active',
    });
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('المظهر'));
    expect(find.text('الحساب'), findsOneWidget);
    expect(find.text('اسم المستخدم'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.text('المظهر'))),
      TextDirection.rtl,
    );

    await tester.tap(find.byKey(const Key('personalization_entry')));
    await _pumpUntilFound(tester, find.text('مباشر وعملي'));
    expect(
      find.text(
        'اختر طريقة صياغة ردود المساعد في المحادثة. تبقى الحقائق وقرارات التدريب والسلامة ولغة الرد كما هي.',
      ),
      findsOneWidget,
    );
    expect(
      Directionality.of(tester.element(find.text('مباشر وعملي'))),
      TextDirection.rtl,
    );
    await tester.tap(find.byIcon(Icons.arrow_back));
    await _pumpUntilFound(tester, find.text('المظهر'));

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('مدربي'));
    expect(find.text('مغادرة المدرب'), findsOneWidget);
    expect(
      find.text(
        'أثناء نشاط علاقتك بمدربك، يمكنه الاطلاع على بيانات تدريبك الحالية '
        'والسابقة. مغادرتك لمدربك تلغي إمكانية الاطلاع فورًا.',
      ),
      findsOneWidget,
    );
    expect(find.text('مدربك'), findsOneWidget);
    expect(find.text('طلبات البرنامج التدريبي'), findsOneWidget);
    expect(find.text('لا توجد طلبات للبرنامج التدريبي بعد.'), findsOneWidget);
    expect(find.text('Coach note: keep the current program this week.'),
        findsOneWidget);
    final Finder checkInNote =
        find.textContaining('Discuss sleep at the next check-in.');
    expect(checkInNote, findsOneWidget);
    expect(
      tester.widget<Text>(checkInNote).data,
      endsWith('Discuss sleep at the next check-in.'),
    );
    expect(find.textContaining('2026-09-26'), findsNWidgets(2));
    expect(find.textContaining('٢٠٢٦'), findsNothing);
    expect(
      Directionality.of(tester.element(find.text('مدربك'))),
      TextDirection.rtl,
    );
    final Text dateAndChannel = tester.widget<Text>(
      find.text('\u20662026-09-26\u2069 · داخل التطبيق'),
    );
    expect(dateAndChannel.textDirection, isNull);
    expect(
      Directionality.of(
          tester.element(find.text('\u20662026-09-26\u2069 · داخل التطبيق'))),
      TextDirection.rtl,
    );
  });

  testWidgets('Arabic player profile labels keep profile data and digits',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false)
      ..displayLanguage = 'ar'
      ..currentGoal = 'Build strength.';
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('المظهر'));
    expect(find.text('تسجيل الدخول المرتبط'), findsOneWidget);
    await tester.tap(find.text('الملف التدريبي'));
    await _pumpUntilFound(tester, find.byKey(const Key('weight_kg_field')));

    expect(find.text('الملف التدريبي'), findsWidgets);
    expect(find.text('جدول التدريب'), findsOneWidget);
    expect(find.text('طرق تسجيل الدخول'), findsNothing);
    expect(find.text('Build strength.'), findsOneWidget);
    final TextField weightField =
        tester.widget<TextField>(find.byKey(const Key('weight_kg_field')));
    // The English and Arabic fields both use profile.weightKg.toString(), so
    // this Double value stays `75.0` in Western digits in either language.
    expect(weightField.controller!.text, '75.0');
    expect(
      Directionality.of(tester.element(find.text('الملف التدريبي').first)),
      TextDirection.rtl,
    );
    expect(
      Directionality.of(
          tester.element(find.byKey(const Key('weight_kg_field')))),
      TextDirection.ltr,
    );
  });

  testWidgets('player previews access, consents, then ends the assignment',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.pendingAssignmentToken = 'assignment-invite-token-123456';
    fake.pendingCoachDisplayName = 'Coach Bob';
    fake.pendingCoachSpecialization = 'Strength';
    await _pumpApp(tester, fake);

    // Open the player assignment surface from the app bar.
    await _openSettings(tester);
    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('My coach'));

    expect(find.text('Invite code from your coach'), findsOneWidget);
    expect(
      find.text(
        'Enter your coach’s invite code. Your coach can view your training data '
        'only after you accept, and access ends when either of you leaves the '
        'coaching relationship.',
      ),
      findsOneWidget,
    );
    expect(find.textContaining('coach invite'), findsNothing);

    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'short');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(
        tester, find.text('Enter the invite code from your coach.'));

    // A bad code is rejected and grants nothing.
    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'wrong-code-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Invalid or expired invite code.'));
    expect(fake.activeAssignmentId, isNull);

    // Preview reveals identity and exact access; nothing is consumed yet.
    await tester.enterText(find.byKey(const Key('assignment_code_field')),
        'assignment-invite-token-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Accept assignment'));
    expect(find.text('Your coach will be Coach Bob'), findsOneWidget);
    expect(find.text('Strength'), findsOneWidget);
    expect(fake.activeAssignmentId, isNull);

    // Explicit consent binds immediately and shows the active coach.
    await tester.tap(find.text('Accept assignment'));
    await _pumpUntilFound(tester, find.text('Your coach'));
    expect(find.text('Coach Bob'), findsOneWidget);
    expect(fake.activeAssignmentId, 'assignment-1');

    // The player can end it; the invite section returns.
    await tester.tap(find.widgetWithText(OutlinedButton, 'Leave coach'));
    await _pumpUntilFound(tester, find.text('Leave coach?'));
    await tester.tap(find.widgetWithText(FilledButton, 'Leave coach'));
    await _pumpUntilFound(tester, find.text('My coach'));
    expect(fake.activeAssignmentId, isNull);
  });

  testWidgets('editing the code after preview clears the previewed consent',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.pendingAssignmentToken = 'coach-a-token-123456';
    fake.pendingCoachDisplayName = 'Coach A';
    await _pumpApp(tester, fake);

    await _openSettings(tester);

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('My coach'));

    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'coach-a-token-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Accept assignment'));
    expect(find.text('Your coach will be Coach A'), findsOneWidget);

    // Switching the code invalidates the preview, so consent cannot target coach B.
    fake.pendingAssignmentToken = 'coach-b-token-123456';
    fake.pendingCoachDisplayName = 'Coach B';
    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'coach-b-token-123456');
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Accept assignment'), findsNothing);
    expect(find.text('Your coach will be Coach A'), findsNothing);
    expect(fake.activeAssignmentId, isNull);

    // Re-previewing binds consent to coach B only.
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Your coach will be Coach B'));
    await tester.tap(find.text('Accept assignment'));
    await _pumpUntilFound(tester, find.text('Coach B'));
    expect(fake.activeCoachDisplayName, 'Coach B');
  });

  testWidgets(
      'a committed assignment is not reported as failed when a read would fail',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.pendingAssignmentToken = 'coach-b-token-123456';
    fake.pendingCoachDisplayName = 'Coach Bob';
    await _pumpApp(tester, fake);

    await _openSettings(tester);

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('My coach'));

    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'coach-b-token-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Accept assignment'));

    final int meCallsBefore =
        fake.adapter.requests.where((r) => r.path == '/assignments/me').length;
    // Any post-redeem account read would now fail transiently.
    fake.myAssignmentFails = true;

    await tester.tap(find.text('Accept assignment'));
    await _pumpUntilFound(tester, find.text('Your coach'));
    expect(find.text('Coach Bob'), findsOneWidget);
    expect(find.text('The service is unavailable.'), findsNothing);
    expect(
      fake.adapter.requests.where((r) => r.path == '/assignments/me').length,
      meCallsBefore,
    );
  });

  testWidgets('coach issues a code, reviews notices, revokes, disables',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'started_at': '2026-09-24T10:00:00Z',
      'status': 'active',
    });
    fake.assignmentNotices.add(<String, dynamic>{
      'notice_id': 'n1',
      'kind': 'assignment_redeemed',
      'message':
          'bob accepted your coaching invite and is now assigned to you.',
      'created_at': '2026-09-24T10:00:00Z',
      'read_at': null,
    });
    await _pumpApp(tester, fake);

    // The coach shell opens on the Roster tab (#119); the invite and the
    // notices live on the Profile tab.
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(find.text('bob'), findsOneWidget);

    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Invite a player'));
    expect(
        find.text(
            'bob accepted your coaching invite and is now assigned to you.'),
        findsOneWidget);

    // Issuing shows the one-time bearer code and remaining capacity.
    expect(find.text('Create player invite'), findsOneWidget);
    await tester.tap(find.text('Create player invite'));
    await _pumpUntilFound(tester, find.text('assignment-invite-token-123456'));
    expect(fake.issuedAssignmentToken, 'assignment-invite-token-123456');

    await tester.tap(find.text('Roster'));
    await _pumpUntilFound(tester, find.text('Active assignments'));

    // Revoke removes the assignment from the console.
    await tester.tap(find.text('Revoke'));
    await _pumpUntilFound(tester, find.text('Revoke assignment?'));
    await tester.tap(find.widgetWithText(FilledButton, 'Revoke'));
    await _pumpUntilFound(tester, find.text('No assigned players yet.'));
    expect(fake.assignments, isEmpty);

    // Disabling coaching clears the capability and ends every assignment.
    fake.meFails =
        true; // A follow-up account read would fail after the commit.
    await tester.tap(find.text('Disable coaching'));
    await _pumpUntilFound(tester, find.text('Disable coaching?'));
    await tester.tap(find.widgetWithText(FilledButton, 'Disable coaching'));
    await _pumpUntilFound(
        tester, find.text('Coaching disabled. 0 assignment(s) ended.'));
    expect(fake.coach, isFalse);
    // Without the capability the account falls back to Player mode (#119).
    await _pumpUntilFound(tester, find.text('Home'));
    expect(find.text('Roster'), findsNothing);
  });
}
