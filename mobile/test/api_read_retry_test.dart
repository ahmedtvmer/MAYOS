import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

class _RetryAdapter implements HttpClientAdapter {
  _RetryAdapter(this.respond);

  final ResponseBody Function(RequestOptions, int) respond;
  final List<RequestOptions> requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    requests.add(options);
    return respond(options, requests.length);
  }

  @override
  void close({bool force = false}) {}
}

ApiClient _client(_RetryAdapter adapter, List<Duration> delays) => ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
      retryDelay: (Duration delay) async => delays.add(delay),
    );

void main() {
  // Regression #690: on 2026-11-09 healthy servers received no mobile requests.
  for (final DioExceptionType type in <DioExceptionType>[
    DioExceptionType.connectionError,
    DioExceptionType.connectionTimeout,
    DioExceptionType.receiveTimeout,
  ]) {
    test('GET recovers after three $type failures with jittered backoff',
        () async {
      final List<Duration> delays = <Duration>[];
      final _RetryAdapter adapter = _RetryAdapter((options, attempt) {
        if (attempt <= 3) {
          throw DioException(requestOptions: options, type: type);
        }
        return ResponseBody.fromString('{"Chest":5}', 200,
            headers: <String, List<String>>{
              Headers.contentTypeHeader: <String>[Headers.jsonContentType],
            });
      });

      expect(await _client(adapter, delays).volume(days: 28),
          <String, double>{'Chest': 5});
      expect(adapter.requests, hasLength(4));
      expect(delays, hasLength(3));
      for (int retry = 0; retry < 3; retry++) {
        final int base = 1000 * (1 << retry);
        expect(delays[retry].inMilliseconds,
            inInclusiveRange((base * 0.8).round(), (base * 1.2).round()));
      }
      for (final RequestOptions request in adapter.requests) {
        expect(request.method, 'GET');
        expect(request.path, '/dashboard/volume');
        expect(request.queryParameters, <String, dynamic>{'days': 28});
        expect(request.connectTimeout, const Duration(seconds: 15));
        expect(request.receiveTimeout, const Duration(seconds: 30));
      }
    });
  }

  test('an exhausted GET surfaces the offline failure after four attempts',
      () async {
    final List<Duration> delays = <Duration>[];
    final _RetryAdapter adapter = _RetryAdapter((options, _) {
      throw DioException.connectionError(
          requestOptions: options, reason: 'No network');
    });

    await expectLater(
      _client(adapter, delays).volume(),
      throwsA(isA<ApiException>()
          .having((error) => error.statusCode, 'status', isNull)
          .having((error) => error.message, 'message',
              "You're offline. We'll retry when you're back online.")),
    );
    expect(adapter.requests, hasLength(4));
    expect(delays, hasLength(3));
  });

  final Map<String, Future<void> Function(ApiClient)> mutations =
      <String, Future<void> Function(ApiClient)>{
    'POST': (api) => api.logout(),
    'PUT': (api) async {
      await api.updateAssistantPreference('preference-1', 'Use dumbbells');
    },
    'PATCH': (api) async {
      await api.correctSessionPerformedDate('session-1', '2026-11-09');
    },
    'DELETE': (api) => api.clearChatHistory(),
  };
  for (final entry in mutations.entries) {
    test('${entry.key} transport failures are never automatically retried',
        () async {
      final List<Duration> delays = <Duration>[];
      final _RetryAdapter adapter = _RetryAdapter((options, _) {
        throw DioException.connectionError(
            requestOptions: options, reason: 'No network');
      });

      await expectLater(entry.value(_client(adapter, delays)),
          throwsA(isA<ApiException>()));
      expect(adapter.requests.single.method, entry.key);
      expect(delays, isEmpty);
    });
  }

  for (final int status in <int>[401, 408, 429, 500, 503]) {
    test('GET with HTTP $status is never retried', () async {
      final List<Duration> delays = <Duration>[];
      final _RetryAdapter adapter =
          _RetryAdapter((_, __) => ResponseBody.fromString('', status));

      await expectLater(_client(adapter, delays).volume(),
          throwsA(isA<ApiException>()
              .having((error) => error.statusCode, 'status', status)));
      expect(adapter.requests, hasLength(1));
      expect(delays, isEmpty);
    });
  }

  for (final DioExceptionType type in <DioExceptionType>[
    DioExceptionType.cancel,
    DioExceptionType.badCertificate,
    DioExceptionType.unknown,
    DioExceptionType.sendTimeout,
  ]) {
    test('GET $type is not a retryable transport blip', () async {
      final List<Duration> delays = <Duration>[];
      final _RetryAdapter adapter = _RetryAdapter((options, _) {
        throw DioException(requestOptions: options, type: type);
      });

      await expectLater(_client(adapter, delays).volume(),
          throwsA(isA<ApiException>()));
      expect(adapter.requests, hasLength(1));
      expect(delays, isEmpty);
    });
  }

  test('a receive timeout carrying a response is never retried', () async {
    final List<Duration> delays = <Duration>[];
    final _RetryAdapter adapter = _RetryAdapter((options, _) {
      throw DioException(
        requestOptions: options,
        type: DioExceptionType.receiveTimeout,
        response: Response<dynamic>(requestOptions: options, statusCode: 503),
      );
    });

    await expectLater(_client(adapter, delays).volume(),
        throwsA(isA<ApiException>()
            .having((error) => error.statusCode, 'status', 503)));
    expect(adapter.requests, hasLength(1));
    expect(delays, isEmpty);
  });

  test('workout-start reads opt out and keep their short receive timeout',
      () async {
    final List<Duration> delays = <Duration>[];
    final _RetryAdapter adapter = _RetryAdapter((options, _) {
      throw DioException(
          requestOptions: options, type: DioExceptionType.receiveTimeout);
    });
    final ApiClient api = _client(adapter, delays);

    await expectLater(api.baselines(receiveTimeout: const Duration(seconds: 5)),
        throwsA(isA<ApiException>()));
    await expectLater(api.prescription(1, retryTransportFailures: false),
        throwsA(isA<ApiException>()));
    expect(adapter.requests, hasLength(2));
    expect(adapter.requests.first.receiveTimeout, const Duration(seconds: 5));
    expect(delays, isEmpty);
  });

  test('long-running imports retain ten-minute timeout and are not retried',
      () async {
    final List<Duration> delays = <Duration>[];
    final _RetryAdapter adapter = _RetryAdapter((options, _) {
      throw DioException(
          requestOptions: options, type: DioExceptionType.receiveTimeout);
    });

    final ApiClient api = _client(adapter, delays);
    await expectLater(
      api.coachImportProgramSheet(
        'assignment-1',
        bytes: Uint8List(0),
        fileName: 'program.csv',
      ),
      throwsA(isA<ApiException>()),
    );
    await expectLater(
      api.coachImportProgramText('assignment-1', text: 'Squat 3x8'),
      throwsA(isA<ApiException>()),
    );
    expect(adapter.requests, hasLength(2));
    for (final RequestOptions request in adapter.requests) {
      expect(request.method, 'POST');
      expect(request.receiveTimeout, const Duration(minutes: 10));
      expect(request.connectTimeout, const Duration(seconds: 15));
    }
    expect(delays, isEmpty);
  });
}
