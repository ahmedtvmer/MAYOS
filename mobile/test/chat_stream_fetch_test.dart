import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_models.dart';
import 'package:mayos_mobile/src/core/chat_stream_fetch_types.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_api_adapter.dart';

void main() {
  test('web chat #394 parses frames split across fetch chunks', () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 200,
        body: Stream<List<int>>.fromIterable(<List<int>>[
          utf8.encode('data: {"token":"first"}\n\ndata: {"do'),
          utf8.encode('ne":true,"response_content":"first"}\n\n'),
        ]),
      ));
    });
    final ApiClient api = await _client(fetch);

    final List<ChatStreamEvent> events =
        await api.streamChatMessage('Explain this.').toList();

    expect(events, hasLength(2));
    expect((events.first as ChatToken).token, 'first');
    expect(events.last, isA<ChatDone>());
  });

  test('coach assistant reuses fetch transport and answer-frame decoding',
      () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 200,
        body: Stream<List<int>>.fromIterable(<List<int>>[
          utf8.encode('data: {"token":"Steady "}\n\ndata: {"done":true,'),
          utf8.encode('"answer":"Steady progress."}\n\n'),
        ]),
      ));
    });
    final ApiClient api = await _client(fetch);

    final List<ChatStreamEvent> events = await api
        .streamCoachAssistant(
          assignmentId: 'assignment-1',
          question: 'How is training?',
          history: <CoachAssistantTurn>[
            const CoachAssistantTurn(role: 'coach', content: 'Earlier?'),
          ],
        )
        .toList();

    expect(fetch.url.toString(),
        'http://test.local/coach/assignments/assignment-1/assistant');
    expect(jsonDecode(fetch.body), <String, dynamic>{
      'question': 'How is training?',
      'history': <Map<String, dynamic>>[
        <String, dynamic>{'role': 'coach', 'content': 'Earlier?'},
      ],
    });
    expect((events[0] as ChatToken).token, 'Steady ');
    expect((events[1] as ChatDone).responseContent, 'Steady progress.');
  });

  test('web chat #394 reassembles a multibyte character across chunks',
      () async {
    final List<int> bytes = utf8.encode('data: {"token":"€"}\n\n');
    final int split = bytes.indexOf(0xE2) + 1;
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 200,
        body: Stream<List<int>>.fromIterable(<List<int>>[
          bytes.sublist(0, split),
          bytes.sublist(split),
        ]),
      ));
    });

    final List<ChatStreamEvent> events =
        await (await _client(fetch)).streamChatMessage('x').toList();

    expect((events.single as ChatToken).token, '€');
  });

  test('429 fetch response surfaces the server detail and status', () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 429,
        body: Stream<List<int>>.value(
            utf8.encode('{"detail":"Daily AI limit reached."}')),
      ));
    });

    final ApiException error = await _expectApiException(
        (await _client(fetch)).streamChatMessage('x'));

    expect(error.statusCode, 429);
    expect(error.message, 'Daily AI limit reached.');
  });

  test('mid-stream fetch failure is a network ApiException', () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 200,
        body: Stream<List<int>>.error(
            const ChatStreamTransportException()),
      ));
    });

    final ApiException error = await _expectApiException(
        (await _client(fetch)).streamChatMessage('x'));

    expect(error.statusCode, isNull);
  });

  test('401 fetch response invokes unauthorized callback', () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 401,
        body: Stream<List<int>>.value(
            utf8.encode('{"detail":"Session expired."}')),
      ));
    });
    final ApiClient api = await _client(fetch);
    bool unauthorized = false;
    api.onUnauthorized = () => unauthorized = true;

    final ApiException error =
        await _expectApiException(api.streamChatMessage('x'));

    expect(error.statusCode, 401);
    expect(unauthorized, isTrue);
  });

  test('deleted-account 401 fetch response invokes its callback', () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 401,
        body: Stream<List<int>>.value(utf8.encode(
            '{"error":"account_deleted","detail":"Account deleted."}')),
      ));
    });
    final ApiClient api = await _client(fetch);
    bool accountDeleted = false;
    bool unauthorized = false;
    api.onAccountDeleted = () => accountDeleted = true;
    api.onUnauthorized = () => unauthorized = true;

    await _expectApiException(api.streamChatMessage('x'));

    expect(accountDeleted, isTrue);
    expect(unauthorized, isFalse);
  });

  test('426 fetch response invokes the app update callback', () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 426,
        body: Stream<List<int>>.value(utf8.encode(
            '{"error":"app_update_required","min_build":23,'
            '"store_url":"https://example.com/store",'
            '"detail":"Update required."}')),
      ));
    });
    final ApiClient api = await _client(fetch);
    AppVersionPolicy? requestedPolicy;
    api.onAppUpdateRequired = (AppVersionPolicy policy) {
      requestedPolicy = policy;
    };

    await _expectApiException(api.streamChatMessage('x'));

    expect(requestedPolicy?.minBuild, 23);
    expect(requestedPolicy?.storeUrl, 'https://example.com/store');
  });

  test('cancelling the fetch stream aborts its request', () async {
    late _FakeRequest request;
    final Completer<void> bodyListened = Completer<void>();
    final StreamController<List<int>> body = StreamController<List<int>>(
      onListen: bodyListened.complete,
    );
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String bodyText) {
      request = _FakeRequest(
        ChatStreamFetchResponse(statusCode: 200, body: body.stream),
        onAbort: () => body.close(),
      );
      return request;
    });
    final ApiClient api = await _client(fetch);

    final StreamSubscription<ChatStreamEvent> subscription =
        api.streamChatMessage('x').listen((ChatStreamEvent event) {});
    await bodyListened.future;
    await subscription.cancel();

    expect(request.aborted, isTrue);
  });

  test('fetch carries Dio chat headers while other calls still use Dio',
      () async {
    final _FakeFetch fetch = _FakeFetch((Uri url, Map<String, String> headers,
        String body) {
      return _FakeRequest(ChatStreamFetchResponse(
        statusCode: 200,
        body: const Stream<List<int>>.empty(),
      ));
    });
    final ApiClient api = await _client(fetch, language: 'ar');

    await api.streamChatMessage('hello').drain<void>();

    expect(fetch.url.toString(), 'http://test.local/chat/messages');
    expect(fetch.headers['Authorization'], 'Bearer test-token');
    expect(fetch.headers['X-MAYOS-Client'], 'web/test');
    expect(fetch.headers['X-MAYOS-Build'], '17');
    expect(fetch.headers['Accept-Language'], 'ar');
    expect(jsonDecode(fetch.body), <String, String>{'content': 'hello'});

    final FakeApiAdapter adapter = FakeApiAdapter(
        (_) => const FakeResponse(204));
    final ApiClient apiWithDio = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
      chatStreamFetch: fetch.call,
    );
    await apiWithDio.clearChatHistory();
    expect(adapter.requests.single.path, '/chat/history');
  });
}

