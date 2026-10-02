import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show HapticFeedback;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'rest_alerts_web_stub.dart'
    if (dart.library.js_interop) 'rest_alerts_web.dart' as platform;
import 'rest_length.dart';
import 'secure_store.dart';
import 'display_language/workout_copy.dart';

/// What the platform alert layer shows and schedules for ONE rest (#125).
@immutable
class RestAlertInfo {
  const RestAlertInfo({
    required this.endsAt,
    required this.totalSeconds,
    required this.exerciseName,
    required this.setNumber,
    this.lastLabel,
    this.languageCode = 'en',
  });

  /// When the rest ends (any zone; the platform layer converts).
  final DateTime endsAt;

  /// The length this rest started with — what "Rest m:ss" shows.
  final int totalSeconds;

  final String exerciseName;

  /// The set row number that started the rest, 1-based as the keypad shows.
  final int setNumber;

  /// `100 × 5 @1` — the "last" part of the notification line, when known.
  final String? lastLabel;
  final String languageCode;

  /// The notification's second line: `Next: <exercise> · set N · last <prev>`.
  String get line => WorkoutCopy(languageCode).restNotificationLine(
        exerciseName: exerciseName,
        setNumber: setNumber,
        lastLabel: lastLabel,
      );
}

/// The ONE seam between the rest timer and the platform's alert machinery —
/// notification, exact/inexact alarm, and the end-of-rest vibration + sound
/// (#125). The app side only ever talks to this; Android gets a real
/// implementation, web gets foreground-only sound/vibration, and tests get a
/// fake.
///
/// Every method resolves promptly: the platform work is best-effort and
/// never awaited by the workout (a test host answers no platform channel at
/// all, and a workout must not wait on one).
abstract class RestAlerts {
  /// Called the first time a rest timer starts: shows a one-line explanation
  /// and asks for the notification + exact-alarm permissions, once per device
  /// install. Refusing never blocks the timer — the implementation falls back
  /// to an inexact while-idle alarm and never asks again (#125).
  Future<void> ensureReady();

  /// Shows, or updates, the ongoing countdown notification.
  Future<void> showRest(RestAlertInfo info);

  /// Removes the ongoing countdown notification.
  Future<void> removeRest();

  /// Schedules the end-of-rest vibration + sound as an alarm.
  Future<void> scheduleEnd(RestAlertInfo info);

  /// Cancels the scheduled end-of-rest alarm.
  Future<void> cancelEnd();

  /// The in-app end-of-rest alert: vibration plus a short sound, announced
  /// for [info] (the rest's "Back to <exercise>" line). Posted in the
  /// foreground too — it is the end signal a killed app never reaches (#125).
  Future<void> playEnd(RestAlertInfo info);
}

/// The no-op implementation for non-Android targets without foreground alerts.
class NoopRestAlerts implements RestAlerts {
  const NoopRestAlerts();

  @override
  Future<void> ensureReady() async {}

  @override
  Future<void> showRest(RestAlertInfo info) async {}

  @override
  Future<void> removeRest() async {}

  @override
  Future<void> scheduleEnd(RestAlertInfo info) async {}

  @override
  Future<void> cancelEnd() async {}

  @override
  Future<void> playEnd(RestAlertInfo info) async {}
}

/// Web has no scheduled notification or background alarm. The foreground
/// logger calls [playEnd] only while its page is visible (#180).
class WebRestAlerts implements RestAlerts {
  @override
  Future<void> ensureReady() => platform.prepareWebRestAudio();

  @override
  Future<void> showRest(RestAlertInfo info) async {}

  @override
  Future<void> removeRest() async {}

  @override
  Future<void> scheduleEnd(RestAlertInfo info) async {}

  @override
  Future<void> cancelEnd() async {}

  @override
  Future<void> playEnd(RestAlertInfo info) => platform.playWebRestEnd();
}

/// Unlocks web audio synchronously from the user gesture that starts a rest.
void unlockWebRestAudio() {
  if (kIsWeb) {
    platform.unlockWebRestAudio();
  }
}

/// The real Android implementation (#125): an ongoing, system-drawn countdown
/// chronometer notification visible on the lock screen, plus the end-of-rest
/// vibration and sound scheduled through `SCHEDULE_EXACT_ALARM` (falling back
/// to an inexact while-idle alarm when the user refused) — no foreground
/// service.
///
/// Every platform call is detached and error-swallowing: a plugin that is
/// unavailable (a test host answers no channel) must never block or break the
/// workout, and the in-app bar remains the source of truth while the app is
/// open.
class AndroidRestAlerts implements RestAlerts {
  AndroidRestAlerts({
    SecureStore? store,
    void Function(String line)? explain,
    Future<bool?> Function()? requestNotificationsPermission,
    Future<bool?> Function()? requestExactAlarmsPermission,
    Future<bool?> Function()? canScheduleExactNotifications,
    Future<void> Function()? initialize,
    DateTime Function()? now,
    String Function()? displayLanguage,
  })  : _store = store ?? SecureStore(),
        _explain = explain,
        _requestNotificationsPermission = requestNotificationsPermission,
        _requestExactAlarmsPermission = requestExactAlarmsPermission,
        _canScheduleExact = canScheduleExactNotifications,
        _initializePlugin = initialize,
        _now = now ?? DateTime.now,
        _displayLanguage = displayLanguage ?? (() => 'en');

