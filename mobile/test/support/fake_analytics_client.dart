import 'package:mayos_mobile/src/core/analytics_client.dart';

class FakeAnalyticsClient implements AnalyticsClient {
  final List<String> identifiedAccountIds = <String>[];
  final List<String> identifiedRoles = <String>[];
  final List<String> resetAccountIds = <String>[];
  final List<Map<String, Object>> events = <Map<String, Object>>[];
  final List<bool> enabledChanges = <bool>[];
  final Set<String> _discardedWorkoutIds = <String>{};

  String? _currentAccountId;
  bool enabled = true;

  @override
  void setEnabled(bool value) {
    enabled = value;
    enabledChanges.add(value);
  }

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
  void workoutStarted() => _recordWorkoutEvent('workout_started');

  @override
  void workoutDraftDiscarded({required String workoutId}) {
    if (!_discardedWorkoutIds.add(workoutId)) return;
    _recordWorkoutEvent('workout_draft_discarded');
  }

  void _recordWorkoutEvent(String event) {
    events.add(<String, Object>{
      'event': event,
      'properties': <String, Object>{},
    });
  }

  @override
  void reset() {
    if (_currentAccountId != null) resetAccountIds.add(_currentAccountId!);
    _currentAccountId = null;
  }
}
