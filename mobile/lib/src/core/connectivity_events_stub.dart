import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Kept behind the platform import so browser builds need no Android channel.
Stream<bool> browserConnectivityEvents() {
  if (defaultTargetPlatform != TargetPlatform.android) {
    return const Stream<bool>.empty();
  }
  const MethodChannel channel = MethodChannel('com.mayos/connectivity');
  late final StreamController<bool> events;

  Future<void> start() async {
    channel.setMethodCallHandler((MethodCall call) async {
      if (call.method == 'changed' && call.arguments is bool && events.hasListener) {
        events.add(call.arguments as bool);
      }
    });
    try {
      final bool? online = await channel.invokeMethod<bool>('startListening');
      if (online != null && events.hasListener) events.add(online);
    } on MissingPluginException {
      // Non-Android hosts and older binaries retain API/backoff recovery.
    } on PlatformException {
      // A missing system signal must not prevent session confirmation by API.
    }
  }

  Future<void> stop() async {
    channel.setMethodCallHandler(null);
    try {
      await channel.invokeMethod<void>('stopListening');
    } on MissingPluginException {
      // No platform subscription exists on the test host.
    } on PlatformException {
      // The Activity may already have torn down the subscription.
    }
  }

  events = StreamController<bool>(onListen: start, onCancel: stop);
  return events.stream;
}

bool browserReportedOffline() => false;
