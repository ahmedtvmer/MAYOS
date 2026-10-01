import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/ui/mayos_app_header.dart';
import '../../../core/display_language.dart';
import '../../../core/ui/mayos_bottom_navigation.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../../shared/mode_switch.dart';
import '../dashboard/dashboard_tab.dart';
import '../program/program_tab.dart';
import '../progress/progress_tab.dart';
import '../workout/active_workout_controller.dart';
import '../workout/active_workout_prompt.dart';

/// The player navigation shell.
///
/// Bottom navigation is Home, Program, and Progress (#48); Progress ships only
/// because its Strength and Volume experiences derive from real ledger data.
/// Settings opens from the header; every other working surface (coach
/// profile/invite/assignment, workout drafts, assistant chat, profile, plan,
/// logout) is reached from Settings or the header, never a placeholder
/// destination.
class PlayerShell extends ConsumerStatefulWidget {
  const PlayerShell({super.key});

  @override
  ConsumerState<PlayerShell> createState() => _PlayerShellState();
}

class _PlayerShellState extends ConsumerState<PlayerShell> {
  static const List<MayosNavItem> _items = <MayosNavItem>[
    MayosNavItem(
      label: 'Home',
      icon: Icons.home_outlined,
      selectedIcon: Icons.home,
    ),
    MayosNavItem(
      label: 'Program',
      icon: Icons.article_outlined,
      selectedIcon: Icons.article,
    ),
    MayosNavItem(
      label: 'Progress',
      icon: Icons.insights_outlined,
      selectedIcon: Icons.insights,
    ),
  ];

  /// Set once this shell visit has offered Resume / Discard, so the prompt
  /// appears at most once per opening of the app (#123).
  bool _offeredResume = false;

  @override
  void initState() {
    super.initState();
    // The stored Active workout may already have been restored before the
    // shell mounted; check once off the first frame, then rely on the listener
    // below for a restore that lands later.
    Future<void>.microtask(() {
      if (mounted) {
        _offerResume(ref.read(activeWorkoutControllerProvider));
      }
    });
  }

  /// Offers Resume / Discard when this account restored an Active workout
  /// from device storage; a workout the player just started never re-triggers
  /// the offer. Web resumes its browser-stored workout too.
  void _offerResume(ActiveWorkoutState active) {
    if (_offeredResume ||
        !active.ready ||
        !active.restoredFromDevice ||
        active.workout == null) {
      return;
    }
    _offeredResume = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      unawaited(offerActiveWorkoutOnOpen(context, ref));
    });
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<ActiveWorkoutState>(
      activeWorkoutControllerProvider,
      (_, ActiveWorkoutState next) => _offerResume(next),
    );
    final int index = ref.watch(playerShellTabProvider);
    final bool isCoach =
        ref.watch(authControllerProvider).session?.account.isCoach ?? false;
    final String settingsLabel =
        MayosCopy(ref.watch(displayLanguageProvider)).settings;
    return MayosScaffold(
      header: MayosAppHeader(
        actions: <Widget>[
          IconButton(
            tooltip: 'Assistant',
            onPressed: () => context.push(chatPath),
            icon: const Icon(Icons.chat_bubble_outline),
          ),
          IconButton(
            tooltip: settingsLabel,
            onPressed: () => context.push(settingsPath),
            icon: const Icon(Icons.settings_outlined),
          ),
          // A coach account carries the C/P mode badge in Player mode too
          // (#119); non-coach accounts render nothing here.
          if (isCoach) const ModeAvatarButton(),
        ],
      ),
      body: IndexedStack(
        index: index,
        children: const <Widget>[
          DashboardTab(),
          ProgramTab(),
          ProgressTab(),
        ],
      ),
      bottomBar: MayosBottomNavigation(
        items: _items,
        index: index,
        onSelected: (int selected) =>
            ref.read(playerShellTabProvider.notifier).state = selected,
      ),
    );
  }
}
