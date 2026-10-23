/// Browser details and persisted dismissal state for the Home install prompt.
enum InstallPromptVariant {
  button('button'),
  iosHint('ios_hint'),
  none('none');

  const InstallPromptVariant(this.wireValue);
  final String wireValue;
}

class InstallPromptEnvironment {
  const InstallPromptEnvironment({
    required this.isIosShareBrowser,
    required this.hasInstallButton,
    required this.isStandalone,
    required this.wasDismissed,
    this.isInAppBrowser = false,
  });

  final bool isIosShareBrowser;
  final bool hasInstallButton;
  final bool isStandalone;
  final bool wasDismissed;
  final bool isInAppBrowser;

  InstallPromptVariant? get variant {
    if (isStandalone || wasDismissed || isInAppBrowser) return null;
    if (hasInstallButton) return InstallPromptVariant.button;
    if (isIosShareBrowser) return InstallPromptVariant.iosHint;
    return null;
  }
}

abstract interface class InstallPromptStore {
  Future<InstallPromptEnvironment> readEnvironment();

  Future<void> rememberDismissal();

  Future<String> promptInstall();

  void listenForInstalled(void Function() onInstalled);

  void listenForInstallState(void Function() onInstallStateChanged);

  bool consumeInstalled();
}
