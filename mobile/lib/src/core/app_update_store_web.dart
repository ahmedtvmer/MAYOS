import 'dart:async';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:web/web.dart' as web;

import 'app_update_store.dart';

AppUpdateStore createAppUpdateStore() => _WebAppUpdateStore();

class _WebAppUpdateStore implements AppUpdateStore {
  _WebAppUpdateStore() {
    web.window.addEventListener('myos-update-waiting', ((web.Event _) {
      _events.add(_waiting);
    }).toJS);
  }

  final StreamController<bool> _events = StreamController<bool>.broadcast();

  bool get _waiting =>
      ((web.window as JSObject).getProperty<JSBoolean?>(
        'MYOS_UPDATE_WAITING'.toJS,
      )?.toDart ?? false);

  @override
  Stream<bool> get updateWaiting => Stream<bool>.multi((controller) {
        controller.add(_waiting);
        final StreamSubscription<bool> subscription =
            _events.stream.listen(controller.add);
        controller.onCancel = subscription.cancel;
      });

  @override
  Future<void> applyUpdate() async {
    final JSFunction? apply = (web.window as JSObject)
        .getProperty<JSFunction?>('MYOS_APPLY_UPDATE'.toJS);
    apply?.callAsFunction();
  }
}
