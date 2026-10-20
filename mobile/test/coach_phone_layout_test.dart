import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/models.dart';

import 'support/coach_layout_harness.dart';
import 'support/fake_mayos_api.dart';

void main() {
  testWidgets('roster card opens Player and restores scroll after back',
      (WidgetTester tester) async {
    final String today = isoDateOf(DateTime.now());
    final List<Map<String, dynamic>> assignments = <Map<String, dynamic>>[
      for (int index = 0; index < 12; index++)
        <String, dynamic>{
          'assignment_id': 'assignment-$index',
          'player_username': 'player_$index',
          'started_at': '2026-09-01T10:00:00Z',
          'status': 'active',
          'current_missed_streak': index == 11 ? 2 : index == 0 ? 1 : 0,
          'stall_length': 0,
          'alerts_new': index == 11 ? 1 : 0,
          'alerts_acknowledged': 0,
          'pending_requests': 0,
          'next_follow_up_on': index == 11 ? today : null,
          'last_workout_on': '2026-10-18',
          'program_name': 'Upper/Lower',
        },
    ];
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) => fake.assignments.addAll(assignments),
      ready: (_) => find.byKey(const Key('coach_roster_list_screen')),
      pageScrollable: (_) => find.descendant(
        of: find.byKey(const Key('coach_roster_list_screen')),
        matching: find.byType(Scrollable),
      ).first,
      assertions: (WidgetTester tester, String language) async {
        final bool arabic = language == 'ar';
        final Finder row = find.byKey(const Key('roster_row_assignment-11'));
        expect(find.text('player_11'), findsOneWidget);
        expect(
          find.text(
            arabic
                ? '${String.fromCharCode(0x2066)}$today${String.fromCharCode(0x2069)}'
                : today,
          ),
          findsWidgets,
        );
        expect(
          find.text(arabic ? 'شارات التنبيه' : 'Alert badges'),
          findsWidgets,
        );
        expect(
          find.descendant(
            of: find.byKey(const Key('roster_row_assignment-1')),
            matching: find.text(arabic ? 'شارات التنبيه' : 'Alert badges'),
          ),
          findsNothing,
          reason: 'Cards without alert badges omit that labelled field.',
        );
        expect(
          find.text(arabic ? 'الانتظام' : 'Attendance'),
          findsWidgets,
        );
        expect(
          find.text(arabic ? 'المتابعة القادمة' : 'Next follow-up'),
          findsWidgets,
        );
        expect(
          find.text(arabic ? 'المتابعة اليوم' : 'Follow-up today'),
          findsOneWidget,
        );
        expect(
          find.text(arabic ? 'حالة المتابعة' : 'Follow-up status'),
          findsOneWidget,
        );
        expect(
          find.text(
            arabic
                ? 'يومان فائتان'
                : '2 missed days',
          ),
          findsOneWidget,
        );
        expect(
          find.text(arabic ? 'يوم واحد فائت' : '1 missed day'),
          findsOneWidget,
        );
        expect(find.text(arabic ? 'آخر نشاط' : 'Recent workout'), findsNothing);
        final Finder revoke = find.byKey(
          const Key('roster_revoke_assignment-11'),
        );
        expect(
          find.ancestor(of: revoke, matching: row),
          findsOneWidget,
          reason: 'Revoke must stay associated with the player card.',
        );
        await tester.ensureVisible(revoke);
        await tester.pumpAndSettle();
        expect(revoke.hitTestable(), findsOneWidget);

        final Finder scrollable = find.descendant(
          of: find.byKey(const Key('coach_roster_list_screen')),
          matching: find.byType(Scrollable),
        ).first;
        final ScrollableState scrollState =
            tester.state<ScrollableState>(scrollable);
        scrollState.position.jumpTo(120);
        await tester.pumpAndSettle();
        await tester.ensureVisible(row);
        await tester.pumpAndSettle();
        final double offsetBeforeOpen = scrollState.position.pixels;
        expect(offsetBeforeOpen, greaterThan(0));

        await tester.tap(row);
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('coach_player_history_app_bar')),
          findsOneWidget,
        );
        expect(find.byKey(const Key('coach_roster_master_pane')), findsNothing);
        expect(tester.takeException(), isNull);
        if (arabic) {
          await tester.tap(find.byType(BackButton));
        } else {
          await tester.binding.handlePopRoute();
        }
        await tester.pumpAndSettle();
        expect(row, findsOneWidget);
        final Finder returnedScrollable = find.descendant(
          of: find.byKey(const Key('coach_roster_list_screen')),
          matching: find.byType(Scrollable),
        ).first;
        expect(
          tester.state<ScrollableState>(returnedScrollable).position.pixels,
          offsetBeforeOpen,
        );
      },
    );
  });

  testWidgets('desktop roster keeps its master and player panes',
      (WidgetTester tester) async {
    final String today = isoDateOf(DateTime.now());
    final String yesterday = isoDateOf(DateTime.now().subtract(
      const Duration(days: 1),
    ));
    await pumpCoachDesktopLayout(
      tester,
      configureFake: (FakeMayosApi fake) => fake.assignments.addAll(
        <Map<String, dynamic>>[
          <String, dynamic>{
          'assignment_id': 'assignment-desktop',
          'player_username': 'desktop_player',
          'started_at': '2026-09-01T10:00:00Z',
          'status': 'active',
          'current_missed_streak': 3,
          'stall_length': 0,
          'alerts_new': 0,
          'pending_requests': 0,
          'next_follow_up_on': yesterday,
          'last_workout_on': null,
          },
          <String, dynamic>{
            'assignment_id': 'assignment-today',
            'player_username': 'today_player',
            'started_at': '2026-09-01T10:00:00Z',
            'status': 'active',
            'current_missed_streak': 0,
            'stall_length': 0,
            'alerts_new': 0,
            'pending_requests': 0,
            'next_follow_up_on': today,
            'last_workout_on': null,
          },
        ],
      ),
      ready: find.byKey(const Key('coach_roster_list_screen')),
      logicalSize: const Size(1440, 960),
    );
    expect(find.text('Missed 3d'), findsOneWidget);
    expect(find.text('Follow-up overdue'), findsOneWidget);
    expect(find.text('Follow-up today'), findsOneWidget);
    await tester.tap(find.byKey(const Key('roster_row_assignment-desktop')));
    await tester.pumpAndSettle();
    expect(find.text('desktop_player'), findsWidgets);
    expect(find.text('History'), findsOneWidget);
    expect(find.text('Check-ins'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('resume on phone Player route refreshes mounted roster once',
      (WidgetTester tester) async {
    final FakeMayosApi fake = createCoachFake()
      ..assignments.add(<String, dynamic>{
        'assignment_id': 'assignment-resume',
        'player_username': 'resume_player',
        'started_at': '2026-09-01T10:00:00Z',
        'status': 'active',
        'current_missed_streak': 0,
        'stall_length': 0,
        'alerts_new': 0,
        'pending_requests': 0,
        'next_follow_up_on': null,
        'last_workout_on': null,
      });
    await pumpCoachApp(
      tester,
      fake,
      logicalSize: const Size(360, 800),
    );
    final Finder row = find.byKey(const Key('roster_row_assignment-resume'));
    for (int attempt = 0; attempt < 60 && row.evaluate().isEmpty; attempt++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    await tester.tap(row);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('coach_player_history_app_bar')), findsOneWidget);
    final int requestsBefore = fake.adapter.requests
        .where((request) => request.method == 'GET' &&
            request.path == '/coach/assignments')
        .length;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    final int requestsAfter = fake.adapter.requests
        .where((request) => request.method == 'GET' &&
            request.path == '/coach/assignments')
        .length;
    expect(requestsAfter - requestsBefore, 1);
    expect(tester.takeException(), isNull);
  });
}
