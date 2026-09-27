import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'auth_widgets.dart';

/// Logged-out entry point: submit an email and always see the same confirmation
/// (anti-enumeration), whether or not the email is linked (ADR 007/037).
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final TextEditingController _email = TextEditingController();
  bool _busy = false;
  String? _error;
  String? _confirmation;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
      _confirmation = null;
    });
    try {
      final String message = await ref
          .read(authControllerProvider.notifier)
          .requestPasswordReset(_email.text.trim());
      if (mounted) {
        setState(() => _confirmation = message);
      }
      TextInput.finishAutofillContext();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = mutationFailureMessage(error));
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AuthScaffold(
      title: 'Forgot password',
      lead: 'Enter your recovery email and we will send a reset link. '
          'Open it on this device to choose a new password.',
      wallpaper: true,
      message: _error == null ? null : AuthInlineNotice(message: _error!),
      primary: MayosButton(
        key: const Key('forgot_submit'),
        label: 'Send reset link',
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: 'Back to log in',
          onPressed: _busy ? null : () => context.go(loginPath),
        ),
      ],
      children: <Widget>[
        MayosTextField(
          fieldKey: const Key('forgot_email'),
          controller: _email,
          label: 'Email',
          enabled: !_busy,
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.done,
          autocorrect: false,
          autofillHints: const <String>[AutofillHints.email],
          onSubmitted: (_) => _busy ? null : _submit(),
        ),
        if (_confirmation != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          AuthInlineNotice(
            kind: AuthNoticeKind.success,
            message: _confirmation!,
          ),
        ],
      ],
    );
  }
}
