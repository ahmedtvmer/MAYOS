import 'home_screen_install_hint_store.dart';

HomeScreenInstallHintStore createHomeScreenInstallHintStore() =>
    _StubHomeScreenInstallHintStore();

class _StubHomeScreenInstallHintStore implements HomeScreenInstallHintStore {
  @override
  Future<HomeScreenInstallHintEnvironment> readEnvironment() async =>
      const HomeScreenInstallHintEnvironment(
        isWeb: false,
        isIosSafari: false,
        isStandalone: false,
        wasDismissed: false,
      );

  @override
  Future<bool> rememberDismissal() async => false;
}
