import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/theme/mayos_spacing.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';
import 'package:mayos_mobile/src/core/ui/mayos_scaffold.dart';
import 'package:mayos_mobile/src/features/coach/coach_assignments_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

Future<void> _pumpUntilFound(
  WidgetTester tester,
  Finder finder, {
  int attempts = 40,
}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  required Size size,
  AppMode? mode,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final InMemoryAppModeStore modeStore = InMemoryAppModeStore(
    mode == null ? null : <String, AppMode>{'account-alice': mode},
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(modeStore),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text(fake.coach ? 'Roster' : 'Home'));
}

FakeMayosApi _playerFake() {
  final FakeMayosApi fake = FakeMayosApi()
    ..issuedToken = 'token-alice'
    ..currentUsername = 'alice'
    ..tokenValid = true
    ..profileExists = true
    ..recoveryEmail = 'alice@example.com';
  return fake;
}

FakeMayosApi _coachFake() {
  final FakeMayosApi fake = FakeMayosApi()
    ..issuedToken = 'token-alice'
    ..currentUsername = 'alice'
    ..tokenValid = true
    ..coach = true
    ..profileExists = true
    ..recoveryEmail = 'alice@example.com'
    ..coachDisplayName = 'Coach Alice';
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'started_at': '2026-09-24T10:00:00Z',
    'status': 'active',
  });
  fake.coachAlerts.add(<String, dynamic>{
    'alert_id': 'alert-1',
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'kind': 'missed_day',
    'state': 'new',
    'created_at': '2026-09-24T08:00:00Z',
    'streak_start_date': '2026-09-20',
    'last_missed_date': '2026-09-21',
    'missed_count': 2,
    'acknowledged_at': null,
    'resolved_at': null,
    'resolved_by': null,
  });
  fake.coachAlerts.add(<String, dynamic>{
    'alert_id': 'alert-2',
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'kind': 'missed_day',
    'state': 'resolved',
    'created_at': '2026-09-20T08:00:00Z',
    'streak_start_date': '2026-09-15',
    'last_missed_date': '2026-09-17',
    'missed_count': 3,
    'acknowledged_at': '2026-09-21T08:00:00Z',
    'resolved_at': '2026-09-22T08:00:00Z',
    'resolved_by': 'coach',
  });
  return fake;
}

Finder _railDestination(String label) => find.descendant(
      of: find.byType(MayosNavigationRail),
      matching: find.text(label),
    );

Finder _bottomDestination(String label) => find.descendant(
      of: find.byType(MayosBottomNavigation),
      matching: find.text(label),
    );

void _resize(WidgetTester tester, Size size) {
  tester.view.physicalSize = size;
}

