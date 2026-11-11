import 'dart:async';

import 'package:dio/dio.dart';

import 'saved_player_data.dart';
import 'token_store.dart';
import 'token_subject.dart';

/// An allow-list keeps cached reads out of Coach mode and mutations. Auth reads
/// always reach the service: only AuthRepository can restore a saved session.
class SavedPlayerReads extends Interceptor {
  SavedPlayerReads(this._tokens, this._store);

  final TokenStore _tokens;
  final SavedPlayerDataStore _store;
  static const String _contextKey = 'savedPlayerRead';
  static const String cachedResponse = 'savedPlayerResponse';
  static const Set<String> _paths = <String>{
    '/auth/me',
    '/profile/schedule',
    '/assignments/me',
    '/checkpoint-reviews',
    '/dashboard/training-status',
    '/dashboard/volume',
    '/dashboard/personal-records',
    '/workouts/sessions/latest',
    '/programs/active',
    '/workouts/prescription',
    '/nutrition',
    '/nutrition/food-log',
  };

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final _SavedReadContext? context = await _attachReadContext(options);
    if (context == null || !_store.offline || options.path == '/auth/me') {
      handler.next(options);
      return;
    }
    final Response<dynamic>? saved = await _savedResponse(options, context);
    if (saved == null) {
      handler.next(options);
      return;
    }
    handler.resolve(saved, true);
  }

  Future<_SavedReadContext?> _attachReadContext(RequestOptions request) async {
    if (!_isSavedPlayerRead(request)) return null;
    final String? token = await _tokens.read();
    if (token == null || token.isEmpty || !_hasMatchingToken(request, token)) {
      return null;
    }
    // The persisted id may require platform storage. Keep the request live;
    // a successful response can resolve the id after the service answers.
    final String? accountId = unverifiedTokenSubject(token);
    final _SavedReadContext context = _SavedReadContext(
      token, accountId, _store.generation,
    );
    request.extra[_contextKey] = context;
    return context;
  }

  @override
  void onResponse(Response<dynamic> response, ResponseInterceptorHandler handler) {
    final RequestOptions request = response.requestOptions;
    final dynamic context = request.extra[_contextKey];
    if (context is! _SavedReadContext) {
      handler.next(response);
      return;
    }
    unawaited(_saveResponse(response, context).catchError((Object _) {
      // Snapshot caching must not hold up a live API response.
    }));
    handler.next(response);
  }

  @override
  void onError(DioException error, ErrorInterceptorHandler handler) async {
    final dynamic context = error.requestOptions.extra[_contextKey];
    // Never hide a refusal, deletion, cancellation, or an invalid session.
    if (context is _SavedReadContext && _canFallback(error)) {
      final Response<dynamic>? saved =
          await _savedResponse(error.requestOptions, context);
      if (saved != null) {
        _store.useSavedData();
        handler.resolve(saved);
        return;
      }
    }
    handler.next(error);
  }

  static bool _isSavedPlayerRead(RequestOptions request) =>
      request.method == 'GET' && _paths.contains(request.path);

  static bool _hasMatchingToken(RequestOptions request, String? token) =>
      token != null &&
      token.isNotEmpty &&
      request.headers['Authorization'] == 'Bearer $token';

  Future<String?> _accountIdFor(String token) async {
    final String? accountId =
        unverifiedTokenSubject(token) ?? await _tokens.readAccountId();
    return accountId == null || accountId.isEmpty ? null : accountId;
  }

  Future<bool> _canSave(
          Response<dynamic> response, _SavedReadContext context) async =>
      response.extra[cachedResponse] != true &&
      response.statusCode != null &&
      response.statusCode! < 300 &&
      await _tokens.read() == context.token &&
      _store.generation == context.generation;

  static String? _responseAccountId(
      RequestOptions request, _SavedReadContext context, Object? body) {
    if (request.path != '/auth/me') return context.accountId;
    final Object? accountId = body is Map ? body['account_id'] : null;
    return accountId is String && accountId.isNotEmpty ? accountId : null;
  }

  static bool _canFallback(DioException error) =>
      error.response == null &&
      error.type != DioExceptionType.cancel &&
      error.requestOptions.path != '/auth/me';

  Future<Response<dynamic>?> _savedResponse(
      RequestOptions request, _SavedReadContext context) async {
    final String? accountId =
        context.accountId ?? await _accountIdFor(context.token);
    if (accountId == null || !await _isCurrentContext(context, accountId)) {
      return null;
    }
    final Map<String, dynamic>? snapshot =
        await _store.read(accountId, _resource(request));
    if (snapshot == null || _isStaleDaily(request.path, snapshot)) return null;
    // Recheck after I/O: teardown may have happened while storage was read.
    if (!await _isCurrentContext(context, accountId)) return null;
    return Response<dynamic>(
      requestOptions: request,
      statusCode: 200,
      data: snapshot['body'],
      extra: <String, dynamic>{cachedResponse: true},
    );
  }

  Future<bool> _isCurrentContext(
    _SavedReadContext context,
    String accountId,
  ) async =>
      accountId.isNotEmpty &&
      await _tokens.read() == context.token &&
      _store.generation == context.generation;

  Future<void> _saveAfterAccountIdResolves(
    Response<dynamic> response,
    _SavedReadContext context,
  ) async {
    if (!await _canSave(response, context)) return;
    final String? accountId = await _accountIdFor(context.token);
    final RequestOptions request = response.requestOptions;
    if (accountId == null || !await _canSave(response, context)) return;
    await _store.write(
      accountId,
      _resource(request),
      <String, dynamic>{
        'body': response.data,
        'day': _today(),
      },
      context.generation,
    );
  }

  Future<void> _saveResponse(
    Response<dynamic> response,
    _SavedReadContext context,
  ) async {
    if (!await _canSave(response, context)) return;
    final RequestOptions request = response.requestOptions;
    final String? accountId =
        _responseAccountId(request, context, response.data);
    if (accountId == null) {
      if (request.path != '/auth/me') {
        await _saveAfterAccountIdResolves(response, context);
      }
      return;
    }
    if (context.accountId != null && context.accountId != accountId) {
      return;
    }
    await _writeResponseSnapshot(response, context, accountId);
  }

  Future<void> _writeResponseSnapshot(
    Response<dynamic> response,
    _SavedReadContext context,
    String accountId,
  ) =>
      _store.write(
        accountId,
        _resource(response.requestOptions),
        <String, dynamic>{
          'body': response.data,
          'day': _today(),
        },
        context.generation,
      );

  static bool _isStaleDaily(String path, Map<String, dynamic> snapshot) =>
      _isDaily(path) && snapshot['day'] != _today();

  static bool _isDaily(String path) =>
      path == '/workouts/prescription' || path.startsWith('/nutrition');

  static String _today() => DateTime.now().toIso8601String().substring(0, 10);

  static String _resource(RequestOptions request) {
    final List<String> keys = request.queryParameters.keys.toList()..sort();
    final String query = Uri(queryParameters: <String, String>{
      for (final String key in keys) key: '${request.queryParameters[key]}',
    }).query;
    return query.isEmpty ? request.path : '${request.path}?$query';
  }
}

class _SavedReadContext {
  const _SavedReadContext(this.token, this.accountId, this.generation);
  final String token;
  final String? accountId;
  final int generation;
}
