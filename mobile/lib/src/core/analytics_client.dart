import 'dart:async';

import 'package:posthog_flutter/posthog_flutter.dart';

import 'client_dimensions.dart';
import 'posthog_web_setup_stub.dart'
    if (dart.library.js_interop) 'posthog_web_setup_web.dart';

const String configuredPostHogClientKey =
    String.fromEnvironment('POSTHOG_CLIENT_KEY');
const String postHogEuHost = 'https://eu.i.posthog.com';

const Set<String> onboardingAnalyticsSteps = <String>{
  'disclosure',
  'gender',
  'proportions',
  'age',
  'height_cm',
  'weight_kg',
  'training_age_years',
  'current_goal',
  'long_term_goal',
  'weekly_frequency',
  'equipment_access',
  'injuries_or_limitations',
  'stress_and_sleep',
  'rep_preference',
  'review',
};

abstract interface class AnalyticsClient {
  void setEnabled(bool enabled);

  void identify(String accountId, {required String role});

  void onboardingStepViewed(String step);

  void workoutStarted();

  void workoutDraftDiscarded({required String workoutId});

  void reset();
}

class NoOpAnalyticsClient implements AnalyticsClient {
  const NoOpAnalyticsClient();

  @override
  void setEnabled(bool enabled) {}

  @override
  void identify(String accountId, {required String role}) {}

  @override
  void onboardingStepViewed(String step) {}

  @override
  void workoutStarted() {}

  @override
  void workoutDraftDiscarded({required String workoutId}) {}

  @override
  void reset() {}
}

bool analyticsEnabledForBuild({
  required bool isRelease,
  required String clientKey,
}) =>
    isRelease && clientKey.trim().isNotEmpty;

AnalyticsClient createAnalyticsClient({
  required bool isRelease,
  required String clientKey,
  required bool isWeb,
}) {
  if (!analyticsEnabledForBuild(isRelease: isRelease, clientKey: clientKey)) {
    return const NoOpAnalyticsClient();
  }
  return PostHogAnalyticsClient(
    clientKey.trim(),
    isWeb: isWeb,
    commonDimensions: analyticsCommonDimensions(isRelease: isRelease),
  );
}

class PostHogAnalyticsClient implements AnalyticsClient {
  PostHogAnalyticsClient(
    String clientKey, {
    required bool isWeb,
    required Map<String, String> commonDimensions,
  })  : _isWeb = isWeb,
        _commonDimensions = commonDimensions,
        _ready = _initialize(
          clientKey,
          isWeb: isWeb,
          commonDimensions: commonDimensions,
        ).then(
          (_) => true,
          onError: (Object _) => false,
        );

  final bool _isWeb;
  final Map<String, String> _commonDimensions;
  final Future<bool> _ready;
  Future<void> _permissionChange = Future<void>.value();
  bool _accountEnabled = true;
  final Set<String> _discardedWorkoutIds = <String>{};

  static Future<void> _initialize(
    String clientKey, {
    required bool isWeb,
    required Map<String, String> commonDimensions,
  }) async {
    if (isWeb) {
      await initializePostHogWeb(clientKey, commonDimensions)
          .timeout(const Duration(seconds: 8));
      return;
    }
    final PostHogConfig config = PostHogConfig(clientKey)
      ..host = postHogEuHost
      ..captureApplicationLifecycleEvents = false
      ..preloadFeatureFlags = false
      ..sendFeatureFlagEvents = false
      ..rageClickConfig.enabled = false
      ..sessionReplay = false
      ..surveys = false
      ..capturePushNotificationSubscriptions = false
      ..capturePushNotificationOpened = false
      ..errorTrackingConfig.captureFlutterErrors = false
      ..errorTrackingConfig.captureSilentFlutterErrors = false
      ..errorTrackingConfig.capturePlatformDispatcherErrors = false
      ..errorTrackingConfig.captureNativeExceptions = false
      ..errorTrackingConfig.captureNativeCrashes = false
      ..errorTrackingConfig.captureIsolateErrors = false;
    await Posthog().setup(config);
    for (final MapEntry<String, String> property in commonDimensions.entries) {
      await Posthog().register(property.key, property.value);
    }
    await Posthog().register('\$geoip_disable', true);
  }

  Future<void> _run(Future<void> Function() action) async {
    try {
      if (!await _ready) return;
      await _permissionChange;
      if (!_accountEnabled) return;
      await action();
    } on Object {
      // Analytics failures must not interrupt MAYOS account or onboarding work.
    }
  }

  @override
  void setEnabled(bool enabled) {
    _accountEnabled = enabled;
    _permissionChange = _permissionChange.then((_) async {
      if (!await _ready) return;
      if (enabled) {
        await Posthog().enable();
      } else {
        await Posthog().disable();
      }
    }).catchError((Object _) {
      // The local gate remains authoritative if the SDK call fails.
    });
  }

  Future<void> _identify(String accountId, String role) async {
    for (final MapEntry<String, String> property in _commonDimensions.entries) {
      await Posthog().register(property.key, property.value);
    }
    await Posthog().register('role', role);
    await Posthog().identify(userId: accountId);
  }

  @override
  void identify(String accountId, {required String role}) {
    _currentRole = role;
    unawaited(
      _run(
        () => _isWeb
            ? identifyPostHogWeb(accountId, role, _commonDimensions)
            : _identify(accountId, role),
      ),
    );
  }

  @override
  void onboardingStepViewed(String step) {
    if (!onboardingAnalyticsSteps.contains(step)) return;
    final String? role = _currentRole;
    if (role == null) return;
    final Map<String, Object> properties = <String, Object>{
      ..._commonDimensions,
      'role': role,
      'step': step,
    };
    unawaited(
      _run(
        () => _isWeb
            ? capturePostHogWeb(
                'onboarding_step_viewed',
                properties,
              )
            : Posthog().capture(
                eventName: 'onboarding_step_viewed',
                properties: properties,
              ),
      ),
    );
  }

  @override
  void workoutStarted() => _captureWorkoutEvent('workout_started');

  @override
  void workoutDraftDiscarded({required String workoutId}) {
    if (!_discardedWorkoutIds.add(workoutId)) return;
    _captureWorkoutEvent('workout_draft_discarded');
  }

  void _captureWorkoutEvent(String event) {
    final String? role = _currentRole;
    if (role == null) return;
    final Map<String, Object> properties = <String, Object>{
      ..._commonDimensions,
      'role': role,
    };
    unawaited(
      _run(
        () => _isWeb
            ? capturePostHogWeb(event, properties)
            : Posthog().capture(eventName: event, properties: properties),
      ),
    );
  }

  @override
  void reset() {
    _currentRole = null;
    _permissionChange = _permissionChange.then((_) async {
      if (!await _ready) return;
      await (_isWeb ? resetPostHogWeb() : Posthog().reset());
    }).catchError((Object _) {
      // Reset is best effort and must not affect sign-out.
    });
  }

  String? _currentRole;
}
