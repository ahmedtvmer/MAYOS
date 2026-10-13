/// Permission entry points consumed by the post-onboarding explanation.
///
/// Kept separate from alert scheduling so onboarding and widget tests depend
/// only on permission state and requests.
abstract class RestAlertPermissionAccess {
  /// Whether this build has Android notification and alarm permissions.
  bool get isSupported;

  /// True only when both notification and exact-alarm access are available.
  Future<bool> areGranted();

  /// Requests notifications first, then exact-alarm access.
  Future<void> request();
}

class UnsupportedRestAlertPermissionAccess
    implements RestAlertPermissionAccess {
  const UnsupportedRestAlertPermissionAccess();

  @override
  bool get isSupported => false;

  @override
  Future<bool> areGranted() async => true;

  @override
  Future<void> request() async {}
}
