import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'secure_store.dart';

/// The two app surfaces of one account (CONTEXT.md): training for oneself, or
/// coaching assigned players. Neither is a separate account.
enum AppMode { player, coach }

/// The effective mode for an account.
///
/// With no stored choice a coach opens in Coach mode and everyone else in
/// Player mode. A stored Coach choice on an account that no longer holds the
/// coach capability falls back to Player mode.
AppMode resolveAppMode({required bool isCoach, AppMode? stored}) {
  if (!isCoach || stored == AppMode.player) {
    return AppMode.player;
  }
  return AppMode.coach;
}

/// Device persistence for the last mode used, keyed by account ID so two
/// accounts sharing a device never inherit each other's mode.
abstract class AppModeStore {
  Future<AppMode?> read(String accountId);

  Future<void> write(String accountId, AppMode mode);
}

/// Reuses the app's keystore-backed [SecureStore]; a keystore failure must
/// never crash startup, so a read falls back to the capability default.
class SecureAppModeStore implements AppModeStore {
  SecureAppModeStore({SecureStore? store}) : _store = store ?? SecureStore();

  final SecureStore _store;

  static const String _prefix = 'mode.account.';

  @override
  Future<AppMode?> read(String accountId) async {
    try {
      final String? raw = await _store.readString('$_prefix$accountId');
      switch (raw) {
        case 'coach':
          return AppMode.coach;
        case 'player':
          return AppMode.player;
        default:
          return null;
      }
    } on Object {
      return null;
    }
  }

  @override
  Future<void> write(String accountId, AppMode mode) async {
    try {
      await _store.writeString('$_prefix$accountId', mode.name);
    } on Object {
      // Persistence is best-effort; the in-memory mode still applies.
    }
  }
}

/// In-memory fake for tests. Sharing one instance across provider containers
/// simulates a restart reading the same per-account choice.
class InMemoryAppModeStore implements AppModeStore {
  InMemoryAppModeStore([Map<String, AppMode>? values])
      : values = values ?? <String, AppMode>{};

  final Map<String, AppMode> values;

  @override
  Future<AppMode?> read(String accountId) async => values[accountId];

  @override
  Future<void> write(String accountId, AppMode mode) async {
    values[accountId] = mode;
  }
}

/// The current effective mode for the signed-in account.
@immutable
class AppModeState {
  const AppModeState({required this.mode});

  final AppMode mode;
}

/// Owns the Player mode / Coach mode choice for the signed-in account.
class AppModeController extends StateNotifier<AppModeState> {
  AppModeController(this._store)
      : super(const AppModeState(mode: AppMode.player));

  final AppModeStore _store;

  String? _accountId;
  AppMode? _stored;

  /// Re-resolves the mode whenever the session's account or capabilities change.
  ///
  /// A new account lands on its capability default at once so the shell never
  /// waits on the keystore; the stored choice corrects it as soon as the read
  /// returns.
  Future<void> syncAccount({
    required String? accountId,
    required bool isCoach,
  }) async {
    if (accountId == null) {
      _accountId = null;
      _stored = null;
      state = const AppModeState(mode: AppMode.player);
      return;
    }
    if (accountId != _accountId) {
      _accountId = accountId;
      state =
          AppModeState(mode: resolveAppMode(isCoach: isCoach, stored: null));
      AppMode? stored;
      try {
        stored = await _store.read(accountId);
      } on Object {
        stored = null;
      }
      if (!mounted || _accountId != accountId) {
        return;
      }
      _stored = stored;
      _apply(isCoach: isCoach);
      return;
    }
    _apply(isCoach: isCoach);
  }

  void _apply({required bool isCoach}) {
    final AppMode resolved =
        resolveAppMode(isCoach: isCoach, stored: _stored);
    if (state.mode != resolved) {
      state = AppModeState(mode: resolved);
    }
  }

  /// Applies [mode] immediately, then persists it for this account.
  Future<void> setMode(
    AppMode mode, {
    required String? accountId,
    required bool isCoach,
  }) async {
    _stored = mode;
    state = AppModeState(
      mode: resolveAppMode(isCoach: isCoach, stored: mode),
    );
    if (accountId != null) {
      await _store.write(accountId, mode);
    }
  }
}
