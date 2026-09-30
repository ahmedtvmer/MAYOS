import 'package:flutter/material.dart';

import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_card.dart';

class DeloadBanner extends StatelessWidget {
  const DeloadBanner({
    super.key,
    required this.decision,
    required this.onOpenAssistant,
  });

  final DeloadDecision decision;
  final VoidCallback onOpenAssistant;

  @override
  Widget build(BuildContext context) {
    if (!decision.isVisible) return const SizedBox.shrink();
    final MayosThemeExtension colors = MayosTheme.of(context);
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      color: colors.accentSubtle,
      borderColor: colors.selectedBorder,
      child: _bannerContents(colors),
    );
  }

  Widget _bannerContents(MayosThemeExtension colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        _title(colors),
        const SizedBox(height: MayosSpacing.xs),
        Text(
          decision.reason ?? 'Fatigue signal detected.',
          style: MayosTypography.bodySecondary.copyWith(
            color: colors.textSecondary,
          ),
        ),
        const SizedBox(height: MayosSpacing.xs),
        Text(
          decision.changeSummary,
          style: MayosTypography.bodySecondary.copyWith(
            color: colors.textPrimary,
          ),
        ),
        _assistantButton(colors),
      ],
    );
  }

  Widget _title(MayosThemeExtension colors) => Row(
        children: <Widget>[
          Icon(Icons.battery_alert_outlined, color: colors.accent),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              decision.title,
              style: MayosTypography.sectionHeading.copyWith(
                color: colors.textPrimary,
              ),
            ),
          ),
        ],
      );

  Widget _assistantButton(MayosThemeExtension colors) => Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(
          key: const ValueKey<String>('deload_banner.chat'),
          onPressed: onOpenAssistant,
          icon: const Icon(Icons.chat_bubble_outline, size: 18),
          label: const Text('Ask the assistant'),
          style: TextButton.styleFrom(foregroundColor: colors.accent),
        ),
      );
}
