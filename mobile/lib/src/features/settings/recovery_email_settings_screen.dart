import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/settings_copy.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';

enum _RecoveryEmailChangeStatus { ready, busy, changed }

class RecoveryEmailSettingsScreen extends ConsumerStatefulWidget {
  const RecoveryEmailSettingsScreen({super.key});

  @override
  ConsumerState<RecoveryEmailSettingsScreen> createState() =>
      _RecoveryEmailSettingsScreenState();
}

class _RecoveryEmailSettingsScreenState
    extends ConsumerState<RecoveryEmailSettingsScreen> {
  final TextEditingController _email = TextEditingController();
  final TextEditingController _code = TextEditingController();

  _RecoveryEmailChangeStatus _status = _RecoveryEmailChangeStatus.ready;
  String? _currentEmail;
  String? _pendingEmail;
  String? _error;
  bool _hasLocalRecoveryEmailState = false;
  bool _codeSent = false;

  SettingsCopy get _copy => SettingsCopy(ref.read(displayLanguageProvider));

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _requestCode() async {
    final String email = _email.text.trim().toLowerCase();
    final String? currentEmail =
        ref.read(recoveryEmailDetailsProvider).valueOrNull?.email;
    if (email.isEmpty) {
      _showRecoveryEmailError();
      return;
    }
    setState(() {
      _status = _RecoveryEmailChangeStatus.busy;
      _error = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .requestRecoveryEmailChange(email);
    } on ApiException catch (error) {
      final String? message = error.message ==
              'This email is already linked to another account.'
          ? _copy.recoveryEmailAlreadyLinked
          : null;
      _showRecoveryEmailError(message);
      return;
    }
    if (!mounted) return;
    _code.clear();
    setState(() {
      _currentEmail = currentEmail ?? _currentEmail;
      _pendingEmail = email;
      _codeSent = true;
      _hasLocalRecoveryEmailState = true;
      _status = _RecoveryEmailChangeStatus.ready;
    });
  }

  Future<void> _verifyCode() async {
    setState(() {
      _status = _RecoveryEmailChangeStatus.busy;
      _error = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .verifyRecoveryEmailChange(_code.text.trim());
    } on ApiException {
      _showRecoveryEmailError();
      return;
    }
    if (!mounted) return;
    final String email = _hasLocalRecoveryEmailState
        ? _pendingEmail ?? _email.text.trim()
        : ref.read(recoveryEmailDetailsProvider).valueOrNull?.pendingEmail ??
            _email.text.trim();
    _completeRecoveryEmailChange(email);
  }

  void _showRecoveryEmailError([String? message]) {
    if (!mounted) return;
    setState(() {
      _status = _RecoveryEmailChangeStatus.ready;
      _error = message ?? _copy.recoveryEmailChangeFailed;
    });
  }

  void _completeRecoveryEmailChange(String email) {
    ref.read(authControllerProvider.notifier).recoveryEmailChanged(email);
    TextInput.finishAutofillContext();
    setState(() {
      _hasLocalRecoveryEmailState = true;
      _currentEmail = email;
      _pendingEmail = null;
      _codeSent = false;
      _status = _RecoveryEmailChangeStatus.changed;
    });
  }

  void _useDifferentEmail(String? pendingEmail) {
    setState(() {
      _email.text = pendingEmail ?? _email.text;
      _hasLocalRecoveryEmailState = true;
      _pendingEmail = pendingEmail;
      _code.clear();
      _codeSent = false;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    return ref.watch(recoveryEmailDetailsProvider).when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (Object error, StackTrace stack) => _buildLoadFailure(),
      data: (RecoveryEmailDetails details) => _buildContent(context, details),
    );
  }

  Widget _buildContent(BuildContext context, RecoveryEmailDetails details) {
    final String? currentEmail =
        _hasLocalRecoveryEmailState ? _currentEmail : details.email;
    final String? pendingEmail =
        _hasLocalRecoveryEmailState ? _pendingEmail : details.pendingEmail;
    final bool codeSent = _hasLocalRecoveryEmailState
        ? _codeSent
        : details.pendingEmail != null;
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        MayosSectionHeader(
          title: _copy.currentRecoveryEmail,
          subtitle: currentEmail ?? _copy.recoveryEmailNotSet,
        ),
        _buildChangeCard(context, pendingEmail, codeSent),
      ],
    );
  }

  Widget _buildLoadFailure() {
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        Text(_copy.recoveryEmailLoadFailed),
        const SizedBox(height: MayosSpacing.md),
        MayosButton(
          label: _copy.retry,
          onPressed: () => ref.invalidate(recoveryEmailDetailsProvider),
        ),
      ],
    );
  }

  Widget _buildChangeCard(
    BuildContext context,
    String? pendingEmail,
    bool codeSent,
  ) {
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(_copy.recoveryEmailCodeLead),
          const SizedBox(height: MayosSpacing.md),
          _buildChangeStep(context, pendingEmail, codeSent),
          if (_error != null) _buildError(context),
        ],
      ),
    );
  }

  Widget _buildChangeStep(
    BuildContext context,
    String? pendingEmail,
    bool codeSent,
  ) {
    if (_status == _RecoveryEmailChangeStatus.changed) {
      return _buildChangedNotice(context);
    }
    return codeSent
        ? _buildVerificationStep(pendingEmail)
        : _buildAddressStep();
  }

  Widget _buildChangedNotice(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(
          _copy.recoveryEmailChanged,
          style: TextStyle(color: MayosTheme.of(context).success),
        ),
        const SizedBox(height: MayosSpacing.xs),
        Text(_copy.recoveryEmailChangeSuccessLead),
      ],
    );
  }

  Widget _buildVerificationStep(String? pendingEmail) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(_copy.recoveryEmailCodeSent),
        if (pendingEmail != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          Text(_copy.pendingRecoveryEmail),
          Text(pendingEmail, textDirection: TextDirection.ltr),
        ],
        const SizedBox(height: MayosSpacing.sm),
        _buildCodeField(),
        const SizedBox(height: MayosSpacing.sm),
        _buildVerificationActions(pendingEmail),
      ],
    );
  }

  Widget _buildCodeField() {
    return MayosTextField(
      fieldKey: const Key('recovery_email_change_code'),
      controller: _code,
      label: _copy.recoveryEmailCode,
      keyboardType: TextInputType.number,
      textDirection: TextDirection.ltr,
      textInputAction: TextInputAction.done,
      autocorrect: false,
      enableSuggestions: false,
      maxLength: 6,
      onSubmitted: (_) => _verifyCode(),
    );
  }

  Widget _buildVerificationActions(String? pendingEmail) {
    final bool isBusy = _status == _RecoveryEmailChangeStatus.busy;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        MayosButton(
          key: const Key('recovery_email_change_verify'),
          label: _copy.verifyAndChangeRecoveryEmail,
          loading: isBusy,
          onPressed: isBusy ? null : _verifyCode,
        ),
        MayosButton(
          label: _copy.useDifferentRecoveryEmail,
          variant: MayosButtonVariant.tertiary,
          loading: isBusy,
          onPressed: isBusy ? null : () => _useDifferentEmail(pendingEmail),
        ),
      ],
    );
  }

  Widget _buildAddressStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        MayosTextField(
          fieldKey: const Key('recovery_email_change_address'),
          controller: _email,
          label: _copy.newRecoveryEmail,
          keyboardType: TextInputType.emailAddress,
          textDirection: TextDirection.ltr,
          textInputAction: TextInputAction.done,
          autocorrect: false,
          enableSuggestions: false,
          onSubmitted: (_) => _requestCode(),
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('recovery_email_change_send'),
          label: _copy.sendRecoveryEmailCode,
          loading: _status == _RecoveryEmailChangeStatus.busy,
          onPressed: _status == _RecoveryEmailChangeStatus.busy
              ? null
              : _requestCode,
        ),
      ],
    );
  }

  Widget _buildError(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.sm),
      child: Text(
        _error!,
        style: TextStyle(color: MayosTheme.of(context).danger),
      ),
    );
  }
}
