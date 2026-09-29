import 'package:flutter/material.dart';

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
/// [remainingSeconds] is recomputed from the wall clock on every rebuild by
/// the logger's ticker, so the countdown is exact in the foreground rather
/// than drifting with timer ticks.
class RestTimerControls extends StatelessWidget {
  const RestTimerControls({
    super.key,
    required this.remainingSeconds,
    required this.totalSeconds,
    required this.exerciseName,
    required this.onMinus,
    required this.onPlus,
    required this.onSkip,
  });

  /// Whole seconds left (already rounded up, 0 at the end).
  final int remainingSeconds;

  /// The length the rest started with — the draining fill's denominator.
  final int totalSeconds;

  final String exerciseName;
  final VoidCallback onMinus;
  final VoidCallback onPlus;
  final VoidCallback onSkip;

  double get _fill {
    if (totalSeconds <= 0) {
      return 0;
    }
    final double fraction = remainingSeconds / totalSeconds;
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
                action('−15', onMinus,
                    key: const ValueKey<String>('rest.minus')),
                Expanded(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(
                        restMmSs(remainingSeconds),
                        style: MayosTypography.numericMedium
                            .copyWith(color: c.textPrimary),
                      ),
                      Text(
                        'Rest · $exerciseName',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: MayosTypography.caption
                            .copyWith(color: c.textMuted),
                      ),
                    ],
                  ),
                ),
                action('+15', onPlus, key: const ValueKey<String>('rest.plus')),
                action('Skip', onSkip,
                    key: const ValueKey<String>('rest.skip')),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
