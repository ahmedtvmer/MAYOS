import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// One workout reminder the server planned for this device (#840).
@immutable
class PlannedReminder {
  const PlannedReminder({
    required this.date,
    required this.at,
    required this.title,
    required this.body,
    required this.url,
  });

  factory PlannedReminder.fromJson(Map<String, dynamic> json) =>
      PlannedReminder(
        date: json['date'] as String,
        at: DateTime.parse(json['at'] as String),
        title: json['title'] as String,
        body: json['body'] as String,
        url: json['url'] as String,
      );

  /// The Player-local training day, `yyyy-mm-dd`.
  final String date;

  /// When the reminder fires, as an absolute instant.
  final DateTime at;
  final String title;
  final String body;
  final String url;
}

/// Schedules workout reminders as local notifications, so they fire offline
/// (#840). Android gets the real implementation; elsewhere it is a no-op.
abstract class LocalReminderScheduler {
  bool get isSupported;

  /// Asks for the Android 13+ notification permission. True when granted.
  Future<bool> requestPermission();

  /// Replaces every scheduled workout reminder with [reminders].
  Future<void> replaceAll(List<PlannedReminder> reminders);
}

class NoopLocalReminderScheduler implements LocalReminderScheduler {
  const NoopLocalReminderScheduler();

  @override
  bool get isSupported => false;

  @override
  Future<bool> requestPermission() async => false;

  @override
  Future<void> replaceAll(List<PlannedReminder> reminders) async {}
}

/// The reminders still worth scheduling: future ones, at most [maxReminders].
List<PlannedReminder> remindersToSchedule(
  List<PlannedReminder> plan, {
  required DateTime now,
  int maxReminders = AndroidLocalReminderScheduler.maxReminders,
}) =>
    plan.where((PlannedReminder item) => item.at.isAfter(now)).take(maxReminders).toList();

/// Android: inexact, allow-while-idle notifications. Exact alarms stay for the
/// rest timer only (#840). The plugin's boot receiver restores them after a
/// reboot (`RECEIVE_BOOT_COMPLETED`).
class AndroidLocalReminderScheduler implements LocalReminderScheduler {
  AndroidLocalReminderScheduler({
    String Function()? channelName,
    String Function()? channelDescription,
  })  : _channelName = channelName ?? (() => 'Workout reminders'),
        _channelDescription =
            channelDescription ?? (() => 'Reminders on your training days');

  /// One id per planned day; the server plans at most 14.
  static const int maxReminders = 14;
  static const int _firstId = 526000;
  static const String _channel = 'mayos_workout_reminders';

  final String Function() _channelName;
  final String Function() _channelDescription;
  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  Future<void>? _init;

  Future<void> _ensureInitialized() => _init ??= () async {
        try {
          tzdata.initializeTimeZones();
        } on Object {
          // Scheduling below uses UTC instants, which need no local zone.
        }
        await _plugin.initialize(
          settings: const InitializationSettings(
            android: AndroidInitializationSettings('@mipmap/ic_launcher'),
          ),
        );
      }();

  AndroidFlutterLocalNotificationsPlugin? get _android =>
      _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();

  @override
  bool get isSupported => true;

  @override
  Future<bool> requestPermission() async {
    try {
      await _ensureInitialized();
      return await _android?.requestNotificationsPermission() ?? false;
    } on Object {
      return false;
    }
  }

  @override
  Future<void> replaceAll(List<PlannedReminder> reminders) async {
    try {
      await _ensureInitialized();
      for (int index = 0; index < maxReminders; index++) {
        await _plugin.cancel(id: _firstId + index);
      }
      final NotificationDetails details = NotificationDetails(
        android: AndroidNotificationDetails(
          _channel,
          _channelName(),
          channelDescription: _channelDescription(),
          importance: Importance.defaultImportance,
          priority: Priority.defaultPriority,
          // Lock-screen safe: the copy names no exercise or health detail.
          visibility: NotificationVisibility.public,
          autoCancel: true,
        ),
      );
      final List<PlannedReminder> due =
          remindersToSchedule(reminders, now: DateTime.now());
      for (int index = 0; index < due.length; index++) {
        final PlannedReminder reminder = due[index];
        await _plugin.zonedSchedule(
          id: _firstId + index,
          scheduledDate: tz.TZDateTime.from(reminder.at.toUtc(), tz.UTC),
          title: reminder.title,
          body: reminder.body,
          notificationDetails: details,
          androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
          payload: reminder.url,
        );
      }
    } on Object {
      // Best-effort: an unavailable plugin keeps whatever was scheduled.
    }
  }
}

LocalReminderScheduler platformLocalReminderScheduler({
  String Function()? channelName,
  String Function()? channelDescription,
}) {
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    return AndroidLocalReminderScheduler(
      channelName: channelName,
      channelDescription: channelDescription,
    );
  }
  return const NoopLocalReminderScheduler();
}

/// Fetches the server's reminder plan and hands it to the scheduler (#840).
///
/// A failed fetch (offline, signed out) leaves the existing schedule as it is,
/// so reminders already planned still fire.
class LocalReminderSync {
  LocalReminderSync({
    required this.scheduler,
    required Future<Map<String, dynamic>> Function() fetchPlan,
    bool Function()? canSync,
  })  : _fetchPlan = fetchPlan,
        _canSync = canSync ?? (() => true);

  final LocalReminderScheduler scheduler;
  final Future<Map<String, dynamic>> Function() _fetchPlan;
  final bool Function() _canSync;
  Future<void>? _running;

  Future<void> sync() {
    if (!scheduler.isSupported || !_canSync()) return Future<void>.value();
    return _running ??= _sync().whenComplete(() => _running = null);
  }

  /// Removes every scheduled reminder, as on sign-out.
  Future<void> clear() => scheduler.isSupported
      ? scheduler.replaceAll(const <PlannedReminder>[])
      : Future<void>.value();

  Future<void> _sync() async {
    final Map<String, dynamic> plan;
    try {
      plan = await _fetchPlan();
    } on Object {
      return;
    }
    final List<PlannedReminder> reminders = <PlannedReminder>[
      for (final Object? item in (plan['reminders'] as List<Object?>? ?? const <Object?>[]))
        if (item is Map) PlannedReminder.fromJson(Map<String, dynamic>.from(item)),
    ];
    await scheduler.replaceAll(reminders);
  }
}