Future<void> _checkOverlayWidths(
  WidgetTester tester, {
  required double expectedSheetWidth,
  double? expectedSnackBarWidth,
  double? minimumSnackBarWidth,
  required double expectedCenter,
}) async {
  final BuildContext context =
      tester.element(find.byKey(MayosScaffold.bodyContentKey));
  final Future<void> sheet = showModalBottomSheet<void>(
    context: context,
    builder: (BuildContext context) => const SizedBox(
      key: ValueKey<String>('overlay.sheet'),
      width: double.infinity,
      height: 120,
    ),
  );
  await tester.pumpAndSettle();
  final Rect sheetRect = tester.getRect(
    find.byKey(const ValueKey<String>('overlay.sheet')),
  );
  expect(sheetRect.width, expectedSheetWidth);
  expect(sheetRect.center.dx, expectedCenter);
  Navigator.of(context).pop();
  await tester.pumpAndSettle();
  await sheet;

  ScaffoldMessenger.of(context).showSnackBar(
    const SnackBar(content: Text('Overlay width check')),
  );
  await tester.pumpAndSettle();
  final Rect snackRect = tester.getRect(
    find.descendant(
      of: find.byType(SnackBar),
      matching: find.byType(Material),
    ),
  );
  if (expectedSnackBarWidth != null) {
    expect(snackRect.width, expectedSnackBarWidth);
  }
  if (minimumSnackBarWidth != null) {
    expect(snackRect.width, greaterThan(minimumSnackBarWidth));
  }
  expect(snackRect.center.dx, expectedCenter);
  ScaffoldMessenger.of(context).hideCurrentSnackBar();
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'Player mode switches layouts, preserves tab state, and centres pushed screens',
    (WidgetTester tester) async {
      await _pumpApp(tester, _playerFake(), size: const Size(1280, 800));

      expect(find.byType(MayosNavigationRail), findsOneWidget);
      expect(find.byType(NavigationRail), findsOneWidget);
      expect(find.byType(MayosBottomNavigation), findsNothing);
      expect(_railDestination('Home'), findsOneWidget);
      expect(_railDestination('Program'), findsOneWidget);
      expect(_railDestination('Progress'), findsOneWidget);

      final Rect shellBody = tester.getRect(
        find.byKey(MayosScaffold.bodyContentKey),
      );
      expect(shellBody.width, MayosLayout.playerColumnMaxWidth);
      expect(
        shellBody.center.dx,
        (MayosLayout.navigationRailWidth + 1280) / 2,
      );

      await tester.tap(_railDestination('Progress'));
      await _pumpUntilFound(tester, find.text('Strength'));
      await tester.tap(find.text('Volume'));
      await _pumpUntilFound(tester, find.text('Weighted sets'));
      await tester.tap(find.text('28 days'));
      await _pumpUntilFound(
        tester,
        find.text('Last 28 days · working sets per muscle'),
      );

      _resize(tester, const Size(390, 844));
      await tester.pump();
      expect(find.byType(MayosNavigationRail), findsNothing);
      expect(find.byType(MayosBottomNavigation), findsOneWidget);
      expect(_bottomDestination('Home'), findsOneWidget);
      expect(_bottomDestination('Program'), findsOneWidget);
      expect(_bottomDestination('Progress'), findsOneWidget);
      expect(
        tester
            .widget<MayosBottomNavigation>(find.byType(MayosBottomNavigation))
            .index,
        2,
      );
      expect(
        find.text('Last 28 days · working sets per muscle'),
        findsOneWidget,
      );

      _resize(tester, const Size(1280, 800));
      await tester.pump();
      expect(find.byType(MayosNavigationRail), findsOneWidget);
      expect(
        tester
            .widget<MayosNavigationRail>(find.byType(MayosNavigationRail))
            .index,
        2,
      );
      expect(
        find.text('Last 28 days · working sets per muscle'),
        findsOneWidget,
      );

      await tester.tap(find.byIcon(Icons.settings_outlined));
      await _pumpUntilFound(tester, find.text('Appearance'));
      await tester.tap(find.text('Plan'));
      await _pumpUntilFound(
        tester,
        find.text('Lifter and Coach plans are independent.'),
      );
      final Rect pushedBody = tester.getRect(
        find.byKey(MayosScaffold.bodyContentKey),
      );
      expect(pushedBody.width, MayosLayout.playerColumnMaxWidth);
      expect(pushedBody.center.dx, 640);
      await _checkOverlayWidths(
        tester,
        expectedSheetWidth: MayosLayout.playerColumnMaxWidth,
        expectedSnackBarWidth: MayosLayout.playerColumnMaxWidth,
        expectedCenter: 640,
      );
    },
  );

  testWidgets(
    'Coach mode uses tabs below 1024 and a full-width rail at and above it',
    (WidgetTester tester) async {
      await _pumpApp(
        tester,
        _coachFake(),
        mode: AppMode.coach,
        size: const Size(390, 844),
      );
      expect(find.byType(MayosBottomNavigation), findsOneWidget);
      expect(find.byType(MayosNavigationRail), findsNothing);
      for (final String destination in <String>[
        'Roster',
        'Alerts',
        'Requests',
        'Profile',
      ]) {
        expect(_bottomDestination(destination), findsOneWidget);
      }
      expect(
        find.descendant(
          of: find.byType(MayosBottomNavigation),
          matching: find.text('1'),
        ),
        findsOneWidget,
      );

      await tester.tap(_bottomDestination('Alerts'));
      await _pumpUntilFound(tester, find.text('Show resolved'));
      await tester.tap(find.text('Show resolved'));
      const String resolved =
          'Missed 3 expected training days (2026-09-15 to 2026-09-17)';
      await _pumpUntilFound(tester, find.text(resolved));

      _resize(tester, const Size(1023, 800));
      await tester.pump();
      expect(find.byType(MayosBottomNavigation), findsOneWidget);
      expect(find.byType(MayosNavigationRail), findsNothing);
      expect(find.text(resolved), findsOneWidget);

      _resize(tester, const Size(1024, 800));
      await tester.pump();
      expect(find.byType(MayosNavigationRail), findsOneWidget);
      expect(find.byType(NavigationRail), findsOneWidget);
      expect(find.byType(MayosBottomNavigation), findsNothing);
      final MayosNavigationRail rail = tester.widget<MayosNavigationRail>(
        find.byType(MayosNavigationRail),
      );
      expect(rail.index, 1);
      for (final String destination in <String>[
        'Roster',
        'Alerts',
        'Requests',
        'Profile',
      ]) {
        expect(_railDestination(destination), findsOneWidget);
      }
      expect(
        find.descendant(
          of: find.byType(MayosNavigationRail),
          matching: find.text('1'),
        ),
        findsOneWidget,
      );
      expect(find.text(resolved), findsOneWidget);

      _resize(tester, const Size(1280, 800));
      await tester.pump();
      expect(find.byType(MayosNavigationRail), findsOneWidget);
      expect(find.byType(MayosBottomNavigation), findsNothing);
      expect(
        tester
            .widget<MayosNavigationRail>(find.byType(MayosNavigationRail))
            .index,
        1,
      );
      expect(find.text(resolved), findsOneWidget);
      await tester.tap(_railDestination('Roster'));
      await _pumpUntilFound(tester, find.text('Active assignments'));
      expect(
        tester.getRect(find.byKey(MayosScaffold.bodyContentKey)).width,
        1280 - MayosLayout.navigationRailWidth,
      );
      expect(
        tester.getRect(find.byType(CoachAssignmentsScreen)).width,
        1280 - MayosLayout.navigationRailWidth,
      );
      await _checkOverlayWidths(
        tester,
        expectedSheetWidth: MayosLayout.coachOverlayMaxWidth,
        expectedSnackBarWidth: MayosLayout.coachOverlayMaxWidth,
        expectedCenter: 640,
      );

      _resize(tester, const Size(800, 800));
      await tester.pump();
      await _checkOverlayWidths(
        tester,
        expectedSheetWidth: 800,
        minimumSnackBarWidth: MayosLayout.coachOverlayMaxWidth,
        expectedCenter: 400,
      );
    },
  );
}
