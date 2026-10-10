/// One browser-style fetch request used only for the assistant SSE stream.
///
/// Keeping this small transport seam outside the web implementation lets the
/// response parsing and cancellation behaviour run in VM tests.
typedef ChatStreamFetch = ChatStreamFetchRequest Function({
  required Uri url,
  required Map<String, String> headers,
  required String body,
});

abstract interface class ChatStreamFetchRequest {
  Future<ChatStreamFetchResponse> get response;

  /// Aborts both a pending fetch and an open response body.
  void abort();
}

/// Marks a failure from fetch itself or its response byte reader.
class ChatStreamTransportException implements Exception {
  const ChatStreamTransportException();
}

class ChatStreamFetchResponse {
  const ChatStreamFetchResponse({
    required this.statusCode,
    required this.body,
  });

  final int statusCode;
  final Stream<List<int>> body;
}
