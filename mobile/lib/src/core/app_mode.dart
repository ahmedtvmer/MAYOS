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

/// The effective mode for the signed-in account, plus how far resolution has
/// got.
///
/// [ready] is false while the account's stored choice is still being read, and
/// [accountId] is the account the state belongs to (null while signed out).
/// Together they let the router hold on splash until this exact account's mode
/// is known, without depending on which Riverpod listener fires first (#119).
@immutable
class AppModeState {
  const AppModeState({
    required this.mode,
    required this.ready,
    required this.accountId,
  });

  final AppMode mode;

  /// Whether the stored choice for [accountId] has been read.
  final bool ready;

  /// The account this state resolves; null while signed out.
  final String? accountId;

  /// True when [mode] is resolved and belongs to [accountId].
  bool isResolvedFor(String? accountId) => ready && this.accountId == accountId;

  @override
  bool operator ==(Object other) =>
      other is AppModeState &&
      other.mode == mode &&
      other.ready == ready &&
      other.accountId == accountId;

  @override
  int get hashCode => Object.hash(mode, ready, accountId);
}

/// Owns the Player mode / Coach mode choice for the signed-in account.
class AppModeController extends StateNotifier<AppModeState> {
  AppModeController(this._store)
      : super(const AppModeState(
          mode: AppMode.player,
          ready: true,
          accountId: null,
        ));

  final AppModeStore _store;

  String? _accountId;
  AppMode? _stored;
  bool _isCoach = false;

  /// True while the stored choice for [_accountId] is still being read.
  bool _reading = false;

  /// Invalidates an in-flight store read. Bumped when the account changes and
  /// when [setMode] records a newer choice, so a late read never overwrites a
  /// decision made after it started (#119).
  int _epoch = 0;

  /// Re-resolves the mode whenever the session's account or capabilities change.
  ///
  /// A new account starts with `ready == false` and only becomes routable once
  /// its stored choice has been read, so the app opens in the stored mode
  /// rather than flashing the capability default (#119).
  Future<void> syncAccount({
    required String? accountId,
    required bool isCoach,
  }) async {
    _isCoach = isCoach;
    if (accountId == null) {
      _epoch++;
      _accountId = null;
      _stored = null;
      _reading = false;
      _apply();
      return;
    }
    if (accountId != _accountId) {
      _accountId = accountId;
      _stored = null;
      _reading = true;
      final int epoch = ++_epoch;
      _apply();
      AppMode? stored;
      try {
        stored = await _store.read(accountId);
      } on Object {
        stored = null;
      }
      if (!mounted || epoch != _epoch || _accountId != accountId) {
        // Superseded by a newer sync or by setMode; drop this read.
        return;
      }
      _reading = false;
      _stored = stored;
      _apply();
      return;
    }
    _apply();
  }

  /// Applies [mode] immediately, then persists it for this account.
  Future<void> setMode(
    AppMode mode, {
    required String? accountId,
    required bool isCoach,
  }) async {
    // A choice made now beats any store read still in flight (#119).
    _epoch++;
    _reading = false;
    _isCoach = isCoach;
    _stored = mode;
    if (accountId != null) {
      _accountId = accountId;
    }
    _apply();
    if (accountId != null) {
      await _store.write(accountId, mode);
    }
  }

  void _apply() {
    final AppModeState next = AppModeState(
      mode: resolveAppMode(isCoach: _isCoach, stored: _stored),
      ready: _accountId == null || !_reading,
      accountId: _accountId,
    );
    if (next != state) {
      state = next;
    }
  }
}
