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

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen>
    with GoogleSignInAction<RegisterScreen> {
  final TextEditingController _username = TextEditingController();
  final TextEditingController _password = TextEditingController();
  final TextEditingController _confirm = TextEditingController();
  final TextEditingController _coachInviteCode = TextEditingController();
  bool _rememberMe = false;
  bool _showCoachInviteCode = false;
  bool _busy = false;
  String? _error;
  FailureMessage? _apiFailure;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    _confirm.dispose();
    _coachInviteCode.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final NewPasswordValidation? passwordError =
        validateNewPassword(_password.text, _confirm.text);
    if (passwordError != null) {
      final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
      setState(() => _apiFailure = null);
      setState(
          () => _error = newPasswordValidationMessage(passwordError, copy));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _apiFailure = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).register(
            username: _username.text.trim(),
            password: _password.text,
            rememberMe: _rememberMe,
            coachInviteCode:
                _showCoachInviteCode && _coachInviteCode.text.trim().isNotEmpty
                    ? _coachInviteCode.text.trim()
                    : null,
            displayLanguage: ref.read(displayLanguageProvider),
          );
      TextInput.finishAutofillContext();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _apiFailure = apiFailureMessage(error));
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
    return AuthScaffold(
      title: copy.createAccount,
      lead: copy.registerLead,
      wallpaper: true,
      showHomeScreenInstallHint: true,
      message: googleFailure != null
          ? AuthInlineNotice(message: copy.failureMessage(googleFailure!))
          : (_apiFailure != null
              ? AuthInlineNotice(message: copy.failureMessage(_apiFailure!))
              : (_error == null ? null : AuthInlineNotice(message: _error!))),
      primary: MayosButton(
        key: const Key('register_submit'),
        label: copy.createAccount,
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: copy.alreadyHaveAccount,
          onPressed: _busy
              ? null
              : () => context.go(carryingLocation(context, loginPath)),
        ),
        AuthLink(
          key: const Key('register_coach_invite_toggle'),
          label: _showCoachInviteCode
              ? copy.hideCoachInvite
              : copy.iHaveCoachInvite,
          onPressed: _busy
              ? null
              : () => setState(() {
                    _showCoachInviteCode = !_showCoachInviteCode;
                    if (!_showCoachInviteCode) _coachInviteCode.clear();
                  }),
        ),
      ],
      children: <Widget>[
        GoogleSignInSection(
          key: const Key('register_google'),
          loading: googleBusy,
          onPressed: googleBusy ? null : continueWithGoogle,
          onWebOutcome: continueWithGoogleOutcome,
        ),
        MayosTextField(
          fieldKey: const Key('register_username'),
          controller: _username,
          label: copy.username,
          enabled: !_busy,
          textInputAction: TextInputAction.next,
          keyboardType: TextInputType.text,
          autofillHints: const <String>[AutofillHints.newUsername],
        ),
        if (_showCoachInviteCode) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          MayosTextField(
            fieldKey: const Key('register_coach_invite_code'),
            controller: _coachInviteCode,
            label: copy.coachInviteCode,
            enabled: !_busy,
            textInputAction: TextInputAction.next,
            keyboardType: TextInputType.text,
            autofillHints: const <String>[],
          ),
        ],
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('register_password'),
          toggleKey: const Key('register_password_toggle'),
          controller: _password,
          label: copy.password,
          helperText: copy.passwordLengthHint,
          textInputAction: TextInputAction.next,
          autofillHints: const <String>[AutofillHints.newPassword],
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('register_confirm'),
          toggleKey: const Key('register_confirm_toggle'),
          controller: _confirm,
          label: copy.confirmPassword,
          textInputAction: TextInputAction.done,
          autofillHints: const <String>[AutofillHints.newPassword],
          onSubmitted: (_) => _busy ? null : _submit(),
        ),
        AuthConsentRow(
          label: copy.keepMeSignedIn,
          value: _rememberMe,
          enabled: !_busy,
          onChanged: (bool value) => setState(() => _rememberMe = value),
        ),
        // The policy link sits with the consent control, not in the action bar,
        // so the disclosure is read where the account is created (#43).
        const SizedBox(height: MayosSpacing.xs),
        AuthLink(
          key: const Key('register_privacy_policy'),
          label: copy.privacyPolicy,
          onPressed: _busy ? null : () => openPrivacyPolicy(context, ref),
        ),
      ],
    );
  }
}
