import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/local_reminders.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/settings/push_settings_card.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';

class _FakeScheduler implements LocalReminderScheduler {
  _FakeScheduler({this.grant = true});

  final bool grant;
  int permissionRequests = 0;
  final List<List<PlannedReminder>> scheduled = <List<PlannedReminder>>[];

  @override
  bool get isSupported => true;

  @override
  Future<bool> requestPermission() async {
    permissionRequests += 1;
    return grant;
  }

  @override
  Future<void> replaceAll(List<PlannedReminder> reminders) async {
    scheduled.add(reminders);
  }
}

Map<String, dynamic> _reminder(String date, String at) => <String, dynamic>{
      'date': date, 'at': at, 'template': 'start', 'title': 'MAYOS',
      'body': 'A little movement can brighten your day.', 'url': '/home?push=program',
    };

void main() {
  group('offline workout reminders (#840)', () {
    test('only future reminders are scheduled, at most fourteen', () {
      final DateTime now = DateTime.utc(2026, 11, 16, 12);
      final List<PlannedReminder> plan = <PlannedReminder>[
        PlannedReminder.fromJson(_reminder('2026-11-16', '2026-11-16T11:00:00+00:00')),
        for (int day = 17; day < 40; day++)
          PlannedReminder.fromJson(_reminder('2026-11-$day', '2026-11-${day}T16:00:00+00:00')),
      ];

      final List<PlannedReminder> due = remindersToSchedule(plan, now: now);

      expect(due, hasLength(14));
      expect(due.first.date, '2026-11-17');
      expect(due.every((PlannedReminder item) => item.at.isAfter(now)), isTrue);
    });

    test('a sync replaces the schedule with the server plan', () async {
      final _FakeScheduler scheduler = _FakeScheduler();
      final LocalReminderSync sync = LocalReminderSync(
        scheduler: scheduler,
        fetchPlan: () async => <String, dynamic>{
          'timezone': 'Africa/Cairo',
          'reminders': <Object>[_reminder('2026-11-17', '2026-11-17T18:00:00+02:00')],
        },
      );

      await sync.sync();

      expect(scheduler.scheduled, hasLength(1));
      final PlannedReminder reminder = scheduler.scheduled.single.single;
      expect(reminder.date, '2026-11-17');
      expect(reminder.at, DateTime.utc(2026, 11, 17, 16));
      expect(reminder.url, '/home?push=program');
    });

    test('an offline sync keeps the reminders already scheduled', () async {
      final _FakeScheduler scheduler = _FakeScheduler();
      final LocalReminderSync sync = LocalReminderSync(
        scheduler: scheduler,
        fetchPlan: () async => throw ApiException('offline'),
      );

      await sync.sync();

      expect(scheduler.scheduled, isEmpty);
    });

    test('only a signed-in Player syncs, and clearing removes every reminder', () async {
      final _FakeScheduler scheduler = _FakeScheduler();
      int fetches = 0;
      final LocalReminderSync sync = LocalReminderSync(
        scheduler: scheduler,
        fetchPlan: () async {
          fetches += 1;
          return <String, dynamic>{'reminders': <Object>[]};
        },
        canSync: () => false,
      );

      await sync.sync();
      await sync.clear();

      expect(fetches, 0);
      expect(scheduler.scheduled.single, isEmpty);
    });

    Future<(List<FakeRequest>, _FakeScheduler)> pumpSettings(
      WidgetTester tester, {
      required bool grant,
    }) async {
      final List<FakeRequest> requests = <FakeRequest>[];
      Map<String, dynamic> prefs = <String, dynamic>{
        'workout_reminders': false, 'alerts': true, 'coach_updates': true,
        'reminder_time': '18:00', 'quiet_start': '22:00', 'quiet_end': '08:00',
        'timezone': 'Africa/Cairo',
      };
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await tokens.save('player-token');
      final ApiClient api = ApiClient(
        tokens: tokens,
        baseUrl: 'http://test.local',
        adapter: FakeApiAdapter((FakeRequest request) {
          requests.add(request);
          if (request.path == '/push' && request.method == 'GET') {
            return FakeResponse(200, <String, dynamic>{
              'enabled': false, 'subscribed': false, 'public_key': null, 'preferences': prefs,
            });
          }
          if (request.path == '/push/preferences') {
            prefs = request.body;
            return FakeResponse(200, prefs);
          }
          if (request.path == '/push/local-reminders') {
            return FakeResponse(200, <String, dynamic>{
              'timezone': 'Africa/Cairo',
              'reminders': <Object>[_reminder('2099-11-17', '2099-11-17T18:00:00+02:00')],
            });
          }
          return const FakeResponse(404, <String, dynamic>{'detail': 'Not found'});
        }),
      );
      final _FakeScheduler scheduler = _FakeScheduler(grant: grant);
      await tester.pumpWidget(ProviderScope(
        overrides: <Override>[
          displayLanguageProvider.overrideWith((ref) =>
              DisplayLanguageController(InMemoryDisplayLanguageStore(), systemLanguage: 'en')),
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWithValue(api),
          localReminderSchedulerProvider.overrideWithValue(scheduler),
          localReminderSyncProvider.overrideWithValue(LocalReminderSync(
            scheduler: scheduler,
            fetchPlan: api.localReminders,
          )),
        ],
        child: const MaterialApp(home: Scaffold(body: PushSettingsCard())),
      ));
      await tester.pumpAndSettle();
      return (requests, scheduler);
    }

    testWidgets('Android Settings turns reminders on after the permission and schedules them',
        (WidgetTester tester) async {
      final (List<FakeRequest> requests, _FakeScheduler scheduler) =
          await pumpSettings(tester, grant: true);
      expect(find.byKey(const Key('android_reminder_settings')), findsOneWidget);
      expect(find.text('Push notifications are available in the installed web app.'), findsNothing);
      expect(scheduler.permissionRequests, 0, reason: 'never asked before the Player turns reminders on');

      await tester.tap(find.byKey(const Key('android_workout_reminders_switch')));
      await tester.pumpAndSettle();

      expect(scheduler.permissionRequests, 1);
      final FakeRequest saved = requests.lastWhere((FakeRequest r) => r.path == '/push/preferences');
      expect(saved.body['workout_reminders'], isTrue);
      expect(scheduler.scheduled.single.single.date, '2099-11-17');
    });

    testWidgets('a refused permission saves nothing and explains how to allow it',
        (WidgetTester tester) async {
      final (List<FakeRequest> requests, _FakeScheduler scheduler) =
          await pumpSettings(tester, grant: false);

      await tester.tap(find.byKey(const Key('android_workout_reminders_switch')));
      await tester.pumpAndSettle();

      expect(requests.where((FakeRequest r) => r.path == '/push/preferences'), isEmpty);
      expect(scheduler.scheduled, isEmpty);
      expect(find.textContaining('Notifications are blocked.'), findsOneWidget);
    });
  });
}
