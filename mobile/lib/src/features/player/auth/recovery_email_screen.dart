import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import 'auth_widgets.dart';

/// ADR 007 gate: the recovery email must be verified before dashboard or onboarding.
class RecoveryEmailScreen extends ConsumerStatefulWidget {
  const RecoveryEmailScreen({super.key});

  @override
  ConsumerState<RecoveryEmailScreen> createState() =>
      _RecoveryEmailScreenState();
}

class _RecoveryEmailScreenState extends ConsumerState<RecoveryEmailScreen> {
  final TextEditingController _email = TextEditingController();
  final TextEditingController _code = TextEditingController();
  bool? _editingAddress;
  bool _emailSeeded = false;
  bool _busy = false;
  bool _codeSent = false;
  FailureMessage? _error;
  String? _notice;

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    super.dispose();
  }

  bool _isEditing(bool hasRecoveryEmail) =>
      _editingAddress ?? !hasRecoveryEmail;

  void _seedSavedEmail(String? savedEmail) {
    if (_emailSeeded) return;
    _emailSeeded = true;
    if (savedEmail != null) _email.text = savedEmail;
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      final bool verified = await ref
          .read(authControllerProvider.notifier)
          .setRecoveryEmail(_email.text.trim());
      TextInput.finishAutofillContext();
      if (!mounted) return;
      _code.clear();
      setState(() {
        _editingAddress = false;
        _busy = false;
        _codeSent = false;
      });
      if (!verified) await _sendCode();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = apiFailureMessage(error);
          _busy = false;
        });
      }
    }
  }

  Future<void> _sendCode() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .sendRecoveryEmailVerificationCode();
      if (mounted) {
        setState(() {
          _notice =
              MayosCopy(ref.read(displayLanguageProvider)).recoveryCodeSent;
          _busy = false;
          _codeSent = true;
        });
      }
    } on ApiException {
      if (mounted) {
        setState(() {
          _error = ServerFailureMessage(
            MayosCopy(ref.read(displayLanguageProvider)).recoveryCodeSendError,
          );
          _busy = false;
        });
      }
    }
  }

  Future<void> _verify() async {
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .verifyRecoveryEmail(_code.text.trim());
      TextInput.finishAutofillContext();
    } on ApiException {
      if (mounted) {
        setState(() {
          _error = ServerFailureMessage(
            MayosCopy(ref.read(displayLanguageProvider)).recoveryCodeError,
          );
          _busy = false;
        });
      }
    }
  }

  void _changeAddress(String? savedEmail) {
    setState(() {
      _editingAddress = true;
      _email.text = savedEmail ?? '';
      _code.clear();
      _error = null;
      _notice = null;
      _codeSent = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    final session = ref.watch(authControllerProvider).session;
    final bool hasRecoveryEmail = session?.hasRecoveryEmail ?? false;
    final bool editingAddress = _isEditing(hasRecoveryEmail);
    _seedSavedEmail(session?.recoveryEmail);

    return AuthScaffold(
      title: copy.recoveryEmail,
      lead: editingAddress ? copy.recoveryEmailLead : copy.recoveryEmailCodeLead,
      message: _error != null
          ? AuthInlineNotice(message: copy.failureMessage(_error!))
          : _notice == null
              ? null
              : AuthInlineNotice(message: _notice!),
      primary: MayosButton(
        key: const Key('recovery_submit'),
        label: editingAddress ? copy.saveEmail : copy.verifyRecoveryEmail,
        loading: _busy,
        onPressed: _busy ? null : editingAddress ? _save : _verify,
      ),
      links: <Widget>[
        if (!editingAddress) ...<Widget>[
          AuthLink(
            label: copy.changeRecoveryEmail,
            onPressed: _busy
                ? null
                : () => _changeAddress(session?.recoveryEmail),
          ),
          AuthLink(
            label: _codeSent
                ? copy.resendVerificationCode
                : copy.sendVerificationCode,
            onPressed: _busy ? null : _sendCode,
          ),
        ],
        AuthLink(
          label: copy.logOut,
          onPressed: _busy
              ? null
              : () => ref.read(authControllerProvider.notifier).logout(),
        ),
      ],
      children: <Widget>[
        if (editingAddress)
          MayosTextField(
            fieldKey: const Key('recovery_email'),
            controller: _email,
            label: copy.email,
            enabled: !_busy,
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.done,
            textCapitalization: TextCapitalization.none,
            autocorrect: false,
            autofillHints: const <String>[AutofillHints.email],
            onSubmitted: (_) => _busy ? null : _save(),
          )
        else
          MayosTextField(
            fieldKey: const Key('recovery_verification_code'),
            controller: _code,
            label: copy.verificationCode,
            enabled: !_busy,
            keyboardType: TextInputType.number,
            textInputAction: TextInputAction.done,
            autocorrect: false,
            enableSuggestions: false,
            maxLength: 6,
            onSubmitted: (_) => _busy ? null : _verify(),
          ),
      ],
    );
  }
}
