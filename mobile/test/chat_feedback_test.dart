import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_models.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_button.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/core/refetch_on_reconnect.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

/// Assistant reply feedback tests (#748): the 👍/👎 bar under a fresh reply,
/// the optional 👎 reasons sheet, the required-reason report flow with the
/// reported-hidden card, and the Arabic surface for both.

/// What the mocked platform clipboard last received from ⋯ → Copy.
String? clipboardData;

/// True when the keyboard is attached to the chat composer's EditableText.
bool _composerHasFocus(WidgetTester tester) {
  if (!tester.testTextInput.hasAnyClients) return false;
  final EditableTextState editable = tester.state<EditableTextState>(
    find.descendant(
      of: find.byKey(const Key('chat_composer')),
      matching: find.byType(EditableText),
    ),
  );
  return editable.widget.focusNode!.hasFocus;
}

final Map<String, dynamic> _signedContext = <String, dynamic>{
  'message_id': 'srv-reply-1',
  'question_text': 'How should I bench?',
  'reply_text': 'Keep three working sets and two reps in reserve.',
  'language': 'en',
  'route': 'assistant',
  'redact_terms': const <String>[],
  'signature': 'a' * 64,
};

FakeMayosApi _fakePlayer(String username) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-$username';
  fake.currentUsername = username;
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = '$username@example.com';
  return fake;
}