Future<ApiClient> _client(_FakeFetch fetch, {String language = 'en'}) async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('test-token');
  return ApiClient(
    tokens: tokens,
    baseUrl: 'http://test.local',
    chatStreamFetch: fetch.call,
    clientHeaderLoader: () => 'web/test',
    buildHeaderLoader: () => '17',
    displayLanguageLoader: () => language,
  );
}

Future<ApiException> _expectApiException(Stream<ChatStreamEvent> stream) async {
  try {
    await stream.toList();
  } on ApiException catch (error) {
    return error;
  }
  fail('Expected ApiException.');
}

class _FakeFetch {
  _FakeFetch(this._createRequest);

  final ChatStreamFetchRequest Function(
      Uri url, Map<String, String> headers, String body) _createRequest;
  Uri? url;
  Map<String, String> headers = <String, String>{};
  String body = '';

  ChatStreamFetchRequest call({
    required Uri url,
    required Map<String, String> headers,
    required String body,
  }) {
    this.url = url;
    this.headers = Map<String, String>.from(headers);
    this.body = body;
    return _createRequest(url, headers, body);
  }
}

class _FakeRequest implements ChatStreamFetchRequest {
  _FakeRequest(ChatStreamFetchResponse response, {this.onAbort})
      : response = Future<ChatStreamFetchResponse>.value(response);

  @override
  final Future<ChatStreamFetchResponse> response;
  final void Function()? onAbort;
  bool aborted = false;

  @override
  void abort() {
    aborted = true;
    onAbort?.call();
  }
}
