import 'browser_key_value_store.dart';
import 'install_prompt_store.dart';

InstallPromptStore createInstallPromptStore(
  BrowserKeyValueStore _, {
  DateTime Function()? clock,
}) =>
    _StubInstallPromptStore();

class _StubInstallPromptStore implements InstallPromptStore {
  @override
  Future<InstallPromptEnvironment> readEnvironment() async =>
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: false,
        isStandalone: false,
        wasDismissed: false,
      );

  @override
  Future<void> rememberDismissal() async {}

  @override
  Future<String> promptInstall() async => 'unavailable';

  @override
  void listenForInstalled(void Function() onInstalled) {}

  @override
  void listenForInstallState(void Function() onInstallStateChanged) {}

  @override
  bool consumeInstalled() => false;
}