Future<void> _pumpUntilFound(
  WidgetTester tester,
  Finder finder, {
  int attempts = 60,
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

Future<void> _pumpChat(
  WidgetTester tester,
  FakeMayosApi fake, {
  required InMemoryChatCacheStore store,
  required List<Map<String, dynamic>> seedHistory,
  String languageCode = 'en',
}) async {
  fake.displayLanguage = languageCode;
  const String accountId = 'account-alice';
  if (seedHistory.isNotEmpty) {
    store.seedHistory(accountId, <ChatMessage>[
      for (final Map<String, dynamic> row in seedHistory) ChatMessage.fromJson(row),
    ]);
  }
  await store.writeDisclosureAccepted(accountId);
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save(fake.issuedToken!);
  await tester.pumpWidget(    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        systemDisplayLanguageProvider.overrideWithValue(languageCode),
        themeModeStoreProvider
            .overrideWithValue(InMemoryThemeModeStore(ThemeMode.light)),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
            retryDelay: (_) async {},
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
        chatCacheStoreProvider.overrideWithValue(store),
        workoutCacheStoreProvider.overrideWithValue(InMemoryWorkoutCacheStore()),
        deviceTimezoneProvider
            .overrideWithValue(Future<String>.value('America/New_York')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value('America/New_York')),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(
    tester,
    find.text(languageCode == 'ar' ? 'الرئيسية' : 'Home'),
  );
  await tester.tap(find.byTooltip(languageCode == 'ar' ? 'المساعد' : 'Assistant'));
  await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
}

Future<void> _sendAMessage(WidgetTester tester, FakeMayosApi fake, String text) async {
  await tester.enterText(find.byKey(const Key('chat_composer')), text);
  await tester.tap(find.byKey(const Key('chat_send')));
  await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_up')));
  expect(fake.chatFeedbackVoteCount, 0);
}

void main() {
  Map<String, dynamic> _assistantRow({Map<String, dynamic>? feedback}) =>
      <String, dynamic>{
        'id': 'srv-reply-1',
        'role': 'assistant',
        'content': 'Keep three working sets and two reps in reserve.',
        'created_at': '2026-11-01T10:00:00Z',
        'kind': 'message',
        if (feedback != null) 'feedback': feedback,
      };

  setUpAll(() {
    // Clipboard.setData throws in widget tests unless the platform channel is
    // mocked; capture what the ⋯ → Copy action stored.
    TestWidgetsFlutterBinding.ensureInitialized();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (MethodCall call) async {
      if (call.method == 'Clipboard.setData') {
        clipboardData = (call.arguments as Map<dynamic, dynamic>)['text'] as String?;
      }
      return null;
    });
  });

  testWidgets('a fresh reply shows the vote bar and one-tap votes are idempotent',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.chatFeedbackContext = json.decode(json.encode(_signedContext))
        as Map<String, dynamic>;
    await _pumpChat(tester, fake, store: InMemoryChatCacheStore(), seedHistory: const []);
    await _sendAMessage(tester, fake, 'How should I bench?');

    await tester.tap(find.byKey(const Key('assistant_feedback_up')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_up')));
    await tester.pump(const Duration(milliseconds: 200));
    expect(fake.chatFeedbackVoteCount, 1);

    // Tapping 👍 again undoes the vote (vote: null).
    await tester.tap(find.byKey(const Key('assistant_feedback_up')));
    await tester.pump(const Duration(milliseconds: 200));
    expect(fake.chatFeedbackVoteCount, 2);
  });

  testWidgets('👎 opens the optional reasons sheet and closing keeps the vote',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.chatFeedbackContext = json.decode(json.encode(_signedContext))
        as Map<String, dynamic>;
    await _pumpChat(tester, fake, store: InMemoryChatCacheStore(), seedHistory: const []);
    await _sendAMessage(tester, fake, 'How should I bench?');

    await tester.tap(find.byKey(const Key('assistant_feedback_down')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_reason_offensive')));
    expect(fake.chatFeedbackVoteCount, 1); // committed immediately

    // Close without choosing anything: the 👎 stays.
    await tester.tapAt(const Offset(20, 40));
    await tester.pump(const Duration(milliseconds: 300));
    expect(fake.chatFeedbackVoteCount, 1);

    // Tapping 👎 again undoes the vote; a third tap re-votes and reopens the
    // sheet, and "Got it" saves the chosen reasons.
    await tester.tap(find.byKey(const Key('assistant_feedback_down')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(fake.chatFeedbackVoteCount, 2);

    await tester.tap(find.byKey(const Key('assistant_feedback_down')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_reason_not_helpful')));
    expect(fake.chatFeedbackVoteCount, 3);
    await tester.tap(find.byKey(const Key('assistant_feedback_reason_not_helpful')));
    await tester.tap(find.byKey(const Key('assistant_feedback_reasons_done')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(fake.chatFeedbackVoteCount, 4);
  });

  testWidgets('Report requires a reason, hides the reply, and can be shown again',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.chatFeedbackContext = json.decode(json.encode(_signedContext))
        as Map<String, dynamic>;
    await _pumpChat(tester, fake, store: InMemoryChatCacheStore(), seedHistory: const []);
    await _sendAMessage(tester, fake, 'How should I bench?');

    await tester.tap(find.byKey(const Key('assistant_feedback_menu')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_report')));
    await tester.tap(find.byKey(const Key('assistant_feedback_report')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_report_send')));

    // No reason chosen: send is disabled.
    final MayosButton sendButton = tester.widget<MayosButton>(
      find.byKey(const Key('assistant_feedback_report_send')),
    );
    expect(sendButton.onPressed, isNull);

    await tester.tap(find.byKey(const Key('assistant_feedback_reason_offensive')));
    await tester.enterText(find.byKey(const Key('assistant_feedback_note')), 'rude reply');
    await tester.tap(find.byKey(const Key('assistant_feedback_report_send')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_reported_card')));
    // The sheet is animating closed while the card appears; let the modal
    // barrier leave the overlay before tapping the card's action.
    await tester.pumpAndSettle();

    expect(fake.chatFeedbackReportCount, 1);
    // The reply text is hidden behind the reported card until "Show anyway".
    expect(find.textContaining('Keep your elbows tucked', findRichText: true), findsNothing);
    expect(find.text('You reported this reply'), findsOneWidget);

    await tester.tap(find.byKey(const Key('assistant_feedback_show_anyway')));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.textContaining('Keep your elbows tucked', findRichText: true), findsOneWidget);
  });

  testWidgets('history restores vote state and the reported-hidden card',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    // The app treats the server as the source of truth for history, so the
    // reported-hidden state must come back through `GET /chat/history`'s
    // feedback annotation, not the local cache.
    fake.chatHistory.addAll(<Map<String, dynamic>>[
      <String, dynamic>{
        'id': 'u1',
        'role': 'user',
        'content': 'How should I bench?',
        'created_at': '2026-11-01T09:59:59Z',
      },
      _assistantRow(feedback: <String, dynamic>{
        'feedback_id': 'fb-1',
        'vote': 'down',
        'reported': true,
      }),
    ]);
    fake.chatFeedback['srv-reply-1'] = <String, dynamic>{
      'feedback_id': 'fb-1',
      'vote': 'down',
      'reported': true,
    };
    await _pumpChat(
      tester,
      fake,
      store: InMemoryChatCacheStore(),
      seedHistory: const [],
    );
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_reported_card')));
    expect(find.textContaining('Keep three working sets', findRichText: true), findsNothing);
    await tester.tap(find.byKey(const Key('assistant_feedback_show_anyway')));
    await tester.pump(const Duration(milliseconds: 200));
    // Showing it again reveals the restored reply text (issue #748).
    expect(find.textContaining('Keep three working sets', findRichText: true), findsOneWidget);
    // The restored 👎 bar is interactive and can be undone by bare message id.
    await tester.tap(find.byKey(const Key('assistant_feedback_down')));
    await tester.pump(const Duration(milliseconds: 200));
    expect(fake.chatFeedbackVoteCount, 1);
  });

  testWidgets('the reason sheet lists Offensive and Unsafe advice first in Arabic',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.chatFeedbackContext = json.decode(json.encode(_signedContext))
        as Map<String, dynamic>;
    await _pumpChat(
      tester,
      fake,
      store: InMemoryChatCacheStore(),
      seedHistory: const [],
      languageCode: 'ar',
    );
    await _sendAMessage(tester, fake, 'كيف أتدريب البنش؟');

    await tester.tap(find.byKey(const Key('assistant_feedback_menu')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_report')));
    await tester.tap(find.byKey(const Key('assistant_feedback_report')));
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_reason_offensive')));

    // Offensive and Unsafe advice sit above the other reasons (issue #748).
    final double offensiveY =
        tester.getTopLeft(find.byKey(const Key('assistant_feedback_reason_offensive'))).dy;
    final double unsafeY =
        tester.getTopLeft(find.byKey(const Key('assistant_feedback_reason_unsafe_advice'))).dy;
    final double notHelpfulY =
        tester.getTopLeft(find.byKey(const Key('assistant_feedback_reason_not_helpful'))).dy;
    expect(offensiveY, lessThan(unsafeY));
    expect(unsafeY, lessThan(notHelpfulY));
    expect(find.text('مسيء'), findsOneWidget);
    expect(find.text('نصيحة غير آمنة'), findsOneWidget);
    expect(find.text('ما الخطأ في هذه الإجابة؟'), findsOneWidget);
  });

  testWidgets('a reply arriving while the composer has focus keeps focus and text',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    await _pumpChat(tester, fake, store: InMemoryChatCacheStore(), seedHistory: const []);

    await tester.enterText(find.byKey(const Key('chat_composer')), 'draft while reading');
    await tester.pump();
    expect(_composerHasFocus(tester), isTrue);
    final Element composerBefore =
        find.byKey(const Key('chat_composer')).evaluate().single;

    // A reconnect reload restores a rateable reply while the composer keeps
    // focus and text — the rebuild must not remount the composer's subtree.
    fake.chatHistory.add(<String, dynamic>{
      'id': 'srv-reply-1',
      'role': 'assistant',
      'content': 'Keep three working sets and two reps in reserve.',
      'created_at': '2026-11-01T10:00:00Z',
    });
    fake.chatFeedback['srv-reply-1'] = <String, dynamic>{
      'feedback_id': 'fb-1',
      'vote': null,
      'reported': false,
    };
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    container.read(reconnectProvider.notifier).state += 1;
    await _pumpUntilFound(tester, find.byKey(const Key('assistant_feedback_up')));
    await tester.pumpAndSettle();

    // The reply's vote bar took the TourTarget id over...
    expect(find.byKey(const Key('assistant_feedback_up')), findsOneWidget);
    // ...and the composer kept its element (no remount), its text, and focus.
    final Element composerAfter =
        find.byKey(const Key('chat_composer')).evaluate().single;
    expect(composerAfter, same(composerBefore));
    expect(_composerHasFocus(tester), isTrue);
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('chat_composer')))
          .controller!
          .text,
      'draft while reading',
    );
  });
}
