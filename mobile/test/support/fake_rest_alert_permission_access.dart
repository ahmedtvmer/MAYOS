import 'package:mayos_mobile/src/core/rest_alert_permission_access.dart';

/// Platform-free permission seam for the post-onboarding widget tests.
class FakeRestAlertPermissionAccess implements RestAlertPermissionAccess {
  FakeRestAlertPermissionAccess({
    this.granted = false,
    this.supported = true,
  });

  bool granted;
  final bool supported;
  int grantedChecks = 0;
  final List<String> requests = <String>[];

  @override
  bool get isSupported => supported;

  @override
  Future<bool> areGranted() async {
    grantedChecks += 1;
    return granted;
  }

  @override
  Future<void> request() async {
    requests
      ..add('notifications')
      ..add('exact_alarm');
  }
}
