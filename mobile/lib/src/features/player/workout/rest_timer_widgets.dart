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
    return InkWell(
      onTap: onPressed,
      borderRadius: MayosRadii.pillRadius,
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
            Icon(Icons.timer_outlined, size: 14, color: c.accent),
            const SizedBox(width: MayosSpacing.xxs),
            Text(
              _label,
              style: MayosTypography.captionStrong.copyWith(color: c.accent),
            ),
          ],
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
                      horizontal: MayosSpacing.lg,
                      vertical: MayosSpacing.sm),
                  child: Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          seconds <= 0
                              ? 'Off'
                              : restMmSs(seconds),
                          style: selected
                              ? MayosTypography.bodySecondary
                                  .copyWith(color: MayosTheme.of(context).accent)
                              : MayosTypography.bodySecondary,
                        ),
                      ),
                      if (selected)
                        Icon(Icons.check,
                            size: 20, color: MayosTheme.of(context).accent),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );

/// The slim rest bar pinned to the bottom of the logger, shown only while the
/// keypad is hidden (#125): **−15 · m:ss + "Rest · <exercise>" · +15 · Skip**,
/// with a draining fill behind it.
///
/// [remaining] is recomputed from the wall clock on every rebuild by the
/// logger's ticker, so the countdown is exact in the foreground rather than
/// drifting with timer ticks.
class RestTimerBar extends StatelessWidget {
  const RestTimerBar({
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
    Widget action(String label, VoidCallback onTap, {Key? key}) => InkWell(
          key: key,
          onTap: onTap,
          borderRadius: MayosRadii.smallRadius,
          child: Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.sm, vertical: MayosSpacing.sm),
            child: Text(
              label,
              style: MayosTypography.label.copyWith(color: c.accent),
            ),
          ),
        );

    return Container(
      key: const ValueKey<String>('rest.bar'),
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.border)),
      ),
      child: Stack(
        children: <Widget>[
          // The draining fill: the time still left, from the left edge.
          Positioned.fill(
            child: FractionallySizedBox(
              alignment: Alignment.centerLeft,
              widthFactor: _fill,
              child: ColoredBox(color: c.accent.withValues(alpha: 0.14)),
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
                        style:
                            MayosTypography.caption.copyWith(color: c.textMuted),
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
