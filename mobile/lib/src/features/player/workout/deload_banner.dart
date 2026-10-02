import 'package:flutter/material.dart';

import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
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
    final MayosCopy copy = displayCopyOf(context);
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      color: colors.accentSubtle,
      borderColor: colors.selectedBorder,
      child: _bannerContents(colors, copy),
    );
  }

  Widget _bannerContents(
    MayosThemeExtension colors,
    MayosCopy copy,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        _title(colors, copy),
        const SizedBox(height: MayosSpacing.xs),
        Text(
          decision.reason ?? copy.fatigueSignalDetected,
          style: MayosTypography.bodySecondary.copyWith(
            color: colors.textSecondary,
          ),
        ),
        const SizedBox(height: MayosSpacing.xs),
        Text(
          copy.isArabic
              ? copy.deloadChangeSummary(
                  applied: decision.isApplied,
                  suggested: decision.isSuggested,
                  volumeMultiplier: decision.volumeMultiplier,
                  intensityCapRpe: decision.intensityCapRpe,
                )
              : decision.changeSummary,
          textDirection: copy.isArabic ? TextDirection.ltr : null,
          textAlign: copy.isArabic ? TextAlign.end : null,
          style: MayosTypography.bodySecondary.copyWith(
            color: colors.textPrimary,
          ),
        ),
        _assistantButton(colors, copy),
      ],
    );
  }

  Widget _title(MayosThemeExtension colors, MayosCopy copy) => Row(
        children: <Widget>[
          Icon(Icons.battery_alert_outlined, color: colors.accent),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              copy.isArabic
                  ? decision.isApplied
                      ? copy.deloadApplied
                      : copy.deloadSuggested
                  : decision.title,
              style: MayosTypography.sectionHeading.copyWith(
                color: colors.textPrimary,
              ),
            ),
          ),
        ],
      );

  Widget _assistantButton(
    MayosThemeExtension colors,
    MayosCopy copy,
  ) =>
      Align(
        alignment: AlignmentDirectional.centerStart,
        child: TextButton.icon(
          key: const ValueKey<String>('deload_banner.chat'),
          onPressed: onOpenAssistant,
          icon: const Icon(Icons.chat_bubble_outline, size: 18),
          label: Text(copy.askAssistant),
          style: TextButton.styleFrom(foregroundColor: colors.accent),
        ),
      );
}
