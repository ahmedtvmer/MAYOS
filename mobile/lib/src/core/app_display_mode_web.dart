import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:web/web.dart' as web;

String currentAppDisplayMode() {
  final JSBoolean? iosStandalone = (web.window.navigator as JSObject)
      .getProperty<JSBoolean?>('standalone'.toJS);
  final bool isStandalone = (iosStandalone?.toDart ?? false) ||
      web.window.matchMedia('(display-mode: standalone)').matches;
  return isStandalone ? 'standalone' : 'browser';
}
