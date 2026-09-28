import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';

void main() {
  test('a coach defaults to Coach mode, everyone else to Player mode', () {
    expect(resolveAppMode(isCoach: true), AppMode.coach);
    expect(resolveAppMode(isCoach: false), AppMode.player);
    expect(
        resolveAppMode(isCoach: true, stored: AppMode.coach), AppMode.coach);
    expect(
        resolveAppMode(isCoach: true, stored: AppMode.player), AppMode.player);
  });

  test('a stored Coach mode falls back to Player mode without the capability',
      () {
    expect(resolveAppMode(isCoach: false, stored: AppMode.coach),
        AppMode.player);
    expect(resolveAppMode(isCoach: false, stored: AppMode.player),
        AppMode.player);
  });

  test('the store keeps one choice per account ID', () async {
    final InMemoryAppModeStore store = InMemoryAppModeStore();
    final AppModeController controller = AppModeController(store);

    // No stored mode: the coach account opens in Coach mode.
    await controller.syncAccount(accountId: 'account-a', isCoach: true);
    expect(controller.state.mode, AppMode.coach);

    // Switching that account to Player mode persists under its own ID only.
    await controller.setMode(
      AppMode.player,
      accountId: 'account-a',
      isCoach: true,
    );
    expect(store.values, <String, AppMode>{'account-a': AppMode.player});
    expect(controller.state.mode, AppMode.player);

    // A second account on the same device keeps its own default.
    await controller.syncAccount(accountId: 'account-b', isCoach: true);
    expect(controller.state.mode, AppMode.coach);
    expect(store.values.containsKey('account-b'), isFalse);

    // Returning to the first account restores its stored choice.
    await controller.syncAccount(accountId: 'account-a', isCoach: true);
    expect(controller.state.mode, AppMode.player);
  });

  test('losing the coach capability resolves to Player mode', () async {
    final InMemoryAppModeStore store = InMemoryAppModeStore();
    final AppModeController controller = AppModeController(store);
    await controller.syncAccount(accountId: 'account-a', isCoach: true);
    expect(controller.state.mode, AppMode.coach);

    await controller.setMode(
      AppMode.coach,
      accountId: 'account-a',
      isCoach: true,
    );

    // The capability is revoked elsewhere and the session refreshes: the
    // stored Coach choice must not survive it.
    await controller.syncAccount(accountId: 'account-a', isCoach: false);
    expect(controller.state.mode, AppMode.player);

    // Signing out resets to the player default.
    await controller.syncAccount(accountId: null, isCoach: false);
    expect(controller.state.mode, AppMode.player);
  });

  test('a new account is not resolved until its stored choice is read',
      () async {
    final AppModeController controller = AppModeController(
      InMemoryAppModeStore(<String, AppMode>{
        'account-a': AppMode.player,
      }),
    );
    final Future<void> pending =
        controller.syncAccount(accountId: 'account-a', isCoach: true);
    // The state is scoped to the account but not ready: the router holds on
    // splash instead of flashing the coach default while the stored Player
    // choice is still being read (#119).
    expect(controller.state.accountId, 'account-a');
    expect(controller.state.ready, isFalse);
    expect(controller.state.isResolvedFor('account-a'), isFalse);
    await pending;
    expect(controller.state.ready, isTrue);
    expect(controller.state.mode, AppMode.player);
    expect(controller.state.isResolvedFor('account-a'), isTrue);
  });

  test('a choice made while the store read is pending beats that read',
      () async {
    final _GatedStore store = _GatedStore();
    final AppModeController controller = AppModeController(store);
    final Future<void> syncing =
        controller.syncAccount(accountId: 'account-a', isCoach: true);
    expect(controller.state.ready, isFalse);

    // The user picks Player mode before the slow read returns Coach mode.
    await controller.setMode(
      AppMode.player,
      accountId: 'account-a',
      isCoach: true,
    );
    expect(controller.state.mode, AppMode.player);
    expect(controller.state.ready, isTrue);

    // The stale read lands late and must not overwrite the newer choice.
    store.completeRead(AppMode.coach);
    await syncing;
    expect(controller.state.mode, AppMode.player);
    expect(controller.state.isResolvedFor('account-a'), isTrue);
    expect(store.values, <String, AppMode>{'account-a': AppMode.player});
  });

  test('state equality covers mode, readiness, and account', () {
    const AppModeState base = AppModeState(
      mode: AppMode.coach,
      ready: true,
      accountId: 'account-a',
    );
    expect(base, const AppModeState(
      mode: AppMode.coach,
      ready: true,
      accountId: 'account-a',
    ));
    expect(
      base == const AppModeState(
        mode: AppMode.player,
        ready: true,
        accountId: 'account-a',
      ),
      isFalse,
    );
    expect(
      base == const AppModeState(
        mode: AppMode.coach,
        ready: false,
        accountId: 'account-a',
      ),
      isFalse,
    );
    expect(
      base == const AppModeState(
        mode: AppMode.coach,
        ready: true,
        accountId: 'account-b',
      ),
      isFalse,
    );
  });
}

/// A store whose read never completes until the test says so, so a choice
/// made mid-read can be raced against the read's own result (#119).
class _GatedStore implements AppModeStore {
  final Completer<AppMode?> readGate = Completer<AppMode?>();
  final Map<String, AppMode> values = <String, AppMode>{};

  void completeRead(AppMode? mode) => readGate.complete(mode);

  @override
  Future<AppMode?> read(String accountId) => readGate.future;

  @override
  Future<void> write(String accountId, AppMode mode) async {
    values[accountId] = mode;
  }
}
