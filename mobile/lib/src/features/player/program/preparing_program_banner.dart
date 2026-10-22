import 'package:flutter/material.dart';

import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../../../core/ui/myos_card.dart';

class PreparingProgramBanner extends StatelessWidget {
  const PreparingProgramBanner({super.key, required this.assignment});

  final Assignment assignment;

  @override
  Widget build(BuildContext context) {
    final String message =
        displayCopyOf(context)
            .coachPreparingProgram(assignment.coach.displayName);
    return MyosCard(child: _messageContent(context, message));
  }

  Widget _messageContent(BuildContext context, String message) {
    final MyosThemeExtension colors = MyosTheme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(Icons.edit_note_outlined, color: colors.accent),
        const SizedBox(width: MyosSpacing.sm),
        Expanded(
          child: FirstStrongDirection(
            text: message,
            child: Text(
              message,
              style: MyosTypography.of(context).bodySecondary
                  .copyWith(color: colors.textPrimary),
            ),
          ),
        ),
      ],
    );
  }
}
