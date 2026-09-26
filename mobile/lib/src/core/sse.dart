// Minimal Server-Sent Events (SSE) decoding for the chat stream.
//
// The service frames assistant turns as `text/event-stream`: `data: {json}`
// lines for tokens and the done frame, and `event: error` for a failed turn
// (`svc/routers/chat.py`). SseDecoder is deliberately transport-free so it
// can be unit-tested without a network.

/// One decoded SSE frame.
class SseEvent {
  const SseEvent({required this.event, required this.data});

  /// The `event:` field, defaulting to `message` when the server omits it
  /// (the SSE specification default).
  final String event;

  /// The concatenated `data:` field(s) of the frame.
  final String data;
}

/// Incremental SSE decoder that tolerates arbitrary chunk boundaries.
///
/// Feed it decoded UTF-8 text with [addChunk]; it buffers a partial frame and
/// returns only whole events, so a frame split across two network chunks is
/// never dropped. Comment lines (`:`) are ignored and frames are separated by
/// a blank line, per the SSE specification. A chunk boundary that splits a
/// `\r\n` pair is held back (a trailing `\r` is not normalised until the next
/// chunk arrives), so the pair never becomes a false blank line.
class SseDecoder {
  String _pending = '';

  /// A `\r` held back from the end of the previous chunk: the next chunk may
  /// begin with `\n`, and together they are one CRLF.
  String _heldCarriageReturn = '';

  /// Appends [chunk] and returns every complete event it completes.
  List<SseEvent> addChunk(String chunk) {
    // Reattach a held-back '\r' before normalising, so a CRLF split across the
    // boundary is collapsed to one newline rather than becoming a blank line.
    final String combined = _heldCarriageReturn + chunk;
    _heldCarriageReturn = '';
    final bool holdCarriageReturn = combined.endsWith('\r');
    final String chunkForParse = holdCarriageReturn
        ? combined.substring(0, combined.length - 1)
        : combined;
    _pending += chunkForParse.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
    if (holdCarriageReturn) {
      _heldCarriageReturn = '\r';
    }
    return _drain();
  }

  /// Signals end of input: normalises a held-back trailing `\r` and returns
  /// any final frame the server sent without a trailing blank line. Call once
  /// after the last [addChunk].
  List<SseEvent> close() {
    if (_heldCarriageReturn.isNotEmpty) {
      _pending += '\n';
      _heldCarriageReturn = '';
    }
    final List<SseEvent> drained = _drain();
    if (_pending.isEmpty) {
      return drained;
    }
    final SseEvent? event = _parseBlock(_pending.replaceAll('\r', '\n'));
    _pending = '';
    return <SseEvent>[...drained, if (event != null) event];
  }

  List<SseEvent> _drain() {
    final List<SseEvent> events = <SseEvent>[];
    int boundary;
    while ((boundary = _pending.indexOf('\n\n')) != -1) {
      final String block = _pending.substring(0, boundary);
      _pending = _pending.substring(boundary + 2);
      final SseEvent? event = _parseBlock(block);
      if (event != null) {
        events.add(event);
      }
    }
    return events;
  }

  static SseEvent? _parseBlock(String block) {
    String event = 'message';
    final StringBuffer data = StringBuffer();
    bool hasData = false;
    for (final String line in block.split('\n')) {
      if (line.isEmpty || line.startsWith(':')) {
        continue;
      }
      final int colon = line.indexOf(':');
      final String field = colon == -1 ? line : line.substring(0, colon);
      String value = colon == -1 ? '' : line.substring(colon + 1);
      if (value.startsWith(' ')) {
        value = value.substring(1);
      }
      if (field == 'event') {
        event = value;
      } else if (field == 'data') {
        if (hasData) {
          data.write('\n');
        }
        data.write(value);
        hasData = true;
      }
    }
    if (!hasData) {
      return null;
    }
    return SseEvent(event: event, data: data.toString());
  }
}
