import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'chat_stream_fetch_types.dart';

ChatStreamFetch? createChatStreamFetch() => _browserFetch;

ChatStreamFetchRequest _browserFetch({
  required Uri url,
  required Map<String, String> headers,
  required String body,
}) =>
    _BrowserFetchRequest(url: url, headers: headers, body: body);

class _BrowserFetchRequest implements ChatStreamFetchRequest {
  _BrowserFetchRequest({
    required Uri url,
    required Map<String, String> headers,
    required String body,
  }) : _controller = web.AbortController() {
    final web.Headers requestHeaders = web.Headers();
    for (final MapEntry<String, String> header in headers.entries) {
      requestHeaders.append(header.key, header.value);
    }
    response = _fetch(url, requestHeaders, body);
  }

  final web.AbortController _controller;
  @override
  late final Future<ChatStreamFetchResponse> response;

  Future<ChatStreamFetchResponse> _fetch(
    Uri url,
    web.Headers headers,
    String body,
  ) async {
    try {
      final web.Response result = await web.window
          .fetch(
            url.toString().toJS,
            web.RequestInit(
              method: 'POST',
              headers: headers,
              body: body.toJS,
              signal: _controller.signal,
            ),
          )
          .toDart;
      final web.ReadableStream? responseBody = result.body;
      return ChatStreamFetchResponse(
        statusCode: result.status,
        body: responseBody == null
            ? const Stream<List<int>>.empty()
            : _read(responseBody),
      );
    } on Object {
      // JavaScript promises may reject with values outside Dart's Exception
      // hierarchy.
      throw const ChatStreamTransportException();
    }
  }

  Stream<List<int>> _read(web.ReadableStream stream) async* {
    web.ReadableStreamDefaultReader? reader;
    try {
      reader = stream.getReader() as web.ReadableStreamDefaultReader;
      while (true) {
        final web.ReadableStreamReadResult result = await reader.read().toDart;
        if (result.done) return;
        final JSUint8Array? chunk = result.value as JSUint8Array?;
        if (chunk != null) yield chunk.toDart;
      }
    } on Object {
      // Normalize reader failures to the same transport error as fetch failures.
      throw const ChatStreamTransportException();
    } finally {
      reader?.releaseLock();
    }
  }

  @override
  void abort() => _controller.abort();
}
