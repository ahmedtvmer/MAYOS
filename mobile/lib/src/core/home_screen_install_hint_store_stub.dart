import 'browser_key_value_store.dart';
import 'home_screen_install_hint_store.dart';

HomeScreenInstallHintStore createHomeScreenInstallHintStore(
  BrowserKeyValueStore _,
) =>
    _StubHomeScreenInstallHintStore();

class _StubHomeScreenInstallHintStore implements HomeScreenInstallHintStore {
  @override
  Future<HomeScreenInstallHintEnvironment> readEnvironment() async =>
      const HomeScreenInstallHintEnvironment(
        isIosSafari: false,
        isStandalone: false,
        wasDismissed: false,
      );

  @override
  Future<void> rememberDismissal() async {}
}
