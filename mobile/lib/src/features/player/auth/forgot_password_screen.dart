import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
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
  bool _confirmation = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
      _confirmation = false;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .requestPasswordReset(_email.text.trim());
      if (mounted) {
        setState(() => _confirmation = true);
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
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    return AuthScaffold(
      title: copy.forgotPassword,
      lead: copy.forgotEmailHint,
      wallpaper: true,
      message: _error == null ? null : AuthInlineNotice(message: _error!),
      primary: MayosButton(
        key: const Key('forgot_submit'),
        label: copy.sendResetLink,
        loading: _busy,
        onPressed: _busy ? null : _submit,
      ),
      links: <Widget>[
        AuthLink(
          label: copy.backToLogIn,
          onPressed: _busy ? null : () => context.go(loginPath),
        ),
      ],
      children: <Widget>[
        MayosTextField(
          fieldKey: const Key('forgot_email'),
          controller: _email,
          label: copy.email,
          enabled: !_busy,
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.done,
          autocorrect: false,
          autofillHints: const <String>[AutofillHints.email],
          onSubmitted: (_) => _busy ? null : _submit(),
        ),
        if (_confirmation) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          AuthInlineNotice(
            kind: AuthNoticeKind.success,
            message: copy.resetRequestConfirmation,
          ),
          const SizedBox(height: MayosSpacing.sm),
          Text(copy.noEmailHint),
          AuthLink(
            key: const Key('forgot_signup'),
            label: copy.signUp,
            onPressed: _busy
                ? null
                : () => context.go(carryingLocation(context, registerPath)),
          ),
          Text(copy.forgotSettingsHint),
        ],
      ],
    );
  }
}
