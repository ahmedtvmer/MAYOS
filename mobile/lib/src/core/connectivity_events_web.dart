import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

Stream<bool> browserConnectivityEvents() {
  return Stream<bool>.multi((MultiStreamController<bool> events) {
    final web.EventListener onlineListener =
        ((web.Event _) => events.add(true)).toJS;
    final web.EventListener offlineListener =
        ((web.Event _) => events.add(false)).toJS;
    web.window.addEventListener('online', onlineListener);
    web.window.addEventListener('offline', offlineListener);
    events.onCancel = () {
      web.window.removeEventListener('online', onlineListener);
      web.window.removeEventListener('offline', offlineListener);
    };
    events.add(web.window.navigator.onLine);
  });
}
