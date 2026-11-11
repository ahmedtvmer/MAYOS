import 'dart:async';

import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;

import 'connectivity_events_stub.dart'
    if (dart.library.js_interop) 'connectivity_events_web.dart' as platform;
import 'connectivity_status_stub.dart'
    if (dart.library.io) 'connectivity_status_io.dart' as device;

/// Emits browser online/offline events or Android network validation changes.
/// Other platforms provide an empty stream; API signals and backoff still work.
Stream<bool> browserConnectivityEvents() =>
    platform.browserConnectivityEvents();

Future<bool> reportedOfflineStatus() async {
  if (kIsWeb) return platform.browserReportedOffline();
  if (defaultTargetPlatform == TargetPlatform.android) {
    return device.androidReportedOffline();
  }
  return false;
}
