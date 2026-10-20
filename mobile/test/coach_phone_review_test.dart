import 'package:flutter/material.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'support/coach_layout_harness.dart';
import 'support/fake_mayos_api.dart';

Future<void> _waitFor(WidgetTester tester, Finder finder) async {
  for (int attempt = 0; attempt < 60 && finder.evaluate().isEmpty; attempt++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  expect(finder, findsWidgets);
}

void main() {
  testWidgets('roster assistant panel fits and sends on a phone in both languages',
      (WidgetTester tester) async {
    FakeMayosApi? fakeUsed;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) {
        fakeUsed = fake;
        fake.coachRosterAiEnabled = true;
        fake.coachRosterAiAvailable = true;
        fake.coachPlan = 'pro';
        fake.coachRosterAssistantAnswer =
            '| Player | Status | Note |\n| --- | --- | --- |\n| Pabcdef123456 | Ready | On track |';
        fake.assignments.add(<String, dynamic>{
          'assignment_id': 'assignment-1',
          'player_username': 'bob',
          'started_at': '2026-09-24T10:00:00Z',
          'status': 'active',
        });
      },
      ready: (String language) => find.byKey(const ValueKey<String>('mayos_scaffold_body')),
      pageScrollable: (String language) => find.byType(Scrollable).first,
      allowedInnerStrips: (String language) => find.byKey(
        const Key('coach_roster_assistant_answer'),
      ),
      assertions: (WidgetTester tester, String language) async {
        await tester.tap(find.text(language == 'ar' ? 'المساعد' : 'Assistant'));
        final Finder question = find.byKey(const Key('coach_roster_assistant_question'));
        await _waitFor(tester, question);
        await tester.enterText(question,
            language == 'ar' ? 'من يحتاج إلى متابعة؟' : 'Who needs attention?');
        await tester.pump();
        await tester.tap(find.byKey(const Key('coach_roster_assistant_send')));
        await _waitFor(tester, find.textContaining('Pabcdef123456'));
        expect(fakeUsed!.coachRosterAssistantRequests, hasLength(1));
        expect(find.byType(SelectionArea), findsWidgets);
        expect(tester.takeException(), isNull);
      },
    );
  });

  testWidgets('Coach assistant desktop input and table reply remain selectable',
      (WidgetTester tester) async {
    final FakeMayosApi fake = createCoachFake()
      ..coachAiEnabled = true
      ..coachAssistantAnswer =
          '| Exercise | Sets | Notes |\n| --- | ---: | --- |\n| Lat Pulldown | 3 | Full range |'
      ..assignments.add(<String, dynamic>{
        'assignment_id': 'assignment-1',
        'player_username': 'bob',
        'started_at': '2026-09-24T10:00:00Z',
        'status': 'active',
      });
    await pumpCoachApp(tester, fake, logicalSize: const Size(1440, 960));
    await _waitFor(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _waitFor(tester, find.byKey(const Key('coach_assistant_entry')).hitTestable());
    await tester.tap(find.byKey(const Key('coach_assistant_entry')));
    final Finder composer = find.byKey(const Key('coach_assistant_question'));
    await _waitFor(tester, composer);
    final container = ProviderScope.containerOf(tester.element(composer));
    container.read(coachAssistantControllerProvider.notifier).openFor('assignment-1');
    container.read(coachAssistantControllerProvider.notifier).recordExchange(
      'assignment-1',
      question: 'Show a summary',
      answer: '| Exercise | Sets | Notes |\n| --- | ---: | --- |\n| Lat Pulldown | 3 | Full range |',
    );
    await tester.pump();
    await _waitFor(tester, find.text('Lat Pulldown'));
    expect(find.byType(SelectionArea), findsOneWidget);
    expect(find.byKey(const Key('coach_assistant_reply_bubble')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('roster assistant panel keeps its desktop input and reply',
      (WidgetTester tester) async {
    final FakeMayosApi fake = createCoachFake()
      ..coachRosterAiEnabled = true
      ..coachRosterAiAvailable = true
      ..coachPlan = 'pro'
      ..coachRosterAssistantAnswer =
          '| Player | Status |\n| --- | --- |\n| Pabcdef123456 | Ready |'
      ..assignments.add(<String, dynamic>{
        'assignment_id': 'assignment-1',
        'player_username': 'bob',
        'started_at': '2026-09-24T10:00:00Z',
        'status': 'active',
      });
    await pumpCoachApp(tester, fake, logicalSize: const Size(1440, 960));
    await _waitFor(tester, find.text('Active assignments'));
    await tester.tap(find.text('Assistant'));
    final Finder question = find.byKey(const Key('coach_roster_assistant_question'));
    await _waitFor(tester, question);
    expect(find.byKey(const Key('coach_roster_assistant_send')), findsOneWidget);
    await tester.enterText(question, 'Who needs attention?');
    await tester.pump();
    await tester.tap(find.byKey(const Key('coach_roster_assistant_send')).hitTestable());
    await _waitFor(tester, find.byKey(const Key('coach_roster_assistant_answer')));
    expect(fake.coachRosterAssistantRequests, hasLength(1));
    expect(tester.takeException(), isNull);
  });

}
