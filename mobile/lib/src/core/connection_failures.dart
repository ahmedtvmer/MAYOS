import 'dart:async';

import 'package:dio/dio.dart';

import 'connectivity_events.dart';
import 'connection_route_templates.dart';
import 'secure_store.dart';
import 'token_store.dart';

export 'connection_route_templates.dart' show connectionFailureRouteTemplate;

const int maxBufferedConnectionFailures = 200;
const String connectionFailuresEndpoint = '/client/connection-failures';
const String connectionFailureAccountKey = 'connectionFailureAccountId';
const String connectionFailureSkipAuthKey = 'skipAuth';
const Duration _connectionFailureStorageTimeout = Duration(seconds: 1);
const String _anonymousBuffer = 'device-before-sign-in';
const Set<String> _failureTypes = <String>{
  'dns',
  'connect_timeout',
  'receive_timeout',
  'connection_reset',
  'other',
};

class ClientConnectionFailure {
  const ClientConnectionFailure({
    required this.occurredAt,
    required this.failureType,
    required this.offlineReported,
    required this.platform,
    required this.appBuild,
    required this.routeTemplate,
  });

  final DateTime occurredAt;
  final String failureType;
  final bool offlineReported;
  final String platform;
  final String appBuild;
  final String routeTemplate;

  Map<String, Object> toJson() => <String, Object>{
        'occurred_at': occurredAt.toUtc().toIso8601String(),
        'failure_type': failureType,
        'offline_reported': offlineReported,
        'platform': platform,
        'app_build': appBuild,
        'route_template': routeTemplate,
      };

  static ClientConnectionFailure? tryParse(Object? value) {
    if (value is! Map<String, dynamic>) return null;
    final Object? rawTime = value['occurred_at'];
    final Object? rawType = value['failure_type'];
    final Object? rawOffline = value['offline_reported'];
    final Object? rawPlatform = value['platform'];
    final Object? rawBuild = value['app_build'];
    final Object? rawRoute = value['route_template'];
    if (rawTime is! String ||
        rawType is! String ||
        !_failureTypes.contains(rawType) ||
        rawOffline is! bool ||
        (rawPlatform != 'web' && rawPlatform != 'android') ||
        rawBuild is! String ||
        rawBuild.length > 64 ||
        rawRoute is! String ||
        !rawRoute.startsWith('/') ||
        rawRoute.length > 256 ||
        rawRoute.contains('?') ||
        rawRoute.contains('#') ||
        rawRoute != connectionFailureRouteTemplate(rawRoute)) {
      return null;
    }
    final DateTime? occurredAt = DateTime.tryParse(rawTime);
    if (occurredAt == null) return null;
    return ClientConnectionFailure(
      occurredAt: occurredAt.toUtc(),
      failureType: rawType,
      offlineReported: rawOffline,
      platform: rawPlatform as String,
      appBuild: rawBuild,
      routeTemplate: rawRoute,
    );
  }
}

abstract interface class ConnectionFailureStore {
  Future<List<ClientConnectionFailure>> read(String accountId);

  Future<void> write(String accountId, List<ClientConnectionFailure> failures);

  Future<void> deleteForAccount(String accountId);
}

/// Keeps callers without app-level store wiring independent of platform storage.
class MemoryConnectionFailureStore implements ConnectionFailureStore {
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
    _failures[accountId] = _boundedFailureCopy(failures);
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    _failures.remove(accountId);
  }
}

List<ClientConnectionFailure> _boundedFailureCopy(
  List<ClientConnectionFailure> failures,
) {
  // Empty, under-limit, and exact-limit lists stay intact; overflow keeps the
  // newest reports because they are most useful for reconnect diagnostics.
  final List<ClientConnectionFailure> bounded =
      failures.length <= maxBufferedConnectionFailures
          ? failures
          : failures.sublist(failures.length - maxBufferedConnectionFailures);
  return List<ClientConnectionFailure>.of(bounded);
}

class ConnectionFailureOptions {
  const ConnectionFailureOptions({
    this.store,
    this.offlineStatusLoader,
  });

  /// App wiring supplies the device store; unset options stay in memory.
  final ConnectionFailureStore? store;
  final Future<bool> Function()? offlineStatusLoader;
}

class SecureConnectionFailureStore implements ConnectionFailureStore {
  SecureConnectionFailureStore({SecureStore? store})
      : _store = store ?? SecureStore();

  final SecureStore _store;
  final MemoryConnectionFailureStore _fallback =
      MemoryConnectionFailureStore();
  final Set<String> _memoryAccounts = <String>{};

  static String _key(String accountId) => 'connection_failures.$accountId';

