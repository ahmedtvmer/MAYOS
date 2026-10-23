import 'dart:async';

import 'app_update_store.dart';

AppUpdateStore createAppUpdateStore() => _StubAppUpdateStore();

class _StubAppUpdateStore implements AppUpdateStore {
  @override
  Stream<bool> get updateWaiting => const Stream<bool>.empty();

  @override
  Future<void> applyUpdate() async {}
}
