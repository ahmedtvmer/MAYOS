import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/privacy_policy.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'auth_widgets.dart';
import 'google_sign_in_action.dart';
import 'google_sign_in_button.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen>
    with GoogleSignInAction<LoginScreen> {
  final TextEditingController _username = TextEditingController();
  final TextEditingController _password = TextEditingController();
  bool _rememberMe = false;
  bool _busy = false;
  FailureMessage? _error;

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
        setState(() => _error = apiFailureMessage(error));
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    final Uri uri = GoRouterState.of(context).uri;
    final bool resetJustCompleted = uri.queryParameters['reset'] == '1';
    final authState = ref.watch(authControllerProvider);
    final String? notice = authState.notice;
    return AuthScaffold(
      title: copy.logIn,
      lead: copy.signInLead,
      wallpaper: true,
      showHomeScreenInstallHint: true,
      message: googleFailure != null
          ? AuthInlineNotice(message: copy.failureMessage(googleFailure!))
          : (_error == null
              ? null
              : AuthInlineNotice(message: copy.failureMessage(_error!))),
      primary: MayosButton(
        key: const Key('login_submit'),
        label: copy.logIn,
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: copy.createAccountLink,
          onPressed: _busy
              ? null
              : () => context.go(carryingLocation(context, registerPath)),
        ),
        AuthLink(
          label: copy.forgotPasswordQuestion,
          onPressed: _busy ? null : () => context.go(forgotPasswordPath),
        ),
        AuthLink(
          key: const Key('login_privacy_policy'),
          label: copy.privacyPolicy,
          onPressed: _busy ? null : () => openPrivacyPolicy(context, ref),
        ),
      ],
      children: <Widget>[
        if (resetJustCompleted)
          AuthInlineNotice(
            kind: AuthNoticeKind.success,
            message: copy.passwordChanged,
          )
        else if (notice != null)
          AuthInlineNotice(
            kind: AuthNoticeKind.info,
            message: authState.noticeFailure == null
                ? notice
                : copy.failureMessage(authState.noticeFailure!),
          ),
        if (resetJustCompleted || notice != null)
          const SizedBox(height: MayosSpacing.md),
        GoogleSignInSection(
          key: const Key('login_google'),
          loading: googleBusy,
          onPressed: googleBusy ? null : continueWithGoogle,
          onWebOutcome: continueWithGoogleOutcome,
        ),
        MayosTextField(
          fieldKey: const Key('login_username'),
          controller: _username,
          label: copy.username,
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
          label: copy.password,
          textInputAction: TextInputAction.done,
          autofillHints: const <String>[AutofillHints.password],
          onSubmitted: (_) => _busy ? null : _submit(),
        ),
        AuthConsentRow(
          label: copy.keepMeSignedIn,
          value: _rememberMe,
          enabled: !_busy,
          onChanged: (bool value) => setState(() => _rememberMe = value),
        ),
      ],
    );
  }
}
