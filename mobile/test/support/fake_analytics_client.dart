import 'package:mayos_mobile/src/core/analytics_client.dart';

class FakeAnalyticsClient implements AnalyticsClient {
  final List<String> identifiedAccountIds = <String>[];
  final List<String> identifiedRoles = <String>[];
  final List<String> resetAccountIds = <String>[];
  final List<Map<String, Object>> events = <Map<String, Object>>[];

  String? _currentAccountId;

  @override
  void identify(String accountId, {required String role}) {
    _currentAccountId = accountId;
    identifiedAccountIds.add(accountId);
    identifiedRoles.add(role);
  }

  @override
  void onboardingStepViewed(String step) {
    if (!onboardingAnalyticsSteps.contains(step)) return;
    events.add(<String, Object>{
      'event': 'onboarding_step_viewed',
      'properties': <String, Object>{'step': step},
    });
  }

  @override
  void reset() {
    if (_currentAccountId != null) resetAccountIds.add(_currentAccountId!);
    _currentAccountId = null;
  }
}
