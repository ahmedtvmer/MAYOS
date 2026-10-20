import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_markdown.dart';
import 'package:mayos_mobile/src/features/coach/coach_assistant_state.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_mayos_api.dart';

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 50}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 5; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
  expect(finder, findsWidgets, reason: 'Timed out waiting for $finder');
}

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake) async {
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
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
  await _pumpUntilFound(tester, find.text('Roster'));
}

FakeMayosApi _coachFake({
  required bool coachAiEnabled,
  bool coachRosterAiEnabled = false,
  bool coachPro = false,
  bool? coachRosterAiAvailable,
}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = true;
  fake.coachAiEnabled = coachAiEnabled;
  fake.coachRosterAiEnabled = coachRosterAiEnabled;
  fake.coachPlan = coachPro ? 'pro' : 'free';
  fake.coachRosterAiAvailable = coachRosterAiAvailable ?? coachPro;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  fake.assignments.addAll(<Map<String, dynamic>>[
    <String, dynamic>{
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'started_at': '2026-09-24T10:00:00Z',
      'status': 'active',
    },
    <String, dynamic>{
      'assignment_id': 'assignment-2',
      'player_username': 'carol',
      'started_at': '2026-09-25T10:00:00Z',
      'status': 'active',
    },
    <String, dynamic>{
      'assignment_id': 'assignment-ended',
      'player_username': 'former-player',
      'started_at': '2026-09-20T10:00:00Z',
      'status': 'ended',
    },
  ]);
  return fake;
}

ProviderContainer _container(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(MayosApp)));

Future<void> _choosePlayer(WidgetTester tester, String username) async {
  final Finder picker = find.byType(DropdownButtonFormField<String>);
  await tester.ensureVisible(picker);
  await tester.tap(picker);
  await tester.pumpAndSettle();
  await tester.tap(find.text(username).last);
  await tester.pumpAndSettle();
}

Finder _rosterMarkdown(String source) => find.byWidgetPredicate(
      (Widget widget) => widget is MayosMarkdown && widget.source == source,
    );