  @override
  Future<List<ClientConnectionFailure>> read(String accountId) async {
    if (_memoryAccounts.contains(accountId)) {
      return _fallback.read(accountId);
    }
    final dynamic stored;
    try {
      stored = await _store
          .readJson(_key(accountId))
          .timeout(_connectionFailureStorageTimeout);
    } on Object {
      _memoryAccounts.add(accountId);
      return _fallback.read(accountId);
    }
    final List<ClientConnectionFailure> failures =
        _parseStoredFailures(stored);
    await _fallback.write(accountId, failures);
    _memoryAccounts.add(accountId);
    return failures;
  }

  List<ClientConnectionFailure> _parseStoredFailures(Object? stored) {
    if (stored is! List) return <ClientConnectionFailure>[];
    try {
      final List<ClientConnectionFailure> failures = stored
          .map(ClientConnectionFailure.tryParse)
          .whereType<ClientConnectionFailure>()
          .toList(growable: true);
      if (failures.length > maxBufferedConnectionFailures) {
        failures.removeRange(0, failures.length - maxBufferedConnectionFailures);
      }
      return failures;
    } on FormatException {
      return <ClientConnectionFailure>[];
    } on TypeError {
      return <ClientConnectionFailure>[];
    }
  }

  @override
  Future<void> write(
    String accountId,
    List<ClientConnectionFailure> failures,
  ) async {
    final List<ClientConnectionFailure> bounded =
        _boundedFailureCopy(failures);
    await _fallback.write(accountId, bounded);
    _memoryAccounts.add(accountId);
    try {
      await _store
          .writeJson(
            key: _key(accountId),
            value: bounded
                .map((ClientConnectionFailure failure) => failure.toJson())
                .toList(growable: false),
          )
          .timeout(_connectionFailureStorageTimeout);
    } on Object {
      // The bounded memory copy remains available when device storage stalls.
    }
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    await _fallback.deleteForAccount(accountId);
    _memoryAccounts.add(accountId);
    unawaited(_deletePersistedAccount(accountId));
  }

  Future<void> _deletePersistedAccount(String accountId) async {
    try {
      await _store.delete(_key(accountId));
    } on Object {
      // Device storage can be unavailable while the in-memory copy is cleared.
    }
  }
}

class PersistedConnectionFailureReporter {
  PersistedConnectionFailureReporter({
    required TokenStore tokens,
    required Dio dio,
    ConnectionFailureStore? store,
    Future<bool> Function()? offlineStatusLoader,
  })  : _tokens = tokens,
        _dio = dio,
        _store = store ?? MemoryConnectionFailureStore(),
        _offlineStatusLoader = offlineStatusLoader ?? reportedOfflineStatus;

  final TokenStore _tokens;
  final Dio _dio;
  final ConnectionFailureStore _store;
  final Future<bool> Function() _offlineStatusLoader;
  final Map<String, List<ClientConnectionFailure>> _buffers =
      <String, List<ClientConnectionFailure>>{};
  final Set<String> _loadedAccounts = <String>{};
  Future<void> _queue = Future<void>.value();
  bool _uploading = false;
  DateTime? _retryAfter;

  Future<void> record(DioException failure) async {
    if (!_shouldRecord(failure)) return;
    final String accountId =
        failure.requestOptions.extra[connectionFailureAccountKey] as String? ??
            _anonymousBuffer;
    await _exclusive(() async {
      final ClientConnectionFailure? event = await _eventFrom(failure);
      if (event == null) return;
      await _append(accountId, event);
    });
  }

  void flushAfterSuccessfulRequest(RequestOptions request) {
    if (!_hasBearer(request) || _isReportingRequest(request)) return;
    if (_uploading ||
        (_retryAfter != null && DateTime.now().isBefore(_retryAfter!))) return;
    _uploading = true;
    unawaited(_flushSafely(request));
  }

  Future<void> _flushSafely(RequestOptions request) async {
    try {
      await _flushPending(request);
    } on Object {
      // Keep the batch for a later successful request, without a retry storm.
      _retryAfter = DateTime.now().add(const Duration(minutes: 1));
    } finally {
      _uploading = false;
    }
  }

  Future<void> _flushPending(RequestOptions request) async {
    final String? accountId =
        request.extra[connectionFailureAccountKey] as String?;
    if (accountId == null || accountId.isEmpty) return;
    if (accountId != _tokens.lastKnownAccountId) return;
    final List<ClientConnectionFailure> batch =
        await _exclusive(() => _batchForAccount(accountId));
    if (batch.isEmpty) return;
    // Network I/O stays outside the storage queue so another failure can be
    // recorded immediately, even while this upload waits for a timeout.
    await _sendBatch(request, batch);
    await _exclusive(() async {
      final List<ClientConnectionFailure> buffer = await _load(accountId);
      buffer.removeWhere(batch.contains);
      await _persist(accountId, buffer);
    });
  }

