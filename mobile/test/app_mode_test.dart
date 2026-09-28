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

  test('a new account lands on its default, then the stored choice corrects it',
      () async {
    final AppModeController controller = AppModeController(
      InMemoryAppModeStore(<String, AppMode>{
        'account-a': AppMode.player,
      }),
    );
    final Future<void> pending =
        controller.syncAccount(accountId: 'account-a', isCoach: true);
    // The coach default applies before the keystore read returns, so the
    // shell never waits on it...
    expect(controller.state.mode, AppMode.coach);
    await pending;
    // ...and the stored Player choice then wins.
    expect(controller.state.mode, AppMode.player);
  });
}
