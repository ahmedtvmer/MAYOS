import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'theme_mode_store.dart';

/// Owns the selected appearance. Defaults to [ThemeMode.system] for new
/// installations and persists an explicit choice on the device.
class ThemeModeController extends StateNotifier<ThemeMode> {
  ThemeModeController(this._store) : super(ThemeMode.system);

  final ThemeModeStore _store;

  /// Loads the persisted choice once, off the first frame.
  Future<void> initialize() async {
    final ThemeMode? stored = await _store.read();
    if (stored != null && mounted) {
      state = stored;
    }
  }

  Future<void> setMode(ThemeMode mode) async {
    if (state == mode) {
      return;
    }
    state = mode;
    await _store.write(mode);
  }
}
