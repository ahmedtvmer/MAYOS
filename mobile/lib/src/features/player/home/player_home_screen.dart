import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../providers.dart';
import '../../../router.dart';
import '../../coach/coach_profile_screen.dart';
import '../dashboard/dashboard_tab.dart';
import '../program/program_tab.dart';
import '../workout/draft_sync_service.dart';

enum _LogoutChoice { keep, discard }

class PlayerHomeScreen extends ConsumerStatefulWidget {
  const PlayerHomeScreen({super.key});

  @override
  ConsumerState<PlayerHomeScreen> createState() => _PlayerHomeScreenState();
}

class _PlayerHomeScreenState extends ConsumerState<PlayerHomeScreen> {
  int _index = 0;

  /// Logout must never silently destroy unsynced drafts: warn, and let the
  /// player explicitly keep or discard them (ADR 020/033).
  Future<void> _confirmLogout() async {
    final String? accountId =
        ref.read(authControllerProvider).session?.account.accountId;
    final DraftSyncService sync = ref.read(draftSyncServiceProvider);
    final int unsynced =
        accountId == null ? 0 : await sync.unsyncedCountFor(accountId);
    if (!mounted) return;

    if (unsynced > 0) {
      final _LogoutChoice? choice = await showDialog<_LogoutChoice>(
        context: context,
        builder: (BuildContext context) => AlertDialog(
          title: const Text('Unsynced workouts'),
          content: Text(
            'You have $unsynced unsynced workout '
            '${unsynced == 1 ? 'draft' : 'drafts'}. '
            'They stay on this device until they sync; logging out will not delete them.',
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () =>
                  Navigator.of(context).pop(_LogoutChoice.discard),
              child: const Text('Discard drafts and log out'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(_LogoutChoice.keep),
              child: const Text('Keep drafts and log out'),
            ),
          ],
        ),
      );
      if (choice == null) {
        return;
      }
      if (choice == _LogoutChoice.discard && accountId != null) {
        await sync.discardAllForAccount(accountId);
      }
    }
    if (!mounted) return;
    await ref.read(authControllerProvider.notifier).logout();
  }

  @override
  Widget build(BuildContext context) {
    final bool isCoach =
        ref.watch(authControllerProvider).session?.account.isCoach ?? false;

    final List<Widget> tabs = <Widget>[
      const DashboardTab(),
      const ProgramTab(),
      if (isCoach) const CoachProfileScreen(),
    ];
    final List<String> titles = <String>[
      'Dashboard',
      'Program',
      if (isCoach) 'Coach',
    ];
    final List<NavigationDestination> destinations = <NavigationDestination>[
      const NavigationDestination(
        icon: Icon(Icons.insights_outlined),
        selectedIcon: Icon(Icons.insights),
        label: 'Dashboard',
      ),
      const NavigationDestination(
        icon: Icon(Icons.fitness_center_outlined),
        selectedIcon: Icon(Icons.fitness_center),
        label: 'Program',
      ),
      if (isCoach)
        const NavigationDestination(
          icon: Icon(Icons.groups_outlined),
          selectedIcon: Icon(Icons.groups),
          label: 'Coach',
        ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Text(titles[_index.clamp(0, titles.length - 1)]),
        actions: <Widget>[
          IconButton(
            tooltip: 'Assistant chat',
            onPressed: () => context.go(chatPath),
            icon: const Icon(Icons.forum_outlined),
          ),
          IconButton(
            tooltip: 'Coaching assignment',
            onPressed: () => context.go(assignmentPath),
            icon: const Icon(Icons.badge_outlined),
          ),
          if (isCoach)
            IconButton(
              tooltip: 'Player invites',
              onPressed: () => context.go(coachAssignmentsPath),
              icon: const Icon(Icons.handshake_outlined),
            ),
          if (!isCoach)
            IconButton(
              tooltip: 'Redeem coach invite',
              onPressed: () => context.go(coachInvitePath),
              icon: const Icon(Icons.workspace_premium_outlined),
            ),
          if (ref.watch(offlineWorkoutDraftsEnabledProvider))
            IconButton(
              tooltip: 'Workouts',
              onPressed: () => context.go(workoutsPath),
              icon: const Icon(Icons.cloud_upload_outlined),
            ),
          IconButton(
            tooltip: 'Profile',
            onPressed: () => context.go(profilePath),
            icon: const Icon(Icons.person_outline),
          ),
          IconButton(
            tooltip: 'Plan',
            onPressed: () => context.go(planPath),
            icon: const Icon(Icons.card_membership_outlined),
          ),
          IconButton(
            tooltip: 'Log out',
            onPressed: _confirmLogout,
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: IndexedStack(
        index: _index.clamp(0, tabs.length - 1),
        children: tabs,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index.clamp(0, destinations.length - 1),
        onDestinationSelected: (int index) => setState(() => _index = index),
        destinations: destinations,
      ),
    );
  }
}
