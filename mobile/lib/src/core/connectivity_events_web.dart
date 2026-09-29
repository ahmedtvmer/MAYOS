import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

Stream<bool> browserConnectivityEvents() {
  final StreamController<bool> events = StreamController<bool>();
  late final web.EventListener onlineListener;
  late final web.EventListener offlineListener;

  events.onListen = () {
    onlineListener = ((web.Event _) => events.add(true)).toJS;
    offlineListener = ((web.Event _) => events.add(false)).toJS;
    web.window.addEventListener('online', onlineListener);
    web.window.addEventListener('offline', offlineListener);
    events.add(web.window.navigator.onLine);
  };
  events.onCancel = () {
    web.window.removeEventListener('online', onlineListener);
    web.window.removeEventListener('offline', offlineListener);
  };

  return events.stream;
}
