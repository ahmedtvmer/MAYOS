import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// How the app reacts to coming back to the foreground and to failed
/// connections (#894).
///
/// The default keeps the historical behaviour: every resume refreshes and the
/// first transport failure shows the offline banner. `main.dart` installs
/// [ForegroundPolicy.release], so tests opt in to the release timings only
/// where they test them.
class ForegroundPolicy {
  const ForegroundPolicy({
    this.resumeRefreshAfter,
    this.offlineGrace = Duration.zero,
  });

  /// The release app's timings.
  static const ForegroundPolicy release = ForegroundPolicy(
    resumeRefreshAfter: Duration(seconds: 30),
    offlineGrace: Duration(seconds: 3),
  );

  /// Minimum time in the background before a resume refreshes data. `null`
  /// refreshes on every resume.
  final Duration? resumeRefreshAfter;

  /// How long a transport failure waits for a successful response before the
  /// app reports itself offline. A stale connection after resume fails once
  /// and then succeeds, which must not flash the offline banner.
  final Duration offlineGrace;
}

final Provider<ForegroundPolicy> foregroundPolicyProvider =
    Provider<ForegroundPolicy>((ref) => const ForegroundPolicy());

/// Decides whether a lifecycle change is a real return to the app.
///
/// Pulling down the notification shade, a permission prompt or the Google
/// account sheet only make the app `inactive`; they never refresh. With a
/// threshold, a resume refreshes only after the app was `hidden` or `paused`
/// for at least that long.
class ResumeGate {
  ResumeGate(this.threshold, {DateTime Function()? now})
      : _now = now ?? DateTime.now;

  final Duration? threshold;
  final DateTime Function() _now;
  DateTime? _backgroundedAt;

  /// Feeds one lifecycle change; returns true when data should refresh now.
  bool onLifecycle(AppLifecycleState state) {
    final Duration? minimum = threshold;
    if (minimum == null) return state == AppLifecycleState.resumed;
    switch (state) {
      case AppLifecycleState.hidden:
      case AppLifecycleState.paused:
        _backgroundedAt ??= _now();
        return false;
      case AppLifecycleState.resumed:
        final DateTime? since = _backgroundedAt;
        _backgroundedAt = null;
        return since != null && _now().difference(since) >= minimum;
      case AppLifecycleState.inactive:
      case AppLifecycleState.detached:
        return false;
    }
  }
}
