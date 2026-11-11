import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_stream_fetch_types.dart';
import 'package:mayos_mobile/src/core/connection_failures.dart';
import 'package:mayos_mobile/src/core/secure_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_api_adapter.dart';

class _WriteCompletionTracker {
  final List<Completer<void>> _waiters = <Completer<void>>[];
  int _writeCount = 0;

  void markWrite() {
    _writeCount++;
    final List<Completer<void>> waiters = List<Completer<void>>.of(_waiters);
    _waiters.clear();
    for (final Completer<void> waiter in waiters) {
      if (!waiter.isCompleted) waiter.complete();
    }
  }

  Future<void> waitForWrites(int count) async {
    while (_writeCount < count) {
      final Completer<void> waiter = Completer<void>();
      _waiters.add(waiter);
      try {
        await waiter.future.timeout(const Duration(seconds: 2));
      } finally {
        _waiters.remove(waiter);
      }
    }
  }
}

// #690 read retries are covered in api_read_retry_test.dart; these tests skip the waits.
Future<void> _noRetryDelay(Duration _) async {}

class _MemoryConnectionFailureStore implements ConnectionFailureStore {
  final Map<String, List<ClientConnectionFailure>> _failures =
      <String, List<ClientConnectionFailure>>{};
  final _WriteCompletionTracker _writes = _WriteCompletionTracker();
  void Function(String, List<ClientConnectionFailure>)? onWrite;

  @override
  Future<List<ClientConnectionFailure>> read(String accountId) async =>
      List<ClientConnectionFailure>.of(
        _failures[accountId] ?? <ClientConnectionFailure>[],
      );

  @override
  Future<void> write(
    String accountId,
    List<ClientConnectionFailure> failures,
  ) async {
    _failures[accountId] = List<ClientConnectionFailure>.of(failures);
    _markWriteAttempt();
    onWrite?.call(accountId, failures);
  }

  void _markWriteAttempt() => _writes.markWrite();

  Future<void> waitForWrites(int count) => _writes.waitForWrites(count);

  @override
  Future<void> deleteForAccount(String accountId) async {
    _failures.remove(accountId);
  }
}

class _PendingFetchRequest implements ChatStreamFetchRequest {
  final Completer<ChatStreamFetchResponse> completed =
      Completer<ChatStreamFetchResponse>();

  @override
  Future<ChatStreamFetchResponse> get response => completed.future;

  @override
  void abort() {
    if (!completed.isCompleted) {
      completed.completeError(const ChatStreamTransportException('Aborted'));
    }
  }
}

class _UnavailableConnectionFailureStore extends _MemoryConnectionFailureStore {
  @override
  Future<List<ClientConnectionFailure>> read(String accountId) async =>
      throw Exception('Device storage unavailable');

  @override
  Future<void> write(String accountId, List<ClientConnectionFailure> failures) =>
      _writeUnavailable();

  Future<void> _writeUnavailable() async {
    _markWriteAttempt();
    throw Exception('Device storage unavailable');
  }
}

class _UnavailableSecureStore extends SecureStore {
  @override
  Future<dynamic> readJson(String key) async =>
      throw StateError('Device storage unavailable');

  @override
  Future<void> writeJson({required String key, required Object value}) async =>
      throw StateError('Device storage unavailable');

  @override
  Future<void> delete(String key) async =>
      throw StateError('Device storage unavailable');
}

class _TrackingSecureStore extends SecureStore {
  final _WriteCompletionTracker _writes = _WriteCompletionTracker();

  @override
  Future<void> writeJson({required String key, required Object value}) async {
    await super.writeJson(key: key, value: value);
    _writes.markWrite();
  }

  Future<void> waitForWrites(int count) => _writes.waitForWrites(count);
}

Future<InMemoryTokenStore> _signedInTokens() async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tokens.saveAccountId('account-alice');
  return tokens;
}

