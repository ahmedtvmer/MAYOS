import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_app_header.dart';
import '../../core/ui/mayos_bottom_navigation.dart';
import '../../core/ui/mayos_scaffold.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/display_language/coach_copy.dart';
import '../../providers.dart';
import '../../router.dart';
import '../shared/mode_switch.dart';
import 'coach_alerts_screen.dart';
import 'coach_assignments_screen.dart';
import 'coach_requests_screen.dart';
import 'coach_shared.dart';

/// The coach shell's navigation indices (#119/#121). Named so a new tab never
/// silently shifts an existing destination or a test's index.
abstract final class CoachShellTab {
  static const int roster = 0;
  static const int alerts = 1;
  static const int requests = 2;
  static const int profile = 3;
}

/// The Coach mode shell (#119/#121). The browser location selects the active
/// tab, and the assignment route keeps the roster open beside its player page
/// on desktop.
class CoachShell extends ConsumerWidget {
  const CoachShell({
    super.key,
    required this.child,
    this.assignmentId,
  });

  final Widget child;
  final String? assignmentId;

  List<MayosNavItem> _items(CoachCopy copy) => <MayosNavItem>[
        MayosNavItem(
          label: copy.roster,
          icon: Icons.groups_outlined,
          selectedIcon: Icons.groups,
        ),
        MayosNavItem(
          label: copy.alerts,
          icon: Icons.notifications_outlined,
          selectedIcon: Icons.notifications,
        ),
        MayosNavItem(
          label: copy.requests,
          icon: Icons.inbox_outlined,
          selectedIcon: Icons.inbox,
        ),
        MayosNavItem(
          label: copy.profile,
          icon: Icons.badge_outlined,
          selectedIcon: Icons.badge,
        ),
      ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final int newAlerts = ref.watch(coachNewAlertsCountProvider);
    final int pendingRequests = ref.watch(coachPendingRequestsCountProvider);
    final List<MayosNavItem> items = _items(coachCopyOf(context));
    final String path = GoRouterState.of(context).uri.path;
    final int index = _tabForPath(path);
    final bool assignmentSelected = assignmentId != null;
    final bool desktop = isDesktopLayout(context);
    final Widget roster = CoachAssignmentsScreen(
      key: const Key('coach_roster_list_screen'),
      selectedAssignmentId: assignmentId,
    );
    final Widget paneBody = index != CoachShellTab.roster
        ? child
        : assignmentSelected && desktop
            ? CoachListDetail(
                list: roster,
                detail: child,
                listKey: const Key('coach_roster_master_pane'),
                detailKey: const Key('coach_player_detail_pane'),
              )
            : assignmentSelected
                ? Stack(
                    fit: StackFit.expand,
                    children: <Widget>[
                      Offstage(offstage: true, child: roster),
                      child,
                    ],
                  )
                : roster;
    final Widget body = _keepBadgeTabsMounted(paneBody, path);

    final Widget shell = MayosScaffold(
      header: const MayosAppHeader(
        actions: <Widget>[ModeAvatarButton()],
      ),
      body: body,
      showOfflineBanner: !assignmentSelected,
      bottomBar: MayosBottomNavigation(
        items: <MayosNavItem>[
          for (int i = 0; i < items.length; i++)
            MayosNavItem(
              label: items[i].label,
              icon: items[i].icon,
              selectedIcon: items[i].selectedIcon,
              badge: switch (i) {
                CoachShellTab.alerts => newAlerts,
                CoachShellTab.requests => pendingRequests,
                _ => 0,
              },
            ),
        ],
        index: index,
        onSelected: (int selected) {
          context.go(switch (selected) {
            CoachShellTab.alerts => coachAlertsPath,
            CoachShellTab.requests => coachRequestsPath,
            CoachShellTab.profile => coachProfilePath,
            _ => coachRosterPath,
          });
        },
      ),
    );
    return shell;
  }

  Widget _keepBadgeTabsMounted(Widget body, String path) => Stack(
        fit: StackFit.expand,
        children: <Widget>[
          body,
          if (path != coachAlertsPath)
            const Offstage(child: CoachAlertsScreen()),
          if (path != coachRequestsPath &&
              !path.startsWith('$coachRequestsPath/'))
            const Offstage(child: CoachRequestsScreen()),
        ],
      );

  static int _tabForPath(String path) {
    if (path == coachAlertsPath) return CoachShellTab.alerts;
    if (path == coachRequestsPath || path.startsWith('$coachRequestsPath/')) {
      return CoachShellTab.requests;
    }
    if (path == coachProfilePath) return CoachShellTab.profile;
    return CoachShellTab.roster;
  }
}
