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

/// Logged-out reset screen for the App Link / hosted fallback.
///
/// The single-use token arrives in the query string (``/reset-password?token=``);
/// on success the local session is dropped and the app routes to login. On
/// failure the service's one generic message is shown and a new link can be
/// requested (ADR 007/037).
class ResetPasswordScreen extends ConsumerStatefulWidget {
  const ResetPasswordScreen({super.key, required this.token});

  final String token;

  @override
  ConsumerState<ResetPasswordScreen> createState() =>
      _ResetPasswordScreenState();
}

class _ResetPasswordScreenState extends ConsumerState<ResetPasswordScreen> {
  /// Used only when there is no token to submit and no server detail to show;
  /// the server's own generic message is shown verbatim whenever it responds.
  static const String _genericFallback =
      'Could not reset the password. Request a new link.';

  late final TextEditingController _token =
      TextEditingController(text: widget.token);
  final TextEditingController _password = TextEditingController();
  final TextEditingController _confirm = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _token.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  /// Prefers the server's own `detail`; falls back only when none is present.
  String _errorMessage(ApiException error) {
    if (isNetworkFailure(error)) {
      return needsConnectionMessage;
    }
    final String detail = error.message.trim();
    return detail.isEmpty ? _genericFallback : detail;
  }

  Future<void> _submit() async {
    final String token = _token.text.trim();
    final String password = _password.text;
    setState(() => _error = null);
    if (token.isEmpty) {
      setState(() => _error = _genericFallback);
      return;
    }
    if (password.length < 8) {
      setState(() => _error = 'Use at least 8 characters.');
      return;
    }
    if (password != _confirm.text) {
      setState(() => _error = 'The passwords do not match.');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref
          .read(authControllerProvider.notifier)
          .completePasswordReset(token: token, newPassword: password);
      TextInput.finishAutofillContext();
      if (mounted) {
        context.go('$loginPath?reset=1');
      }
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = _errorMessage(error));
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
      title: 'Reset password',
      lead: 'Choose a new password for your account.',
      message: _error == null ? null : AuthInlineNotice(message: _error!),
      primary: MayosButton(
        key: const Key('reset_submit'),
        label: 'Set new password',
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: 'Request a new link',
          onPressed: _busy ? null : () => context.go(forgotPasswordPath),
        ),
      ],
      children: <Widget>[
        MayosTextField(
          fieldKey: const Key('reset_token'),
          controller: _token,
          label: 'Reset code',
          readOnly: true,
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('reset_password'),
          toggleKey: const Key('reset_password_toggle'),
          controller: _password,
          label: 'New password',
          helperText: 'At least 8 characters',
          textInputAction: TextInputAction.next,
          autofillHints: const <String>[AutofillHints.newPassword],
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('reset_confirm'),
          toggleKey: const Key('reset_confirm_toggle'),
          controller: _confirm,
          label: 'Confirm password',
          textInputAction: TextInputAction.done,
          autofillHints: const <String>[AutofillHints.newPassword],
          onSubmitted: (_) => _busy ? null : _submit(),
        ),
      ],
    );
  }
}