  /// The ongoing countdown notification and the one-shot end alert, kept as
  /// two ids so ending a rest cancels only the right pair.
  static const int _restId = 525101;
  static const int _endId = 525102;

  static const String _restChannel = 'mayos_rest_timer';
  static const String _endChannel = 'mayos_rest_end';

  /// The device-wide "already asked once" flag: set whether the player
  /// granted or refused, so the prompts never appear twice (#125).
  static const String _askedKey = 'rest_alerts.asked';

  final SecureStore _store;
  final void Function(String line)? _explain;

  /// Injectable permission calls, so the ask-once / refuse-once policy can be
  /// tested without a platform (#125). Null means "ask the plugin".
  final Future<bool?> Function()? _requestNotificationsPermission;
  final Future<bool?> Function()? _requestExactAlarmsPermission;
  final Future<bool?> Function()? _canScheduleExact;

  /// Injectable plugin/timezone initialization, so the "everything waits for
  /// ONE init" policy can be tested without a platform (#125). Null means
  /// "run the real initialization".
  final Future<void> Function()? _initializePlugin;
  final DateTime Function() _now;
  final String Function() _displayLanguage;
  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();

  /// The memoized initialization, created on first use and shared by every
  /// entry point: a second call during the first rest awaits the same future
  /// instead of racing ahead of an init that has not finished yet (#125).
  Future<void>? _init;

  Future<void> _ensureInitialized() => _init ??= _initialize();

  /// Runs [action] once the plugin is initialized, detached: an unavailable
  /// channel simply never answers, and the workout never waits on it.
  void _later(Future<void> Function() action) {
    Future<void>.microtask(() async {
      try {
        await _ensureInitialized();
        await action();
      } on Object {
        // Best-effort (#125).
      }
    });
  }

