import 'package:flutter/material.dart';

import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/display_language/program_change_copy.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';

class ProgramChangeSummaryCard extends StatelessWidget {
  const ProgramChangeSummaryCard({
    super.key,
    required this.summary,
    this.onViewProgram,
    this.message,
    this.onDismiss,
  });

  final Map<String, dynamic> summary;
  final String? message;
  final VoidCallback? onViewProgram;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final ProgramChangeCopy copy = programChangeCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    final bool unchanged = summary['unchanged'] == true;
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _heading(context, copy, colors, unchanged),
          if (message != null) _noticeMessage(context, colors),
          ..._changeLines(context, copy, colors, unchanged),
          _actions(copy),
        ],
      ),
    );
  }

  Widget _heading(
    BuildContext context,
    ProgramChangeCopy copy,
    MayosThemeExtension colors,
    bool unchanged,
  ) =>
      unchanged
          ? _text(context, copy.approvedAsIs, colors.textPrimary)
          : Text(copy.heading, style: MayosTypography.sectionHeading);

  Widget _noticeMessage(BuildContext context, MayosThemeExtension colors) =>
      Padding(
        padding: const EdgeInsets.only(top: MayosSpacing.xs),
        child: _text(context, message!, colors.textSecondary),
      );

  List<Widget> _changeLines(
    BuildContext context,
    ProgramChangeCopy copy,
    MayosThemeExtension colors,
    bool unchanged,
  ) {
    if (unchanged) return const <Widget>[];
    final List<Map<String, dynamic>> changes = _changes();
    return <Widget>[
      const SizedBox(height: MayosSpacing.sm),
      for (final Map<String, dynamic> change in changes.take(10))
        _changeLine(context, copy, colors, change),
      if (changes.length > 10)
        _text(context, copy.andMore(changes.length - 10), colors.textSecondary),
    ];
  }

  Widget _changeLine(
    BuildContext context,
    ProgramChangeCopy copy,
    MayosThemeExtension colors,
    Map<String, dynamic> change,
  ) =>
      Padding(
        padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
        child: _text(context, '• ${copy.line(change)}', colors.textPrimary),
      );

  Widget _actions(ProgramChangeCopy copy) =>
      Padding(
        padding: const EdgeInsets.only(top: MayosSpacing.sm),
        child: Wrap(
          spacing: MayosSpacing.xs,
          children: <Widget>[
            if (onViewProgram != null)
              MayosButton(
                label: copy.viewProgram,
                variant: MayosButtonVariant.secondary,
                expand: false,
                onPressed: onViewProgram,
              ),
            if (onDismiss != null)
              MayosButton(
                label: copy.dismiss,
                variant: MayosButtonVariant.tertiary,
                expand: false,
                onPressed: onDismiss,
              ),
          ],
        ),
      );

  List<Map<String, dynamic>> _changes() {
    final dynamic rawChanges = summary['changes'];
    if (rawChanges is! List) return const <Map<String, dynamic>>[];
    return rawChanges.whereType<Map<String, dynamic>>().toList();
  }

  Widget _text(BuildContext context, String text, Color color) =>
      FirstStrongDirection(
        text: text,
        child: Text(
          text,
          textAlign: TextAlign.start,
          style: MayosTypography.bodySecondary.copyWith(color: color),
        ),
      );
}
