import 'dart:async';

import 'connectivity_events_stub.dart'
    if (dart.library.js_interop) 'connectivity_events_web.dart' as platform;

/// Emits browser online/offline events or Android network validation changes.
/// Other platforms provide an empty stream; API signals and backoff still work.
Stream<bool> browserConnectivityEvents() =>
    platform.browserConnectivityEvents();
