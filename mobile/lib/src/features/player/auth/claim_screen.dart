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

/// Logged-out path for an imported account: redeem the owner-issued claim code
/// to set a password and sign in, mirroring the login session (ADR 019).
///
/// The username may arrive prefilled from the login screen's claim-required
/// prompt. Every claim failure is a generic message so the endpoint's
/// account-existence secrecy is preserved, while a weak password is reported on
/// the password field.
class ClaimScreen extends ConsumerStatefulWidget {
  const ClaimScreen({super.key, this.initialUsername});

  final String? initialUsername;

  @override
  ConsumerState<ClaimScreen> createState() => _ClaimScreenState();
}

class _ClaimScreenState extends ConsumerState<ClaimScreen> {
  late final TextEditingController _username =
      TextEditingController(text: widget.initialUsername ?? '');
  final TextEditingController _code = TextEditingController();
  final TextEditingController _password = TextEditingController();
  final TextEditingController _confirm = TextEditingController();
  bool _rememberMe = false;
  bool _busy = false;
  String? _error;
  String? _passwordError;

  /// The one generic 401 message; the same for unknown account, wrong/expired
  /// code, and an already-claimed ledger (anti-enumeration, ADR 019).
  static const String _genericFailure = 'Invalid or expired claim code.';

  @override
  void dispose() {
    _username.dispose();
    _code.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  /// Prefers the server's own weak-password message; a 401 stays generic.
  String _serverError(ApiException error) {
    if (isNetworkFailure(error)) {
      return needsConnectionMessage;
    }
    final String detail = error.message.trim();
    return detail.isEmpty ? _genericFailure : detail;
  }

  Future<void> _submit() async {
    final String username = _username.text.trim();
    final String code = _code.text.trim();
    final String password = _password.text;
    setState(() {
      _error = null;
      _passwordError = null;
    });
    if (username.isEmpty) {
      setState(() => _error = 'Enter your username.');
      return;
    }
    if (code.isEmpty) {
      setState(() => _error = 'Enter the claim code from the owner.');
      return;
    }
    final String? lengthError = passwordLengthError(password);
    if (lengthError != null) {
      setState(() => _passwordError = lengthError);
      return;
    }
    final String? confirmationError =
        passwordConfirmationError(password, _confirm.text);
    if (confirmationError != null) {
      setState(() => _error = confirmationError);
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(authControllerProvider.notifier).claim(
            username: username,
            claimCode: code,
            password: password,
            rememberMe: _rememberMe,
          );
      TextInput.finishAutofillContext();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          if (error.statusCode == 400) {
            _passwordError = _serverError(error);
          } else if (error.statusCode == 401) {
            // Fixed generic message: never disclose whether the account exists.
            _error = _genericFailure;
          } else {
            _error = _serverError(error);
          }
        });
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
      title: 'Claim imported account',
      lead: 'Enter the claim code from the MAYOS owner or team and choose a '
          'password to start signing in.',
      wallpaper: true,
      message: _error == null ? null : AuthInlineNotice(message: _error!),
      primary: MayosButton(
        key: const Key('claim_submit'),
        label: 'Claim account',
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
          fieldKey: const Key('claim_username'),
          controller: _username,
          label: 'Username',
          enabled: !_busy,
          textInputAction: TextInputAction.next,
          keyboardType: TextInputType.text,
          autocorrect: false,
          autofillHints: const <String>[AutofillHints.username],
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('claim_code'),
          controller: _code,
          label: 'Claim code',
          enabled: !_busy,
          textInputAction: TextInputAction.next,
          keyboardType: TextInputType.text,
          autocorrect: false,
          enableSuggestions: false,
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('claim_password'),
          toggleKey: const Key('claim_password_toggle'),
          controller: _password,
          label: 'New password',
          helperText: 'At least 8 characters',
          errorText: _passwordError,
          textInputAction: TextInputAction.next,
          autofillHints: const <String>[AutofillHints.newPassword],
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('claim_confirm'),
          toggleKey: const Key('claim_confirm_toggle'),
          controller: _confirm,
          label: 'Confirm password',
          textInputAction: TextInputAction.done,
          autofillHints: const <String>[AutofillHints.newPassword],
          onSubmitted: (_) => _busy ? null : _submit(),
        ),
        AuthConsentRow(
          label: 'Keep me signed in',
          value: _rememberMe,
          enabled: !_busy,
          onChanged: (bool value) => setState(() => _rememberMe = value),
        ),
      ],
    );
  }
}
