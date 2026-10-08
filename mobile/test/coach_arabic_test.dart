import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language/coach_copy.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/ui/mayos_markdown.dart';
import 'package:mayos_mobile/src/features/coach/coach_exercise_table.dart'
    show CoachCompactExerciseRow;
import 'package:mayos_mobile/src/features/coach/coach_history_segment.dart';
import 'package:mayos_mobile/src/features/coach/coach_player_history_screen.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

Future<void> _pumpUntilFound(
  WidgetTester tester,
  Finder finder, {
  int attempts = 40,
}) async {
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

FakeMayosApi _coachFake({bool assistant = false}) {
  final FakeMayosApi fake = FakeMayosApi()
    ..issuedToken = 'token-arabic-coach'
    ..currentUsername = 'coach_ar'
    ..tokenValid = true
    ..coach = true
    ..profileExists = true
    ..recoveryEmail = 'coach@example.com'
    ..displayLanguage = 'ar'
    ..coachAiEnabled = assistant
    ..coachDisplayName = 'Coach Arabic'
    ..coachBio = 'Coach bio from the service.'
    ..coachSpecialization = 'Powerlifting'
    ..coachCapacity = 12;
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-ar',
    'player_username': 'player_ar',
    'started_at': '2026-09-24T10:00:00Z',
    'status': 'active',
    'current_missed_streak': 3,
    'alerts_new': 1,
  });
  fake.coachAlerts.add(<String, dynamic>{
    'alert_id': 'alert-ar',
    'assignment_id': 'assignment-ar',
    'player_username': 'player_ar',
    'kind': 'missed_expected_days',
    'streak_start_date': '2026-09-20',
    'last_missed_date': '2026-09-21',
    'missed_count': 2,
    'state': 'new',
    'created_at': '2026-09-22T08:00:00Z',
    'acknowledged_at': null,
    'resolved_at': null,
    'resolved_by': null,
  });
  fake.assignmentNotices.add(<String, dynamic>{
    'notice_id': 'notice-ar',
    'kind': 'player_update',
    'message': 'API notice: program schedule changed.',
    'created_at': '2026-10-01T12:00:00Z',
    'read_at': null,
  });
  return fake;
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  Size logicalSize = const Size(540, 1200),
  double devicePixelRatio = 2,
}) async {
  tester.view.physicalSize = Size(
    logicalSize.width * devicePixelRatio,
    logicalSize.height * devicePixelRatio,
  );
  tester.view.devicePixelRatio = devicePixelRatio;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save(fake.issuedToken!);
  await tester.pumpWidget(authApp(fake, tokens));
  await _pumpUntilFound(tester, find.text('علاقات التدريب النشطة'));
}

