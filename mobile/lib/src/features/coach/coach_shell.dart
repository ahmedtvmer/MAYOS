import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/ui/mayos_app_header.dart';
import '../../core/ui/mayos_bottom_navigation.dart';
import '../../core/ui/mayos_scaffold.dart';
import '../../providers.dart';
import '../shared/mode_switch.dart';
import 'coach_alerts_screen.dart';
import 'coach_assignments_screen.dart';
import 'coach_profile_screen.dart';
import 'coach_requests_screen.dart';

/// The coach shell's bottom-tab indices (#119/#121). Named so a new tab never
/// silently shifts an existing destination or a test's index.
abstract final class CoachShellTab {
  static const int roster = 0;
  static const int alerts = 1;
  static const int requests = 2;
  static const int profile = 3;
}

/// The Coach mode shell (#119/#121): bottom tabs **Roster · Alerts · Requests ·
/// Profile**.
///
/// It opens on Roster; the Alerts tab carries a count badge of new alerts and
/// the Requests tab a count badge of pending program requests. The three data
/// tabs host today's coach screens; tapping a roster row still opens the
/// player history drill-down.
class CoachShell extends ConsumerStatefulWidget {
  const CoachShell({super.key});

  @override
  ConsumerState<CoachShell> createState() => _CoachShellState();
}

class _CoachShellState extends ConsumerState<CoachShell> {
  static const List<MayosNavItem> _items = <MayosNavItem>[
    MayosNavItem(
      label: 'Roster',
      icon: Icons.groups_outlined,
      selectedIcon: Icons.groups,
    ),
    MayosNavItem(
      label: 'Alerts',
      icon: Icons.notifications_outlined,
      selectedIcon: Icons.notifications,
    ),
    MayosNavItem(
      label: 'Requests',
      icon: Icons.inbox_outlined,
      selectedIcon: Icons.inbox,
    ),
    MayosNavItem(
      label: 'Profile',
      icon: Icons.badge_outlined,
      selectedIcon: Icons.badge,
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final int index = ref.watch(coachShellTabProvider);
    final int newAlerts = ref.watch(coachNewAlertsCountProvider);
    final int pendingRequests =
        ref.watch(coachPendingRequestsCountProvider);
    return MayosScaffold(
      header: const MayosAppHeader(
        actions: <Widget>[ModeAvatarButton()],
      ),
      body: IndexedStack(
        index: index,
        children: const <Widget>[
          CoachAssignmentsScreen(),
          CoachAlertsScreen(),
          CoachRequestsScreen(),
          CoachProfileScreen(),
        ],
      ),
      bottomBar: MayosBottomNavigation(
        items: <MayosNavItem>[
          for (int i = 0; i < _items.length; i++)
            MayosNavItem(
              label: _items[i].label,
              icon: _items[i].icon,
              selectedIcon: _items[i].selectedIcon,
              badge: switch (i) {
                CoachShellTab.alerts => newAlerts,
                CoachShellTab.requests => pendingRequests,
                _ => 0,
              },
            ),
        ],
        index: index,
        onSelected: (int selected) =>
            ref.read(coachShellTabProvider.notifier).state = selected,
      ),
    );
  }
}
