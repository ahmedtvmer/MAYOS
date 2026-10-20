import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/theme/mayos_spacing.dart';

import 'support/coach_layout_harness.dart';
import 'support/fake_mayos_api.dart';

void main() {
  testWidgets('Player history, program, and check-ins fit both phone languages',
      (WidgetTester tester) async {
    late FakeMayosApi fake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi configuredFake) {
        fake = configuredFake
          ..assignments.add(<String, dynamic>{
            'assignment_id': 'assignment-1',
            'player_username': 'bob',
            'started_at': '2026-09-24T10:00:00Z',
            'status': 'active',
          })
          ..coachActiveProgram = <String, dynamic>{
            'has_draft': false,
            'program': <String, dynamic>{
              'program_name': 'Full Body',
              'split_type': 'Full Body',
              'weekly_frequency': 2,
              'instructions': '',
              'version': 7,
              'provenance': 'coach',
              'days': <Map<String, dynamic>>[
                <String, dynamic>{
                  'day_name': 'Full A',
                  'day_order': 1,
                  'exercises': <Map<String, dynamic>>[
                    for (int index = 1; index <= 9; index++)
                      <String, dynamic>{
                        'exercise_id': 'sq-$index',
                        'exercise_name':
                            index == 1 ? 'Squat' : 'Exercise $index',
                        'target_sets': 4,
                        'target_reps_min': 6,
                        'target_reps_max': 8,
                        'target_rpe': 8.0,
                        'rest_seconds': 150,
                      },
                  ],
                },
                <String, dynamic>{
                  'day_name': 'Full B',
                  'day_order': 2,
                  'exercises': <Map<String, dynamic>>[
                    <String, dynamic>{
                      'exercise_id': 'row',
                      'exercise_name': 'Machine Row',
                      'target_sets': 3,
                      'target_reps_min': 8,
                      'target_reps_max': 12,
                      'target_rpe': 8.0,
                      'rest_seconds': 120,
                    },
                  ],
                },
              ],
            },
          };
      },
      ready: (_) => find.byKey(const Key('coach_roster_list_screen')),
      pageScrollable: (_) => find.descendant(
        of: find.byKey(const Key('coach_roster_list_screen')),
        matching: find.byType(Scrollable),
      ).first,
      allowedInnerStrips: (_) =>
          find.byKey(const Key('coach_program_day_tabs_scroll')),
      assertions: (WidgetTester tester, String language) async {
        final bool arabic = language == 'ar';
        final String program = arabic ? 'البرنامج التدريبي' : 'Program';
        final String checkIns = arabic ? 'التواصل' : 'Check-ins';
        await tester.tap(find.text('bob'));
        await _pumpUntilFound(
          tester,
          find.byKey(const Key('coach_player_history_screen')),
        );
        await tester.pumpAndSettle();
        await _expectNoHorizontalPlayerScroll(tester);
        expect(find.text(arabic ? 'الحجم الأسبوعي' : 'Weekly volume'),
            findsWidgets);
        expect(
          find.text(arabic ? 'مجموعات التدريب' : 'Working sets'),
          findsWidgets,
          reason: 'Weekly volume phone cards show their data label.',
        );

        await _expandHistory(tester, 'recentSessions');
        expect(find.textContaining('2026-09-23'), findsWidgets);
        expect(find.text(arabic ? 'المجموعات' : 'Sets'), findsWidgets);
        expect(
          find.textContaining(arabic ? 'إجمالي الوزن المرفوع' : 'Volume (kg)'),
          findsWidgets,
        );
        final Finder recentSession = find.byKey(
          const Key('coach_history_recent_session_s2_toggle'),
        );
        await tester.ensureVisible(recentSession);
        await tester.tap(recentSession);
        await tester.pumpAndSettle();
        await _expectNoHorizontalPlayerScroll(tester);
        await _expandHistory(tester, 'records');
        expect(find.text('Bench Press'), findsWidgets);
        expect(
          find.textContaining(arabic ? 'النوع:' : 'Type:'),
          findsWidgets,
          reason: 'Personal record cards show their compact summary.',
        );
        await _expandHistory(tester, 'exercises');
        expect(find.text('Bench Press'), findsWidgets);
        final Finder exerciseTitle = find.text('Bench Press').last;
        await tester.scrollUntilVisible(
          exerciseTitle,
          300,
          scrollable: find.ancestor(
            of: exerciseTitle,
            matching: find.byType(Scrollable),
          ).first,
        );
        await tester.ensureVisible(exerciseTitle);
        await tester.pump();
        expect(exerciseTitle.hitTestable(), findsOneWidget);
        await tester.tap(exerciseTitle);
        await tester.pumpAndSettle();
        await _pumpUntilFound(tester, find.textContaining('e1RM:'));
        expect(
          find.textContaining(arabic ? 'الوزن:' : 'Weight:'),
          findsOneWidget,
          reason: 'Exercise history cards show their compact point details.',
        );
        await _expectNoHorizontalPlayerScroll(tester);

        await _scrollPlayerToTop(tester);
        final Finder programSegment = find.bySemanticsLabel(program);
        await tester.ensureVisible(programSegment);
        await tester.tap(programSegment);
        await tester.pumpAndSettle();
        expect(find.text('Full A'), findsWidgets);
        expect(find.text('Full B'), findsOneWidget);
        expect(find.text('Squat'), findsOneWidget);
        expect(find.text('Exercise 8'), findsOneWidget);
        expect(find.text('Exercise 9'), findsNothing);
        expect(find.text('Machine Row'), findsNothing);
        final Finder showAll = find.byKey(
          const Key('coach_program_show_remaining'),
        );
        expect(showAll, findsOneWidget);
        await _scrollPlayerUntilVisible(tester, showAll);
        await tester.tap(showAll);
        await tester.pumpAndSettle();
        expect(find.text('Exercise 9'), findsOneWidget);
        expect(find.text('Machine Row'), findsNothing);
        final Finder secondDayTab = find.byKey(
          const Key('coach_program_day_tab_1'),
        );
        await _scrollPlayerUntilVisible(tester, secondDayTab);
        await tester.tap(secondDayTab);
        await tester.pumpAndSettle();
        expect(find.text('Machine Row'), findsOneWidget);
        expect(find.text('Squat'), findsNothing);
        expect(find.text('Exercise 9'), findsNothing);
        expect(find.textContaining('×'), findsWidgets);
        await _expectNoHorizontalPlayerScroll(tester);

        await _scrollPlayerToTop(tester);
        final Finder checkInsSegment = find.bySemanticsLabel(checkIns);
        await tester.ensureVisible(checkInsSegment);
        await tester.tap(checkInsSegment);
        await tester.pumpAndSettle();
        await _expectNoHorizontalPlayerScroll(tester);
        await tester.ensureVisible(
          find.byKey(const Key('record_check_in_button')),
        );
        await tester.tap(find.byKey(const Key('record_check_in_button')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('check_in_channel_phone')), findsOneWidget);
        await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
        await tester.tap(find.byKey(const Key('check_in_channel_phone')));
        await tester.enterText(
          find.byKey(const Key('check_in_note_field')),
          'Phone follow-up recorded',
        );
        await tester.tap(find.byKey(const Key('check_in_submit_button')));
        await tester.pumpAndSettle();
        expect(find.text('Phone follow-up recorded'), findsOneWidget);
        expect(fake.checkIns, hasLength(1));
        await _expectNoHorizontalPlayerScroll(tester);
      },
    );
  });

  testWidgets('Player program tabs work at 900 by 700 in both languages',
      (WidgetTester tester) async {
    for (final String language in <String>['en', 'ar']) {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      final FakeMayosApi fake = createCoachFake(language: language)
        ..assignments.add(<String, dynamic>{
          'assignment_id': 'assignment-1',
          'player_username': 'bob',
          'started_at': '2026-09-24T10:00:00Z',
          'status': 'active',
        })
        ..coachActiveProgram = <String, dynamic>{
          'has_draft': false,
          'program': <String, dynamic>{
            'program_name': 'Full Body',
            'split_type': 'Full Body',
            'weekly_frequency': 2,
            'instructions': '',
            'version': 7,
            'provenance': 'coach',
            'days': <Map<String, dynamic>>[
              <String, dynamic>{
                'day_name': 'Full A',
                'day_order': 1,
                'exercises': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'exercise_id': 'sq',
                    'exercise_name': 'Squat',
                    'target_sets': 4,
                    'target_reps_min': 6,
                    'target_reps_max': 8,
                    'target_rpe': 8.0,
                    'rest_seconds': 150,
                  },
                ],
              },
              <String, dynamic>{
                'day_name': 'Full B',
                'day_order': 2,
                'exercises': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'exercise_id': 'row',
                    'exercise_name': 'Machine Row',
                    'target_sets': 3,
                    'target_reps_min': 8,
                    'target_reps_max': 12,
                    'target_rpe': 8.0,
                    'rest_seconds': 120,
                  },
                ],
              },
            ],
          },
        };
      await pumpCoachApp(
        tester,
        fake,
        logicalSize: const Size(900, 700),
        language: language,
      );
      await _pumpUntilFound(
        tester,
        find.byKey(const Key('coach_roster_list_screen')),
      );
      await tester.tap(find.text('bob'));
      await _pumpUntilFound(
        tester,
        find.byKey(const Key('coach_player_history_screen')),
      );
      await tester.pumpAndSettle();
      final String program =
          language == 'ar' ? 'البرنامج التدريبي' : 'Program';
      final Finder programSegment = find.bySemanticsLabel(program);
      await tester.ensureVisible(programSegment);
      await tester.tap(programSegment);
      await tester.pumpAndSettle();

      expect(find.text('Full A'), findsWidgets);
      expect(find.text('Full B'), findsOneWidget);
      expect(find.text('Squat'), findsOneWidget);
      expect(find.text('Machine Row'), findsNothing);
      expect(tester.takeException(), isNull);

      await tester.tap(find.byKey(const Key('coach_program_day_tab_1')));
      await tester.pumpAndSettle();
      expect(find.text('Machine Row'), findsOneWidget);
      expect(find.text('Squat'), findsNothing);
      expect(tester.takeException(), isNull);
    }
  });

  testWidgets('Player program keeps its desktop table at 1440 by 960',
      (WidgetTester tester) async {
    await pumpCoachDesktopLayout(
      tester,
      configureFake: (FakeMayosApi fake) {
        fake.assignments.add(<String, dynamic>{
          'assignment_id': 'assignment-1',
          'player_username': 'bob',
          'started_at': '2026-09-24T10:00:00Z',
          'status': 'active',
        });
        fake.coachActiveProgram = <String, dynamic>{
          'has_draft': false,
          'program': <String, dynamic>{
            'program_name': 'Full Body',
            'split_type': 'Full Body',
            'weekly_frequency': 1,
            'instructions': '',
            'version': 7,
            'provenance': 'coach',
            'days': <Map<String, dynamic>>[
              <String, dynamic>{
                'day_name': 'Full A',
                'day_order': 1,
                'exercises': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'exercise_id': 'sq',
                    'exercise_name': 'Squat',
                    'target_sets': 4,
                    'target_reps_min': 6,
                    'target_reps_max': 8,
                    'target_rpe': 8.0,
                    'rest_seconds': 150,
                  },
                ],
              },
            ],
          },
        };
      },
      ready: find.text('Active assignments'),
      logicalSize: const Size(1440, 960),
    );
    await tester.tap(find.text('bob'));
    await tester.pumpAndSettle();
    final Finder volumeIndicator = find.byType(LinearProgressIndicator).first;
    final Finder volumeBar = volumeIndicator;
    final Rect barRect = tester.getRect(volumeBar);
    final Rect setsRect = tester.getRect(find.text('12.5').first);
    final List<Rect> rowRects = find
        .ancestor(of: volumeBar, matching: find.byType(Row))
        .evaluate()
        .map((Element element) {
          final RenderBox box = element.renderObject as RenderBox;
          return box.localToGlobal(Offset.zero) & box.size;
        })
        .toList();
    final Rect rowRect = rowRects.first;
    expect(
      barRect.width / rowRect.width,
      closeTo(0.458, 0.03),
    );
    expect(setsRect.left - barRect.right, closeTo(MayosSpacing.xs, 1));
    expect(
      (setsRect.left - rowRect.left) / rowRect.width,
      closeTo(0.558, 0.03),
    );
    expect(
      (setsRect.right - rowRect.left) / rowRect.width,
      closeTo(0.624, 0.03),
    );
    await _expandHistory(tester, 'recentSessions');
    expect(find.text('2026-09-23'), findsWidgets);
    expect(find.text('Lower 1'), findsWidgets);
    await _expandHistory(tester, 'records');
    expect(find.text('Exercise'), findsWidgets);
    expect(find.text('Type'), findsOneWidget);
    expect(find.text('Value'), findsOneWidget);
    expect(find.text('Date'), findsWidgets);
    await _scrollPlayerToTop(tester);
    await tester.tap(find.text('Program').first);
    await tester.pumpAndSettle();

    expect(find.text('Full A'), findsWidgets);
    expect(find.text('Exercise'), findsOneWidget);
    expect(find.text('Action'), findsOneWidget);
    expect(find.text('—'), findsWidgets);
    expect(find.text('Squat'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

Future<void> _expectNoHorizontalPlayerScroll(WidgetTester tester) async {
  final Finder screen = find.byKey(const Key('coach_player_history_screen'));
  expect(screen, findsOneWidget);
  for (final Element element in find
      .descendant(of: screen, matching: find.byType(Scrollable))
      .evaluate()) {
    final Scrollable scrollable = element.widget as Scrollable;
    if (scrollable.axisDirection == AxisDirection.left ||
        scrollable.axisDirection == AxisDirection.right) {
      bool isDayTabStrip = false;
      element.visitAncestorElements((Element ancestor) {
        if (ancestor.widget.key ==
            const Key('coach_program_day_tabs_scroll')) {
          isDayTabStrip = true;
          return false;
        }
        return true;
      });
      if (isDayTabStrip) continue;
    }
    expect(
      scrollable.axisDirection,
      isNot(anyOf(AxisDirection.left, AxisDirection.right)),
    );
  }
  expect(tester.takeException(), isNull);
  await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
}

Future<void> _scrollPlayerToTop(WidgetTester tester) async {
  final Finder pageScrollable = find.descendant(
    of: find.byKey(const Key('coach_player_history_scroll')),
    matching: find.byType(Scrollable),
  ).first;
  tester.state<ScrollableState>(pageScrollable).position.jumpTo(0);
  await tester.pumpAndSettle();
}

Future<void> _scrollPlayerUntilVisible(
  WidgetTester tester,
  Finder target,
) async {
  await tester.scrollUntilVisible(
    target,
    300,
    scrollable: find.descendant(
      of: find.byKey(const Key('coach_player_history_scroll')),
      matching: find.byType(Scrollable),
    ).first,
  );
  await tester.pumpAndSettle();
}

Future<void> _pumpUntilFound(
  WidgetTester tester,
  Finder finder,
) async {
  for (int attempt = 0; attempt < 60 && finder.evaluate().isEmpty; attempt++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  expect(finder, findsWidgets);
}

Future<void> _expandHistory(WidgetTester tester, String section) async {
  final Finder control = find.byKey(
    Key('coach_history_section_${section}_semantics'),
  );
  await tester.ensureVisible(control);
  await tester.pumpAndSettle();
  expect(control.hitTestable(), findsOneWidget);
  await tester.tap(control);
  await tester.pumpAndSettle();
}