  Future<List<ClientConnectionFailure>> _batchForAccount(String accountId) async {
    final List<ClientConnectionFailure> buffer = await _load(accountId);
    final List<ClientConnectionFailure> anonymous = await _load(_anonymousBuffer);
    if (anonymous.isNotEmpty) {
      buffer.addAll(anonymous);
      buffer.sort((left, right) => left.occurredAt.compareTo(right.occurredAt));
      if (buffer.length > maxBufferedConnectionFailures) {
        buffer.removeRange(0, buffer.length - maxBufferedConnectionFailures);
      }
      anonymous.clear();
      await _persist(accountId, buffer);
      await _persist(_anonymousBuffer, anonymous);
    }
    return List<ClientConnectionFailure>.of(buffer);
  }

  Future<void> _sendBatch(
    RequestOptions request,
    List<ClientConnectionFailure> batch,
  ) async {
    await _dio.post<dynamic>(
      connectionFailuresEndpoint,
      options: Options(
        // Pin the original account's authorization across session changes.
        headers: <String, dynamic>{
          'Authorization': request.headers['Authorization'],
        },
        extra: <String, dynamic>{connectionFailureSkipAuthKey: true},
      ),
      data: <String, Object>{
        'failures': batch
            .map((ClientConnectionFailure event) => event.toJson())
            .toList(growable: false),
      },
    );
  }

  bool _shouldRecord(DioException failure) {
    final RequestOptions request = failure.requestOptions;
    return failure.response == null &&
        failure.type != DioExceptionType.cancel &&
        !_isReportingRequest(request);
  }

  Future<ClientConnectionFailure?> _eventFrom(DioException failure) async {
    final RequestOptions request = failure.requestOptions;
    final String clientHeader =
        request.headers['X-MAYOS-Client'] as String? ?? '';
    final List<String> clientParts = clientHeader.split('/');
    final String platform = clientParts.first;
    if (platform != 'web' && platform != 'android') return null;
    final String? buildHeader = request.headers['X-MAYOS-Build'] as String?;
    return ClientConnectionFailure(
      occurredAt: DateTime.now().toUtc(),
      failureType: _failureType(failure),
      offlineReported: await _offlineStatusLoader(),
      platform: platform,
      appBuild: buildHeader ?? clientParts.last,
      routeTemplate: connectionFailureRouteTemplate(request.path),
    );
  }

  Future<void> _append(String accountId, ClientConnectionFailure event) async {
    final List<ClientConnectionFailure> buffer = await _load(accountId);
    buffer.add(event);
    if (buffer.length > maxBufferedConnectionFailures) {
      buffer.removeRange(0, buffer.length - maxBufferedConnectionFailures);
    }
    await _persist(accountId, buffer);
  }

  Future<void> _persist(
    String accountId,
    List<ClientConnectionFailure> buffer,
  ) async {
    try {
      await _store
          .write(accountId, buffer)
          .timeout(_connectionFailureStorageTimeout);
    } on Object {
      // Device storage can be unavailable; keep the bounded in-memory buffer.
    }
  }

  Future<List<ClientConnectionFailure>> _load(String accountId) async {
    if (!_loadedAccounts.contains(accountId)) {
      List<ClientConnectionFailure> stored;
      try {
        stored = await _store
            .read(accountId)
            .timeout(_connectionFailureStorageTimeout);
      } on Object {
        // Reporting still works for this session when device storage fails.
        stored = <ClientConnectionFailure>[];
      }
      _buffers[accountId] = stored;
      _loadedAccounts.add(accountId);
    }
    return _buffers.putIfAbsent(accountId, () => <ClientConnectionFailure>[]);
  }

  Future<T> _exclusive<T>(Future<T> Function() action) async {
    final Completer<void> next = Completer<void>();
    final Future<void> previous = _queue;
    _queue = next.future;
    await previous;
    try {
      return await action();
    } finally {
      next.complete();
    }
  }

  static bool _hasBearer(RequestOptions request) {
    final Object? authorization = request.headers['Authorization'];
    return authorization is String && authorization.startsWith('Bearer ');
  }

  static bool _isReportingRequest(RequestOptions request) =>
      Uri.tryParse(request.path)?.path == connectionFailuresEndpoint;

  static String _failureType(DioException failure) {
    if (failure.type == DioExceptionType.connectionTimeout) {
      return 'connect_timeout';
    }
    if (failure.type == DioExceptionType.receiveTimeout) {
      return 'receive_timeout';
    }
    final String reason = failure.error?.toString().toLowerCase() ?? '';
    if (reason.contains('failed host lookup') ||
        reason.contains('name or service not known') ||
        reason.contains('nodename nor servname') ||
        reason.contains('getaddrinfo failed')) {
      return 'dns';
    }
    if (reason.contains('connection reset') ||
        reason.contains('reset by peer')) {
      return 'connection_reset';
    }
    return 'other';
  }
}

