import 'package:flutter/material.dart';

import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_progress.dart';

/// The logger's persistent bottom workout bar (#160): `{ticked}/{total} sets`,
/// a progress bar and **Finish**, always in reach, plus #125's rest controls
/// while a rest runs — one bottom bar for the whole screen.
///
/// Presentation only: it is the last child of the logger's column, so it
/// sits fixed at the bottom of the screen and the list above it shrinks to
/// the space that is left — the last card scrolls clear without the bar ever
/// overlaying content. The logger swaps it for the keypad while an edit is
/// open, and hides it behind the workout summary.
///
/// The bar owns its bottom safe area *inside* its surface: the decorated
/// container runs to the physical screen bottom while the rows are padded
/// above the system-navigation inset, so a gesture-nav phone shows no
/// page-background seam under the bar (#160).
///
/// The rows are stacked rather than squeezed into one line so the counts and
/// the full-width Finish stay readable at the 2x text scale the design sweep
/// checks (#45/#160), and so Finish never changes place when a rest starts.
class LoggerBottomBar extends StatelessWidget {
  const LoggerBottomBar({
    super.key,
    required this.setsTicked,
    required this.setsTotal,
    required this.progressValue,
    required this.onFinish,
    this.restControls,
  });

  /// Ticked working sets over total working sets — the same
  /// `workoutProgressOf` counts the header's progress line shows (#159), so
  /// the two can never disagree.
  final int setsTicked;

  final int setsTotal;

  /// The progress bar's fill, from `workoutSetsFractionOf` — worked out once
  /// by the logger beside the counts it comes from (#160).
  final double progressValue;

  /// Finish's flow — the unticked-sets sheet, then the summary
  /// (#123/#124) — or null while Finish is blocked (unknown timezone,
  /// offline program), so the button renders disabled exactly as before.
  final VoidCallback? onFinish;

  /// #125's rest controls (−15 · m:ss · +15 · Skip with the draining
  /// fill), supplied by the logger only while a rest is running.
  final Widget? restControls;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final WorkoutCopy copy = workoutCopyOf(context);
    return Container(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.border)),
      ),
      // The surface keeps going under the inset; the content stops above it.
      child: SafeArea(
        top: false,
        // The route Scaffold may clear padding while retaining viewPadding.
        maintainBottomViewPadding: true,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.symmetric(
                  horizontal: MayosSpacing.lg, vertical: MayosSpacing.xs),
              child: Row(
                children: <Widget>[
                  // The counts, in the label role; `Flexible` so an enormous
                  // text scale ellipsizes instead of overflowing the row.
                  Flexible(
                    child: Text(
                      copy.setsProgress(setsTicked, setsTotal),
                      key: const ValueKey<String>('logger.bottomBar.progress'),
                      textAlign: copy.isArabic ? TextAlign.end : null,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: MayosTypography.of(context).label
                          .copyWith(color: c.textSecondary),
                    ),
                  ),
                  const SizedBox(width: MayosSpacing.sm),
                  Expanded(
                    child: MayosProgressIndicator(value: progressValue),
                  ),
                ],
              ),
            ),
            if (restControls != null) restControls!,
            Padding(
              padding: const EdgeInsetsDirectional.fromSTEB(MayosSpacing.lg,
                  MayosSpacing.xxs, MayosSpacing.lg, MayosSpacing.sm),
              child: MayosButton(
                label: copy.finishWorkout,
                icon: Icons.check,
                onPressed: onFinish,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
