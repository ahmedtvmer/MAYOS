import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
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

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final String token = _code.text.trim();
    if (token.length < 10) {
      setState(() => _error = 'Enter your MAYOS coach code.');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
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
          _error = error.message;
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
          label: 'MAYOS coach code',
          errorText: _error,
        ),
        const SizedBox(height: MayosSpacing.lg),
        MayosButton(
          key: widget.submitButtonKey,
          label: 'Enable coaching',
          loading: _submitting,
          onPressed: _submit,
        ),
      ],
    );
  }
}
