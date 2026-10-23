import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app_update_store_stub.dart'
    if (dart.library.js_interop) 'app_update_store_web.dart' as platform;

abstract interface class AppUpdateStore {
  Stream<bool> get updateWaiting;
  Future<void> applyUpdate();
}

final Provider<AppUpdateStore> appUpdateStoreProvider =
    Provider<AppUpdateStore>((ref) => platform.createAppUpdateStore());
