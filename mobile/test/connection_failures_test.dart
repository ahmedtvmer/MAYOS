import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/connection_failures.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_api_adapter.dart';

class _MemoryConnectionFailureStore implements ConnectionFailureStore {
  final Map<String, List<ClientConnectionFailure>> _failures =
      <String, List<ClientConnectionFailure>>{};

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
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    _failures.remove(accountId);
  }
}

void main() {
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
    final List<ClientConnectionFailure> buffered =
        await store.read('account-alice');
    expect(buffered, hasLength(1));
    expect(buffered.single.routeTemplate, '/profile/injuries/{id}');
    expect(buffered.single.offlineReported, isTrue);
    expect(buffered.single.platform, 'android');
    expect(buffered.single.appBuild, '42');
    expect(buffered.single.failureType, 'other');

    await api.setProductEmailConsent(true);
    await batchUploaded.future;

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
      connectionFailureOptions: ConnectionFailureOptions(
        store: store,
        offlineStatusLoader: () async => false,
      ),
      clientHeaderLoader: () => 'web/1.2.3',
    );

    for (int index = 0; index < maxBufferedConnectionFailures + 1; index++) {
      try {
        await api.deleteInjury(id: 'injury-$index');
      } on ApiException {
        // Each failed call is expected; the API client retains its failure.
      }
    }

    expect(await store.read('account-alice'), hasLength(200));
  });
}
