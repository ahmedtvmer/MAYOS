import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/active_workout.dart';
import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/rest_length.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../providers.dart';

/// The rest picker (#125): Off, then 1:00–5:00 in 15-second steps. Returns
/// the picked length in seconds, or null when dismissed.
Future<int?> showRestLengthPicker(
  BuildContext context, {
  required int initial,
}) =>
    showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      builder: (BuildContext context) => SafeArea(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 560),
          child: ListView.builder(
            shrinkWrap: true,
            itemCount: kRestLengthOptions.length,
            itemBuilder: (BuildContext context, int index) {
              final int seconds = kRestLengthOptions[index];
              final bool selected = seconds == initial;
              return InkWell(
                key: ValueKey<String>('rest.option.$seconds'),
                onTap: () => Navigator.of(context).pop(seconds),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: MayosSpacing.lg,
                    vertical: MayosSpacing.sm,
                  ),
                  child: Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          seconds <= 0
                              ? workoutCopyOf(context).restOff
                              : restMmSs(seconds),
                          textDirection:
                              seconds <= 0 ? null : TextDirection.ltr,
                          style: selected
                              ? MayosTypography.of(context).bodySecondary.copyWith(
                                  color: MayosTheme.of(context).accent,
                                )
                              : MayosTypography.of(context).bodySecondary,
                        ),
                      ),
                      if (selected)
                        Icon(
                          Icons.check,
                          size: MayosIconSizes.medium,
                          color: MayosTheme.of(context).accent,
                        ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );

/// #125's rest controls — **−15 · m:ss + "Rest · <exercise>" · +15 ·
/// Skip** — with a draining fill behind them, as the logger's persistent
/// bottom bar shows them while a rest runs (#160).
///
/// This is the whole of the old slim rest bar, minus its own frame: the
/// bottom bar wraps it so there is exactly one bottom bar on screen, and it
/// disappears with that bar while the keypad is open. Every action keeps a
/// full 48dp target (#45).
///
/// The countdown carries its own quarter-second ticker, so only this row
/// repaints while a rest runs rather than the whole logger screen (#160).
/// Every tick reads [ActiveRestTimer] against the app clock, so the count
/// is exact in the foreground instead of drifting with timer ticks. The
/// end-of-rest alert stays with the logger's own ticker (#125), which keeps
/// running even when this row is hidden behind the keypad.
class RestTimerControls extends ConsumerStatefulWidget {
  const RestTimerControls({
    super.key,
    required this.rest,
    required this.onMinus,
    required this.onPlus,
    required this.onSkip,
  });

  /// The running rest: its end time drives the countdown and the draining
  /// fill's denominator. The logger still owns every change to it.
  final ActiveRestTimer rest;

  final VoidCallback onMinus;
  final VoidCallback onPlus;
  final VoidCallback onSkip;

  @override
  ConsumerState<RestTimerControls> createState() => _RestTimerControlsState();
}

class _RestTimerControlsState extends ConsumerState<RestTimerControls> {
  /// The countdown's own quarter-second tick: it wakes this row alone, so a
  /// running rest costs one small repaint instead of the whole screen
  /// (#160).
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(
      const Duration(milliseconds: 250),
      (_) => _onTick(),
    );
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _ticker = null;
    super.dispose();
  }

  void _onTick() {
    if (mounted) {
      setState(() {});
    }
  }

  /// Whole seconds left (already rounded up, 0 at the end), straight from
  /// the app clock.
  int get _remainingSeconds =>
      widget.rest.remainingSeconds(ref.read(clockProvider)());

  double get _fill {
    final int totalSeconds = widget.rest.totalSeconds;
    if (totalSeconds <= 0) {
      return 0;
    }
    final double fraction = _remainingSeconds / totalSeconds;
    return fraction.clamp(0.0, 1.0);
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final WorkoutCopy copy = workoutCopyOf(context);
    // A full 48dp target for every action (#45): the label sits centred in
    // the minimum target rather than sizing the target from the text.
    Widget action(String label, VoidCallback onTap, {Key? key}) => InkWell(
          key: key,
          onTap: onTap,
          borderRadius: MayosRadii.smallRadius,
          child: SizedBox(
            height: kMayosMinTapTarget,
            child: Center(
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: MayosSpacing.sm),
                child: Text(
                  label,
                  textDirection: label == '−15' || label == '+15'
                      ? TextDirection.ltr
                      : null,
                  style: MayosTypography.of(context).label.copyWith(color: c.accent),
                ),
              ),
            ),
          ),
        );

    return Container(
      key: const ValueKey<String>('rest.controls'),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: c.border)),
      ),
      child: Stack(
        children: <Widget>[
          // The draining fill: the time still left, from the left edge.
          Positioned.fill(
            child: FractionallySizedBox(
              alignment: AlignmentDirectional.centerStart,
              widthFactor: _fill,
              // The draining fill: the rest's own accent wash, a token rather
              // than a raw alpha (DESIGN.md).
              child: ColoredBox(color: c.accentWash),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: MayosSpacing.xs,
              vertical: MayosSpacing.xxs,
            ),
            child: Row(
              children: <Widget>[
                action(
                  '−15',
                  widget.onMinus,
                  key: const ValueKey<String>('rest.minus'),
                ),
                Expanded(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(
                        restMmSs(_remainingSeconds),
                        textDirection: TextDirection.ltr,
                        style: MayosTypography.of(context).numericMedium.copyWith(
                          color: c.textPrimary,
                        ),
                      ),
                      Text(
                        copy.restForExercise(widget.rest.exerciseName),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: MayosTypography.of(context).caption.copyWith(
                          color: c.textMuted,
                        ),
                      ),
                    ],
                  ),
                ),
                action(
                  '+15',
                  widget.onPlus,
                  key: const ValueKey<String>('rest.plus'),
                ),
                action(
                  copy.skipRest,
                  widget.onSkip,
                  key: const ValueKey<String>('rest.skip'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
