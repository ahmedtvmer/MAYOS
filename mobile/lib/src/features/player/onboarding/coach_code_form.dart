import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';

/// Shared account-bound Coach invite redemption form for onboarding and Settings.
class CoachCodeForm extends ConsumerStatefulWidget {
  const CoachCodeForm({
    super.key,
    required this.description,
    required this.onRedeemed,
    this.fieldKey,
    this.submitButtonKey,
  });

  final String description;
  final VoidCallback onRedeemed;
  final Key? fieldKey;
  final Key? submitButtonKey;

  @override
  ConsumerState<CoachCodeForm> createState() => _CoachCodeFormState();
}

class _CoachCodeFormState extends ConsumerState<CoachCodeForm> {
  final TextEditingController _code = TextEditingController();
  bool _submitting = false;
  String? _error;
  FailureMessage? _failure;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final String token = _code.text.trim();
    if (token.length < 10) {
      setState(() => _error = displayCopyOf(context).enterCoachCodeLead);
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
      _failure = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).redeemCoachInvite(token);
      if (mounted) {
        widget.onRedeemed();
      }
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _failure = apiFailureMessage(error);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(
          widget.description,
          style: Theme.of(context)
              .textTheme
              .bodyMedium
              ?.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: widget.fieldKey,
          controller: _code,
          autocorrect: false,
          enableSuggestions: false,
          textDirection: TextDirection.ltr,
          label: displayCopyOf(context).coachCode,
          errorText: _failure == null
              ? _error
              : displayCopyOf(context).failureMessage(_failure!),
        ),
        const SizedBox(height: MayosSpacing.lg),
        MayosButton(
          key: widget.submitButtonKey,
          label: displayCopyOf(context).enableCoaching,
          loading: _submitting,
          onPressed: _submit,
        ),
      ],
    );
  }
}
