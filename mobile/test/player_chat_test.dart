import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart' show MaxLengthEnforcement;
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/account_data_eraser.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_models.dart';
import 'package:mayos_mobile/src/core/chat_message_limit.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/workout_start_notice_store.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/sse.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_markdown.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_repository.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches, then a few more so transitions
/// settle without relying on `pumpAndSettle` (indeterminate spinners never settle).
Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
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

FakeMayosApi _fakePlayer(String username) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-$username';
  fake.currentUsername = username;
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = '$username@example.com';
  return fake;
}

Future<void> _pumpChat(
  WidgetTester tester,
  FakeMayosApi fake, {
  required InMemoryChatCacheStore store,
  InMemoryWorkoutCacheStore? workoutCache,
  ActiveWorkoutStore? activeWorkout,
  DraftStore? drafts,
  BaselineCacheStore? baselineCache,
  Key? scopeKey,
  ThemeMode? themeMode,
  Size? size,
  String languageCode = 'en',
}) async {
  fake.displayLanguage = languageCode;
  await _pumpHome(tester, fake,
      chatCache: store,
      workoutCache: workoutCache,
      activeWorkout: activeWorkout,
      drafts: drafts,
      baselineCache: baselineCache,
      scopeKey: scopeKey,
      themeMode: themeMode,
      size: size,
      languageCode: languageCode);
  await tester
      .tap(find.byTooltip(languageCode == 'ar' ? 'المساعد' : 'Assistant'));
  await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
}

