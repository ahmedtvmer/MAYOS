import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

/// A recorded request, so tests can assert the wire contract the app sends.
class FakeRequest {
  FakeRequest({
    required this.method,
    required this.path,
    required this.body,
    required this.headers,
    required this.query,
  });

  final String method;
  final String path;
  final Map<String, dynamic> body;
  final Map<String, dynamic> headers;
  final Map<String, dynamic> query;
}

class FakeResponse {
  const FakeResponse(this.status, [this.body]);

  final int status;
  final Object? body;
}

typedef FakeHandler = FakeResponse Function(FakeRequest request);

/// A dio [HttpClientAdapter] backed by an in-memory router. Exercises the real
/// interceptors, transformers, and error mapping without a network or the
/// flutter_secure_storage plugin.
class FakeApiAdapter implements HttpClientAdapter {
  FakeApiAdapter(this._handler);

  final FakeHandler _handler;
  final List<FakeRequest> requests = <FakeRequest>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final String raw = await _read(requestStream);
    dynamic decoded;
    if (raw.isNotEmpty) {
      try {
        decoded = jsonDecode(raw);
      } on FormatException {
        decoded = null;
      }
    }
    final FakeRequest request = FakeRequest(
      method: options.method.toUpperCase(),
      path: options.path,
      body: decoded is Map<String, dynamic> ? decoded : <String, dynamic>{},
      headers: Map<String, dynamic>.from(options.headers),
      query: Map<String, dynamic>.from(options.queryParameters),
    );
    requests.add(request);

    final FakeResponse response = _handler(request);
    return ResponseBody.fromString(
      response.body == null ? '' : jsonEncode(response.body),
      response.status,
      headers: response.body == null
          ? null
          : <String, List<String>>{
              Headers.contentTypeHeader: <String>[Headers.jsonContentType],
            },
    );
  }

  Future<String> _read(Stream<Uint8List>? stream) async {
    if (stream == null) {
      return '';
    }
    final List<int> bytes = <int>[];
    await for (final Uint8List chunk in stream) {
      bytes.addAll(chunk);
    }
    return utf8.decode(bytes);
  }

  @override
  void close({bool force = false}) {}
}
