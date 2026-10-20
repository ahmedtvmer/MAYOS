import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_api_adapter.dart';

void main() {
  test('pasted Program import sends text as multipart without a file', () async {
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse(200, <String, dynamic>{'rows': <dynamic>[]}),
    );
    final ApiClient api = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
    );

    await api.coachImportProgramText('assignment-1', text: 'Day 1\nSquat 3x8');

    final FakeRequest request = adapter.requests.single;
    expect(request.method, 'POST');
    expect(request.path,
        '/coach/assignments/assignment-1/program-import');
    expect(request.headers['content-type'], contains('multipart/form-data'));
    expect(request.rawBody, contains('name="text"'));
    expect(request.rawBody, contains('Day 1\nSquat 3x8'));
    expect(request.rawBody, isNot(contains('name="file"')));
  });
}
