import 'package:flutter/services.dart';

const MethodChannel _connectivityChannel =
    MethodChannel('com.mayos/connectivity');

Future<bool> androidReportedOffline() async {
  try {
    final bool? connected = await _connectivityChannel
        .invokeMethod<bool>('hasInternetConnection');
    return connected == null ? false : !connected;
  } on MissingPluginException {
    return false;
  } on PlatformException {
    return false;
  }
}