void main() {
  testWidgets(
      'the Assistant tab picker opens the one-player assistant and '
      'switching players clears the in-memory transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(coachAiEnabled: true);
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Assistant'));
    await _pumpUntilFound(
        tester, find.byType(DropdownButtonFormField<String>));
    expect(find.text('Roster questions'), findsNothing);
    expect(find.text('Ask about one player'), findsOneWidget);

    final CoachAssistantController controller =
        _container(tester).read(coachAssistantControllerProvider.notifier);
    controller.openFor('assignment-2');
    controller.recordExchange(
      'assignment-2',
      question: 'Existing question',
      answer: 'Existing answer',
    );

    final Finder picker = find.byType(DropdownButtonFormField<String>);
    await tester.ensureVisible(picker);
    await tester.tap(picker);
    await tester.pumpAndSettle();
    expect(find.text('former-player'), findsNothing);
    await tester.tap(find.text('bob').last);
    await tester.pumpAndSettle();
    expect(
      _container(tester).read(coachAssistantControllerProvider)!.assignmentId,
      'assignment-2',
    );
    expect(
      _container(tester).read(coachAssistantControllerProvider)!.turns,
      hasLength(2),
    );
    await tester.tap(find.byKey(const Key('coach_assistant_open_player')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('coach_assistant_question')));

    expect(
      _container(tester).read(coachAssistantControllerProvider)!.assignmentId,
      'assignment-1',
    );
    expect(
      _container(tester).read(coachAssistantControllerProvider)!.turns,
      isEmpty,
    );
    controller.recordExchange(
      'assignment-1',
      question: 'How is bob progressing?',
      answer: 'The supplied figures show steady progress.',
    );
    expect(
      _container(tester).read(coachAssistantControllerProvider)!.turns,
      hasLength(2),
    );
    expect(_router(tester).routeInformationProvider.value.uri.path,
        coachAssistantPath);

    Navigator.of(
            tester.element(find.byKey(const Key('coach_assistant_question'))))
        .pop();
    await tester.pumpAndSettle();
    await _choosePlayer(tester, 'carol');
    expect(
      _container(tester).read(coachAssistantControllerProvider)!.assignmentId,
      'assignment-1',
    );
    expect(
      _container(tester).read(coachAssistantControllerProvider)!.turns,
      hasLength(2),
    );
    await tester.tap(find.byKey(const Key('coach_assistant_open_player')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('coach_assistant_question')));

    final transcript =
        _container(tester).read(coachAssistantControllerProvider)!;
    expect(transcript.assignmentId, 'assignment-2');
    expect(transcript.turns, isEmpty);
    expect(find.text('How is bob progressing?'), findsNothing);
    expect(fake.coachAssistantRequests, isEmpty);
  });

  testWidgets('the picker resets when a roster refresh removes its selection',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(coachAiEnabled: true);
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Assistant'));
    await _pumpUntilFound(
        tester, find.byType(DropdownButtonFormField<String>));
    await _choosePlayer(tester, 'bob');
    expect(find.text('bob'), findsOneWidget);
    final Key? originalKey =
        tester.widget<DropdownButtonFormField<String>>(
      find.byType(DropdownButtonFormField<String>),
    ).key;

    fake.assignments.removeWhere(
      (Map<String, dynamic> row) => row['assignment_id'] == 'assignment-1',
    );
    _container(tester).read(coachRosterRevisionProvider.notifier).state++;
    await tester.pumpAndSettle();

    final Key? refreshedKey =
        tester.widget<DropdownButtonFormField<String>>(
      find.byType(DropdownButtonFormField<String>),
    ).key;
    expect(refreshedKey, isNot(originalKey));
    expect(find.text('bob'), findsNothing);
  });

  testWidgets(
      'the Assistant tab explains when Coach AI is disabled and '
      'does not show the picker or chat', (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(coachAiEnabled: false);
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Assistant'));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_ai_disabled')));

    expect(
        find.textContaining('turned off for this deployment'), findsOneWidget);
    expect(find.byType(DropdownButtonFormField<String>), findsNothing);
    expect(find.byKey(const Key('coach_assistant_open_player')), findsNothing);
    expect(find.byKey(const Key('coach_assistant_question')), findsNothing);
  });

  testWidgets(
      'roster replies keep aliases and coverage separate, show names, and link players',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(
      coachAiEnabled: true,
      coachRosterAiEnabled: true,
      coachPro: true,
    );
    await _pumpApp(tester, fake);
    await tester.tap(find.text('Assistant'));
    await _pumpUntilFound(tester, find.text('Ask about the roster'));

    expect(find.textContaining('Player chat'), findsOneWidget);
    expect(
      find.textContaining('The hosted model receives only the Roster signal snapshot'),
      findsOneWidget,
    );
    final Finder questionField =
        find.byKey(const Key('coach_roster_assistant_question'));
    await tester.ensureVisible(questionField);
    await tester.enterText(questionField, 'Who needs attention today?');
    await tester.pump();
    await tester.tap(find.byKey(const Key('coach_roster_assistant_send')));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('coach_roster_player_link_Pabcdef123456')),
    );

    expect(
      _rosterMarkdown('Pabcdef123456 (Bob Display) needs attention.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('coach_roster_coverage_summary')), findsOneWidget);
    expect(fake.coachRosterAssistantRequests, hasLength(1));
    expect(fake.coachRosterAssistantRequests.single['question'],
        'Who needs attention today?');
    expect(fake.coachRosterAssistantRequests.single['history'], isEmpty);
    final CoachRosterAssistantTranscript transcript = _container(tester)
        .read(coachRosterAssistantControllerProvider);
    expect(transcript.exchanges.single.answer,
        'Pabcdef123456 needs attention.');
    expect(transcript.exchanges.single.coverageSummary,
        startsWith('Snapshot coverage:'));
    expect(
        transcript.exchanges.single.assignmentByPlayerId['Pabcdef123456'],
        'assignment-1');

    await tester.enterText(questionField, 'What about that player?');
    await tester.pump();
    await tester.tap(find.byKey(const Key('coach_roster_assistant_send')));
    await _pumpUntilFound(
      tester,
      _rosterMarkdown('Pabcdef123456 (Bob Display) needs attention.'),
    );
    final Map<String, dynamic> followUp = fake.coachRosterAssistantRequests[1];
    expect(followUp['history'], <Map<String, String>>[
      <String, String>{'role': 'coach', 'content': 'Who needs attention today?'},
      <String, String>{
        'role': 'assistant',
        'content': 'Pabcdef123456 needs attention.',
      },
    ]);
    expect(jsonEncode(followUp), isNot(contains('bob')));

    final Finder link = find.byKey(
      const Key('coach_roster_player_link_Pabcdef123456'),
    );
    await tester.ensureVisible(link.last);
    await tester.tap(link.last);
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('coach_assistant_question')),
    );
    expect(find.byKey(const Key('coach_assistant_question')), findsOneWidget);
  });

  testWidgets('a Free Coach sees the roster urgency order and upgrade note',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(
      coachAiEnabled: true,
      coachRosterAiEnabled: true,
      coachPro: false,
    );
    await _pumpApp(tester, fake);
    await tester.tap(find.text('Assistant'));
    await _pumpUntilFound(tester, find.text('Ask about the roster'));

    expect(
      find.text(
        'The Roster urgency order is available. AI roster questions require Coach Pro.',
      ),
      findsOneWidget,
    );
    expect(find.byKey(const Key('coach_roster_urgency_order')), findsOneWidget);
    expect(find.text('1. bob'), findsOneWidget);
    expect(find.text('2. carol'), findsOneWidget);
    expect(find.byKey(const Key('coach_roster_assistant_question')),
        findsNothing);
    expect(find.text('Roster'), findsOneWidget);
  });

  testWidgets('a trial Coach without a Coach plan row sees roster chat',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(
      coachAiEnabled: true,
      coachRosterAiEnabled: true,
      coachPro: false,
      coachRosterAiAvailable: true,
    )..coachPlan = null;
    await _pumpApp(tester, fake);
    await tester.tap(find.text('Assistant'));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('coach_roster_assistant_question')),
    );

    final Account account = _container(tester)
        .read(authControllerProvider)
        .session!
        .account;
    expect(account.plans.coach, isNull);
    expect(account.coachRosterAiAvailable, isTrue);
    expect(find.byKey(const Key('coach_roster_assistant_question')), findsOneWidget);
    expect(find.text('The Roster urgency order is available. AI roster questions require Coach Pro.'), findsNothing);
  });
}

GoRouter _router(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(MayosApp)))
        .read(routerProvider);
