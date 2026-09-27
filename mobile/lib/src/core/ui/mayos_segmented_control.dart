import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

/// One option in a [MayosSegmentedControl].
class MayosSegment<T> {
  const MayosSegment({
    required this.value,
    required this.label,
    this.icon,
  });

  final T value;
  final String label;
  final IconData? icon;
}

/// A polished segmented selector for a small, exclusive set of choices.
///
/// Used for the appearance control; deliberately not a debug switch.
class MayosSegmentedControl<T> extends StatelessWidget {
  const MayosSegmentedControl({
    super.key,
    required this.segments,
    required this.selected,
    required this.onChanged,
  });

  final List<MayosSegment<T>> segments;
  final T selected;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(MayosSpacing.xxs),
      decoration: BoxDecoration(
        color: c.surfaceSunken,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: c.border),
      ),
      child: Row(
        children: <Widget>[
          for (final MayosSegment<T> segment in segments)
            Expanded(
              child: _SegmentButton<T>(
                segment: segment,
                selected: segment.value == selected,
                onTap: () => onChanged(segment.value),
                textTheme: text,
              ),
            ),
        ],
      ),
    );
  }
}

class _SegmentButton<T> extends StatelessWidget {
  const _SegmentButton({
    required this.segment,
    required this.selected,
    required this.onTap,
    required this.textTheme,
  });

  final MayosSegment<T> segment;
  final bool selected;
  final VoidCallback onTap;
  final TextTheme textTheme;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Semantics(
      button: true,
      selected: selected,
      label: segment.label,
      excludeSemantics: true,
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOutCubic,
          constraints: const BoxConstraints(minHeight: 44),
          padding: const EdgeInsets.symmetric(
              horizontal: MayosSpacing.xs, vertical: MayosSpacing.sm),
          decoration: BoxDecoration(
            color: selected ? c.surfaceElevated : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: selected ? c.selectedBorder : Colors.transparent,
              width: 1.2,
            ),
            boxShadow: selected ? c.shadows : null,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: <Widget>[
              if (segment.icon != null) ...<Widget>[
                Icon(
                  segment.icon,
                  size: 17,
                  color: selected ? c.accent : c.textMuted,
                ),
                const SizedBox(width: 6),
              ],
              Flexible(
                child: Text(
                  segment.label,
                  overflow: TextOverflow.ellipsis,
                  style: textTheme.labelSmall?.copyWith(
                    color: selected ? c.accent : c.textSecondary,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
