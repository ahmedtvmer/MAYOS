import 'package:flutter/material.dart';

import '../../../core/display_language/copy_context.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../../../core/ui/mayos_card.dart';

class PreparingProgramBanner extends StatelessWidget {
  const PreparingProgramBanner({super.key, required this.coachName});

  final String coachName;

  @override
  Widget build(BuildContext context) {
    final String message =
        displayCopyOf(context).coachPreparingProgram(coachName);
    return MayosCard(child: _messageContent(context, message));
  }

  Widget _messageContent(BuildContext context, String message) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(Icons.edit_note_outlined, color: colors.accent),
        const SizedBox(width: MayosSpacing.sm),
        Expanded(
          child: FirstStrongDirection(
            text: message,
            child: Text(
              message,
              style: MayosTypography.bodySecondary
                  .copyWith(color: colors.textPrimary),
            ),
          ),
        ),
      ],
    );
  }
}
