import 'chat_stream_fetch_types.dart';
import 'chat_stream_fetch_stub.dart'
    if (dart.library.js_interop) 'chat_stream_fetch_web.dart' as platform;

export 'chat_stream_fetch_types.dart';

/// Creates the web fetch implementation, or null on native platforms.
ChatStreamFetch? createChatStreamFetch() => platform.createChatStreamFetch();
