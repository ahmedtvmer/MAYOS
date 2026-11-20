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
import 'package:mayos_mobile/src/core/rest_alert_permission_access.dart';
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
  await tester.tap(find.text('Training profile'));
  await _pumpUntilFound(tester, find.text('Training profile'));

  await tester.tap(find.byType(DropdownButtonFormField<int>));
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(find.text('3').last);
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> _openProfile(WidgetTester tester) async {
  await _openSettings(tester);
  await tester.tap(find.text('Training profile'));
  await _pumpUntilFound(tester, find.text('Training profile'));
}

Future<void> _scrollProfileUntilBuilt(
  WidgetTester tester,
  Finder target, {
  required Offset dragOffset,
}) async {
  final Finder profileScroll = find.descendant(
    of: find.byType(ProfileScreen),
    matching: find.byType(Scrollable),
  ).first;
  for (int attempt = 0;
      attempt < 8 && target.evaluate().isEmpty;
      attempt++) {
    await tester.drag(profileScroll, dragOffset);
    await tester.pumpAndSettle();
  }
  expect(target.evaluate(), isNotEmpty,
      reason: 'Profile scroll should build the requested control');
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
  testWidgets('female profile Weak points default is removable and editable', (tester) async {
    final FakeMayosApi fake = _playerFake()..gender = 'female';
    await _pumpApp(tester, fake);
    await _changeTrainingDays(tester);
    final Finder scrollable = find.descendant(
      of: find.byType(ProfileScreen), matching: find.byType(Scrollable));
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile_weak_points_section')), 250,
      scrollable: scrollable.first);
    await tester.tap(find.byKey(const Key('profile_weak_points_section')));
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile_weak_point_chest')), 150,
      scrollable: scrollable.first);
    await tester.ensureVisible(find.byKey(const Key('profile_weak_point_chest')));
    await tester.pumpAndSettle();
    final FilterChip glutes = tester.widget<FilterChip>(
      find.byKey(const Key('profile_weak_point_glutes')),
    );
    expect(glutes.selected, isTrue);
    await tester.tap(find.byKey(const Key('profile_weak_point_chest')));
    await tester.pump();
    expect(tester.widget<FilterChip>(find.byKey(
      const Key('profile_weak_point_glutes'),
    )).selected, isFalse);
    await tester.ensureVisible(find.byKey(const Key('save_weak_points_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('save_weak_points_button')));
    await tester.pumpAndSettle();
    expect(fake.weakPoints, <Map<String, String>>[
      <String, String>{'muscle': 'chest', 'source': 'named'},
    ]);
  });

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

  testWidgets('accepting a goal Weak point saves it from the profile prompt',
      (tester) async {
    final FakeMayosApi fake = _playerFake()
      ..profileSuggestedWeakPoints = <String>['glutes'];
    await _pumpApp(tester, fake);
    await _changeTrainingDays(tester);
    await tester.enterText(find.byKey(const Key('current_goal_field')), 'Grow my glutes');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('This rebuilds your program'));
    await tester.tap(find.byKey(const Key('profile_rebuild_confirm_button')));
    await _pumpUntilFound(tester, find.text('Make Glutes a Weak point?'));
    await tester.tap(find.text('Accept'));
    await tester.pumpAndSettle();
    expect(fake.profileUpdateBodies.any((Map<String, dynamic> body) =>
        body['weak_points'] != null), isTrue);
    expect(fake.weakPoints, <Map<String, String>>[
      <String, String>{'muscle': 'glutes', 'source': 'named'},
    ]);
    expect(find.text('Program rebuilt.'), findsOneWidget);
    final Finder scrollable = find.descendant(
      of: find.byType(ProfileScreen), matching: find.byType(Scrollable));
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile_weak_points_section')), 250,
      scrollable: scrollable.first);
    await tester.tap(find.byKey(const Key('profile_weak_points_section')));
    await tester.pumpAndSettle();
    expect(tester.widget<FilterChip>(find.byKey(const Key('profile_weak_point_glutes'))).selected, isTrue);
    await tester.tap(find.byKey(const Key('save_weak_points_button')));
    await tester.pumpAndSettle();
    expect(fake.weakPoints, <Map<String, String>>[
      <String, String>{'muscle': 'glutes', 'source': 'named'},
    ]);
  });

  testWidgets('dismissing a goal Weak point prompt leaves Weak points unchanged',
      (tester) async {
    final FakeMayosApi fake = _playerFake()
      ..profileSuggestedWeakPoints = <String>['glutes'];
    await _pumpApp(tester, fake);
    await _changeTrainingDays(tester);
    await tester.enterText(find.byKey(const Key('current_goal_field')), 'Grow my glutes');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('This rebuilds your program'));
    await tester.tap(find.byKey(const Key('profile_rebuild_confirm_button')));
    await _pumpUntilFound(tester, find.text('Make Glutes a Weak point?'));
    await tester.tap(find.text('Dismiss'));
    await tester.pumpAndSettle();
    expect(fake.profileUpdateBodies.any((Map<String, dynamic> body) =>
        body['weak_points'] != null), isFalse);
    expect(fake.weakPoints, isNull);
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

  testWidgets('Profile adds a structured injury record', (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    await tester.tap(find.byKey(const Key('add_injury_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('injury_body_area_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Knee').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('injury_description_field')),
      'Pain during squats',
    );
    await tester.tap(find.byKey(const Key('save_injury_button')));
    await tester.pumpAndSettle();

    expect(fake.injuryCreateRequests, 1);
    expect(fake.injuries.single['body_area'], 'knee');
    expect(find.text('Knee · Reported'), findsOneWidget);
    expect(find.text('Pain during squats'), findsOneWidget);
  });

  testWidgets('Profile lists, edits and deletes an exercise clearance in English',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.injuries.add(<String, dynamic>{
      'id': 'injury-clearance-en',
      'body_area': 'knee',
      'catalog_body_parts': <String>['upper legs', 'lower legs'],
      'description': 'Knee pain during training',
      'reported_at': '2026-10-01T10:00:00+00:00',
      'status': 'physician_seen',
      'clarification_pending': false,
      'clearances': <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 'clearance-en-1',
          'injury_id': 'injury-clearance-en',
          'exercise_id': 'leg-curl',
          'exercise_name': 'Leg Curls',
          'original_wording': 'My physician said no leg curls.',
          'verdict': 'not_cleared',
          'note': null,
          'recorded_at': '2026-10-02T10:00:00+00:00',
          'source': 'player-reported physician advice',
        },
      ],
    });
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    expect(find.text('Leg Curls · Not cleared'), findsOneWidget);
    await tester.tap(find.byKey(const Key('edit_clearance_clearance-en-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('clearance_verdict_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cleared').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('save_clearance_button')));
    await tester.pumpAndSettle();

    expect(fake.clearanceUpdateRequests, 1);
    expect(fake.lastClearanceUpdatePayload?['verdict'], 'cleared');
    expect(find.text('Leg Curls · Cleared'), findsOneWidget);

    await tester.tap(find.byKey(const Key('delete_clearance_clearance-en-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm_delete_clearance_clearance-en-1')));
    await tester.pumpAndSettle();
    expect(fake.clearanceDeleteRequests, 1);
    expect(find.text('Leg Curls · Cleared'), findsNothing);
  });

  testWidgets('Profile edits and deletes an exercise clearance in Arabic',
      (tester) async {
    final FakeMayosApi fake = _playerFake()..displayLanguage = 'ar';
    fake.injuries.add(<String, dynamic>{
      'id': 'injury-clearance-ar',
      'body_area': 'knee',
      'catalog_body_parts': <String>['upper legs', 'lower legs'],
      'description': 'ألم في الركبة',
      'reported_at': '2026-10-01T10:00:00+00:00',
      'status': 'physician_seen',
      'clarification_pending': false,
      'clearances': <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 'clearance-ar-1',
          'injury_id': 'injury-clearance-ar',
          'exercise_id': 'leg-curl',
          'exercise_name': 'Leg Curls',
          'original_wording': 'قال الدكتور إن تمرين Leg Curls غير مسموح.',
          'verdict': 'not_cleared',
          'note': null,
          'recorded_at': '2026-10-02T10:00:00+00:00',
          'source': 'player-reported physician advice',
        },
      ],
    });
    await _pumpApp(tester, fake);
    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('المظهر'));
    await tester.scrollUntilVisible(
      find.text('تسجيل الدخول المرتبط'),
      250,
      scrollable: find.descendant(
        of: find.byKey(const Key('settings_section_list')),
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.scrollUntilVisible(
      find.text('الملف التدريبي'),
      -250,
      scrollable: find.descendant(
        of: find.byKey(const Key('settings_section_list')),
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.tap(find.text('الملف التدريبي'));
    await _pumpUntilFound(tester, find.byKey(const Key('weight_kg_field')));

    expect(find.text('Leg Curls · غير مسموح'), findsOneWidget);
    await tester.tap(find.byKey(const Key('edit_clearance_clearance-ar-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('clearance_verdict_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('مسموح').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('save_clearance_button')));
    await tester.pumpAndSettle();
    expect(fake.lastClearanceUpdatePayload?['verdict'], 'cleared');
    expect(find.text('Leg Curls · مسموح'), findsOneWidget);

    await tester.tap(find.byKey(const Key('delete_clearance_clearance-ar-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm_delete_clearance_clearance-ar-1')));
    await tester.pumpAndSettle();
    expect(fake.clearanceDeleteRequests, 1);
    expect(find.text('Leg Curls · مسموح'), findsNothing);
  });

  testWidgets('Profile requires confirmation before resolving an injury',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.injuries.add(<String, dynamic>{
      'id': 'injury-existing',
      'body_area': 'knee',
      'catalog_body_parts': <String>['upper legs', 'lower legs'],
      'description': 'Pain during squats',
      'reported_at': '2026-10-01T10:00:00+00:00',
      'status': 'reported',
      'clarification_pending': false,
    });
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    await tester.tap(find.byKey(const Key('edit_injury_injury-existing')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('injury_status_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Resolved').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('save_injury_button')));
    await tester.pumpAndSettle();

    expect(find.text('Confirm injury resolved'), findsOneWidget);
    expect(fake.injuryUpdateRequests, 0);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(fake.injuryUpdateRequests, 0);
    expect(fake.injuries.single['status'], 'reported');

    await tester.tap(find.byKey(const Key('edit_injury_injury-existing')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('injury_status_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Physician seen').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('injury_description_field')),
      'Checked by a physician',
    );
    await tester.tap(find.byKey(const Key('save_injury_button')));
    await tester.pumpAndSettle();

    expect(fake.injuryUpdateRequests, 1);
    expect(fake.injuries.single['status'], 'physician_seen');
    expect(fake.injuries.single['description'], 'Checked by a physician');

    await tester.tap(find.byKey(const Key('edit_injury_injury-existing')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('injury_status_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Resolved').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('save_injury_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('injury_resolve_confirm_button')));
    await tester.pumpAndSettle();

    expect(fake.injuryUpdateRequests, 2);
    expect(fake.lastInjuryUpdatePayload?['status'], 'resolved');
    expect(fake.injuries.single['status'], 'resolved');
  });

  testWidgets('Profile direct resolve and delete actions confirm and cancel',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.injuries.add(<String, dynamic>{
      'id': 'injury-direct', 'body_area': 'knee',
      'catalog_body_parts': <String>['upper legs', 'lower legs'],
      'description': 'Pain during squats',
      'reported_at': '2026-10-01T10:00:00+00:00', 'status': 'reported',
      'clarification_pending': false,
    });
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    expect(find.text('Mark resolved'), findsOneWidget);
    await tester.tap(find.byKey(const Key('mark_resolved_injury-direct')));
    await tester.pumpAndSettle();
    expect(find.text('Confirm injury resolved'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(fake.injuryUpdateRequests, 0);
    expect(fake.injuries, hasLength(1));

    await tester.tap(find.byKey(const Key('mark_resolved_injury-direct')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('injury_resolve_confirm_button_injury-direct')));
    await tester.pumpAndSettle();
    expect(fake.lastInjuryUpdatePayload?['status'], 'resolved');

    await tester.tap(find.byKey(const Key('delete_injury_injury-direct')));
    await tester.pumpAndSettle();
    expect(find.text('This permanently removes the injury record and its exercise clearances.'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(fake.injuryDeleteRequests, 0);
    expect(fake.injuries, hasLength(1));

    await tester.tap(find.byKey(const Key('delete_injury_injury-direct')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm_delete_injury_injury-direct')));
    await tester.pumpAndSettle();
    expect(fake.injuryDeleteRequests, 1);
    expect(fake.injuries, isEmpty);
  });

  testWidgets('Arabic Profile shows direct injury actions and delete confirmation',
      (tester) async {
    final FakeMayosApi fake = _playerFake()..displayLanguage = 'ar';
    fake.injuries.add(<String, dynamic>{
      'id': 'injury-ar-actions', 'body_area': 'knee',
      'catalog_body_parts': <String>['upper legs', 'lower legs'],
      'description': 'ألم في الركبة',
      'reported_at': '2026-10-01T10:00:00+00:00', 'status': 'reported',
      'clarification_pending': false,
    });
    await _pumpApp(tester, fake);
    await _openSettings(tester);
    await tester.tap(find.text('الملف التدريبي'));
    await _pumpUntilFound(tester, find.byKey(const Key('delete_injury_injury-ar-actions')));
    expect(find.text('تسجيل الإصابة كمحلولة'), findsOneWidget);
    await tester.tap(find.byKey(const Key('delete_injury_injury-ar-actions')));
    await tester.pumpAndSettle();
    expect(find.text('حذف الإصابة نهائيًا؟'), findsOneWidget);
    await tester.tap(find.text('إلغاء'));
    await tester.pumpAndSettle();
    expect(fake.injuryDeleteRequests, 0);
  });

  testWidgets('Arabic Profile shows Arabic injury resolution confirmation',
      (tester) async {
    final FakeMayosApi fake = _playerFake()..displayLanguage = 'ar';
    fake.injuries.add(<String, dynamic>{
      'id': 'injury-arabic-confirm',
      'body_area': 'knee',
      'catalog_body_parts': <String>['upper legs', 'lower legs'],
      'description': 'ألم في الركبة',
      'reported_at': '2026-10-01T10:00:00+00:00',
      'status': 'reported',
      'clarification_pending': false,
    });
    await _pumpApp(tester, fake);
    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('المظهر'));
    await tester.scrollUntilVisible(
      find.text('تسجيل الدخول المرتبط'),
      250,
      scrollable: find
          .descendant(
            of: find.byKey(const Key('settings_section_list')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.scrollUntilVisible(
      find.text('الملف التدريبي'),
      -250,
      scrollable: find
          .descendant(
            of: find.byKey(const Key('settings_section_list')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.tap(find.text('الملف التدريبي'));
    await _pumpUntilFound(tester, find.byKey(const Key('weight_kg_field')));

    expect(find.text('الركبة · تم الإبلاغ'), findsOneWidget);
    expect(find.text('ألم في الركبة'), findsOneWidget);
    await tester.tap(find.byKey(const Key('edit_injury_injury-arabic-confirm')));
    await tester.pumpAndSettle();
    expect(find.text('تعديل الإصابة'), findsOneWidget);
    expect(find.text('منطقة الإصابة'), findsOneWidget);
    expect(find.text('الوصف'), findsOneWidget);
    expect(find.text('الحالة'), findsOneWidget);
    await tester.tap(find.byKey(const Key('injury_status_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('تم التعافي').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('save_injury_button')));
    await tester.pumpAndSettle();

    expect(find.text('تأكيد حل الإصابة'), findsOneWidget);
    expect(find.text('هل تؤكد أن هذه الإصابة انتهت؟'), findsOneWidget);
  });

  for (final String language in <String>['en', 'ar']) {
    testWidgets('Movement restriction picker confirms suggestions and saves ($language)', (tester) async {
      final FakeMayosApi fake = _playerFake()
        ..displayLanguage = language
        ..injuriesOrLimitations = 'FAI syndrome'
        ..profileSuggestedMovementRestrictions = <String>['Deep hip flexion'];
      await _pumpApp(tester, fake);
      if (language == 'ar') {
        await _openSettings(tester);
        await tester.tap(find.text('الملف التدريبي'));
        await _pumpUntilFound(tester, find.byType(ProfileScreen));
      } else {
        await _openProfile(tester);
      }
      final Finder scrollable = find.descendant(
        of: find.byType(ProfileScreen), matching: find.byType(Scrollable));
      final Finder section = find.byKey(const Key('profile_movement_restrictions_section'));
      await tester.scrollUntilVisible(section, 250, scrollable: scrollable.first);
      await tester.tap(section);
      await tester.pump();
      final Finder deepHip = find.byKey(const Key('profile_movement_restriction_Deep hip flexion'));
      await tester.scrollUntilVisible(deepHip, 200, scrollable: scrollable.first);
      await tester.ensureVisible(deepHip);
      await tester.pumpAndSettle();
      expect(tester.widget<FilterChip>(deepHip).selected, isFalse);
      expect(find.textContaining(language == 'ar' ? 'ثني الورك العميق' : 'Deep hip flexion'), findsWidgets);
      await tester.tap(deepHip);
      final Finder saveRestrictions = find.byKey(const Key('save_movement_restrictions_button'));
      await tester.scrollUntilVisible(saveRestrictions, 200, scrollable: scrollable.first);
      await tester.ensureVisible(saveRestrictions);
      await tester.pumpAndSettle();
      fake.failOffline('PATCH', '/profile');
      await tester.tap(find.byKey(const Key('save_movement_restrictions_button')));
      await _pumpUntilFound(tester, find.byKey(const Key('save_movement_restrictions_button')));
      fake.offlineRequests.remove('PATCH /profile');
      await tester.tap(find.byKey(const Key('save_movement_restrictions_button')));
      await _pumpUntilFound(tester, find.text(language == 'ar' ? 'أُعيد إنشاء البرنامج التدريبي.' : 'Program rebuilt.'));
      expect(fake.movementRestrictions, <String>['Deep hip flexion']);
    });
  }

  testWidgets('Training profile pre-fills editable values and saves goal/weight without rebuild',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.currentGoal = 'Build muscle';
    fake.injuries.add(<String, dynamic>{
      'id': 'legacy-injury',
      'body_area': 'shoulder',
      'catalog_body_parts': <String>['shoulders', 'upper arms'],
      'description': 'Right shoulder limitation',
      'reported_at': '2026-10-01T10:00:00+00:00',
      'status': 'reported',
      'clarification_pending': false,
    });
    fake.weightKg = 82.5;
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    expect(find.text('Build muscle'), findsOneWidget);
    expect(find.text('Shoulder · Reported'), findsOneWidget);
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

  testWidgets('player can log a weight entry from the Training profile',
      (tester) async {
    final FakeMayosApi fake = _playerFake()..weightKg = 82.5;
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    await tester.enterText(find.byKey(const Key('weight_kg_field')), '83');
    await tester.ensureVisible(find.byKey(const Key('log_weight_button')));
    await tester.tap(find.byKey(const Key('log_weight_button')));
    await _pumpUntilFound(tester, find.text('Weight logged for ${_todayIso()}.'));

    expect(fake.weightEntryRequests, 1);
    expect(fake.lastLoggedWeightKg, 83);
    expect(fake.weightKg, 83);
  });

  testWidgets('Training profile can set and clear a target weight',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    await tester.enterText(
        find.byKey(const Key('target_weight_kg_field')), '82.5');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Profile saved.'));

    expect(fake.targetWeightKg, 82.5);
    expect(fake.profileUpdateBodies.last['target_weight_kg'], 82.5);

    await tester.enterText(find.byKey(const Key('target_weight_kg_field')), '');
    await tester.ensureVisible(find.text('Save profile'));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Profile saved.'));
    expect(fake.targetWeightKg, isNull);
  });

  testWidgets('older intake contract shows a service update error instead of hanging',
      (tester) async {
    final FakeMayosApi fake = _playerFake()
      ..legacyEquipmentIntakeContract = true;
    await _pumpApp(tester, fake);
    await _openSettings(tester);
    await tester.tap(find.text('Training profile'));
    await _pumpUntilFound(
      tester,
      find.text(
        'The service needs an update before this profile can be edited. Please try again later.',
      ),
    );

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(
      find.text(
        'The service needs an update before this profile can be edited. Please try again later.',
      ),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  // Boundary cases: missing editor fields, unsupported field types, empty or
  // duplicate choices, and absent/reversed numeric bounds must fail before UI setup.
  final List<(String, String, Map<String, dynamic>?)> invalidContracts =
      <(String, String, Map<String, dynamic>?)>[
    ('missing goal', 'current_goal', null),
    ('missing equipment', 'equipment_access', null),
    ('missing reps', 'rep_preference', null),
    ('unsupported goal', 'current_goal', <String, dynamic>{'type': 'enum'}),
    ('unsupported weight', 'weight_kg', <String, dynamic>{'type': 'text'}),
    (
      'unsupported frequency',
      'weekly_frequency',
      <String, dynamic>{'type': 'float'}
    ),
    (
      'empty equipment choices',
      'equipment_access',
      <String, dynamic>{'allowed_values': <String>[]}
    ),
    ('unsupported reps', 'rep_preference', <String, dynamic>{'type': 'text'}),
    (
      'empty rep choices',
      'rep_preference',
      <String, dynamic>{'allowed_values': <String>[]}
    ),
    (
      'duplicate rep choices',
      'rep_preference',
      <String, dynamic>{
        'allowed_values': <String>['balanced', 'balanced']
      }
    ),
    (
      'blank equipment choice',
      'equipment_access',
      <String, dynamic>{
        'allowed_values': <String>['  ']
      }
    ),
    (
      'missing frequency bound',
      'weekly_frequency',
      <String, dynamic>{'minimum': null}
    ),
    (
      'reversed frequency bounds',
      'weekly_frequency',
      <String, dynamic>{'minimum': 5, 'maximum': 1}
    ),
    (
      'range excludes saved frequency',
      'weekly_frequency',
      <String, dynamic>{'minimum': 1, 'maximum': 3}
    ),
    ('malformed field type', 'weight_kg', <String, dynamic>{'type': 42}),
    ('non-string equipment choice', 'equipment_access', <String, dynamic>{'allowed_values': <Object>[42]}),
    ('null rep choice', 'rep_preference', <String, dynamic>{'allowed_values': <Object?>[null]}),
  ];
  for (final (String description, String field, Map<String, dynamic>? override)
      in invalidContracts) {
    testWidgets('invalid Training profile contract: $description',
        (tester) async {
      final FakeMayosApi fake = _playerFake();
      if (override == null) {
        fake.omittedIntakeFields.add(field);
      } else {
        fake.intakeFieldOverrides[field] = override;
      }
      await _pumpApp(tester, fake);
      await _openSettings(tester);
      await tester.tap(find.text('Training profile'));
      final Finder error = find.text(
        'The service needs an update before this profile can be edited. Please try again later.',
      );
      await _pumpUntilFound(tester, error);
      expect(error, findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.text('Save profile'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

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
    // Start from a Mon/Wed/Fri schedule; the fake's default covers every day.
    fake.scheduleVersions.first['weekdays'] = <int>[1, 3, 5];
    await _pumpApp(tester, fake);
    await _openProfile(tester);

    // The schedule is its own section, seeded from the service's current version.
    expect(find.text('Training schedule'), findsOneWidget);

    await _scrollProfileUntilBuilt(
      tester,
      find.byKey(const Key('weekday_chip_2')),
      dragOffset: const Offset(0, -500),
    );
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
    await _scrollProfileUntilBuilt(
      tester,
      find.byType(DropdownButtonFormField<int>),
      dragOffset: const Offset(0, 500),
    );
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

    await _scrollProfileUntilBuilt(
      tester,
      find.byKey(const Key('timezone_field')),
      dragOffset: const Offset(0, -500),
    );
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

    await _scrollProfileUntilBuilt(
      tester,
      find.byKey(const Key('timezone_field')),
      dragOffset: const Offset(0, -500),
    );
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

    await tester.drag(find.byType(Scrollable).first, const Offset(0, -1100));
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
          restAlertPermissionAccessProvider.overrideWithValue(
            const UnsupportedRestAlertPermissionAccess(),
          ),
          _apiOverride(fake),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await _pumpUntilFound(tester, find.byKey(const Key('onboarding_continue')));
    await tester.tap(find.byKey(const Key('onboarding_continue')));
    await _pumpUntilFound(tester, find.text('Create my program'));
    await tester.tap(find.text('Create my program'));
    await _pumpUntilFound(tester, find.text('HOME'));

    expect(find.text('HOME'), findsOneWidget);
    expect(find.text('Upper/Lower 4x'), findsNothing);
    expect(fake.intakeProgram!['program_name'], isNull);
    expect(tester.takeException(), isNull);
  });

  test('IntakeConfirmation parses null program fields without throwing', () {
    final IntakeConfirmation confirmation = IntakeConfirmation.fromJson(
      <String, dynamic>{
        'status': 'confirmed',
        'program_name': null,
        'weekly_frequency': null,
      },
    );
    expect(confirmation.hasProgram, isFalse);
    expect(confirmation.programName, isNull);
    expect(confirmation.weeklyFrequency, isNull);
  });
}
