import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/display_language/coach_copy.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_markdown.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/coach/coach_assistant_state.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches, then a few more so transitions
/// settle without depending on `pumpAndSettle` (indeterminate spinners never
/// settle).
Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 40}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      // Run past the route's exit transition: a popped route stays in the tree
      // until its animation finishes (~500ms), so later finders see it too.
      for (int j = 0; j < 10; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeMode? themeMode,
  Size? size,
}) async {
  tester.view.physicalSize = size ?? const Size(1080, 2400);
  tester.view.devicePixelRatio = size == null ? 2.0 : 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(
            InMemoryThemeModeStore(themeMode)),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
        // Logout must never reach the secure-storage plugin in a widget test.
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
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
      tester, find.text(fake.coach ? 'Roster' : 'Home'));
}

FakeMayosApi _coachFake(
    {bool coachAiEnabled = true, bool secondPlayer = false}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  fake.coachAiEnabled = coachAiEnabled;
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'started_at': '2026-09-24T10:00:00Z',
    'status': 'active',
  });
  if (secondPlayer) {
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'assignment-2',
      'player_username': 'carol',
      'started_at': '2026-09-25T10:00:00Z',
      'status': 'active',
    });
  }
  return fake;
}

ProviderContainer _container(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(MayosApp)));

Finder _assistantMarkdown(String source) => find.byWidgetPredicate(
      (Widget widget) => widget is MayosMarkdown && widget.source == source,
    );

/// The coach shell opens on the Roster tab (#119).
Future<void> _openRoster(WidgetTester tester) async {
  await _pumpUntilFound(tester, find.text('Active assignments'));
}

/// Roster row → player history → the coach assistant button.
Future<void> _openAssistant(WidgetTester tester, String player) async {
  await tester.tap(find.text(player));
  await _pumpUntilFound(tester, find.text('Weekly volume'));
  await tester.tap(find.byKey(const Key('coach_assistant_entry')));
  await _pumpUntilFound(
      tester, find.byKey(const Key('coach_assistant_question')));
}

/// Opens the Program segment so its actions are on screen.
Future<void> _openProgramSegment(WidgetTester tester) async {
  await tester.tap(find.text('Program').first);
  await _pumpUntilFound(tester, find.text('Generate draft'));
}

