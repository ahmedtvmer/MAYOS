/// Browser details used to decide whether the Home Screen hint is appropriate.
class HomeScreenInstallHintEnvironment {
  const HomeScreenInstallHintEnvironment({
    required this.isWeb,
    required this.isIosSafari,
    required this.isStandalone,
    required this.wasDismissed,
  });

  final bool isWeb;
  final bool isIosSafari;
  final bool isStandalone;
  final bool wasDismissed;

  bool get shouldShow => isWeb && isIosSafari && !isStandalone && !wasDismissed;
}

/// Reads the browser state and persists the player's dismissal choice.
abstract interface class HomeScreenInstallHintStore {
  Future<HomeScreenInstallHintEnvironment> readEnvironment();

  /// Returns whether the dismissal could be persisted.
  Future<bool> rememberDismissal();
}
