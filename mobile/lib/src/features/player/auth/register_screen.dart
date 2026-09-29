import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/privacy_policy.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'auth_controller.dart';
import 'auth_widgets.dart';
import 'google_sign_in_button.dart';

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final TextEditingController _username = TextEditingController();
  final TextEditingController _password = TextEditingController();
  final TextEditingController _confirm = TextEditingController();
  bool _rememberMe = false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final String? passwordError =
        validateNewPassword(_password.text, _confirm.text);
    if (passwordError != null) {
      setState(() => _error = passwordError);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).register(
            username: _username.text.trim(),
            password: _password.text,
            rememberMe: _rememberMe,
          );
      TextInput.finishAutofillContext();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.message);
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  /// "Continue with Google": a linked subject signs in here, any other
  /// subject continues into the username picker (#115).
  Future<void> _continueWithGoogle() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ContinueWithGoogleResult result =
          await ref.read(authControllerProvider.notifier).continueWithGoogle();
      if (!mounted) {
        return;
      }
      switch (result) {
        case GoogleSignUpPrompt():
          context.go(googleSignupPath);
        case GoogleSignInRefused(:final message):
          setState(() => _error = message);
        case GoogleSignInDone():
        case GoogleSignInDismissed():
          break;
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
      title: 'Create account',
      lead: 'Set up your MAYOS account to start training.',
      wallpaper: true,
      message: _error == null ? null : AuthInlineNotice(message: _error!),
      primary: MayosButton(
        key: const Key('register_submit'),
        label: 'Create account',
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: 'I already have an account',
          onPressed: _busy ? null : () => context.go(loginPath),
        ),
      ],
      children: <Widget>[
        GoogleSignInSection(
          key: const Key('register_google'),
          loading: _busy,
          onPressed: _busy ? null : _continueWithGoogle,
        ),
        MayosTextField(
          fieldKey: const Key('register_username'),
          controller: _username,
          label: 'Username',
          enabled: !_busy,
          textInputAction: TextInputAction.next,
          keyboardType: TextInputType.text,
          autofillHints: const <String>[AutofillHints.newUsername],
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('register_password'),
          toggleKey: const Key('register_password_toggle'),
          controller: _password,
          helperText: 'At least 8 characters',
          textInputAction: TextInputAction.next,
          autofillHints: const <String>[AutofillHints.newPassword],
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('register_confirm'),
          toggleKey: const Key('register_confirm_toggle'),
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
        // The policy link sits with the consent control, not in the action bar,
        // so the disclosure is read where the account is created (#43).
        const SizedBox(height: MayosSpacing.xs),
        AuthLink(
          key: const Key('register_privacy_policy'),
          label: 'Privacy policy',
          onPressed: _busy ? null : () => openPrivacyPolicy(context, ref),
        ),
      ],
    );
  }
}
