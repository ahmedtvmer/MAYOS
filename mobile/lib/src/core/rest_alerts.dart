import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart'
    show HapticFeedback, SystemSound, SystemSoundType;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'rest_length.dart';
import 'secure_store.dart';

/// What the platform alert layer shows and schedules for ONE rest (#125).
@immutable
class RestAlertInfo {
  const RestAlertInfo({
    required this.endsAt,
    required this.totalSeconds,
    required this.exerciseName,
    required this.setNumber,
    this.lastLabel,
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

  /// The notification's second line: `Next: <exercise> · set N · last <prev>`.
  String get line =>
      'Next: $exerciseName · set $setNumber'
      '${lastLabel == null ? '' : ' · last $lastLabel'}';
}

/// The ONE seam between the rest timer and the platform's alert machinery —
/// notification, exact/inexact alarm, and the end-of-rest vibration + sound
/// (#125). The app side only ever talks to this; Android gets a real
/// implementation, tests get a fake, and web/other platforms get a no-op that
/// keeps the timer in-app only.
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

  /// The in-app end-of-rest vibration + short sound.
  Future<void> playEnd();
}

/// Web and other non-Android targets: no notifications, no alarms — the timer
/// stays in-app only (the issue's Web criteria are out of scope; this must
/// simply not crash, #125).
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
  Future<void> playEnd() async {}
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
  })  : _store = store ?? SecureStore(),
        _explain = explain,
        _requestNotificationsPermission = requestNotificationsPermission,
        _requestExactAlarmsPermission = requestExactAlarmsPermission,
        _canScheduleExact = canScheduleExactNotifications;

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
  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();

  bool _initialized = false;

  /// Runs [action] once the plugin is initialized, detached: an unavailable
  /// channel simply never answers, and the workout never waits on it.
  void _later(Future<void> Function() action) {
    Future<void>.microtask(() async {
      try {
        if (!_initialized) {
          await _initialize();
        }
        await action();
      } on Object {
        // Best-effort (#125).
      }
    });
  }

  Future<void> _initialize() async {
    _initialized = true;
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

  NotificationDetails _restDetails(RestAlertInfo info) => NotificationDetails(
        android: AndroidNotificationDetails(
          _restChannel,
          'Rest timer',
          channelDescription:
              'The running rest countdown while a workout is in progress.',
          importance: Importance.low,
          priority: Priority.low,
          ongoing: true,
          autoCancel: false,
          onlyAlertOnce: true,
          showWhen: true,
          when: info.endsAt.millisecondsSinceEpoch,
          usesChronometer: true,
          chronometerCountDown: true,
          visibility: NotificationVisibility.public,
          playSound: false,
          enableVibration: false,
          category: AndroidNotificationCategory.stopwatch,
        ),
      );

  @override
  Future<void> ensureReady() async {
    Future<void>.microtask(() async {
      try {
        final String asked = await _store.readString(_askedKey) ?? '';
        if (asked == '1') {
          return;
        }
      } on Object {
        // An unreadable flag falls through to a fresh ask (still only once
        // this install can tell).
      }
      try {
        _explain?.call(
            'Rest alerts need permission to reach you when your screen is off.');
      } on Object {
        // No messenger attached (a headless test): the system prompt still
        // carries its own wording.
      }
      try {
        if (!_initialized) {
          await _initialize();
        }
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
      try {
        await _store.writeString(_askedKey, '1');
      } on Object {
        // Best-effort, like the other protected-storage flags.
      }
    });
  }

  @override
  Future<void> showRest(RestAlertInfo info) async {
    final int ms = info.endsAt.difference(DateTime.now()).inMilliseconds;
    final int remaining = ms <= 0 ? 0 : (ms / 1000).ceil();
    _later(() => _plugin.show(
          id: _restId,
          title: 'MAYOS · Rest ${restMmSs(remaining)}',
          body: info.line,
          notificationDetails: _restDetails(info),
        ));
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
  Future<AndroidScheduleMode> endScheduleMode() async =>
      await _exactAllowed()
          ? AndroidScheduleMode.exactAllowWhileIdle
          : AndroidScheduleMode.inexactAllowWhileIdle;

  @override
  Future<void> scheduleEnd(RestAlertInfo info) async {
    _later(() async {
      final AndroidScheduleMode mode = await endScheduleMode();
      await _plugin.zonedSchedule(
        id: _endId,
        scheduledDate: tz.TZDateTime.from(info.endsAt, tz.local),
        title: 'Rest complete',
        body: 'Back to ${info.exerciseName}',
        notificationDetails: NotificationDetails(
          android: AndroidNotificationDetails(
            _endChannel,
            'Rest complete',
            channelDescription: 'The end-of-rest vibration and sound.',
            importance: Importance.high,
            priority: Priority.high,
            playSound: true,
            enableVibration: true,
            autoCancel: true,
            visibility: NotificationVisibility.public,
          ),
        ),
        androidScheduleMode: mode,
      );
    });
  }

  @override
  Future<void> cancelEnd() async {
    _later(() => _plugin.cancel(id: _endId));
  }

  @override
  Future<void> playEnd() async {
    Future<void>.microtask(() async {
      try {
        await HapticFeedback.vibrate();
      } on Object {
        // Best-effort.
      }
      try {
        await SystemSound.play(SystemSoundType.alert);
      } on Object {
        // Best-effort; the scheduled alarm carries the notification sound.
      }
    });
  }
}

/// The alert layer for this build: the real Android implementation on Android,
/// an in-app-only no-op everywhere else (web included, #125).
RestAlerts platformRestAlerts({void Function(String line)? explain}) {
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    return AndroidRestAlerts(explain: explain);
  }
  return const NoopRestAlerts();
}
