import 'package:flutter/material.dart';

import '../secure_store.dart';

/// Device-level persistence for the explicit appearance choice.
///
/// Reuses the app's existing keystore-backed [SecureStore] rather than adding a
/// second storage mechanism, and mirrors the store/fake pattern used by the
/// offline stores so tests can simulate a restart.
abstract class ThemeModeStore {
  Future<ThemeMode?> read();

  Future<void> write(ThemeMode mode);
}

class SecureThemeModeStore implements ThemeModeStore {
  SecureThemeModeStore({SecureStore? store}) : _store = store ?? SecureStore();

  final SecureStore _store;

  static const String _key = 'settings.theme_mode';

  @override
  Future<ThemeMode?> read() async {
    try {
      final String? raw = await _store.readString(_key);
      return _decode(raw);
    } on Object {
      // A keystore read failure must never crash startup; fall back to System.
      return null;
    }
  }

  @override
  Future<void> write(ThemeMode mode) async {
    try {
      await _store.writeString(_key, mode.name);
    } on Object {
      // Persistence is best-effort; the in-memory choice still applies.
    }
  }

  static ThemeMode? _decode(String? raw) {
    switch (raw) {
      case 'light':
        return ThemeMode.light;
      case 'dark':
        return ThemeMode.dark;
      case 'system':
        return ThemeMode.system;
      default:
        return null;
    }
  }
}

/// In-memory fake for tests. Sharing one instance across provider containers
/// simulates an app restart reading the same persisted choice.
class InMemoryThemeModeStore implements ThemeModeStore {
  InMemoryThemeModeStore([this._mode]);

  ThemeMode? _mode;

  @override
  Future<ThemeMode?> read() async => _mode;

  @override
  Future<void> write(ThemeMode mode) async => _mode = mode;
}
