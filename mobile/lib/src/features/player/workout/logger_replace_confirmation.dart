import 'package:flutter/material.dart';

import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';

class LoggerReplaceConfirmation {
  const LoggerReplaceConfirmation({
    required this.confirmed,
    this.keepInProgram = false,
    this.reason,
  });

  final bool confirmed;
  final bool keepInProgram;
  final String? reason;
}

/// Confirmation shown before opening the replacement picker when logged sets
/// need discarding or a live program action is available.
class LoggerReplaceConfirmationDialog extends StatefulWidget {
  const LoggerReplaceConfirmationDialog({
    required this.tickedSetCount,
    required this.programActionAvailable,
    required this.coachControlled,
    super.key,
  });

  final int tickedSetCount;
  final bool programActionAvailable;
  final bool coachControlled;

  @override
  State<LoggerReplaceConfirmationDialog> createState() =>
      _LoggerReplaceConfirmationDialogState();
}

class LoggerCoachRequestReasonPrompt extends StatelessWidget {
  const LoggerCoachRequestReasonPrompt({
    required this.controller,
    required this.reasonRequired,
    required this.submitting,
    required this.onSubmit,
    super.key,
  });

  final TextEditingController controller;
  final bool reasonRequired;
  final bool submitting;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md,
          vertical: MayosSpacing.xs,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            TextField(
              key: const ValueKey<String>('logger.refreshedCoachReasonField'),
              controller: controller,
              minLines: 2,
              maxLines: 3,
              maxLength: 500,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                labelText: workoutCopyOf(context).reasonForCoach,
                errorText: reasonRequired
                    ? workoutCopyOf(context).addReasonToContinue
                    : null,
              ),
            ),
            const SizedBox(height: MayosSpacing.xs),
            MayosButton(
              key: const ValueKey<String>('logger.refreshedCoachSubmit'),
              label: submitting
                  ? workoutCopyOf(context).sending
                  : workoutCopyOf(context).sendRequest,
              onPressed: submitting ? null : onSubmit,
            ),
          ],
        ),
      );
}

class _LoggerReplaceConfirmationDialogState
    extends State<LoggerReplaceConfirmationDialog> {
  final TextEditingController _reason = TextEditingController();
  bool _keepInProgram = false;
  bool _reasonRequired = false;

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final WorkoutCopy copy = workoutCopyOf(context);
    final int ticked = widget.tickedSetCount;
    final String optionLabel = widget.coachControlled
        ? copy.askCoachToMakePermanent
        : copy.keepSwapInProgram;
    final bool asksCoach = widget.coachControlled && _keepInProgram;
    return AlertDialog(
      key: const ValueKey<String>('logger.replaceConfirmation'),
      title: Text(ticked == 0
          ? copy.replaceQuestion
          : copy.discardSetsQuestion(ticked)),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 360),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              if (ticked > 0)
                Padding(
                  padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
                  child: Text(
                    copy.loggedSetsCleared,
                    style: MayosTypography.bodySecondary
                        .copyWith(color: colors.textPrimary),
                  ),
                ),
              if (widget.programActionAvailable)
                CheckboxListTile(
                  key: const ValueKey<String>('logger.keepSwapCheckbox'),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  value: _keepInProgram,
                  title: Text(
                    optionLabel,
                    style: MayosTypography.body
                        .copyWith(color: colors.textPrimary),
                  ),
                  onChanged: (bool? value) => setState(() {
                    _keepInProgram = value ?? false;
                    _reasonRequired = false;
                  }),
                ),
              if (asksCoach) ...<Widget>[
                const SizedBox(height: MayosSpacing.xs),
                TextField(
                  key: const ValueKey<String>('logger.keepSwapReasonField'),
                  controller: _reason,
                  minLines: 2,
                  maxLines: 3,
                  maxLength: 500,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: InputDecoration(
                    labelText: copy.reasonForCoach,
                    errorText:
                        _reasonRequired ? copy.addReasonToContinue : null,
                  ),
                  onChanged: (_) {
                    if (_reasonRequired && _reason.text.trim().isNotEmpty) {
                      setState(() => _reasonRequired = false);
                    }
                  },
                ),
              ],
            ],
          ),
        ),
      ),
      actions: <Widget>[
        MayosButton(
          label: ticked == 0 ? copy.cancel : copy.keepLogging,
          variant: MayosButtonVariant.secondary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(
            const LoggerReplaceConfirmation(confirmed: false),
          ),
        ),
        MayosButton(
          label: copy.replace,
          destructive: ticked > 0,
          expand: false,
          onPressed: () {
            final String reason = _reason.text.trim();
            if (asksCoach && reason.isEmpty) {
              setState(() => _reasonRequired = true);
              return;
            }
            Navigator.of(context).pop(LoggerReplaceConfirmation(
              confirmed: true,
              keepInProgram: _keepInProgram,
              reason: asksCoach ? reason : null,
            ));
          },
        ),
      ],
    );
  }
}
