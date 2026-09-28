import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/account_data_eraser.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_models.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/sse.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_repository.dart';
import 'package:mayos_mobile/src/providers.dart';

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
  Key? scopeKey,
}) async {
  await _pumpHome(tester, fake,
      chatCache: store, workoutCache: workoutCache, scopeKey: scopeKey);
  await tester.tap(find.byTooltip('Assistant'));
  await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
}

/// Pumps the app to the player home screen.
Future<void> _pumpHome(
  WidgetTester tester,
  FakeMayosApi fake, {
  InMemoryChatCacheStore? chatCache,
  InMemoryWorkoutCacheStore? workoutCache,
  Key? scopeKey,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
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
        _apiOverride(fake),
        chatCacheStoreProvider
            .overrideWithValue(chatCache ?? InMemoryChatCacheStore()),
        workoutCacheStoreProvider
            .overrideWithValue(workoutCache ?? InMemoryWorkoutCacheStore()),
        deviceTimezoneProvider
            .overrideWithValue(Future<String>.value('America/New_York')),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
}

Future<void> _acceptDisclosure(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('chat_disclosure_accept')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

TextField _composer(WidgetTester tester) =>
    tester.widget<TextField>(find.byKey(const Key('chat_composer')));

Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
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
    expect(find.text('Keep your '), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 120));
    expect(find.text('Keep your elbows tucked.'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 120));
    expect(find.text('Assistant is replying…'), findsNothing);
    expect(find.text('Keep your elbows tucked.'), findsOneWidget);
    // The finished reply is cached for offline reading.
    final List<ChatMessage> cached = await store.readHistory('account-alice');
    expect(
        cached.any((ChatMessage m) => m.content == 'Keep your elbows tucked.'),
        isTrue);
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
    expect(find.text('Keep your elbows tucked.'), findsNothing);
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
    await _pumpUntilFound(tester, find.text('Keep your elbows tucked.'));
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
    expect(find.text('Solid top set.'), findsOneWidget);
    // The commit pointer renders as a distinct debrief card, not a bubble.
    expect(find.byKey(const Key('chat_debrief')), findsOneWidget);
    expect(find.text('Session debrief'), findsOneWidget);

    expect(_composer(tester).enabled, isFalse);
    expect(find.text('Chat needs a connection.'), findsOneWidget);
  });

  testWidgets('program_updated refreshes the cached program and prescription',
      (tester) async {
    final InMemoryChatCacheStore store = InMemoryChatCacheStore();
    final InMemoryWorkoutCacheStore workoutCache = InMemoryWorkoutCacheStore();
    final FakeMayosApi fake = _fakePlayer('alice')..chatProgramUpdated = true;
    await _pumpChat(tester, fake,
        store: store, workoutCache: workoutCache, scopeKey: UniqueKey());
    await _acceptDisclosure(tester);

    await tester.enterText(
        find.byKey(const Key('chat_composer')), 'rebuild my routine to 3 days');
    await tester.tap(find.byKey(const Key('chat_send')));
    await _pumpUntilFound(tester, find.text('Keep your elbows tucked.'));

    // The program cache was refreshed from the authoritative active program.
    expect(await workoutCache.readProgram('account-alice'), isNotNull);
    expect(
        fake.adapter.requests.any((FakeRequest r) =>
            r.method == 'GET' && r.path == '/programs/active'),
        isTrue);
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
    await _pumpUntilFound(tester, find.text('Keep your elbows tucked.'));
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
      'regenerating a program offline shows the shared needs-connection message',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.failOffline('POST', '/programs/generate');
    await _pumpHome(tester, fake);

    // Open the Program tab, then regenerate.
    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Regenerate program'));
    await tester.tap(find.text('Regenerate program'));
    await _pumpUntilFound(tester, find.text(needsConnectionMessage));

    expect(find.text(needsConnectionMessage), findsOneWidget);
    // A refusal is never queued: no regenerate request succeeded.
    expect(
        fake.adapter.requests.any((FakeRequest r) =>
            r.method == 'POST' && r.path == '/programs/generate'),
        isTrue);
  });

  testWidgets(
      'saving the schedule offline shows the shared needs-connection message',
      (tester) async {
    final FakeMayosApi fake = _fakePlayer('alice');
    fake.failOffline('PUT', '/profile/schedule');
    await _pumpHome(tester, fake);

    await _openSettings(tester);

    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Training schedule'));
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
