import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/active_workout.dart';
import '../../../core/rest_length.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';

/// The exercise card's rest chip (#125): a compact "Rest m:ss" (or
/// "Rest Off") pill that opens the rest-length picker.
class RestLengthChip extends StatelessWidget {
  const RestLengthChip({
    super.key,
    required this.seconds,
    required this.onPressed,
  });

  /// The resolved rest length: 0 means Off.
  final int seconds;

  final VoidCallback onPressed;

  String get _label => seconds <= 0 ? 'Rest Off' : 'Rest ${restMmSs(seconds)}';

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    // The pill stays compact; the tappable area around it is a full 48dp
    // (#158), so the chip meets the accessibility guidance without growing
    // into a fat button.
    return InkWell(
      onTap: onPressed,
      borderRadius: MayosRadii.pillRadius,
      child: SizedBox(
        height: kMayosMinTapTarget,
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.sm, vertical: MayosSpacing.xxs),
            decoration: BoxDecoration(
              color: c.selectedSurface,
              borderRadius: MayosRadii.pillRadius,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Icon(Icons.timer_outlined,
                    size: MayosIconSizes.small, color: c.accent),
                const SizedBox(width: MayosSpacing.xxs),
                Text(
                  _label,
                  style: MayosTypography.captionStrong.copyWith(color: c.accent),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

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
                      horizontal: MayosSpacing.lg, vertical: MayosSpacing.sm),
                  child: Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          seconds <= 0 ? 'Off' : restMmSs(seconds),
                          style: selected
                              ? MayosTypography.bodySecondary.copyWith(
                                  color: MayosTheme.of(context).accent)
                              : MayosTypography.bodySecondary,
                        ),
                      ),
                      if (selected)
                        Icon(Icons.check,
                            size: MayosIconSizes.medium,
                            color: MayosTheme.of(context).accent),
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
/// Every tick reads [ActiveRestTimer] against the wall clock, so the count
/// is exact in the foreground instead of drifting with timer ticks. The
/// end-of-rest alert stays with the logger's own ticker (#125), which keeps
/// running even when this row is hidden behind the keypad.
class RestTimerControls extends StatefulWidget {
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
  State<RestTimerControls> createState() => _RestTimerControlsState();
}

class _RestTimerControlsState extends State<RestTimerControls> {
  /// The countdown's own quarter-second tick: it wakes this row alone, so a
  /// running rest costs one small repaint instead of the whole screen
  /// (#160).
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    _ticker =
        Timer.periodic(const Duration(milliseconds: 250), (_) => _onTick());
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
  /// the wall clock.
  int get _remainingSeconds => widget.rest.remainingSeconds(DateTime.now());

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
                  style: MayosTypography.label.copyWith(color: c.accent),
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
              alignment: Alignment.centerLeft,
              widthFactor: _fill,
              // The draining fill: the rest's own accent wash, a token rather
              // than a raw alpha (DESIGN.md).
              child: ColoredBox(color: c.accentWash),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: Row(
              children: <Widget>[
                action('−15', widget.onMinus,
                    key: const ValueKey<String>('rest.minus')),
                Expanded(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(
                        restMmSs(_remainingSeconds),
                        style: MayosTypography.numericMedium
                            .copyWith(color: c.textPrimary),
                      ),
                      Text(
                        'Rest · ${widget.rest.exerciseName}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: MayosTypography.caption
                            .copyWith(color: c.textMuted),
                      ),
                    ],
                  ),
                ),
                action('+15', widget.onPlus,
                    key: const ValueKey<String>('rest.plus')),
                action('Skip', widget.onSkip,
                    key: const ValueKey<String>('rest.skip')),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
