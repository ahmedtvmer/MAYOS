import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/client_dimensions.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_api_adapter.dart';

void main() {
  test('client header names Android and web with the app version', () {
    expect(
      ApiClient.clientPlatformLabel(
        isWeb: false,
        platform: TargetPlatform.android,
      ),
      'android',
    );
    expect(
      ApiClient.clientPlatformLabel(
        isWeb: true,
        platform: TargetPlatform.android,
      ),
      'web',
    );
    expect(
      ApiClient.clientHeaderFor(platform: 'web', version: '0.1.0'),
      'web/0.1.0',
    );
    expect(
      buildHeaderForPlatform(platform: 'android', buildNumber: 42),
      '42',
    );
    expect(
      buildHeaderForPlatform(platform: 'web', buildNumber: 42),
      isNull,
    );
    expect(
      buildHeaderForPlatform(platform: 'android', buildNumber: null),
      isNull,
    );
  });

  test('every request carries the configured client header', () async {
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse(200, <String, Object>{'ok': true}),
    );
    int versionLoads = 0;
    final ApiClient api = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
      buildHeaderLoader: () => buildHeaderForPlatform(
        platform: 'android',
        buildNumber: 42,
      ),
      clientHeaderLoader: () {
        versionLoads += 1;
        return 'android/1.2.3';
      },
    );

    await api.dio.get<dynamic>('/first');
    await api.dio.get<dynamic>('/second');

    expect(adapter.requests, hasLength(2));
    expect(
      adapter.requests.map((request) => request.headers['X-MAYOS-Client']),
      <String>['android/1.2.3', 'android/1.2.3'],
    );
    expect(
      adapter.requests.map((request) => request.headers['X-MAYOS-Build']),
      <String>['42', '42'],
    );
    expect(versionLoads, 1);
  });

  test('web requests omit the Android build header', () async {
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse(200, <String, Object>{'ok': true}),
    );
    final ApiClient api = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
      buildHeaderLoader: () =>
          buildHeaderForPlatform(platform: 'web', buildNumber: 42),
    );

    await api.dio.get<dynamic>('/first');

    expect(adapter.requests.single.headers['X-MAYOS-Build'], isNull);
  });
}
