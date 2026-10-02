import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_markdown.dart';
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

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save(fake.issuedToken!);
  await tester.pumpWidget(authApp(fake, tokens));
  await _pumpUntilFound(tester, find.text('علاقات التدريب النشطة'));
}

void main() {
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
    await tester.tap(find.byKey(const Key('player_page_actions')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('coach_assistant_entry')));
    expect(find.text('اسأل المساعد'), findsOneWidget);
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
}
