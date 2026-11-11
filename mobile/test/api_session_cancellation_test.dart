import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_api_adapter.dart';

Future<void> _completeWithPumps(
    WidgetTester tester, Future<void> operation) async {
  bool completed = false;
  operation.then<void>((_) {
    completed = true;
  }, onError: (Object error) {
    completed = true;
  });
  for (int frame = 0; frame < 20 && !completed; frame++) {
    await tester.pump(Duration.zero);
  }
  expect(completed, isTrue, reason: 'The async operation did not complete');
  await operation;
}

void main() {
  // Regression #689: a failed attempt leaves Dio's in-flight set before its
  // backoff. Ending the session must cancel that wait as well as live requests.
  testWidgets('ending a session during backoff does not restart its GET',
      (WidgetTester tester) async {
    bool offline = true;
    final FakeApiAdapter adapter = FakeApiAdapter((_) => offline
        ? const FakeResponse.networkFailure()
        : const FakeResponse(200, <String, double>{'Chest': 8}));
    final ApiClient api = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
    );
    addTearDown(api.dispose);
    final Future<void> failedRead =
        expectLater(api.volume(), throwsA(isA<ApiException>()));
    // Dio dispatches through zero-duration timers. A pump without a duration
    // flushes microtasks but leaves those timers waiting on the fake clock.
    await tester.pump(Duration.zero);
    expect(adapter.requests, hasLength(1));

    await _completeWithPumps(tester, api.cancelAuthenticatedRequests());
    await _completeWithPumps(tester, failedRead);
    await tester.pump(const Duration(seconds: 10));
    expect(adapter.requests, hasLength(1));

    // A subsequent session can read, without reviving the previous GET.
    offline = false;
    await _completeWithPumps(tester,
        expectLater(api.volume(), completion(<String, double>{'Chest': 8})));
    expect(adapter.requests, hasLength(2));
  });

  testWidgets('ending a session finishes an in-flight GET cancellation',
      (WidgetTester tester) async {
    final Completer<void> releaseResponse = Completer<void>();
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse.networkFailure(),
    )..beforeRespond = (_) => releaseResponse.future;
    final ApiClient api = ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
    );
    addTearDown(api.dispose);
    final Future<void> failedRead =
        expectLater(api.volume(), throwsA(isA<ApiException>()));
    await tester.pump(Duration.zero);
    expect(adapter.requests, hasLength(1));

    await _completeWithPumps(tester, api.cancelAuthenticatedRequests());
    await _completeWithPumps(tester, failedRead);
    releaseResponse.complete();
    await tester.pump(Duration.zero);
    expect(adapter.requests, hasLength(1));
  });
}
