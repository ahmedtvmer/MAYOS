import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/active_workout.dart';
import '../../../core/personal_records.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_app_header.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'active_workout_prompt.dart';

/// The logger's compact top bar (#159): Back on the shared header (the #156
/// fallback to Home stays its own behaviour), the `Log workout · 32:10` line
/// carrying the live **Workout time**, and the ⋮ menu that discards the
/// workout.
///
/// Presentation only: the time is derived from the Active workout's stored
/// start through the injected clock ([clockProvider]) and re-rendered by a
/// ticker once a second while the bar is on screen, so it has no pause, no
/// state of its own, and stays correct after a restart (#159). While the
/// workout summary is open the bar freezes at that snapshot's duration
/// ([loggerSummaryProvider]) instead of ticking beside it.
class LoggerTopBar extends ConsumerStatefulWidget {
  const LoggerTopBar({super.key});

  /// The ⋮ menu and its one entry, exposed so tests open what a player opens.
  static const Key menuKey = ValueKey<String>('logger.menu');
  static const Key discardKey = ValueKey<String>('logger.menu.discard');

  @override
  ConsumerState<LoggerTopBar> createState() => _LoggerTopBarState();
}

class _LoggerTopBarState extends ConsumerState<LoggerTopBar> {
  /// The one-second tick (#159): Workout time is derived, never counted, so
  /// the ticker only has to redraw — the value comes from the clock.
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) {
        setState(() {});
      }
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _ticker = null;
    super.dispose();
  }

  Future<void> _discard(ActiveWorkout workout) async {
    final bool confirmed = await confirmDiscardWorkout(context);
    if (!confirmed || !mounted) {
      return;
    }
    await ref
        .read(activeWorkoutControllerProvider.notifier)
        .discard(accountId: workout.accountId, workoutId: workout.id);
    if (!mounted) {
      return;
    }
    // Leave the logger the way its Back affordance does (#156): pop the page
    // underneath when there is one, else fall back to Home. The workout
    // itself is already gone — the same effect as Discard in the Resume
    // prompt (#123).
    final bool handled = await Navigator.of(context).maybePop();
    if (!mounted || handled) {
      return;
    }
    context.go(homePath);
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ActiveWorkout? workout =
        ref.watch(activeWorkoutControllerProvider).workout;
    final DateTime now = ref.watch(clockProvider)();
    // While the summary step is open the bar holds the snapshot's duration
    // instead of the clock (#159): no live tick beside the frozen "Duration"
    // stat. Dropping the snapshot — Back to the logger — resumes the tick.
    final WorkoutSummary? summary = ref.watch(loggerSummaryProvider);
    final String label = workout == null
        ? 'Log workout'
        : 'Log workout · '
            '${formatWorkoutTime(summary?.duration ?? workoutElapsed(workout, now: now))}';
    return MayosAppHeader(
      showBack: true,
      // Sans, one line: the serif display role belongs to the day heading
      // alone (#157 typography).
      titleWidget: Text(
        label,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: MayosTypography.sectionHeading.copyWith(color: c.textPrimary),
      ),
      actions: <Widget>[
        if (workout != null)
          PopupMenuButton<String>(
            key: LoggerTopBar.menuKey,
            onSelected: (String value) {
              if (value == 'discard') {
                unawaited(_discard(workout));
              }
            },
            itemBuilder: (BuildContext context) => <PopupMenuItem<String>>[
              PopupMenuItem<String>(
                key: LoggerTopBar.discardKey,
                value: 'discard',
                child: Text(
                  'Discard workout',
                  style: MayosTypography.body,
                ),
              ),
            ],
          ),
      ],
    );
  }
}