/// Pops the top route through [anchor]'s navigator: a pushed route keeps the
/// route beneath it in the tree, so a global "Back" finder matches twice. The
/// pump runs past the exit transition so the popped route is disposed before
/// the next finder runs.
Future<void> _pop(WidgetTester tester, Finder anchor) async {
  Navigator.of(anchor.evaluate().last).pop();
  for (int i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _closeAssistant(WidgetTester tester) =>
    _pop(tester, find.byKey(const Key('coach_assistant_composer')));

Future<void> _closeHistory(WidgetTester tester) =>
    _pop(tester, find.byKey(const Key('log_check_in_action')));

Future<void> _ask(WidgetTester tester, String question) async {
  await tester.enterText(
      find.byKey(const Key('coach_assistant_question')), question);
  // Rebuild so the send button is enabled for the freshly typed text.
  await tester.pump();
  await tester.tap(find.byKey(const Key('coach_assistant_send')));
  await tester.pump(const Duration(milliseconds: 100));
}

/// Pumps until [condition] holds, then settles a few frames.
Future<void> _pumpUntil(WidgetTester tester, bool Function() condition,
    {int attempts = 40}) async {
  for (int i = 0; i < attempts; i++) {
    if (condition()) {
      break;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
  for (int j = 0; j < 4; j++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// Pumps until [finder] holds at least [count] widgets.
Future<void> _pumpUntilCount(WidgetTester tester, Finder finder, int count,
    {int attempts = 40}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().length >= count) {
      break;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
  for (int j = 0; j < 4; j++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  test('the coach assistant disclosure is translated for Arabic Display language', () {
    final String disclosure = const CoachCopy('ar').assistantNote('bob');

    expect(disclosure, contains('المعدات المتاحة'));
    expect(disclosure, contains('\u2066e1RM\u2069'));
    expect(disclosure, contains('آخر 5 ملاحظات'));
    expect(disclosure, contains('300 حرف'));
    expect(disclosure, contains('قد تكشف الملاحظات الهوية'));
  });

  testWidgets('the Ask assistant entry is hidden while the feature is off',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(coachAiEnabled: false);
    await _pumpApp(tester, fake);

    await _openRoster(tester);
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Weekly volume'));

    expect(find.byKey(const Key('coach_assistant_entry')), findsNothing);
    expect(find.text('Ask assistant'), findsNothing);

    await _openProgramSegment(tester);
    expect(find.text('Generate draft'), findsOneWidget);
    expect(find.text('Ask assistant'), findsNothing);
  });

  testWidgets('the enabled entry opens the assistant and one exchange works',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    await _openRoster(tester);
    await _openAssistant(tester, 'bob');

    expect(
      find.text(
        "The hosted model receives bob's goal, Experience level, Equipment access, "
        'bodyweight and e1RM trends, and your last 5 check-in notes '
        '(up to 300 characters each). Notes may contain identifying details. '
        "This exchange isn't saved.",
      ),
      findsOneWidget,
    );
    expect(find.text('0/1000'), findsOneWidget);

    await _ask(tester, 'How is the bench progressing?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));

    expect(find.text('How is the bench progressing?'), findsOneWidget);
    expect(_assistantMarkdown(fake.coachAssistantAnswer), findsOneWidget);
    expect(
      find.textContaining('Volume is steady and the records', findRichText: true),
      findsOneWidget,
    );
    expect(fake.coachAssistantRequests, hasLength(1));
    expect(fake.coachAssistantRequests.single['question'],
        'How is the bench progressing?');
    expect(fake.coachAssistantRequests.single['history'], isEmpty);

    final CoachAssistantTranscript? transcript =
        _container(tester).read(coachAssistantControllerProvider);
    expect(transcript, isNotNull);
    expect(transcript!.assignmentId, 'assignment-1');
    expect(transcript.turns, hasLength(2));
  });

  testWidgets('assistant Markdown fits at 360 dp in light and dark themes',
      (WidgetTester tester) async {
    for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
      final FakeMayosApi fake = _coachFake()
        ..coachAssistantAnswer =
            '# Coaching notes\n\nKeep **one** lift moving.\n\n- Stay patient\n- Add weight slowly';
      await _pumpApp(
        tester,
        fake,
        themeMode: mode,
        size: const Size(360, 640),
      );
      await _openRoster(tester);
      await _openAssistant(tester, 'bob');
      await _ask(tester, '**Keep** this question plain.');
      await _pumpUntilFound(
          tester, _assistantMarkdown(fake.coachAssistantAnswer));

      expect(find.text('**Keep** this question plain.'), findsOneWidget);
      expect(_assistantMarkdown(fake.coachAssistantAnswer), findsOneWidget);
      expect(find.text('Coaching notes', findRichText: true), findsOneWidget);
      expect(find.text('Stay patient', findRichText: true), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }
  });

  testWidgets('the next question carries the previous exchange as history',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');

    await _ask(tester, 'First question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    await _ask(tester, 'Second question?');
    await _pumpUntilCount(tester, _assistantMarkdown(fake.coachAssistantAnswer), 2);

    expect(fake.coachAssistantRequests, hasLength(2));
    final List<dynamic> history =
        fake.coachAssistantRequests[1]['history'] as List<dynamic>;
    expect(history, hasLength(2));
    expect(history.first['role'], 'coach');
    expect(history.first['content'], 'First question?');
    expect(history.last['role'], 'assistant');
    expect(history.last['content'], fake.coachAssistantAnswer);
  });

  testWidgets('only the last 12 transcript turns are sent as history',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');

    // Seed a long transcript for the selected player straight into the store.
    final CoachAssistantController controller =
        _container(tester).read(coachAssistantControllerProvider.notifier);
    for (int i = 0; i < 20; i++) {
      controller.recordExchange('assignment-1', question: 'q$i', answer: 'a$i');
    }

    await _ask(tester, 'Latest question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));

    final List<dynamic> history =
        fake.coachAssistantRequests.single['history'] as List<dynamic>;
    expect(history, hasLength(coachAssistantHistoryMaxTurns));
    expect(history.first['content'], 'q14');
    expect(history.last['content'], 'a19');
  });

  test('historyFor returns only the last 12 turns of a longer transcript', () {
    final CoachAssistantController controller = CoachAssistantController();
    controller.openFor('assignment-1');
    for (int i = 0; i < 20; i++) {
      controller.recordExchange('assignment-1', question: 'q$i', answer: 'a$i');
    }

    final List<CoachAssistantTurn> history =
        controller.historyFor('assignment-1');
    expect(history, hasLength(coachAssistantHistoryMaxTurns));
    expect(history.first.role, 'coach');
    expect(history.first.content, 'q14');
    expect(history.last.role, 'assistant');
    expect(history.last.content, 'a19');
    // Another player's window is empty until they are selected.
    expect(controller.historyFor('assignment-2'), isEmpty);
  });

  test('the stored transcript stays bounded while only the last 12 are sent',
      () async {
    final FakeMayosApi fake = _coachFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final ProviderContainer container = authContainerFor(fake, tokens);
    final CoachAssistantController controller =
        container.read(coachAssistantControllerProvider.notifier);
    controller.openFor('assignment-1');
    for (int i = 0; i < 60; i++) {
      controller.recordExchange('assignment-1', question: 'q$i', answer: 'a$i');
    }

    final CoachAssistantTranscript? transcript =
        container.read(coachAssistantControllerProvider);
    expect(transcript!.turns, hasLength(coachAssistantTranscriptMaxTurns));
    expect(transcript.turns.last.content, 'a59');
    expect(controller.historyFor('assignment-1'),
        hasLength(coachAssistantHistoryMaxTurns));
  });

  test('stored turns stay inside the bounds the next request must satisfy', () {
    final CoachAssistantController controller = CoachAssistantController();
    controller.openFor('assignment-1');
    final String longAnswer =
        'x${List<String>.filled(coachAssistantTurnMaxChars, '😀').join()}';
    controller.recordExchange(
      'assignment-1',
      question:
          List<String>.filled(coachAssistantQuestionMaxChars + 50, 'q').join(),
      answer: longAnswer,
    );

    final List<CoachAssistantTurn> history =
        controller.historyFor('assignment-1');
    expect(history.first.content, hasLength(coachAssistantQuestionMaxChars));
    expect(history.last.content.length, lessThan(coachAssistantTurnMaxChars));
    // The cut never leaves a lone surrogate, so the turn still encodes as the
    // JSON string the service expects.
    expect(history.last.content, endsWith('😀'));
    expect(history.last.toJson()['content'], isA<String>());
  });

  testWidgets('opening the assistant for another player clears the transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake(secondPlayer: true);
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(find.text('Bob question?'), findsOneWidget);

    await _closeAssistant(tester);
    await _closeHistory(tester);
    await _openAssistant(tester, 'carol');

    expect(find.text('Bob question?'), findsNothing);
    expect(_assistantMarkdown(fake.coachAssistantAnswer), findsNothing);
    final CoachAssistantTranscript? transcript =
        _container(tester).read(coachAssistantControllerProvider);
    expect(transcript!.assignmentId, 'assignment-2');
    expect(transcript.turns, isEmpty);

    // The new player's first request carries no inherited history.
    await _ask(tester, 'Carol question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(fake.coachAssistantRequests, hasLength(2));
    expect(fake.coachAssistantRequests.last['history'], isEmpty);
  });

  testWidgets(
      'a 403 clears the transcript, tells the coach, and closes the assistant',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAssistantDenied = true;
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');

    await _ask(tester, 'How is the volume trending?');
    await _pumpUntilFound(tester, find.text('You no longer coach this player'));

    expect(find.text('You no longer coach this player'), findsOneWidget);
    expect(find.byKey(const Key('coach_assistant_question')), findsNothing);
    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets('a roster refresh that lost the assignment clears the transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    await _closeAssistant(tester);
    // The player is revoked or ends coaching: the roster no longer lists them.
    fake.assignments.clear();
    // Closing the drill-down returns to the shell's Roster tab, which reloads.
    await _closeHistory(tester);
    await _pumpUntilFound(tester, find.text('No assigned players yet.'));

    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets('a denied player-history load clears the transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    await _closeAssistant(tester);
    // Revoked on the player's phone: the roster row is still stale, but the
    // drill-down itself is now refused with the generic 403.
    fake.coachHistoryDenied = true;
    await _closeHistory(tester);
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('No active assignment.'));

    expect(find.text('No active assignment.'), findsOneWidget);
    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets('resuming the app reloads the roster and ends a lost assignment',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    // Revoked while the coach is away from the roster.
    fake.assignments.clear();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await _pumpUntil(
        tester,
        () =>
            _container(tester).read(coachAssistantControllerProvider) == null);

    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
    await _closeAssistant(tester);
    await _closeHistory(tester);
    expect(find.text('No assigned players yet.'), findsOneWidget);
  });

  testWidgets('returning to the roster after the drill-down reloads it',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    // Revoked while the coach reads the drill-down under the assistant.
    fake.assignments.clear();
    await _closeAssistant(tester);
    await _closeHistory(tester);
    await _pumpUntil(tester,
        () => find.text('No assigned players yet.').evaluate().isNotEmpty);

    expect(find.text('No assigned players yet.'), findsOneWidget);
    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets(
      'reopening the assistant for a player revoked meanwhile shows no transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));

    await _closeAssistant(tester);
    // Revoked while the coach sits on the now-stale history screen.
    fake.assignments.clear();

    await tester.tap(find.byKey(const Key('coach_assistant_entry')));
    await _pumpUntilFound(tester, find.text('You no longer coach this player'));

    expect(find.text('You no longer coach this player'), findsOneWidget);
    expect(find.byKey(const Key('coach_assistant_question')), findsNothing);
    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets(
      'losing coach_ai_enabled or the coach capability clears the transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    // The operator turns the feature off; a resumed app re-reads /auth/me.
    fake.coachAiEnabled = false;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await _pumpUntil(
        tester,
        () =>
            _container(tester).read(coachAssistantControllerProvider) == null);
    expect(_container(tester).read(coachAssistantControllerProvider), isNull);

    // The coach capability is revoked the same way.
    fake.coachAiEnabled = true;
    fake.coach = false;
    final CoachAssistantController controller =
        _container(tester).read(coachAssistantControllerProvider.notifier);
    controller.openFor('assignment-1');
    controller.recordExchange('assignment-1', question: 'q', answer: 'a');
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await _pumpUntil(
        tester,
        () =>
            _container(tester).read(coachAssistantControllerProvider) == null);
    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets('revoking the assignment clears the transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    await _closeAssistant(tester);
    await _closeHistory(tester);

    await tester.ensureVisible(find.text('Revoke'));
    await tester.pump(const Duration(milliseconds: 200));
    await tester.tap(find.text('Revoke'));
    await _pumpUntilFound(tester, find.text('Revoke assignment?'));
    await tester.tap(find.text('Revoke').last);
    await _pumpUntilFound(tester, find.text('Revoked bob.'));

    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets('disabling coaching clears the transcript',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    await _closeAssistant(tester);
    await _closeHistory(tester);

    await tester.ensureVisible(find.text('Disable coaching'));
    await tester.pump(const Duration(milliseconds: 200));
    await tester.tap(find.text('Disable coaching'));
    await _pumpUntilFound(tester, find.text('Disable coaching?'));
    await tester.tap(find.text('Disable coaching').last);
    await _pumpUntilFound(tester, find.textContaining('Coaching disabled.'));

    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets('logout clears the transcript', (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    await _closeAssistant(tester);
    await _closeHistory(tester);
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Log out'));
    await tester.tap(find.text('Log out'));
    await _pumpUntilFound(tester, find.text('Log in'));

    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  testWidgets('app close clears the transcript (AppLifecycleState.detached)',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');
    await _ask(tester, 'Bob question?');
    await _pumpUntilFound(tester, _assistantMarkdown(fake.coachAssistantAnswer));
    expect(
        _container(tester).read(coachAssistantControllerProvider), isNotNull);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.detached);
    await tester.pump(const Duration(milliseconds: 100));

    expect(_container(tester).read(coachAssistantControllerProvider), isNull);
  });

  test('the transcript store is memory-only: nothing is persisted', () async {
    final FakeMayosApi fake = _coachFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');

    final ProviderContainer first = authContainerFor(fake, tokens);
    expect(first.read(coachAssistantControllerProvider), isNull);
    final CoachAssistantController controller =
        first.read(coachAssistantControllerProvider.notifier);
    controller.openFor('assignment-1');
    controller.recordExchange('assignment-1', question: 'q', answer: 'a');
    expect(first.read(coachAssistantControllerProvider), isNotNull);

    // A fresh container — the test's stand-in for a new process — starts empty:
    // the transcript is never restored from anywhere.
    final ProviderContainer second = authContainerFor(fake, tokens);
    expect(second.read(coachAssistantControllerProvider), isNull);
    expect(
        second
            .read(coachAssistantControllerProvider.notifier)
            .historyFor('assignment-1'),
        isEmpty);

    // And no storage module is reachable from the transcript's own code.
    final RegExp storage = RegExp(
        r'shared_preferences|flutter_secure_storage|SecureStore|ChatCacheStore|DraftStore|WorkoutCacheStore|writeHistory');
    for (final String file in <String>[
      'lib/src/features/coach/coach_assistant_state.dart',
      'lib/src/features/coach/coach_assistant_screen.dart',
    ]) {
      expect(storage.hasMatch(File(file).readAsStringSync()), isFalse,
          reason: '$file must not persist the coach transcript');
    }
    // The provider's own definition wires no store either (the other providers
    // in that file do use storage for other features).
    final String providers = File('lib/src/providers.dart').readAsStringSync();
    final int start = providers
        .indexOf('final StateNotifierProvider<CoachAssistantController');
    expect(start, greaterThan(0));
    final int end = providers.indexOf('});', start);
    expect(end, greaterThan(start));
    expect(storage.hasMatch(providers.substring(start, end)), isFalse,
        reason: 'the coach transcript provider must not be backed by storage');

    // The provider itself is plain state, not a store.
    expect(
        coachAssistantControllerProvider,
        isA<
            StateNotifierProvider<CoachAssistantController,
                CoachAssistantTranscript?>>());
  });

  testWidgets('a 404 from the service reports that the feature is off',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');

    // The operator turns the feature off after the entry was rendered.
    fake.coachAiEnabled = false;
    await _ask(tester, 'Is this on?');
    await _pumpUntilFound(tester, find.text('Coach AI is not available.'));

    expect(find.byKey(const Key('coach_assistant_error')), findsOneWidget);
    expect(find.text('Coach AI is not available.'), findsOneWidget);
    expect(fake.coachAssistantRequests, isEmpty);

    // The 404 re-reads the account, so the entry is gone once we are back on
    // the player history screen.
    await _closeAssistant(tester);
    await _pumpUntil(
        tester,
        () =>
            find.byKey(const Key('coach_assistant_entry')).evaluate().isEmpty);
    await tester.tap(find.text('Program').first);
    await tester.pump();
    expect(find.byKey(const Key('coach_assistant_entry')), findsNothing);
    expect(find.text('Ask assistant'), findsNothing);
  });

  testWidgets('a 429 surfaces the model-limit message like player chat',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAssistantRateLimited = true;
    await _pumpApp(tester, fake);
    await _openRoster(tester);
    await _openAssistant(tester, 'bob');

    await _ask(tester, 'One more question?');
    await _pumpUntilFound(tester,
        find.text('Too many AI requests. Please wait a minute and try again.'));

    expect(
      find.text('Too many AI requests. Please wait a minute and try again.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('coach_assistant_error')), findsOneWidget);
    // A refused turn is never recorded in the transcript.
    expect(_container(tester).read(coachAssistantControllerProvider)!.turns,
        isEmpty);
    expect(fake.coachAssistantRequests, isEmpty);
  });
}
