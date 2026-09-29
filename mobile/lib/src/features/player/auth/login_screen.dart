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

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final TextEditingController _username = TextEditingController();
  final TextEditingController _password = TextEditingController();
  bool _rememberMe = false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).login(
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
    final bool resetJustCompleted =
        GoRouterState.of(context).uri.queryParameters['reset'] == '1';
    final String? notice = ref.watch(authControllerProvider).notice;
    return AuthScaffold(
      title: 'Log in',
      lead: 'Sign in to keep training and pick up where you left off.',
      wallpaper: true,
      message: _error == null
          ? null
          : AuthInlineNotice(
              message: _error!,
            ),
      primary: MayosButton(
        key: const Key('login_submit'),
        label: 'Log in',
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: 'Create an account',
          onPressed: _busy ? null : () => context.go(registerPath),
        ),
        AuthLink(
          label: 'Forgot password?',
          onPressed: _busy ? null : () => context.go(forgotPasswordPath),
        ),
        AuthLink(
          key: const Key('login_privacy_policy'),
          label: 'Privacy policy',
          onPressed: _busy ? null : () => openPrivacyPolicy(context, ref),
        ),
      ],
      children: <Widget>[
        if (resetJustCompleted)
          const AuthInlineNotice(
            kind: AuthNoticeKind.success,
            message: 'Password changed. Sign in with your new password.',
          )
        else if (notice != null)
          AuthInlineNotice(kind: AuthNoticeKind.info, message: notice),
        if (resetJustCompleted || notice != null)
          const SizedBox(height: MayosSpacing.md),
        GoogleSignInSection(
          key: const Key('login_google'),
          loading: _busy,
          onPressed: _busy ? null : _continueWithGoogle,
        ),
        MayosTextField(
          fieldKey: const Key('login_username'),
          controller: _username,
          label: 'Username',
          enabled: !_busy,
          textInputAction: TextInputAction.next,
          keyboardType: TextInputType.text,
          autofillHints: const <String>[AutofillHints.username],
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('login_password'),
          toggleKey: const Key('login_password_toggle'),
          controller: _password,
          textInputAction: TextInputAction.done,
          autofillHints: const <String>[AutofillHints.password],
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
