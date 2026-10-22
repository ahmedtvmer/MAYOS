import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/ui/myos_app_header.dart';
import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/assignment_copy.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/ui/myos_bottom_navigation.dart';
import '../../../core/ui/myos_button.dart';
import '../../../core/ui/myos_scaffold.dart';
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
  List<MyosNavItem> _items(MyosCopy copy) => <MyosNavItem>[
        MyosNavItem(
          label: copy.home,
          icon: Icons.home_outlined,
          selectedIcon: Icons.home,
        ),
        MyosNavItem(
          label: copy.program,
          icon: Icons.article_outlined,
          selectedIcon: Icons.article,
        ),
        MyosNavItem(
          label: copy.progress,
          icon: Icons.insights_outlined,
          selectedIcon: Icons.insights,
        ),
      ];

  /// Set once this shell visit has offered Resume / Discard, so the prompt
  /// appears at most once per opening of the app (#123).
  bool _offeredResume = false;
  bool _rosterAiDisclosureChecked = false;
  bool _startupNoticesComplete = false;

  @override
  void initState() {
    super.initState();
    // The stored Active workout may already have been restored before the
    // shell mounted; check once off the first frame, then rely on the listener
    // below for a restore that lands later.
    Future<void>.microtask(() {
      if (mounted) {
        _offerStartupNotices();
      }
    });
  }

  Future<void> _offerStartupNotices() async {
    await _offerRosterAiDisclosure();
    if (mounted) {
      _startupNoticesComplete = true;
      _offerResume(ref.read(activeWorkoutControllerProvider));
    }
  }

  Future<void> _offerRosterAiDisclosure() async {
    if (_rosterAiDisclosureChecked) return;
    try {
      final Assignment? assignment =
          await ref.read(apiClientProvider).myAssignment();
      if (!mounted) return;
      _rosterAiDisclosureChecked = true;
      if (_needsRosterAiDisclosure(assignment)) {
        await _showRosterAiDisclosure();
      }
    } on ApiException {
      _rosterAiDisclosureChecked = true;
      // Assignment details may be temporarily unavailable; the server still
      // excludes this assignment from roster snapshots until acknowledgement.
    }
  }

  bool _needsRosterAiDisclosure(Assignment? assignment) =>
      assignment != null &&
      (assignment.rosterAiDisclosureVersion != rosterAiDisclosureVersion ||
          assignment.rosterAiDisclosedAt == null);

  Future<void> _showRosterAiDisclosure() => showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (BuildContext dialogContext) => PopScope(
          canPop: false,
          child: _RosterAiDisclosureDialog(
            copy: AssignmentCopy(ref.read(displayLanguageProvider)),
            onAcknowledge: () => ref
                .read(apiClientProvider)
                .acknowledgeRosterAiDisclosure(),
          ),
        ),
      );

  /// Offers Resume / Discard when this account restored an Active workout
  /// from device storage; a workout the player just started never re-triggers
  /// the offer. Web resumes its browser-stored workout too.
  void _offerResume(ActiveWorkoutState active) {
    if (!_startupNoticesComplete ||
        _offeredResume ||
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
    final MyosCopy copy = MyosCopy(ref.watch(displayLanguageProvider));
    final String settingsLabel = copy.settings;
    return MyosScaffold(
      header: MyosAppHeader(
        actions: <Widget>[
          IconButton(
            tooltip: copy.assistant,
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
      bottomBar: MyosBottomNavigation(
        items: _items(copy),
        index: index,
        onSelected: (int selected) =>
            ref.read(playerShellTabProvider.notifier).state = selected,
      ),
    );
  }
}

class _RosterAiDisclosureDialog extends StatefulWidget {
  const _RosterAiDisclosureDialog({
    required this.copy,
    required this.onAcknowledge,
  });

  final AssignmentCopy copy;
  final Future<void> Function() onAcknowledge;

  @override
  State<_RosterAiDisclosureDialog> createState() =>
      _RosterAiDisclosureDialogState();
}

class _RosterAiDisclosureDialogState
    extends State<_RosterAiDisclosureDialog> {
  bool _saving = false;
  FailureMessage? _error;

  Future<void> _acknowledge() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onAcknowledge();
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = apiFailureMessage(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(widget.copy.rosterAiDisclosure),
            if (_error != null) ...<Widget>[
              const SizedBox(height: 12),
              Text(
                displayCopyOf(context).failureMessage(_error!),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
        actions: <Widget>[
          MyosButton(
            label: widget.copy.rosterAiDisclosureOk,
            expand: false,
            loading: _saving,
            onPressed: _saving ? null : _acknowledge,
          ),
        ],
      );
}