/// Pumps the app to the player home screen.
Future<void> _pumpHome(
  WidgetTester tester,
  FakeMayosApi fake, {
  InMemoryChatCacheStore? chatCache,
  InMemoryWorkoutCacheStore? workoutCache,
  ActiveWorkoutStore? activeWorkout,
  DraftStore? drafts,
  BaselineCacheStore? baselineCache,
  Key? scopeKey,
  ThemeMode? themeMode,
  Size? size,
  String languageCode = 'en',
}) async {
  tester.view.physicalSize = size ?? const Size(1080, 2400);
  tester.view.devicePixelRatio = size == null ? 2.0 : 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save(fake.issuedToken!);
  await tester.pumpWidget(
    ProviderScope(
      key: scopeKey,
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        systemDisplayLanguageProvider.overrideWithValue(languageCode),
        themeModeStoreProvider
            .overrideWithValue(InMemoryThemeModeStore(themeMode)),
        _apiOverride(fake),
        chatCacheStoreProvider
            .overrideWithValue(chatCache ?? InMemoryChatCacheStore()),
        workoutCacheStoreProvider
            .overrideWithValue(workoutCache ?? InMemoryWorkoutCacheStore()),
        if (activeWorkout != null)
          activeWorkoutStoreProvider.overrideWithValue(activeWorkout),
        if (drafts != null) draftStoreProvider.overrideWithValue(drafts),
        if (baselineCache != null)
          baselineCacheStoreProvider.overrideWithValue(baselineCache),
        deviceTimezoneProvider
            .overrideWithValue(Future<String>.value('America/New_York')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value('America/New_York')),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(
      tester, find.text(languageCode == 'ar' ? 'الرئيسية' : 'Home'));
}

Future<void> _acceptDisclosure(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('chat_disclosure_accept')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

TextField _composer(WidgetTester tester) =>
    tester.widget<TextField>(find.byKey(const Key('chat_composer')));

Finder _chatMarkdown(String source) => find.byWidgetPredicate(
      (Widget widget) => widget is MayosMarkdown && widget.source == source,
    );

Finder _renderedMarkdownText(String text) =>
    find.textContaining(text, findRichText: true);

Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  test('chat message limit and localized counter copy match the service', () {
    expect(chatMessageMaxChars, 400);
    const MayosCopy english = MayosCopy('en');
    const MayosCopy arabic = MayosCopy('ar');
    expect(english.chatCharactersLeft(80), '80 characters left');
    expect(english.chatCharactersLeft(1), '1 character left');
    expect(
      arabic.chatCharactersLeft(80),
      'المتبقي: \u{2066}80\u{2069} حرفًا',
    );
    expect(arabic.chatCharactersLeft(1), 'المتبقي: حرف واحد');
    expect(arabic.chatCharactersLeft(2), 'المتبقي: حرفان');
    expect(arabic.chatCharactersLeft(3), 'المتبقي: \u{2066}3\u{2069} أحرف');
    expect(
      arabic.chatCharactersLeft(11),
      'المتبقي: \u{2066}11\u{2069} حرفًا',
    );
  });

  test('chat input formatter counts Unicode code points', () {
    const ChatMessageCodePointLengthFormatter formatter =
        ChatMessageCodePointLengthFormatter();
    const String combiningCharacter = 'e\u0301';
    final TextEditingValue bounded = formatter.formatEditUpdate(
      TextEditingValue.empty,
      TextEditingValue(
        text: combiningCharacter * 201,
        selection: TextSelection.collapsed(
          offset: (combiningCharacter * 201).length,
        ),
      ),
    );

    expect(bounded.text.runes.length, 400);
    expect(bounded.text, combiningCharacter * 200);
  });

  testWidgets('chat composer localizes its counter and caps input at 400',
      (tester) async {
    for (final String languageCode in <String>['en', 'ar']) {
      final FakeMayosApi fake = _fakePlayer('alice');
      await _pumpChat(
        tester,
        fake,
        store: InMemoryChatCacheStore(),
        scopeKey: UniqueKey(),
        languageCode: languageCode,
      );
      await _acceptDisclosure(tester);

      expect(_composer(tester).maxLength, chatMessageMaxChars);
      expect(
        _composer(tester).maxLengthEnforcement,
        MaxLengthEnforcement.enforced,
      );
      expect(_composer(tester).decoration!.counterText, '');
      final String character = languageCode == 'ar' ? 'ا' : 'a';
      final Finder composer = find.byKey(const Key('chat_composer'));

      await tester.enterText(composer, character * 319);
      await tester.pump();
      expect(
        find.text(MayosCopy('en').chatCharactersLeft(81)),
        findsNothing,
      );
      expect(
        find.text(MayosCopy('ar').chatCharactersLeft(81)),
        findsNothing,
      );

      await tester.enterText(composer, character * 320);
      await tester.pump();
      expect(
        find.text(const MayosCopy('en').chatCharactersLeft(80)),
        languageCode == 'en' ? findsOneWidget : findsNothing,
      );
      expect(
        find.text(const MayosCopy('ar').chatCharactersLeft(80)),
        languageCode == 'ar' ? findsOneWidget : findsNothing,
      );

      // Simulates a paste above the boundary; the formatter clips it before
      // the send action can pass it to the API.
      await tester.enterText(composer, character * 401);
      await tester.pump();
      expect(_composer(tester).controller!.text.runes.length, 400);
      expect(
        find.text(const MayosCopy('en').chatCharactersLeft(0)),
        languageCode == 'en' ? findsOneWidget : findsNothing,
      );
      expect(
        find.text(const MayosCopy('ar').chatCharactersLeft(0)),
        languageCode == 'ar' ? findsOneWidget : findsNothing,
      );

      await tester.tap(find.byKey(const Key('chat_send')));
      await _pumpUntilFound(tester, _chatMarkdown('Keep your elbows tucked.'));
      final Map<String, dynamic> sent = fake.chatHistory
          .singleWhere(
              (Map<String, dynamic> message) => message['role'] == 'user');
      expect((sent['content'] as String).runes.length, 400);
      await tester.pumpWidget(const SizedBox());
    }
  });

  group('SseDecoder', () {
    test('splits whole frames and survives chunk boundaries', () {
      final SseDecoder decoder = SseDecoder();
      expect(decoder.addChunk('data: {"token": "Ke'), isEmpty);
      final List<SseEvent> first =
          decoder.addChunk('ep "}\n\ndata: {"token": "x"}\n');
      expect(first.length, 1);
      expect(first.single.event, 'message');
      expect(first.single.data, '{"token": "Keep "}');
      final List<SseEvent> second =
          decoder.addChunk('\nevent: error\ndata: {"detail": "nope"}\n\n');
      expect(second.length, 2);
      expect(second.first.data, '{"token": "x"}');
      expect(second.last.event, 'error');
      expect(second.last.data, '{"detail": "nope"}');
    });

    test('ignores comment lines and events without data', () {
      final SseDecoder decoder = SseDecoder();
      expect(decoder.addChunk(': keep-alive\n\n').isEmpty, true);
    });

    test('holds a trailing carriage return across a chunk boundary', () {
      final SseDecoder decoder = SseDecoder();
      // A frame's terminating CRLF+CRLF is split between two chunks; the pair
      // split at the boundary must not become a false blank line.
      // Frame A: `...a"}\r\n\r\n`, delivered as `...a"}\r` + `\n\r\n...`.
      expect(decoder.addChunk('data: {"token": "a"}\r').isEmpty, true);
      final List<SseEvent> events =
          decoder.addChunk('\n\r\ndata: {"token": "b"}\r\n\r\n');
      expect(events.length, 2);
      expect(events.first.data, '{"token": "a"}');
      expect(events.last.data, '{"token": "b"}');
    });

    test('close() returns a final frame without a trailing blank line', () {
      final SseDecoder decoder = SseDecoder();
      expect(decoder.addChunk('data: {"done": true}').isEmpty, true);
      final List<SseEvent> events = decoder.close();
      expect(events.length, 1);
      expect(events.single.data, '{"done": true}');
    });
  });

  test('streaming UTF-8 reassembles a multibyte char split across chunks',
      () async {
    // The euro sign (U+20AC) is 3 bytes; split it mid-sequence across chunks.
    final List<int> bytes = utf8.encode('data: {"token": "€"}\n\n');
    final int firstLen = bytes.indexOf(0xE2) + 1;
    final ApiClient client = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: _ChunkedBytesAdapter(<List<int>>[
        bytes.sublist(0, firstLen),
        bytes.sublist(firstLen),
      ]),
    );
    final List<ChatStreamEvent> events =
        await client.streamChatMessage('x').toList();
    expect(events.length, 1);
    expect((events.single as ChatToken).token, '€');
  });

  testWidgets('Arabic chat chrome preserves assistant text from the API',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.chatHistory.add(<String, dynamic>{
      'id': 'server-reply-1',
      'role': 'assistant',
      'content': 'Server supplied coaching text.',
      'created_at': '2026-10-02T10:00:00Z',
    });
    await _pumpChat(tester, fake,
        store: InMemoryChatCacheStore(), languageCode: 'ar');
    expect(find.byTooltip('مسح سجل المحادثة'), findsOneWidget);
    expect(find.text('قبل أن تبدأ'), findsOneWidget);
    expect(
        find.text(
            'يرد على المحادثة نموذج ذكاء اصطناعي مستضاف. تُرسل رسالتك وسياق التدريب اللازم للإجابة إلى مزود النموذج. قد يتضمن النص الحر تفاصيل تكشف هويتك، لذا لا تكتب ما لا ترغب في معالجته هناك.'),
        findsOneWidget);
    expect(_chatMarkdown('Server supplied coaching text.'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.byTooltip('مسح سجل المحادثة'))),
      TextDirection.rtl,
    );
  });

  testWidgets('disclosure gates the composer and persists per account',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    final FakeMayosApi alice = _fakePlayer('alice');
    await _pumpChat(tester, alice, store: store, scopeKey: UniqueKey());

    expect(find.byKey(const Key('chat_disclosure')), findsOneWidget);
    expect(_composer(tester).enabled, isFalse);

    await _acceptDisclosure(tester);
    expect(find.byKey(const Key('chat_disclosure')), findsNothing);
    expect(_composer(tester).enabled, isTrue);

    // A fresh app start for the same account skips the disclosure.
    await tester.pumpWidget(const SizedBox());
    await _pumpChat(tester, alice, store: store, scopeKey: UniqueKey());
    expect(find.byKey(const Key('chat_disclosure')), findsNothing);
    expect(_composer(tester).enabled, isTrue);

    // A different account on the same device sees it again.
    final FakeMayosApi bob = _fakePlayer('bob');
    await tester.pumpWidget(const SizedBox());
    await _pumpChat(tester, bob, store: store, scopeKey: UniqueKey());
    expect(find.byKey(const Key('chat_disclosure')), findsOneWidget);
    expect(_composer(tester).enabled, isFalse);
  });

  testWidgets('streamed tokens render progressively and done finalizes',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    await _pumpChat(tester, _fakePlayer('alice'),
        store: store, scopeKey: UniqueKey());
    await _acceptDisclosure(tester);

    await tester.enterText(
        find.byKey(const Key('chat_composer')), 'Cue my bench?');
    await tester.tap(find.byKey(const Key('chat_send')));

    // Subscription starts within the first frame; no chunk has arrived yet.
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('Assistant is replying…'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 120));
    expect(_chatMarkdown('Keep your '), findsOneWidget);
    expect(_renderedMarkdownText('Keep your'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 120));
    expect(_chatMarkdown('Keep your elbows tucked.'), findsOneWidget);
    expect(_renderedMarkdownText('Keep your elbows tucked.'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 120));
    expect(find.text('Assistant is replying…'), findsNothing);
    expect(_chatMarkdown('Keep your elbows tucked.'), findsOneWidget);
    // The finished reply is cached for offline reading.
    final List<ChatMessage> cached = await store.readHistory('account-alice');
    expect(
        cached.any((ChatMessage m) => m.content == 'Keep your elbows tucked.'),
        isTrue);
  });

  testWidgets('refusal action opens a prefilled request form for confirmation',
      (tester) async {
    const String question = 'swap bench press for dumbbell press';
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    final FakeMayosApi fake = _fakePlayer('alice')
      ..coachControlsProgram = true
      ..activeAssignmentId = 'assignment-1'
      ..programVersion = 1
      ..chatReplyChunks = <String>[
        'Your assigned coach controls your program. You can review and send a request to your coach.',
      ]
      ..chatRequestSuggestion = <String, dynamic>{
        'kind': 'exercise_substitution',
        'day_name': 'Full A',
        'exercise_id': 'bp',
        'replacement_exercise_id': 'dbp',
        'reason': question,
      };
    await _pumpChat(tester, fake, store: store, scopeKey: UniqueKey());
    await _acceptDisclosure(tester);

    await tester.enterText(find.byKey(const Key('chat_composer')), question);
    await tester.tap(find.byKey(const Key('chat_send')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('chat_request_from_coach')));

    expect(fake.programRequests, isEmpty);
    expect(_chatMarkdown(
      'Your assigned coach controls your program. You can review and send a request to your coach.',
    ), findsOneWidget);
    expect(fake.chatHistory.last.containsKey('request_suggestion'), isFalse);

    await tester.tap(find.byKey(const Key('chat_request_from_coach')));
    await _pumpUntilFound(tester, find.text('Request a program change'));
    expect(
        tester
            .widget<TextField>(find.byKey(const Key('program_request_day_field')))
            .controller!
            .text,
        'Full A');
    expect(
        tester
            .widget<TextField>(
                find.byKey(const Key('program_request_exercise_field')))
            .controller!
            .text,
        'bp');
    expect(
        tester
            .widget<TextField>(
                find.byKey(const Key('program_request_replacement_field')))
            .controller!
            .text,
        'dbp');
    expect(
        tester
            .widget<TextField>(
                find.byKey(const Key('program_request_reason_field')))
            .controller!
            .text,
        question);
    expect(fake.programRequests, isEmpty);

    final Finder reasonField =
        find.byKey(const Key('program_request_reason_field'));
    await tester.enterText(reasonField, 'r' * 501);
    await tester.pump();
    expect(find.text('501 / 500 characters'), findsOneWidget);
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await tester.pump();
    expect(
      find.text('The reason must be 500 characters or fewer.'),
      findsOneWidget,
    );
    expect(find.text('Request a program change'), findsOneWidget);
    expect(fake.programRequests, isEmpty);

    await tester.enterText(reasonField, question);
    await tester.pump();

    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await _pumpUntilFound(tester,
        find.text('Your program change request was sent to your coach.'));
    expect(fake.programRequests, hasLength(1));
    expect(fake.programRequests.single['day_name'], 'Full A');
    expect(fake.programRequests.single['exercise_id'], 'bp');
    expect(fake.programRequests.single['replacement_exercise_id'], 'dbp');
    expect(fake.programRequests.single['reason'], question);
    final List<ChatMessage> cached = await store.readHistory('account-alice');
    final ChatMessage cachedAssistant = cached
        .where((ChatMessage message) => message.role == 'assistant')
        .single;
    expect(cachedAssistant.requestSuggestion, isNotNull);
    expect(cachedAssistant.toJson().containsKey('request_suggestion'), isFalse);
  });

  testWidgets('refusal action uses Arabic copy', (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice')
      ..displayLanguage = 'ar'
      ..coachControlsProgram = true
      ..activeAssignmentId = 'assignment-1'
      ..programVersion = 1
      ..chatReplyChunks = <String>[
        'يتولى مدربك المعيّن التحكم في برنامجك التدريبي. يمكنك مراجعة طلب وإرساله إلى مدربك.',
      ]
      ..chatRequestSuggestion = <String, dynamic>{
        'kind': 'split_change',
        'desired_weekly_frequency': 3,
        'reason': 'change routine to 3 days من فضلك',
      };
    await _pumpChat(
      tester,
      fake,
      store: InMemoryChatCacheStore(),
      scopeKey: UniqueKey(),
      languageCode: 'ar',
    );
    await _acceptDisclosure(tester);
    await tester.enterText(
      find.byKey(const Key('chat_composer')),
      'change routine to 3 days من فضلك',
    );
    await tester.tap(find.byKey(const Key('chat_send')));

    await _pumpUntilFound(
        tester, find.byKey(const Key('chat_request_from_coach')));
    expect(tester.takeException(), isNull, reason: 'chat refusal layout');
    expect(find.text('طلب من المدرب'), findsOneWidget);
    expect(
      _chatMarkdown(
        'يتولى مدربك المعيّن التحكم في برنامجك التدريبي. يمكنك مراجعة طلب وإرساله إلى مدربك.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('chat_request_from_coach')));
    await _pumpUntilFound(tester, find.text('طلب تغيير البرنامج التدريبي'));
    expect(tester.takeException(), isNull, reason: 'request dialog layout');
    expect(
      tester
          .widget<DropdownButtonFormField<int>>(
              find.byKey(const Key('program_request_frequency_field')))
          .initialValue,
      3,
    );
    expect(fake.programRequests, isEmpty);
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await _pumpUntilFound(
      tester,
      find.text('أُرسل طلب تغيير البرنامج التدريبي إلى مدربك.'),
    );
    expect(tester.takeException(), isNull, reason: 'request submission layout');
    expect(fake.programRequests.single['kind'], 'split_change');
    expect(fake.programRequests.single['desired_weekly_frequency'], 3);
    expect(fake.programRequests.single['reason'], 'change routine to 3 days من فضلك');
  });

  testWidgets(
      'partial Markdown streams into the same selectable history render at 360 dp',
      (tester) async {
    for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
      final InMemoryChatCacheStore store = InMemoryChatCacheStore();
      final FakeMayosApi fake = _fakePlayer('alice')
        ..chatReplyChunks = <String>['**Strong', '** and *steady*.'];
      await _pumpChat(
        tester,
        fake,
        store: store,
        scopeKey: UniqueKey(),
        themeMode: mode,
        size: const Size(360, 640),
      );
      await _acceptDisclosure(tester);

      await tester.enterText(
          find.byKey(const Key('chat_composer')), '**How?**');
      await tester.tap(find.byKey(const Key('chat_send')));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 120));

      final MayosMarkdown partial = tester
          .widgetList<MayosMarkdown>(
            _chatMarkdown('**Strong'),
          )
          .first;
      final Key identityKey = partial.key!;
      expect(partial.source, '**Strong');
      expect(_renderedMarkdownText('Strong'), findsOneWidget);
      expect(find.text('**How?**'), findsOneWidget);
      expect(
        tester
            .widget<MarkdownBody>(
              find.descendant(
                of: find.byKey(identityKey),
                matching: find.byType(MarkdownBody),
              ),
            )
            .key,
        isNull,
      );

      await tester.pump(const Duration(milliseconds: 120));
      await tester.pump(const Duration(milliseconds: 120));
      const String reply = '**Strong** and *steady*.';
      expect(find.byKey(identityKey), findsOneWidget);
      expect(
          tester.widget<MayosMarkdown>(find.byKey(identityKey)).source, reply);
      expect(_renderedMarkdownText('Strong and steady.'), findsOneWidget);
      expect(tester.takeException(), isNull);

      // History reuses the same renderer after a stream finishes.
      fake.chatOffline = true;
      await tester.pumpWidget(const SizedBox());
      await _pumpChat(
        tester,
        fake,
        store: store,
        scopeKey: UniqueKey(),
        themeMode: mode,
        size: const Size(360, 640),
      );
      expect(_chatMarkdown(reply), findsOneWidget);
      expect(_renderedMarkdownText('Strong and steady.'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }
  });

  testWidgets('error event shows an error state and never persists a partial',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    final FakeMayosApi fake = _fakePlayer('alice')..chatSendError = true;
    await _pumpChat(tester, fake, store: store, scopeKey: UniqueKey());
    await _acceptDisclosure(tester);

    await tester.enterText(
        find.byKey(const Key('chat_composer')), 'Cue my bench?');
    await tester.tap(find.byKey(const Key('chat_send')));
    await _pumpUntilFound(
        tester, find.text('The assistant is temporarily unavailable.'));

    expect(find.byKey(const Key('chat_send_error')), findsOneWidget);
    expect(_chatMarkdown('Keep your elbows tucked.'), findsNothing);
    // Only the user message reached the server; no assistant reply persisted.
    expect(
        fake.chatHistory
            .where((Map<String, dynamic> m) => m['role'] == 'assistant'),
        isEmpty);
    // The failed turn's user message was reloaded from the server, shown once.
    expect(find.text('Cue my bench?'), findsOneWidget);

    // Retrying after recovery succeeds without duplicating the user message.
    fake.chatSendError = false;
    await tester.tap(find.byKey(const Key('chat_retry')));
    await _pumpUntilFound(tester, _chatMarkdown('Keep your elbows tucked.'));
    expect(find.byKey(const Key('chat_send_error')), findsNothing);
    expect(find.text('Cue my bench?'), findsOneWidget);
    expect(
        fake.chatHistory.where((Map<String, dynamic> m) => m['role'] == 'user'),
        hasLength(1));

    // Let dio's stream receive-timeout watchdog drain before teardown.
    await tester.pump(const Duration(seconds: 31));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
      'offline disables send with a message while cached history renders',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    await store.writeDisclosureAccepted('account-alice');
    store.seedHistory('account-alice', <ChatMessage>[
      const ChatMessage(id: 'm1', role: 'user', content: 'How was my squat?'),
      const ChatMessage(id: 'm2', role: 'assistant', content: 'Solid top set.'),
      const ChatMessage(
        id: 'm3',
        role: 'assistant',
        content:
            '📋 **Session Logged:** Full A (2026-09-26) | 12 Sets | Volume: 4,200.0 kg | Readiness: 4/5 | Saved to Ledger.',
        kind: 'debrief',
      ),
    ]);
    final FakeMayosApi fake = _fakePlayer('alice')..chatOffline = true;
    await _pumpChat(tester, fake, store: store, scopeKey: UniqueKey());

    expect(find.byKey(const Key('chat_offline_banner')), findsOneWidget);
    expect(find.text('How was my squat?'), findsOneWidget);
    expect(_renderedMarkdownText('Solid top set.'), findsOneWidget);
    // The commit pointer renders as a distinct debrief card, not a bubble.
    expect(find.byKey(const Key('chat_debrief')), findsOneWidget);
    expect(find.text('Session debrief'), findsOneWidget);
    expect(
      _chatMarkdown(
        '📋 **Session Logged:** Full A (2026-09-26) | 12 Sets | '
        'Volume: 4,200.0 kg | Readiness: 4/5 | Saved to Ledger.',
      ),
      findsOneWidget,
    );

    expect(_composer(tester).enabled, isFalse);
    expect(find.text('Chat needs a connection.'), findsOneWidget);
  });

  testWidgets('program_updated refreshes the cached program and prescription',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    final InMemoryWorkoutCacheStore workoutCache = InMemoryWorkoutCacheStore();
    final FakeMayosApi fake = _fakePlayer('alice')
      ..chatProgramUpdated = true
      ..prescriptionDeload = <String, dynamic>{
        'state': 'applied',
        'reason': 'Acute readiness floor (1/5 logged).',
        'volume_multiplier': 0.5,
        'intensity_cap_rpe': 7.0,
      };
    await _pumpChat(tester, fake,
        store: store,
        workoutCache: workoutCache,
        activeWorkout: InMemoryActiveWorkoutStore(),
        drafts: InMemoryDraftStore(),
        baselineCache: InMemoryBaselineCacheStore(),
        scopeKey: UniqueKey());
    await _acceptDisclosure(tester);
    final int prescriptionRequestsBeforeChat = fake.adapter.requests
        .where((FakeRequest r) =>
            r.method == 'GET' && r.path == '/workouts/prescription')
        .length;

    await tester.enterText(
        find.byKey(const Key('chat_composer')), 'rebuild my routine to 3 days');
    await tester.tap(find.byKey(const Key('chat_send')));
    await _pumpUntilFound(tester, _chatMarkdown('Keep your elbows tucked.'));

    // The program cache was refreshed from the authoritative active program.
    expect(await workoutCache.readProgram('account-alice'), isNotNull);
    expect(
        fake.adapter.requests.any((FakeRequest r) =>
            r.method == 'GET' && r.path == '/programs/active'),
        isTrue);
    expect(
      fake.adapter.requests.any((FakeRequest r) =>
          r.method == 'GET' && r.path == '/workouts/prescription'),
      isTrue,
    );
    expect(
      fake.adapter.requests
              .where((FakeRequest r) =>
                  r.method == 'GET' && r.path == '/workouts/prescription')
              .length -
          prescriptionRequestsBeforeChat,
      1,
    );
    expect(
      (await workoutCache.readPrescription('account-alice', 1))?.deload.state,
      DeloadState.applied,
    );

    // Start the workout offline from the cache ChatScreen just refreshed. The
    // logger must reflect that prescription on its Deload banner.
    fake.prescriptionOffline = true;
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
    );
    container.read(routerProvider).go('$logWorkoutPath/1');
    await _pumpUntilFound(
      tester,
      find.byKey(const ValueKey<String>('logger.progress')),
    );
    expect(
        find.byKey(const ValueKey<String>('logger.progress')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('logger.deload')), findsOneWidget);
    expect(find.text('Deload applied'), findsOneWidget);
  });

  testWidgets('clearing history requires confirmation and clears the service',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    final FakeMayosApi fake = _fakePlayer('alice');
    await _pumpChat(tester, fake, store: store, scopeKey: UniqueKey());
    await _acceptDisclosure(tester);
    await tester.enterText(
        find.byKey(const Key('chat_composer')), 'Cue my bench?');
    await tester.tap(find.byKey(const Key('chat_send')));
    await _pumpUntilFound(tester, _chatMarkdown('Keep your elbows tucked.'));
    expect(fake.chatHistory, isNotEmpty);

    await tester.tap(find.byKey(const Key('chat_clear')));
    await _pumpUntilFound(tester, find.text('Clear chat history?'));
    await tester.tap(find.text('Clear'));
    await _pumpUntilFound(tester, find.textContaining('Ask your assistant'));

    expect(fake.chatHistory, isEmpty);
    expect(await store.readHistory('account-alice'), isEmpty);
  });

  test('logging out clears the account cached chat history', () async {
    final FakeMayosApi fake = _fakePlayer('alice');
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    await store.writeDisclosureAccepted('account-alice');
    store.seedHistory('account-alice', <ChatMessage>[
      const ChatMessage(id: 'm1', role: 'user', content: 'private'),
    ]);
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save(fake.issuedToken!);
    final AuthRepository repository = AuthRepository(
      api: ApiClient(
          tokens: tokens, baseUrl: 'http://test.local', adapter: fake.adapter),
      tokens: tokens,
      chatCache: store,
      eraser: AccountDataEraser(
        drafts: InMemoryDraftStore(),
        workoutCache: InMemoryWorkoutCacheStore(),
        chatCache: store,
        baselines: InMemoryBaselineCacheStore(),
        activeWorkout: InMemoryActiveWorkoutStore(),
        workoutStartNotice: InMemoryWorkoutStartNoticeStore(),
      ),
    );

    await repository.logout(accountId: 'account-alice');

    expect(await store.readHistory('account-alice'), isEmpty);
    // Disclosure acceptance is per account and stays.
    expect(await store.readDisclosureAccepted('account-alice'), isTrue);
  });

  testWidgets(
      'offline banner retry reloads history and clears the offline state',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    await store.writeDisclosureAccepted('account-alice');
    final FakeMayosApi fake = _fakePlayer('alice')..chatOffline = true;
    await _pumpChat(tester, fake, store: store, scopeKey: UniqueKey());
    expect(find.byKey(const Key('chat_offline_banner')), findsOneWidget);

    fake.chatOffline = false;
    await tester.tap(find.byKey(const Key('chat_offline_retry')));
    await _pumpUntilFound(tester, find.textContaining('Ask your assistant'));
    expect(find.byKey(const Key('chat_offline_banner')), findsNothing);
    expect(_composer(tester).enabled, isTrue);
  });

  testWidgets(
      'saving the schedule offline shows the shared needs-connection message',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.failOffline('PUT', '/profile/schedule');
    await _pumpHome(tester, fake);

    await _openSettings(tester);

    await tester.tap(find.text('Training profile'));
    await _pumpUntilFound(tester, find.text('Training schedule'));
    await tester.drag(find.byType(ListView).first, const Offset(0, -900));
    await tester.pump();
    await tester.ensureVisible(find.text('Save schedule'));
    await tester.tap(find.text('Save schedule'));
    await _pumpUntilFound(tester, find.text(needsConnectionMessage));

    expect(find.text(needsConnectionMessage), findsOneWidget);
  });
}

/// Streams a fixed set of byte chunks through the real dio stream path, so a
/// multibyte character split across chunks exercises the streaming decoder.
class _ChunkedBytesAdapter implements HttpClientAdapter {
  _ChunkedBytesAdapter(this._chunks);

  final List<List<int>> _chunks;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    Stream<Uint8List> body() async* {
      for (final List<int> chunk in _chunks) {
        yield Uint8List.fromList(chunk);
      }
    }

    return ResponseBody(
      body(),
      200,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>['text/event-stream'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