  Future<void> _initialize() async {
    final Future<void> Function()? injected = _initializePlugin;
    if (injected != null) {
      await injected();
      return;
    }
    try {
      tzdata.initializeTimeZones();
    } on Object {
      // A missing timezone database only costs the local-zone lookup below.
    }
    try {
      final TimezoneInfo info = await FlutterTimezone.getLocalTimezone();
      final String identifier = info.identifier.trim();
      if (identifier.isNotEmpty) {
        tz.setLocalLocation(tz.getLocation(identifier));
      }
    } on Object {
      // Fall back to the default location; the alarm still fires at the same
      // instant.
    }
    try {
      await _plugin.initialize(
        settings: const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        ),
      );
    } on Object {
      // Unavailable plugin: every caller degrades to a no-op.
    }
  }

  AndroidFlutterLocalNotificationsPlugin? get _android =>
      _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();

  NotificationDetails _restDetails(RestAlertInfo info, int timeoutAfterMs) =>
      NotificationDetails(
        android: AndroidNotificationDetails(
          _restChannel,
          WorkoutCopy(_displayLanguage()).restTimerChannel,
          channelDescription:
              WorkoutCopy(_displayLanguage()).restTimerChannelDescription,
          importance: Importance.low,
          priority: Priority.low,
          ongoing: true,
          autoCancel: false,
          onlyAlertOnce: true,
          showWhen: true,
          when: info.endsAt.millisecondsSinceEpoch,
          usesChronometer: true,
          chronometerCountDown: true,
          // The countdown never outlives the rest: even if the app is killed,
          // the system drops it at the rest's end instead of ticking into
          // negative time. Re-posted by every ±15 with the new remainder.
          timeoutAfter: timeoutAfterMs > 0 ? timeoutAfterMs : null,
          visibility: NotificationVisibility.public,
          playSound: false,
          enableVibration: false,
          category: AndroidNotificationCategory.stopwatch,
        ),
      );

  /// The end-of-rest alert: the vibration + default sound channel, shown by
  /// the scheduled alarm and by the foreground [playEnd] with the same id, so
  /// at most one "Rest complete" is ever posted for a rest (#125).
  NotificationDetails get _endDetails => NotificationDetails(
        android: AndroidNotificationDetails(
          _endChannel,
          WorkoutCopy(_displayLanguage()).restCompleteNotification,
          channelDescription:
              WorkoutCopy(_displayLanguage()).restEndChannelDescription,
          importance: Importance.high,
          priority: Priority.high,
          playSound: true,
          enableVibration: true,
          autoCancel: true,
          visibility: NotificationVisibility.public,
        ),
      );

  @override
  Future<void> ensureReady() {
    // One in-flight ask: two quick ticks share it instead of racing the
    // "already asked" flag (#125). The prompts themselves stay detached, so
    // the workout never waits on a system dialog.
    _ready ??= _askOnce();
    return Future<void>.value();
  }

  /// The in-flight (and then completed) ask of [ensureReady].
  Future<void>? _ready;

  Future<void> _askOnce() async {
    try {
      final String asked = await _store.readString(_askedKey) ?? '';
      if (asked == '1') {
        return;
      }
    } on Object {
      // An unreadable flag falls through to a fresh ask (still only once
      // this install can tell).
    }
    // Written *before* prompting: a second call landing while the dialogs are
    // open already sees the flag, and an interrupted ask is never repeated
    // (#125).
    try {
      await _store.writeString(_askedKey, '1');
    } on Object {
      // Best-effort, like the other protected-storage flags.
    }
    try {
      _explain
          ?.call(WorkoutCopy(_displayLanguage()).restNotificationPermission);
    } on Object {
      // No messenger attached (a headless test): the system prompt still
      // carries its own wording.
    }
    try {
      await _ensureInitialized();
      final Future<bool?> Function()? notifications =
          _requestNotificationsPermission;
      if (notifications != null) {
        await notifications();
      } else {
        await _android?.requestNotificationsPermission();
      }
      final Future<bool?> Function()? exact = _requestExactAlarmsPermission;
      if (exact != null) {
        await exact();
      } else {
        await _android?.requestExactAlarmsPermission();
      }
    } on Object {
      // A refused or unavailable prompt is just "not granted"; scheduling
      // then falls back to an inexact while-idle alarm.
    }
  }

  @override
  Future<void> showRest(RestAlertInfo info) {
    final int ms = info.endsAt.difference(_now()).inMilliseconds;
    _later(
      () => _plugin.show(
        id: _restId,
        title: WorkoutCopy(_displayLanguage()).restNotificationTitle(
          restMmSs(ms <= 0 ? 0 : (ms / 1000).ceil()),
        ),
        body: info.line,
        notificationDetails: _restDetails(info, ms),
      ),
    );
    return Future<void>.value();
  }

  @override
  Future<void> removeRest() async {
    _later(() => _plugin.cancel(id: _restId));
  }

  Future<bool> _exactAllowed() async {
    final Future<bool?> Function()? injected = _canScheduleExact;
    if (injected != null) {
      return await injected() ?? false;
    }
    return await _android?.canScheduleExactNotifications() ?? false;
  }

  /// The mode the end alarm is scheduled with: exact-while-idle while the
  /// `SCHEDULE_EXACT_ALARM` permission was granted, inexact-while-idle once
  /// it was refused (#125). Read live at every (re)schedule, so the ask
  /// happens only in [ensureReady] and a refusal is never re-asked — just
  /// downgraded. Exposed for the tests; [scheduleEnd] uses it.
  Future<AndroidScheduleMode> endScheduleMode() async => await _exactAllowed()
      ? AndroidScheduleMode.exactAllowWhileIdle
      : AndroidScheduleMode.inexactAllowWhileIdle;

  @override
  Future<void> scheduleEnd(RestAlertInfo info) async {
    _later(() async {
      final AndroidScheduleMode mode = await endScheduleMode();
      await _plugin.zonedSchedule(
        id: _endId,
        scheduledDate: tz.TZDateTime.from(info.endsAt, tz.local),
        title: WorkoutCopy(info.languageCode).restCompleteNotification,
        body:
            WorkoutCopy(info.languageCode).returnToExercise(info.exerciseName),
        notificationDetails: _endDetails,
        androidScheduleMode: mode,
      );
    });
  }

  @override
  Future<void> cancelEnd() async {
    _later(() => _plugin.cancel(id: _endId));
  }

  @override
  Future<void> playEnd(RestAlertInfo info) {
    _later(() async {
      try {
        await HapticFeedback.vibrate();
      } on Object {
        // Best-effort (#125).
      }
      // The foreground end needs a sound Android actually plays:
      // `SystemSound.alert` is a no-op there, so the end notification is
      // posted in the foreground too — same id as the scheduled alarm's, so
      // there is never a second one, and its default sound + vibration are
      // the alert (#125).
      await _plugin.show(
        id: _endId,
        title: WorkoutCopy(info.languageCode).restCompleteNotification,
        body:
            WorkoutCopy(info.languageCode).returnToExercise(info.exerciseName),
        notificationDetails: _endDetails,
      );
    });
    return Future<void>.value();
  }
}

/// The alert layer for this build: Android notifications, in-page web alerts,
/// and a no-op on other targets.
RestAlerts platformRestAlerts({
  void Function(String line)? explain,
  DateTime Function()? now,
  String Function()? displayLanguage,
}) {
  if (kIsWeb) {
    return WebRestAlerts();
  }
  if (defaultTargetPlatform == TargetPlatform.android) {
    return AndroidRestAlerts(
      explain: explain,
      now: now,
      displayLanguage: displayLanguage,
    );
  }
  return const NoopRestAlerts();
}
