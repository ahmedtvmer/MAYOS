import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

const String configuredSentryDsn = String.fromEnvironment('SENTRY_DSN');
const String configuredSentryRelease = String.fromEnvironment(
  'SENTRY_RELEASE',
  defaultValue: 'unknown',
);
const String configuredSentryEnvironment = String.fromEnvironment(
  'SENTRY_ENVIRONMENT',
  defaultValue: 'production',
);

bool _reportingInitialized = false;
@visibleForTesting
bool get errorReportingInitialized => _reportingInitialized;

class SentryScreenObserver extends NavigatorObserver {
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _record(route);
    super.didPush(route, previousRoute);
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    if (newRoute != null) _record(newRoute);
    super.didReplace(newRoute: newRoute, oldRoute: oldRoute);
  }

  void _record(Route<dynamic> route) {
    final String? rawName = route.settings.name;
    if (rawName == null || rawName.isEmpty || !_reportingInitialized) return;
    final String name = rawName.startsWith('/')
        ? sentryRouteTemplate(rawName)
        : rawName;
    Sentry.addBreadcrumb(Breadcrumb(
      category: 'navigation',
      type: 'navigation',
      data: <String, dynamic>{'screen': name},
    ));
  }
}

String sentryRouteTemplate(String path) {
  final String safePath = Uri.tryParse(path)?.path ?? path;
  final List<String> parts = safePath
      .split('/')
      .where((String part) => part.isNotEmpty)
      .toList();
  const Set<String> staticSegments = <String>{
    'auth', 'me', 'login', 'logout', 'google', 'refresh', 'register',
    'player', 'coach', 'players', 'profile', 'program', 'programs',
    'workouts', 'history', 'alerts', 'check-ins', 'requests', 'nutrition',
    'foods', 'exercises', 'search', 'replace', 'schedule', 'settings',
    'consent', 'account', 'email', 'recovery', 'password', 'tour',
    'whats-new', 'assistant', 'chat', 'roster', 'invites', 'assignments',
    'checkpoint', 'checkpoints', 'water', 'weight', 'measurements',
    'versions', 'draft', 'publish', 'acknowledge', 'resolve', 'latest',
    'summary', 'catalog', 'injuries', 'clearances', 'client',
    'connection-failures', 'dashboard', 'training-status', 'sessions',
    'volume', 'personal-records', 'food-log', 'quick-add',
    'personal-foods', 'setup', 'activity', 'adherence', 'goal', 'goal-offer',
    'dismiss', 'pauses', 'intake', 'disclosure', 'design-offer', 'accept',
    'generate', 'notices', 'read', 'program-requests', 'templates',
    'capabilities', 'import', 'preview', 'create', 'update', 'delete', 'clear',
    'end', 'revoke', 'version-policy', 'policy',
  };
  return '/${parts.map((String part) =>
      staticSegments.contains(part) ? part : ':id').join('/')}';
}

Future<void> initializeErrorReporting({
  @visibleForTesting String? testDsn,
  @visibleForTesting void Function(SentryFlutterOptions options)? configure,
}) async {
  final String resolvedDsn = (testDsn ?? configuredSentryDsn).trim();
  if (resolvedDsn.isEmpty) {
    _reportingInitialized = false;
    return;
  }
  await SentryFlutter.init((SentryFlutterOptions options) {
    options
      ..dsn = resolvedDsn
      ..release = configuredSentryRelease
      ..environment = configuredSentryEnvironment
      ..sendDefaultPii = false
      ..attachScreenshot = false
      ..attachViewHierarchy = false
      ..enableUserInteractionBreadcrumbs = false
      ..enableAutoSessionTracking = false
      ..tracesSampleRate = 0
      ..beforeBreadcrumb = filterSentryBreadcrumb
      ..beforeSend = sanitizeSentryEvent;
    options.replay
      ..sessionSampleRate = 0
      ..onErrorSampleRate = 0;
    configure?.call(options);
  });
  _reportingInitialized = true;
}

Breadcrumb? filterSentryBreadcrumb(Breadcrumb? breadcrumb, Hint _) {
  if (breadcrumb == null) return null;
  final String? category = breadcrumb.category;
  if (category == 'navigation') {
    final String? rawScreen = breadcrumb.data?['to'] as String? ??
        breadcrumb.data?['screen'] as String?;
    if (rawScreen == null) return null;
    final String screen = rawScreen.startsWith('/')
        ? sentryRouteTemplate(rawScreen)
        : rawScreen;
    return Breadcrumb(
      category: 'navigation',
      type: 'navigation',
      data: <String, dynamic>{'screen': screen},
    );
  }
  if (category == 'http' || category == 'dio') {
    final Map<String, dynamic>? data = breadcrumb.data;
    if (data == null) return null;
    final String? method = data['http.request.method'] as String? ??
        data['method'] as String?;
    final String? route = data['route'] as String?;
    final Object? status = data['http.response.status_code'] ??
        data['status_code'] ??
        data['status'];
    if (method == null || route == null || status is! int) return null;
    return Breadcrumb(
      category: 'http',
      type: 'http',
      data: <String, dynamic>{'method': method, 'route': route, 'status': status},
    );
  }
  return null;
}

SentryEvent? sanitizeSentryEvent(SentryEvent event, Hint _) {
  final String? anonymousId = event.user?.id;
  event.user = SentryUser(
    id: anonymousId == null || anonymousId.isEmpty ? null : anonymousId,
    ipAddress: '0.0.0.0',
  );
  return event;
}

Future<void> setSentryAnonymousAccountId(String? anonymousId) async {
  if (!_reportingInitialized) return;
  await Sentry.configureScope((Scope scope) {
    scope.setUser(anonymousId == null || anonymousId.isEmpty
        ? null
        : SentryUser(id: anonymousId));
  });
}

@visibleForTesting
Future<void> captureSentryTestError(Object error) async {
  await Sentry.captureException(error);
}
