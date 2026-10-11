import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
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

FakeMayosApi _coachFake({required bool coachAiEnabled}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = true;
  fake.coachAiEnabled = coachAiEnabled;
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
  await tester.tap(find.byType(DropdownButtonFormField<String>));
  await tester.pumpAndSettle();
  await tester.tap(find.text(username).last);
  await tester.pumpAndSettle();
}

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

    await tester.tap(find.byType(DropdownButtonFormField<String>));
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
}

GoRouter _router(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(MayosApp)))
        .read(routerProvider);
