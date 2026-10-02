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

/// ADR 007 gate: a recovery email is mandatory before dashboard or onboarding.
class RecoveryEmailScreen extends ConsumerStatefulWidget {
  const RecoveryEmailScreen({super.key});

  @override
  ConsumerState<RecoveryEmailScreen> createState() =>
      _RecoveryEmailScreenState();
}

class _RecoveryEmailScreenState extends ConsumerState<RecoveryEmailScreen> {
  final TextEditingController _email = TextEditingController();
  bool _busy = false;
  FailureMessage? _error;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .setRecoveryEmail(_email.text.trim());
      TextInput.finishAutofillContext();
      // On success the router releases the gate; this screen is disposed.
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = apiFailureMessage(error);
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    return AuthScaffold(
      title: copy.recoveryEmail,
      lead: copy.recoveryEmailLead,
      message: _error == null
          ? null
          : AuthInlineNotice(message: copy.failureMessage(_error!)),
      primary: MayosButton(
        key: const Key('recovery_submit'),
        label: copy.saveEmail,
        loading: _busy,
        onPressed: _busy ? null : _save,
      ),
      links: <Widget>[
        AuthLink(
          label: copy.logOut,
          onPressed: _busy
              ? null
              : () => ref.read(authControllerProvider.notifier).logout(),
        ),
      ],
      children: <Widget>[
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
        ),
      ],
    );
  }
}
