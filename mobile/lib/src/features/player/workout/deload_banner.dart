import 'package:flutter/material.dart';

import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
import '../../../core/ui/myos_card.dart';

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
    final MyosThemeExtension colors = MyosTheme.of(context);
    final MyosCopy copy = displayCopyOf(context);
    return MyosCard(
      padding: const EdgeInsets.all(MyosSpacing.md),
      color: colors.accentSubtle,
      borderColor: colors.selectedBorder,
      child: _bannerContents(context, colors, copy),
    );
  }

  Widget _bannerContents(
    BuildContext context,
    MyosThemeExtension colors,
    MyosCopy copy,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        _title(context, colors, copy),
        const SizedBox(height: MyosSpacing.xs),
        Text(
          decision.reason ?? copy.fatigueSignalDetected,
          style: MyosTypography.of(context).bodySecondary.copyWith(
            color: colors.textSecondary,
          ),
        ),
        const SizedBox(height: MyosSpacing.xs),
        Text(
          copy.isArabic
              ? copy.deloadChangeSummary(
                  applied: decision.isApplied,
                  suggested: decision.isSuggested,
                  volumeMultiplier: decision.volumeMultiplier,
                  intensityCapRpe: decision.intensityCapRpe,
                )
              : decision.changeSummary,
          textAlign: copy.isArabic ? TextAlign.end : null,
          style: MyosTypography.of(context).bodySecondary.copyWith(
            color: colors.textPrimary,
          ),
        ),
        _assistantButton(colors, copy),
      ],
    );
  }

  Widget _title(
    BuildContext context,
    MyosThemeExtension colors,
    MyosCopy copy,
  ) => Row(
        children: <Widget>[
          Icon(Icons.battery_alert_outlined, color: colors.accent),
          const SizedBox(width: MyosSpacing.xs),
          Expanded(
            child: Text(
              copy.isArabic
                  ? decision.isApplied
                      ? copy.deloadApplied
                      : copy.deloadSuggested
                  : decision.title,
              style: MyosTypography.of(context).sectionHeading.copyWith(
                color: colors.textPrimary,
              ),
            ),
          ),
        ],
      );

  Widget _assistantButton(
    MyosThemeExtension colors,
    MyosCopy copy,
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
