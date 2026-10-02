import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
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
  late final TextEditingController _token =
      TextEditingController(text: widget.token);
  final TextEditingController _password = TextEditingController();
  final TextEditingController _confirm = TextEditingController();
  bool _busy = false;
  String? _error;
  FailureMessage? _apiFailure;

  @override
  void dispose() {
    _token.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  /// Prefers the server's own `detail`; falls back only when none is present.
  FailureMessage _apiFailureMessage(ApiException error) {
    if (isNetworkFailure(error)) {
      return mutationFailureMessage(error);
    }
    final FailureMessage failure = apiFailureMessage(error);
    if (failure case ServerFailureMessage(:final String detail)
        when detail.trim().isEmpty) {
      return const AppFailureMessage(
        AppFailureId.passwordResetFallback,
        'Could not reset the password. Request a new link.',
      );
    }
    return failure;
  }

  Future<void> _submit() async {
    final String token = _token.text.trim();
    final String password = _password.text;
    setState(() {
      _error = null;
      _apiFailure = null;
    });
    if (token.isEmpty) {
      setState(() {
        _apiFailure = const AppFailureMessage(
          AppFailureId.passwordResetFallback,
          'Could not reset the password. Request a new link.',
        );
      });
      return;
    }
    final NewPasswordValidation? passwordError =
        validateNewPassword(password, _confirm.text);
    if (passwordError != null) {
      final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
      setState(
          () => _error = newPasswordValidationMessage(passwordError, copy));
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
        setState(() => _apiFailure = _apiFailureMessage(error));
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
      title: copy.resetPassword,
      lead: copy.resetPasswordLead,
      wallpaper: true,
      message: _apiFailure != null
          ? AuthInlineNotice(message: copy.failureMessage(_apiFailure!))
          : (_error == null ? null : AuthInlineNotice(message: _error!)),
      primary: MayosButton(
        key: const Key('reset_submit'),
        label: copy.setNewPassword,
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: copy.requestNewLink,
          onPressed: _busy ? null : () => context.go(forgotPasswordPath),
        ),
      ],
      children: <Widget>[
        MayosTextField(
          fieldKey: const Key('reset_token'),
          controller: _token,
          label: copy.resetCode,
          readOnly: true,
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('reset_password'),
          toggleKey: const Key('reset_password_toggle'),
          controller: _password,
          label: copy.newPassword,
          helperText: copy.passwordLengthHint,
          textInputAction: TextInputAction.next,
          autofillHints: const <String>[AutofillHints.newPassword],
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthPasswordField(
          fieldKey: const Key('reset_confirm'),
          toggleKey: const Key('reset_confirm_toggle'),
          controller: _confirm,
          label: copy.confirmPassword,
          textInputAction: TextInputAction.done,
          autofillHints: const <String>[AutofillHints.newPassword],
          onSubmitted: (_) => _busy ? null : _submit(),
        ),
      ],
    );
  }
}
