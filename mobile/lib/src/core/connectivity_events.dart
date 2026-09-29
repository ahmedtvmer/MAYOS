import 'dart:async';

import 'connectivity_events_stub.dart'
    if (dart.library.js_interop) 'connectivity_events_web.dart' as platform;

/// Emits the browser's current online state and subsequent online/offline
/// changes. Non-web platforms provide an empty stream.
Stream<bool> browserConnectivityEvents() =>
    platform.browserConnectivityEvents();
