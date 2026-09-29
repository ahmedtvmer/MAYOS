import 'package:mayos_mobile/src/core/rest_alerts.dart';

/// Records every call the app makes on the platform alert seam (#125), for
/// both the unit tests and the logger's widget tests. Nothing here touches a
/// platform channel.
class FakeRestAlerts implements RestAlerts {
  int ensureReadyCalls = 0;
  final List<RestAlertInfo> shown = <RestAlertInfo>[];
  final List<RestAlertInfo> scheduled = <RestAlertInfo>[];
  int removeCalls = 0;
  int cancelEndCalls = 0;
  int playEndCalls = 0;

  @override
  Future<void> ensureReady() async {
    ensureReadyCalls += 1;
  }

  @override
  Future<void> showRest(RestAlertInfo info) async {
    shown.add(info);
  }

  @override
  Future<void> removeRest() async {
    removeCalls += 1;
  }

  @override
  Future<void> scheduleEnd(RestAlertInfo info) async {
    scheduled.add(info);
  }

  @override
  Future<void> cancelEnd() async {
    cancelEndCalls += 1;
  }

  @override
  Future<void> playEnd() async {
    playEndCalls += 1;
  }
}