Future<List<ClientConnectionFailure>> _waitForFailureCount(
  ConnectionFailureStore Function() createStore,
  String accountId,
  int count,
) async {
  final DateTime deadline = DateTime.now().add(const Duration(seconds: 2));
  while (DateTime.now().isBefore(deadline)) {
    final List<ClientConnectionFailure> failures =
        await createStore().read(accountId);
    if (failures.length >= count) return failures;
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  return createStore().read(accountId);
}

ApiClient _client(
  TokenStore tokens,
  ConnectionFailureStore store,
  FakeApiAdapter adapter,
) =>
    ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: adapter,
      clientHeaderLoader: () => 'web/1.2.3',
      retryDelay: _noRetryDelay,
      connectionFailureOptions: ConnectionFailureOptions(
        store: store,
        offlineStatusLoader: () async => false,
      ),
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('final transport failures buffer one private route template and upload on reconnect', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    await tokens.saveAccountId('account-alice');
    final Completer<void> batchUploaded = Completer<void>();
    FakeRequest? upload;
    final FakeApiAdapter adapter = FakeApiAdapter((FakeRequest request) {
      if (request.path == '/profile/injuries/private-injury-37') {
        return const FakeResponse.networkFailure();
      }
      if (request.path == connectionFailuresEndpoint) {
        upload = request;
        batchUploaded.complete();
        return const FakeResponse(202, <String, Object>{'accepted': 1});
      }
      return const FakeResponse(200, <String, Object>{'opted_in': true});
    });
    final ApiClient api = ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: adapter,
      retryDelay: _noRetryDelay,
      connectionFailureOptions: ConnectionFailureOptions(
        store: store,
        offlineStatusLoader: () async => true,
      ),
      clientHeaderLoader: () => 'android/1.2.3',
      buildHeaderLoader: () => '42',
    );

    await expectLater(
      api.deleteInjury(id: 'private-injury-37'),
      throwsA(isA<ApiException>()),
    );
    await store.waitForWrites(1);
    final List<ClientConnectionFailure> buffered =
        await store.read('account-alice');
    expect(buffered, hasLength(1));
    expect(buffered.single.routeTemplate, '/profile/injuries/{id}');
    expect(buffered.single.offlineReported, isTrue);
    expect(buffered.single.platform, 'android');
    expect(buffered.single.appBuild, '42');
    expect(buffered.single.failureType, 'other');

    await api.setProductEmailConsent(true);
    await batchUploaded.future.timeout(const Duration(seconds: 2));

    expect(upload!.body['failures'], hasLength(1));
    expect(upload!.rawBody, isNot(contains('private-injury-37')));
    expect(upload!.rawBody, isNot(contains('account-alice')));
    expect(upload!.rawBody, isNot(contains('query')));
    expect(upload!.rawBody, isNot(contains('body')));
    expect(
      (upload!.body['failures'] as List).single['route_template'],
      '/profile/injuries/{id}',
    );
  });

  test('buffer drops oldest events after reaching 200', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    await tokens.saveAccountId('account-alice');
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse.networkFailure(),
    );
    final ApiClient api = ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: adapter,
      retryDelay: _noRetryDelay,
      connectionFailureOptions: ConnectionFailureOptions(
        store: store,
        offlineStatusLoader: () async => false,
      ),
      clientHeaderLoader: () => 'web/1.2.3',
    );

    await expectLater(api.coachPlayerSummary('first'), throwsA(isA<ApiException>()));
    for (int index = 0; index < maxBufferedConnectionFailures; index++) {
      await expectLater(
        api.deleteInjury(id: 'injury-$index'), throwsA(isA<ApiException>()),
      );
    }
    await store.waitForWrites(1 + maxBufferedConnectionFailures);

    final List<ClientConnectionFailure> failures = await store.read('account-alice');
    expect(failures, hasLength(200));
    expect(failures.every((failure) => failure.routeTemplate == '/profile/injuries/{id}'), isTrue);
  });

  test('known-word ids, queries and request bodies never reach the buffer', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = await _signedInTokens();
    final ApiClient api = _client(tokens, store, FakeApiAdapter(
      (_) => const FakeResponse.networkFailure(),
    ));

    await expectLater(api.updateInjury(
      id: 'search?email=private-query#private-fragment',
      bodyArea: 'private-area', description: 'private-body', status: 'active',
    ), throwsA(isA<ApiException>()));
    await expectLater(api.coachPlayerSummary('private-assignment', days: 23),
        throwsA(isA<ApiException>()));
    await expectLater(api.exerciseHistory('private/exercise?private-value'),
        throwsA(isA<ApiException>()));

    await store.waitForWrites(3);
    final List<ClientConnectionFailure> failures = await store.read('account-alice');
    expect(failures.take(2).map((failure) => failure.routeTemplate), <String>[
      '/profile/injuries/{id}',
      '/coach/assignments/{id}/player/summary',
    ]);
    final String persisted = jsonEncode(failures.map((failure) => failure.toJson()).toList());
    for (final String secret in <String>[
      'search', 'private-query', 'private-fragment', 'private-area',
      'private-body', 'private-assignment', 'private-value', 'days',
    ]) {
      expect(persisted, isNot(contains(secret)));
    }
    expect(failures.last.routeTemplate,
        anyOf('/dashboard/exercises/{id}/history', '/unknown'));
  });

  test('device buffer survives a client restart and clears after an accepted upload', () async {
    FlutterSecureStorage.setMockInitialValues(<String, String>{});
    final InMemoryTokenStore tokens = await _signedInTokens();
    final _TrackingSecureStore deviceStore = _TrackingSecureStore();
    final ApiClient offline = _client(
      tokens,
      SecureConnectionFailureStore(store: deviceStore),
      FakeApiAdapter((_) => const FakeResponse.networkFailure()),
    );
    await expectLater(offline.deleteInjury(id: 'private-id'), throwsA(isA<ApiException>()));
    await deviceStore.waitForWrites(1);
    final _TrackingSecureStore reopenedDeviceStore = _TrackingSecureStore();
    final SecureConnectionFailureStore reopened =
        SecureConnectionFailureStore(store: reopenedDeviceStore);
    expect(await reopened.read('account-alice'), hasLength(1));
    final Completer<FakeRequest> uploaded = Completer<FakeRequest>();
    final ApiClient online = _client(tokens, reopened, FakeApiAdapter((request) {
      if (request.path == connectionFailuresEndpoint) {
        uploaded.complete(request);
        return const FakeResponse(202, <String, Object>{'accepted': 1});
      }
      return const FakeResponse(200, <String, Object>{'opted_in': true});
    }));

    await online.setProductEmailConsent(true);
    final FakeRequest batch = await uploaded.future.timeout(const Duration(seconds: 2));
    expect(batch.body['failures'], hasLength(1));
    expect(batch.headers['Authorization'], 'Bearer token-alice');
    await reopenedDeviceStore.waitForWrites(1);
    expect(
      await SecureConnectionFailureStore().read('account-alice'),
      isEmpty,
    );
  });

  test('secure failure buffer falls back to memory when platform storage fails', () async {
    final SecureConnectionFailureStore store =
        SecureConnectionFailureStore(store: _UnavailableSecureStore());
    const String accountId = 'account-alice';
    final ClientConnectionFailure failure = ClientConnectionFailure(
      occurredAt: DateTime.utc(2026, 11, 11),
      failureType: 'other',
      offlineReported: false,
      platform: 'web',
      appBuild: '42',
      routeTemplate: '/profile/injuries/{id}',
    );

    expect(await store.read(accountId), isEmpty);
    await store.write(accountId, <ClientConnectionFailure>[failure]);
    expect(await store.read(accountId), <ClientConnectionFailure>[failure]);

    await store.deleteForAccount(accountId);
    expect(await store.read(accountId), isEmpty);
  });

  test('unavailable device storage still allows in-memory reporting', () async {
    final InMemoryTokenStore tokens = await _signedInTokens();
    final Completer<FakeRequest> uploaded = Completer<FakeRequest>();
    final _UnavailableConnectionFailureStore store =
        _UnavailableConnectionFailureStore();
    final ApiClient api = _client(tokens, store,
        FakeApiAdapter((request) {
      if (request.path == connectionFailuresEndpoint) {
        uploaded.complete(request);
        return const FakeResponse(202, <String, Object>{'accepted': 1});
      }
      if (request.method == 'DELETE') return const FakeResponse.networkFailure();
      return const FakeResponse(200, <String, Object>{'opted_in': true});
    }));
    await expectLater(api.deleteInjury(id: 'private-id'), throwsA(isA<ApiException>()));
    await store.waitForWrites(1);
    await api.setProductEmailConsent(true);
    final FakeRequest batch = await uploaded.future.timeout(const Duration(seconds: 2));
    expect(batch.body['failures'], hasLength(1));
    expect(batch.rawBody, isNot(contains('private-id')));
  });

  test('a sign-in outage is uploaded after authentication without credentials', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final Completer<FakeRequest> uploaded = Completer<FakeRequest>();
    final ApiClient api = _client(tokens, store, FakeApiAdapter((request) {
      if (request.path == '/auth/login') return const FakeResponse.networkFailure();
      if (request.path == connectionFailuresEndpoint) {
        uploaded.complete(request);
        return const FakeResponse(202, <String, Object>{'accepted': 1});
      }
      return const FakeResponse(200, <String, Object>{'opted_in': true});
    }));
    await expectLater(api.login(
      traineeId: 'private-username', password: 'private-password',
    ), throwsA(isA<ApiException>()));
    await store.waitForWrites(1);
    await tokens.save('token-alice');
    await tokens.saveAccountId('account-alice');
    await api.setProductEmailConsent(true);
    final FakeRequest batch = await uploaded.future.timeout(const Duration(seconds: 2));
    expect(batch.headers['Authorization'], 'Bearer token-alice');
    final List<dynamic> failures = batch.body['failures'] as List<dynamic>;
    expect(failures, hasLength(1));
    expect(failures.single['route_template'], '/auth/login');
    expect(batch.rawBody, isNot(contains('private-username')));
    expect(batch.rawBody, isNot(contains('private-password')));
  });

  for (final (String, FakeResponse) scenario in <(String, FakeResponse)>[
    ('expired authorization', const FakeResponse(401, <String, Object>{'detail': 'Expired'})),
    ('rate limit', const FakeResponse(429, <String, Object>{'detail': 'Rate limited'})),
    ('disconnection', const FakeResponse.networkFailure()),
  ]) {
    test('upload ${scenario.$1} keeps the buffer without recursion or session changes', () async {
      final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
      final InMemoryTokenStore tokens = await _signedInTokens();
      final Completer<void> uploaded = Completer<void>();
      int uploads = 0;
      int unauthorized = 0;
      final ApiClient api = _client(tokens, store, FakeApiAdapter((request) {
        if (request.path == connectionFailuresEndpoint) {
          uploads++;
          if (!uploaded.isCompleted) uploaded.complete();
          return scenario.$2;
        }
        if (request.method == 'DELETE') return const FakeResponse.networkFailure();
        return const FakeResponse(200, <String, Object>{'opted_in': true});
      }));
      api.onUnauthorized = () => unauthorized++;
      await expectLater(api.deleteInjury(id: 'private-id'), throwsA(isA<ApiException>()));
      await store.waitForWrites(1);
      await api.setProductEmailConsent(true);
      await uploaded.future.timeout(const Duration(seconds: 2));
      await Future<void>.delayed(Duration.zero);
      await api.setProductEmailConsent(true);
      expect(await store.read('account-alice'), hasLength(1));
      expect(uploads, 1);
      expect(unauthorized, 0);
      expect(await tokens.read(), 'token-alice');
    });
  }

  for (final (DioExceptionType, String?, String?) scenario in
      <(DioExceptionType, String?, String?)>[
    (DioExceptionType.connectionTimeout, null, 'connect_timeout'),
    (DioExceptionType.receiveTimeout, null, 'receive_timeout'),
    (DioExceptionType.connectionError, 'Failed host lookup: private-host', 'dns'),
    (DioExceptionType.connectionError, 'Connection reset by peer', 'connection_reset'),
    (DioExceptionType.connectionError, 'Unspecified network failure', 'other'),
    (DioExceptionType.cancel, null, null),
  ]) {
    test('${scenario.$1} ${scenario.$3} is classified at the API boundary', () async {
      final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
      final InMemoryTokenStore tokens = await _signedInTokens();
      final ApiClient api = _client(tokens, store, FakeApiAdapter(
        (_) => const FakeResponse(200),
      ));
      api.dio.interceptors.add(InterceptorsWrapper(
        onRequest: (options, handler) => handler.reject(DioException(
          requestOptions: options, type: scenario.$1, error: scenario.$2,
        )),
      ));

      await expectLater(api.deleteInjury(id: 'private-id'), throwsA(isA<ApiException>()));
      if (scenario.$3 != null) await store.waitForWrites(1);
      final List<ClientConnectionFailure> failures = await store.read('account-alice');
      if (scenario.$3 == null) {
        expect(failures, isEmpty);
      } else {
        expect(failures, hasLength(1));
        expect(failures.single.failureType, scenario.$3);
        expect(jsonEncode(failures.single.toJson()), isNot(contains('private-host')));
      }
    });
  }

  test('HTTP errors are never recorded as connection failures', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = await _signedInTokens();
    final ApiClient api = _client(tokens, store, FakeApiAdapter(
      (_) => const FakeResponse(503, <String, String>{'detail': 'Unavailable'}),
    ));
    await expectLater(api.deleteInjury(id: 'private-id'), throwsA(isA<ApiException>()));
    expect(await store.read('account-alice'), isEmpty);
  });

  test('web fetch failures before headers are reported and a later success uploads them', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = await _signedInTokens();
    final _PendingFetchRequest pending = _PendingFetchRequest();
    final Completer<void> started = Completer<void>();
    final Completer<FakeRequest> uploaded = Completer<FakeRequest>();
    final ApiClient api = ApiClient(
      tokens: tokens, baseUrl: 'http://test.local',
      clientHeaderLoader: () => 'web/1.2.3',
      retryDelay: _noRetryDelay,
      connectionFailureOptions: ConnectionFailureOptions(
        store: store, offlineStatusLoader: () async => true,
      ),
      chatStreamFetch: ({required Uri url, required Map<String, String> headers,
          required String body}) {
        started.complete();
        return pending;
      },
      adapter: FakeApiAdapter((request) {
        if (request.path == connectionFailuresEndpoint) {
          uploaded.complete(request);
          return const FakeResponse(202, <String, Object>{'accepted': 1});
        }
        return const FakeResponse(200, <String, Object>{'opted_in': true});
      }),
    );
    final Future<void> failed = expectLater(
      api.streamChatMessage('private-chat-text').toList(), throwsA(isA<ApiException>()),
    );
    await started.future.timeout(const Duration(seconds: 2));
    pending.completed.completeError(const ChatStreamTransportException('Failed to fetch'));
    await failed;
    await store.waitForWrites(1);
    expect((await store.read('account-alice')).single.routeTemplate, '/chat/messages');
    await api.setProductEmailConsent(true);
    final FakeRequest batch = await uploaded.future.timeout(const Duration(seconds: 2));
    expect(batch.rawBody, isNot(contains('private-chat-text')));
    expect(batch.body['failures'], hasLength(1));
  });

  test('cancelling a pending browser request does not record a connection failure', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = await _signedInTokens();
    final _PendingFetchRequest pending = _PendingFetchRequest();
    final Completer<void> started = Completer<void>();
    final ApiClient api = ApiClient(
      tokens: tokens, baseUrl: 'http://test.local',
      clientHeaderLoader: () => 'web/1.2.3',
      retryDelay: _noRetryDelay,
      connectionFailureOptions: ConnectionFailureOptions(
        store: store, offlineStatusLoader: () async => false,
      ),
      chatStreamFetch: ({required Uri url, required Map<String, String> headers,
          required String body}) {
        started.complete();
        return pending;
      },
    );
    final subscription = api.streamChatMessage('private-chat-text').listen((_) {});
    await started.future.timeout(const Duration(seconds: 2));
    await subscription.cancel();
    await Future<void>.delayed(Duration.zero);
    expect(await store.read('account-alice'), isEmpty);
  });

  test('recording continues during upload and acknowledgement preserves newer failures', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = await _signedInTokens();
    final Completer<void> uploadStarted = Completer<void>();
    final Completer<void> releaseUpload = Completer<void>();
    final Completer<void> acknowledged = Completer<void>();
    final FakeApiAdapter adapter = FakeApiAdapter((request) {
      if (request.path == connectionFailuresEndpoint) {
        return const FakeResponse(202, <String, Object>{'accepted': 1});
      }
      if (request.method == 'DELETE') return const FakeResponse.networkFailure();
      return const FakeResponse(200, <String, Object>{'opted_in': true});
    });
    adapter.beforeRespond = (request) async {
      if (request.path == connectionFailuresEndpoint) {
        uploadStarted.complete();
        await releaseUpload.future;
      }
    };
    final ApiClient api = _client(tokens, store, adapter);
    await expectLater(api.deleteInjury(id: 'old'), throwsA(isA<ApiException>()));
    await store.waitForWrites(1);
    await api.setProductEmailConsent(true);
    await uploadStarted.future.timeout(const Duration(seconds: 2));
    try {
      await expectLater(api.deleteInjury(id: 'new').timeout(const Duration(seconds: 2)),
          throwsA(isA<ApiException>()));
      await store.waitForWrites(2);
      expect(await store.read('account-alice'), hasLength(2));
      await api.setProductEmailConsent(true);
      store.onWrite = (_, failures) {
        if (failures.length == 1 && !acknowledged.isCompleted) acknowledged.complete();
      };
    } finally {
      releaseUpload.complete();
    }
    await acknowledged.future.timeout(const Duration(seconds: 2));
    expect(await store.read('account-alice'), hasLength(1));
    expect(adapter.requests.where((request) => request.path == connectionFailuresEndpoint), hasLength(1));
  });

  test('an in-flight failure is attributed to its original account after switching', () async {
    final _MemoryConnectionFailureStore store = _MemoryConnectionFailureStore();
    final InMemoryTokenStore tokens = await _signedInTokens();
    final Completer<void> started = Completer<void>();
    final Completer<void> finish = Completer<void>();
    final FakeApiAdapter adapter = FakeApiAdapter((request) {
      if (request.method == 'DELETE') return const FakeResponse.networkFailure();
      return const FakeResponse(200, <String, Object>{'opted_in': true});
    });
    adapter.beforeRespond = (request) async {
      if (request.method == 'DELETE') {
        started.complete();
        await finish.future;
      }
    };
    final ApiClient api = _client(tokens, store, adapter);
    final Future<void> failure = expectLater(
        api.deleteInjury(id: 'private-id'), throwsA(isA<ApiException>()));
    await started.future.timeout(const Duration(seconds: 2));
    await tokens.save('token-bob');
    await tokens.saveAccountId('account-bob');
    finish.complete();
    await failure;
    await store.waitForWrites(1);
    await api.setProductEmailConsent(true);
    expect(await store.read('account-alice'), hasLength(1));
    expect(await store.read('account-bob'), isEmpty);
    expect(adapter.requests.where((request) => request.path == connectionFailuresEndpoint), isEmpty);
  });
}