Future<void> _pumpArabicHistorySegment(WidgetTester tester) async {
  tester.view.physicalSize = const Size(2880, 4800);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final List<PersonalRecord> records = <PersonalRecord>[
    const PersonalRecord(
      exerciseId: 'squat_weight',
      name: 'Squat',
      recordType: 'max_weight',
      reps: 5,
      value: 95,
      achievedAt: '2026-10-01T10:00:00Z',
      primaryMuscle: 'Quads',
    ),
    const PersonalRecord(
      exerciseId: 'squat_e1rm',
      name: 'Squat',
      recordType: 'max_e1rm',
      reps: 3,
      value: 120,
      achievedAt: '2026-10-02T10:00:00Z',
    ),
    for (final int reps in <int>[1, 2, 11])
      PersonalRecord(
        exerciseId: 'band_reps_$reps',
        name: 'Band Pull-Apart',
        recordType: 'most_reps',
        reps: reps,
        value: reps.toDouble(),
        achievedAt: '2026-10-03T10:00:00Z',
      ),
  ];
  final CoachHistorySegment segment = CoachHistorySegment(
    data: CoachHistorySegmentData(
      summary: const CoachPlayerSummary(
        playerUsername: 'player_ar',
        startedAt: '2026-09-24T10:00:00Z',
        status: 'active',
        volume: <String, double>{},
      ),
      records: records,
      checkpointReviews: const <CheckpointReviewListItem>[],
      exercises: const <CoachPlayerExercise>[
        CoachPlayerExercise(
          id: 'squat',
          name: 'Squat',
          primaryMuscle: 'Quads',
        ),
      ],
      histories: const <String, CoachExerciseHistory>{
        'squat': CoachExerciseHistory(
          equipment: 'barbell',
          history: <CoachExerciseHistoryPoint>[
            CoachExerciseHistoryPoint(
              date: '2026-10-03',
              weightKg: 100,
              reps: 8,
              rpe: 8,
              e1rm: 120,
            ),
          ],
          records: <CoachExerciseRecord>[
            CoachExerciseRecord(
              recordType: 'max_weight',
              reps: 8,
              value: 90,
              achievedAt: '2026-10-03T10:00:00Z',
            ),
          ],
        ),
      },
      openExerciseId: 'squat',
      loadingHistory: false,
      expandedSections: <CoachHistorySection, bool>{
        CoachHistorySection.records: true,
        CoachHistorySection.exercises: true,
      },
    ),
    onToggleSection: (_) {},
    onExerciseToggle: (_) {},
    onCheckpointTap: (_) {},
  );

  await tester.pumpWidget(
    MaterialApp(
      locale: const Locale('ar'),
      supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: MayosTheme.lightForLanguage('ar'),
      home: MediaQuery(
        data: const MediaQueryData(size: Size(1440, 2400)),
        child: SingleChildScrollView(child: segment),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  test('Personal-record rep values use localized singular and plural counts',
      () {
    const CoachCopy english = CoachCopy('en');
    const CoachCopy arabic = CoachCopy('ar');

    expect(english.recordValueLabel('most_reps', '1', 1), '1 rep');
    expect(english.recordValueLabel('most_reps', '2', 2), '2 reps');
    expect(arabic.recordValueLabel('most_reps', '1', 1), 'تكرار واحد');
    expect(arabic.recordValueLabel('most_reps', '2', 2), 'تكراران');
    expect(arabic.recordValueLabel('most_reps', '11', 11),
        '\u206611\u2069 تكرارًا');
    expect(english.recordTypeLabel('future_kind'), 'future_kind');
    expect(arabic.recordTypeLabel('future_kind'), 'future_kind');
    expect(
      english.recordCompactSummary('most_reps', '2', 2, '2026-10-03'),
      'Type: Most reps · Value: 2 reps · Date: 2026-10-03',
    );
    expect(
      arabic.recordCompactSummary('most_reps', '2', 2, '2026-10-03'),
      'النوع: أكبر عدد من التكرارات · القيمة: تكراران · التاريخ: '
          '\u20662026-10-03\u2069',
    );
  });

  test('Arabic Coach program counts localize singular, dual and plural forms',
      () {
    const CoachCopy arabic = CoachCopy('ar');
    expect(arabic.programActionColumn, 'الحركة');
    expect(arabic.showRemainingProgramExercises(1), 'عرض تمرين واحد إضافي');
    expect(arabic.showRemainingProgramExercises(2), 'عرض تمرينان إضافيان');
    expect(arabic.showRemainingProgramExercises(3),
        'عرض \u20663\u2069 تمارين إضافية');
    expect(arabic.showRemainingProgramExercises(11),
        'عرض \u206611\u2069 تمرينًا إضافيًا');
    expect(arabic.programDaySummary(1, 1), 'تمرين واحد • مجموعة عمل واحدة');
    expect(arabic.programDaySummary(2, 2), 'تمرينان • مجموعتا عمل');
    expect(arabic.programDaySummary(3, 3),
        '\u20663\u2069 تمارين • \u20663\u2069 مجموعات عمل');
    expect(arabic.programDaySummary(11, 11),
        '\u206611\u2069 تمرينًا • \u206611\u2069 مجموعة عمل');
  });

  testWidgets('Arabic coach roster localizes a connection failure',
      (WidgetTester tester) async {
    await _pumpApp(
      tester,
      _coachFake()..coachAssignmentsNetworkFails = true,
    );

    expect(
      find.text('تعذر الاتصال بالخدمة. تحقق من اتصالك بالإنترنت.'),
      findsOneWidget,
    );
    expect(
      find.text('Cannot reach the service. Check your connection.'),
      findsNothing,
    );
  });

  testWidgets(
      'Arabic coach shell keeps RTL, Western counts, and server alert text',
      (WidgetTester tester) async {
    await _pumpApp(tester, _coachFake());

    expect(find.text('قائمة اللاعبين'), findsOneWidget);
    expect(find.text('علاقات التدريب النشطة'), findsOneWidget);
    expect(
      find.byWidgetPredicate((Widget widget) {
        if (widget is! Text) return false;
        final String text = widget.data ?? widget.textSpan?.toPlainText() ?? '';
        final String withoutBidiIsolates =
            text.replaceAll('\u2066', '').replaceAll('\u2069', '');
        return withoutBidiIsolates.contains('3 أيام');
      }),
      findsOneWidget,
    );
    expect(find.text('٣'), findsNothing);
    expect(find.textContaining('٣'), findsNothing);
    final Finder rosterUsername = find.descendant(
      of: find.byKey(const Key('roster_row_assignment-ar')),
      matching: find.text('player_ar'),
    );
    expect(
      Directionality.of(tester.element(rosterUsername)),
      TextDirection.rtl,
    );

    await tester.tap(find.text('التنبيهات'));
    await _pumpUntilFound(tester, find.text('عرض التنبيهات المحلولة'));
    expect(find.text('تأكيد الاطلاع'), findsOneWidget);
    expect(
      find.text('Missed 2 expected training days (2026-09-20 to 2026-09-21)'),
      findsOneWidget,
    );
  });

  testWidgets(
      'issue #390: Arabic roster fits at 360dp with long player details',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments[0]
      ..['player_username'] = 'player_ar_with_a_very_long_username'
      ..['last_workout_on'] = '2026-10-07'
      ..['program_name'] =
          'برنامج تدريبي طويل للياقة والقوة';

    await _pumpApp(
      tester,
      fake,
      logicalSize: const Size(360, 800),
      devicePixelRatio: 1,
    );

    final Finder rosterRow =
        find.byKey(const Key('roster_row_assignment-ar'));
    final Finder username = find.descendant(
      of: rosterRow,
      matching: find.text('player_ar_with_a_very_long_username'),
    );
    final Finder subtitle = find.descendant(
      of: rosterRow,
      matching: find.textContaining('2026-10-07'),
    );
    final Finder revoke = find.descendant(
      of: rosterRow,
      matching: find.text('إنهاء العلاقة'),
    );
    expect(username, findsOneWidget);
    expect(subtitle, findsOneWidget);
    expect(revoke, findsOneWidget);
    expect(
      tester.getRect(revoke).top,
      greaterThan(tester.getRect(subtitle).bottom),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'issue #390: Arabic desktop Player page renders with roster '
      'and no overflow',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments[0]
      ..['player_username'] = 'player_ar_with_a_very_long_username'
      ..['last_workout_on'] = '2026-10-07'
      ..['program_name'] =
          'برنامج تدريبي طويل للياقة والقوة';

    await _pumpApp(
      tester,
      fake,
      logicalSize: const Size(1440, 900),
      devicePixelRatio: 1,
    );
    await tester.tap(find.byKey(const Key('roster_row_assignment-ar')));
    await _pumpUntilFound(tester, find.byType(CoachPlayerHistoryScreen));

    expect(find.byType(CoachPlayerHistoryScreen), findsOneWidget);
    expect(find.byKey(const Key('coach_player_detail_pane')), findsOneWidget);
    final Finder rosterRow = find.descendant(
      of: find.byKey(const Key('coach_roster_master_pane')),
      matching: find.byKey(const Key('roster_row_assignment-ar')),
    );
    final Finder subtitle = find.descendant(
      of: rosterRow,
      matching: find.textContaining('2026-10-07'),
    );
    final Finder revoke = find.descendant(
      of: rosterRow,
      matching: find.text('إنهاء العلاقة'),
    );
    expect(subtitle, findsOneWidget);
    expect(revoke, findsOneWidget);
    expect(
      tester.getRect(revoke).top,
      greaterThan(tester.getRect(subtitle).bottom),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('Arabic profile and request screens retain API notices verbatim',
      (WidgetTester tester) async {
    await _pumpApp(tester, _coachFake());

    await tester.tap(find.text('الملف الشخصي'));
    await _pumpUntilFound(tester, find.text('الملف الشخصي للمدرب'));
    await _pumpUntilFound(
      tester,
      find.text('API notice: program schedule changed.'),
    );
    expect(find.text('دعوة لاعب'), findsOneWidget);
    expect(find.text('API notice: program schedule changed.'), findsOneWidget);

    await tester.tap(find.text('الطلبات'));
    await _pumpUntilFound(
      tester,
      find.text('لا توجد طلبات للبرنامج التدريبي بعد.'),
    );
  });

  testWidgets('Arabic player detail opens the localized check-in sheet',
      (WidgetTester tester) async {
    await _pumpApp(tester, _coachFake());

    await tester.tap(find.byKey(const Key('roster_row_assignment-ar')));
    await _pumpUntilFound(tester, find.byType(CoachPlayerHistoryScreen));
    await _pumpUntilFound(tester, find.text('السجل'));
    await _pumpUntilFound(tester, find.text('الاستعداد \u20664/5\u2069'));
    expect(find.text('الاستعداد \u20664/5\u2069'), findsOneWidget);
    expect(find.text('البرنامج التدريبي'), findsOneWidget);
    expect(find.text('السجل'), findsOneWidget);
    expect(find.text('التواصل'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(CoachPlayerHistoryScreen),
        matching: find.text('الطلبات'),
      ),
      findsOneWidget,
    );
    await tester.tap(find.text('التواصل'));
    await _pumpUntilFound(tester, find.text('تسجيل تواصل'));
    await tester.tap(find.byKey(const Key('record_check_in_button')));
    await _pumpUntilFound(tester, find.textContaining('تسجيل تواصل مع'));

    expect(find.text('مكالمة هاتفية'), findsOneWidget);
    final Finder dateLabels = find.byWidgetPredicate((Widget widget) {
      if (widget is! Text) return false;
      final String text = widget.data ?? widget.textSpan?.toPlainText() ?? '';
      return RegExp(r'\d{4}-\d{2}-\d{2}').hasMatch(text);
    });
    expect(dateLabels, findsWidgets);
    for (final Element element in dateLabels.evaluate()) {
      final Text text = element.widget as Text;
      final String value = text.data ?? text.textSpan!.toPlainText();
      expect(RegExp(r'[0-9]{4}-[0-9]{2}-[0-9]{2}').hasMatch(value), isTrue);
      expect(value, isNot(contains('٢٠٢٦')));
    }
    expect(
      Directionality.of(tester.element(find.textContaining('تسجيل تواصل مع'))),
      TextDirection.rtl,
    );
  });

  testWidgets('Arabic History section count uses Western numerals',
      (WidgetTester tester) async {
    await _pumpApp(tester, _coachFake());

    await tester.tap(find.byKey(const Key('roster_row_assignment-ar')));
    await _pumpUntilFound(tester, find.text('مجموعات التدريب آخر ٧ أيام'));
    expect(find.text('يتدرب معك منذ'), findsOneWidget);
    expect(find.text('\u20662026-09-24\u2069'), findsOneWidget);
    expect(find.text('آخر حصة'), findsOneWidget);
    expect(find.text('مجموعات التدريب آخر ٧ أيام'), findsOneWidget);
    expect(find.text('الأرقام القياسية الشخصية'), findsOneWidget);
    expect(
      Directionality.of(
        tester.element(find.text('مجموعات التدريب آخر ٧ أيام')),
      ),
      TextDirection.rtl,
    );
    final Finder section =
        find.byKey(const Key(
          'coach_history_section_recentSessions_semantics',
        ));
    await tester.scrollUntilVisible(section, 300,
        scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(section);
    final Finder title = find.byWidgetPredicate(
      (Widget widget) =>
          widget is Text && widget.data?.startsWith('الحصص الأخيرة') == true,
    );

    expect(tester.widget<Text>(title).data, 'الحصص الأخيرة (\u20662\u2069)');
  });

  testWidgets('Arabic desktop History records and exercise tables localize',
      (WidgetTester tester) async {
    await _pumpArabicHistorySegment(tester);

    expect(find.text('النوع'), findsOneWidget);
    expect(find.text('أقصى وزن'), findsWidgets);
    expect(find.text('e1RM'), findsWidgets);
    expect(find.text('أكبر عدد من التكرارات'), findsWidgets);
    expect(find.text('تكرار واحد'), findsOneWidget);
    expect(find.text('تكراران'), findsOneWidget);
    expect(find.text('\u206611\u2069 تكرارًا'), findsOneWidget);
    expect(find.text('التاريخ'), findsWidgets);
    expect(find.text('الوزن'), findsOneWidget);
    expect(find.text('\u2066100.0 kg\u2069'), findsOneWidget);
    expect(find.textContaining('max_weight'), findsNothing);

    final Finder weightCell = find.text('\u2066100.0 kg\u2069');
    expect(tester.widget<Text>(weightCell).textDirection, TextDirection.ltr);
    expect(
      Directionality.of(tester.element(weightCell)),
      TextDirection.rtl,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('Arabic History has no overflow at 360dp through Exercises',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachPlayerRecords = <Map<String, dynamic>>[
        <String, dynamic>{
          'exercise_id': 'front_squat',
          'name': 'Front Squat',
          'record_type': 'max_e1rm',
          'reps': 5,
          'value': 120.5,
          'achieved_at': '2026-09-20T10:00:00Z',
          'primary_muscle': 'Quads',
        },
      ]
      ..coachPlayerExercises = <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 'front_squat',
          'name': 'Front Squat',
          'primary_muscle': 'Quads',
        },
      ];
    await _pumpApp(tester, fake);
    tester.view.physicalSize = const Size(720, 6000);
    tester.view.devicePixelRatio = 2;

    await tester.tap(find.byKey(const Key('roster_row_assignment-ar')));
    await _pumpUntilFound(tester, find.text('مجموعات التدريب آخر ٧ أيام'));

    final Finder records =
        find.byKey(const Key('coach_history_section_records_semantics'));
    await tester.scrollUntilVisible(
      records,
      300,
      scrollable: find.ancestor(
        of: records,
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.ensureVisible(records);
    await tester.tap(records);
    await tester.pumpAndSettle();
    expect(find.text('Front Squat'), findsOneWidget);
    expect(find.textContaining('النوع: e1RM'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.text('Front Squat'))),
      TextDirection.rtl,
    );

    final Finder exercises =
        find.byKey(const Key('coach_history_section_exercises_semantics'));
    await tester.scrollUntilVisible(
      exercises,
      300,
      scrollable: find.ancestor(
        of: exercises,
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.ensureVisible(exercises);
    await tester.pump();

    await tester.tap(exercises);
    await tester.pumpAndSettle();
    final Finder exerciseTile =
        find.widgetWithText(ExpansionTile, 'Front Squat');
    await tester.scrollUntilVisible(
      exerciseTile,
      300,
      scrollable: find.ancestor(
        of: exerciseTile,
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.ensureVisible(exerciseTile);
    await tester.tap(exerciseTile);
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'Arabic coach assistant keeps mixed reply text verbatim and directs each paragraph',
      (WidgetTester tester) async {
    const String reply = 'رد عربي أول مع Coach والرقم 42/5.\n\n'
        'English first paragraph مع 3 مجموعات.\n\n'
        '- عربي في القائمة مع 4 تكرارات\n'
        '- English list item مع 5 مجموعات\n\n'
        '[المصدر][ref]\n\n'
        '[ref]: https://example.com/source';
    final FakeMayosApi fake = _coachFake(assistant: true)
      ..coachAssistantAnswer = reply;
    await _pumpApp(tester, fake);

    await tester.tap(find.byKey(const Key('roster_row_assignment-ar')));
    await _pumpUntilFound(tester, find.byType(CoachPlayerHistoryScreen));
    expect(find.byTooltip('اسأل المساعد'), findsOneWidget);
    await tester.tap(find.byKey(const Key('coach_assistant_entry')));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('coach_assistant_question')),
    );

    expect(find.text('المساعد'), findsOneWidget);
    expect(find.byTooltip('إرسال'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.text('المساعد'))),
      TextDirection.rtl,
    );
    final Finder questionField =
        find.byKey(const Key('coach_assistant_question'));
    expect(
      (tester.widget(questionField) as TextField).decoration!.hintText,
      'اسأل عن هذا اللاعب',
    );

    await tester.enterText(questionField, 'ما التقدم؟');
    await tester.pump();
    await tester.tap(find.byKey(const Key('coach_assistant_send')));
    final Finder replyMarkdown = find.byWidgetPredicate(
      (Widget widget) => widget is MayosMarkdown && widget.source == reply,
    );
    final Finder referenceLink = find.descendant(
      of: replyMarkdown,
      matching: find.byWidgetPredicate(
        (Widget widget) =>
            widget is SelectableText &&
            widget.textSpan?.toPlainText() == 'المصدر',
      ),
    );
    await _pumpUntilFound(tester, referenceLink);

    expect(
      replyMarkdown,
      findsOneWidget,
    );
    expect(
      find.text('رد عربي أول مع Coach والرقم 42/5.', findRichText: true),
      findsOneWidget,
    );
    expect(
      find.text('English first paragraph مع 3 مجموعات.', findRichText: true),
      findsOneWidget,
    );
    expect(find.textContaining('٤٢'), findsNothing);

    Finder paragraph(String text) => find.descendant(
          of: replyMarkdown,
          matching: find.byWidgetPredicate(
            (Widget widget) =>
                widget is SelectableText &&
                widget.textSpan?.toPlainText() == text,
          ),
        );

    TextDirection paragraphDirection(String text) {
      final Finder selectable = paragraph(text);
      expect(selectable, findsOneWidget);
      return Directionality.of(tester.element(selectable));
    }

    bool containsLinkRecognizer(InlineSpan span) {
      if (span is! TextSpan) return false;
      if (span.recognizer != null) return true;
      return span.children?.any(containsLinkRecognizer) ?? false;
    }

    final SelectableText referenceText = tester.widget<SelectableText>(
      referenceLink,
    );
    expect(containsLinkRecognizer(referenceText.textSpan!), isTrue);
    expect(find.text('المصدر', findRichText: true), findsOneWidget);
    expect(
      paragraphDirection('رد عربي أول مع Coach والرقم 42/5.'),
      TextDirection.rtl,
    );
    expect(
      paragraphDirection('English first paragraph مع 3 مجموعات.'),
      TextDirection.ltr,
    );
    expect(
      paragraphDirection('عربي في القائمة مع 4 تكرارات'),
      TextDirection.rtl,
    );
    expect(
      paragraphDirection('English list item مع 5 مجموعات'),
      TextDirection.ltr,
    );
    expect(paragraphDirection('المصدر'), TextDirection.rtl);
  });

  testWidgets('Arabic Coach program localizes exercise metadata and action',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachActiveProgram = <String, dynamic>{
      'has_draft': false,
      'program': <String, dynamic>{
        'program_name': 'Full Body',
        'split_type': 'Full Body',
        'weekly_frequency': 1,
        'instructions': '',
        'version': 7,
        'provenance': 'coach',
        'active_since': '2026-10-04T10:00:00Z',
        'days': <Map<String, dynamic>>[
          <String, dynamic>{
            'day_name': 'Full A',
            'day_order': 1,
            'exercises': <Map<String, dynamic>>[
              <String, dynamic>{
                'exercise_id': 'press',
                'exercise_name': 'Press',
                'target_sets': 2,
                'target_reps_min': 8,
                'target_reps_max': 10,
                'target_rpe': 9,
                'equipment': 'leverage machine',
                'equipment_category': 'Machine',
                'load_type': 'selectorized',
                'primary_muscle': 'Chest',
                'primary_action': 'Shoulder Flexion',
              },
              <String, dynamic>{
                'exercise_id': 'cable',
                'exercise_name': 'Cable Row',
                'target_sets': 2,
                'target_reps_min': 8,
                'target_reps_max': 10,
                'target_rpe': 9,
                'equipment': 'cable',
                'equipment_category': 'Cable',
              },
              <String, dynamic>{
                'exercise_id': 'dumbbell',
                'exercise_name': 'Dumbbell Press',
                'target_sets': 2,
                'target_reps_min': 8,
                'target_reps_max': 10,
                'target_rpe': 9,
                'equipment': 'dumbbell',
                'equipment_category': 'Free weight',
              },
            ],
          },
        ],
      },
    };
    await _pumpApp(tester, fake);
    await tester.tap(find.byKey(const Key('roster_row_assignment-ar')));
    await _pumpUntilFound(tester, find.byType(CoachPlayerHistoryScreen));
    await _pumpUntilFound(tester, find.text('السجل'));
    await tester.tap(find.text('البرنامج التدريبي').first);
    await _pumpUntilFound(tester, find.text('Press'));

    expect(find.text('الصدر'), findsOneWidget);
    expect(find.textContaining('ثني الكتف'), findsWidgets);
    expect(
      find.textContaining('محمل بدبوس الأوزان'),
      findsOneWidget,
    );
    expect(find.textContaining('كابل'), findsOneWidget);
    expect(find.textContaining('\u2066Dumbbell\u2069'), findsOneWidget);
    expect(find.text('الحركة: ثني الكتف'), findsOneWidget);
    expect(
      find.descendant(
        of: find.ancestor(
          of: find.text('Cable Row'),
          matching: find.byType(CoachCompactExerciseRow),
        ),
        matching: find.text('الحركة: —'),
      ),
      findsOneWidget,
    );
    expect(
      Directionality.of(
        tester.element(find.text('الحركة: ثني الكتف')),
      ),
      TextDirection.rtl,
    );
  });
}
