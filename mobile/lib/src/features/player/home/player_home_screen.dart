import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../providers.dart';
import '../../coach/coach_placeholder_screen.dart';
import '../dashboard/dashboard_tab.dart';
import '../program/program_tab.dart';

class PlayerHomeScreen extends ConsumerStatefulWidget {
  const PlayerHomeScreen({super.key});

  @override
  ConsumerState<PlayerHomeScreen> createState() => _PlayerHomeScreenState();
}

class _PlayerHomeScreenState extends ConsumerState<PlayerHomeScreen> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final bool isCoach =
        ref.watch(authControllerProvider).session?.account.isCoach ?? false;

    final List<Widget> tabs = <Widget>[
      const DashboardTab(),
      const ProgramTab(),
      if (isCoach) const CoachPlaceholderScreen(),
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
            tooltip: 'Log out',
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
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
