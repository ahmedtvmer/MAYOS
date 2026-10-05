import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/catalog.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/profile_copy.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_icon_chip.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';
import '../player/auth/auth_controller.dart';
import '../player/auth/auth_widgets.dart'
    show
        AuthPasswordField,
        NewPasswordValidation,
        newPasswordValidationMessage,
        validateNewPassword;
import '../player/auth/google_auth_gateway.dart';
import '../player/auth/google_sign_in_button.dart';

class AccountSecuritySection extends ConsumerStatefulWidget {
  const AccountSecuritySection({
    super.key,
    required this.account,
    required this.title,
    this.subtitle,
  });

  final Account account;
  final String title;
  final String? subtitle;

  @override
  ConsumerState<AccountSecuritySection> createState() =>
      _AccountSecuritySectionState();
}

class _AccountSecuritySectionState extends ConsumerState<AccountSecuritySection>
    with _AccountSecurityMethods {
  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        MayosSectionHeader(title: widget.title, subtitle: widget.subtitle),
        const SizedBox(height: MayosSpacing.xxs),
        _buildSignInMethods(c),
        _buildSignInNotice(c),
        const SizedBox(height: MayosSpacing.lg),
        _buildAccountDeletionSection(_copy),
      ],
    );
  }
}

class _DeleteAccountPasswordField extends StatefulWidget {
  const _DeleteAccountPasswordField({
    required this.onChanged,
    required this.label,
    required this.enabled,
  });

  final ValueChanged<String> onChanged;
  final String label;
  final bool enabled;

  @override
  State<_DeleteAccountPasswordField> createState() =>
      _DeleteAccountPasswordFieldState();
}

class _DeleteAccountPasswordFieldState
    extends State<_DeleteAccountPasswordField> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MayosTextField(
        fieldKey: const Key('delete_account_password_field'),
        controller: _controller,
        obscureText: true,
        enabled: widget.enabled,
        label: widget.label,
        onChanged: widget.onChanged,
      );
}

mixin _AccountSecurityMethods on ConsumerState<AccountSecuritySection> {
  final TextEditingController _currentPassword = TextEditingController();
  final TextEditingController _newPassword = TextEditingController();
  final TextEditingController _newPasswordConfirm = TextEditingController();

  late Account _account;
  bool _methodBusy = false;
  String? _methodNotice;
  FailureMessage? _methodFailure;
  bool _methodNoticeIsError = false;

  ProfileCopy get _copy => ProfileCopy(ref.read(displayLanguageProvider));

  FailureMessage _accountMutationFailure(ApiException error) =>
      mutationFailureMessage(error);

  @override
  void initState() {
    super.initState();
    _account = widget.account;
  }

  @override
  void didUpdateWidget(covariant AccountSecuritySection oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.account != widget.account) {
      _account = widget.account;
    }
  }

  @override
  void dispose() {
    _currentPassword.dispose();
    _newPassword.dispose();
    _newPasswordConfirm.dispose();
    super.dispose();
  }

  /// Re-reads `GET /auth/me` after a sign-in-method change, so the section
  /// always shows what the service now reports (#116).
  Future<void> _refreshSignInMethods() async {
    try {
      final Account account =
          await ref.read(apiClientProvider).currentAccount();
      if (!mounted) return;
      setState(() => _account = account);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _methodFailure = _accountMutationFailure(error);
        _methodNoticeIsError = true;
      });
    }
  }

  void _setMethodNotice(String message, {required bool error}) {
    setState(() {
      _methodNotice = message;
      _methodFailure = null;
      _methodNoticeIsError = error;
    });
  }

  void _setMethodFailure(FailureMessage failure) {
    setState(() {
      _methodNotice = null;
      _methodFailure = failure;
      _methodNoticeIsError = true;
    });
  }

  /// "Connect Google": one SDK attempt, then `POST /auth/google/link`. Both
  /// service conflicts (#114) are shown verbatim, in the section.
  Future<void> _connectGoogle() => _runConnectGoogle(
        () => ref.read(authControllerProvider.notifier).connectGoogle(),
      );

  Future<void> _connectGoogleOutcome(GoogleAuthOutcome outcome) =>
      _runConnectGoogle(
        () => ref
            .read(authControllerProvider.notifier)
            .connectGoogleOutcome(outcome),
      );

  Future<void> _runConnectGoogle(
      Future<ConnectGoogleResult> Function() connect) async {
    if (_methodBusy) return;
    setState(() {
      _methodBusy = true;
      _methodNotice = null;
      _methodFailure = null;
      _methodNoticeIsError = false;
    });
    try {
      final ConnectGoogleResult result = await connect();
      if (!mounted) return;
      switch (result) {
        case GoogleConnectDone():
          _setMethodNotice(_copy.googleConnected, error: false);
          await _refreshSignInMethods();
        case GoogleConnectDismissed():
          break;
        case GoogleConnectRefused(:final message, :final failureMessage):
          _setMethodFailure(
            failureMessage ?? ServerFailureMessage(message),
          );
      }
    } finally {
      if (mounted) {
        setState(() => _methodBusy = false);
      }
    }
  }

  /// Disconnecting is confirmation-gated and only offered while the account
  /// still has a password (#114), so nobody can lock themselves out.
  Future<void> _confirmDisconnectGoogle() async {
    if (_methodBusy) return;
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext dialogContext) => AlertDialog(
        title: Text(_copy.disconnectGoogleQuestion),
        content: Text(_copy.disconnectGoogleLead),
        actions: <Widget>[
          MayosButton(
            label: _copy.cancel,
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(dialogContext).pop(false),
          ),
          MayosButton(
            key: const Key('disconnect_google_confirm_button'),
            label: _copy.disconnect,
            destructive: true,
            expand: false,
            onPressed: () => Navigator.of(dialogContext).pop(true),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _methodBusy = true;
      _methodNotice = null;
      _methodFailure = null;
      _methodNoticeIsError = false;
    });
    try {
      await ref.read(authControllerProvider.notifier).disconnectGoogle();
      if (!mounted) return;
      _setMethodNotice(_copy.googleDisconnected, error: false);
      await _refreshSignInMethods();
    } on ApiException catch (error) {
      if (!mounted) return;
      _setMethodFailure(_accountMutationFailure(error));
    } finally {
      if (mounted) {
        setState(() => _methodBusy = false);
      }
    }
  }

  /// The first password for a Google-only account (`POST /auth/set-password`),
  /// worded by the app's shared password rule (#114/#116).
  Future<void> _promptSetPassword() => _promptPasswordDialog(
        title: _copy.setPassword,
        intro: _copy.choosePasswordForGoogle,
        askCurrent: false,
        confirmLabel: _copy.setPasswordAction,
        currentKey: null,
        passwordKey: const Key('set_password_field'),
        confirmFieldKey: const Key('set_password_confirm_field'),
        submitKey: const Key('set_password_confirm_button'),
        successNotice: _copy.passwordSetDisconnectGoogle,
        onSubmit: (String current, String password) => ref
            .read(authControllerProvider.notifier)
            .setInitialPassword(password),
      );

  /// Replacing an existing password (`POST /auth/change-password`). The
  /// service revokes every session, so success ends this one with an
  /// explanation on the sign-in screen (ADR 006): there is no [successNotice]
  /// and nothing to re-read.
  Future<void> _promptChangePassword() => _promptPasswordDialog(
        title: _copy.changePassword,
        intro: _copy.changePasswordSignsOut,
        askCurrent: true,
        confirmLabel: _copy.changePasswordAction,
        currentKey: const Key('change_password_current_field'),
        passwordKey: const Key('change_password_new_field'),
        confirmFieldKey: const Key('change_password_confirm_field'),
        submitKey: const Key('change_password_confirm_button'),
        successNotice: null,
        onSubmit: (String current, String password) => ref
            .read(authControllerProvider.notifier)
            .changePassword(currentPassword: current, newPassword: password),
      );

  /// The one password dialog behind both moves above: a Google-only account
  /// sets its first password, an account with one replaces it. Only the
  /// wording, the optional "current password" field, and [onSubmit] differ.
  ///
  /// The password fields live at section level because changing a password
  /// can switch the session while the dialog route is still animating out.
  Future<void> _promptPasswordDialog({
    required String title,
    required String intro,
    required bool askCurrent,
    required String confirmLabel,
    required Key? currentKey,
    required Key passwordKey,
    required Key confirmFieldKey,
    required Key submitKey,
    required String? successNotice,
    required Future<void> Function(String current, String password) onSubmit,
  }) async {
    if (_methodBusy) return;
    _currentPassword.clear();
    _newPassword.clear();
    _newPasswordConfirm.clear();
    bool busy = false;
    bool done = false;
    String? error;
    FailureMessage? dialogFailure;
    await showDialog<void>(
      context: context,
      builder: (BuildContext dialogContext) => StatefulBuilder(
        builder: (BuildContext context, StateSetter setDialogState) =>
            AlertDialog(
          title: Text(title),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(intro),
                const SizedBox(height: MayosSpacing.md),
                if (askCurrent) ...<Widget>[
                  AuthPasswordField(
                    controller: _currentPassword,
                    fieldKey: currentKey,
                    label: _copy.currentPassword,
                  ),
                  const SizedBox(height: MayosSpacing.sm),
                ],
                AuthPasswordField(
                  controller: _newPassword,
                  fieldKey: passwordKey,
                  label: _copy.newPassword,
                ),
                const SizedBox(height: MayosSpacing.sm),
                AuthPasswordField(
                  controller: _newPasswordConfirm,
                  fieldKey: confirmFieldKey,
                  label: _copy.confirmNewPassword,
                ),
                if (error != null || dialogFailure != null) ...<Widget>[
                  const SizedBox(height: MayosSpacing.sm),
                  Text(
                    error ??
                        MayosCopy(ref.read(displayLanguageProvider))
                            .failureMessage(dialogFailure!),
                    style: MayosTypography.of(context).bodySecondary
                        .copyWith(color: MayosTheme.of(context).danger),
                  ),
                ],
              ],
            ),
          ),
          actions: <Widget>[
            MayosButton(
              label: _copy.cancel,
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: busy ? null : () => Navigator.of(dialogContext).pop(),
            ),
            MayosButton(
              key: submitKey,
              label: confirmLabel,
              expand: false,
              loading: busy,
              onPressed: busy
                  ? null
                  : () async {
                      if (askCurrent && _currentPassword.text.isEmpty) {
                        setDialogState(
                            () => error = _copy.enterCurrentPassword);
                        return;
                      }
                      final NewPasswordValidation? invalid =
                          validateNewPassword(
                              _newPassword.text, _newPasswordConfirm.text);
                      if (invalid != null) {
                        final MayosCopy copy =
                            MayosCopy(ref.read(displayLanguageProvider));
                        setDialogState(() => error =
                            newPasswordValidationMessage(invalid, copy));
                        return;
                      }
                      setDialogState(() {
                        busy = true;
                        error = null;
                        dialogFailure = null;
                      });
                      try {
                        await onSubmit(
                            _currentPassword.text, _newPassword.text);
                        done = true;
                        if (dialogContext.mounted) {
                          Navigator.of(dialogContext).pop();
                        }
                      } on ApiException catch (apiError) {
                        setDialogState(() {
                          busy = false;
                          dialogFailure = _accountMutationFailure(apiError);
                        });
                      }
                    },
            ),
          ],
        ),
      ),
    );
    if (!done || successNotice == null || !mounted) return;
    setState(() => _methodBusy = true);
    _setMethodNotice(successNotice, error: false);
    await _refreshSignInMethods();
    if (mounted) {
      setState(() => _methodBusy = false);
    }
  }

  /// Proof-confirmed, irreversible account deletion (ADR 015/039).
  ///
  /// The player sees exactly what is removed, including unsynced drafts on this
  /// device. An account with a password confirms with that password; a
  /// Google-only account has no password to type, so it confirms by re-running
  /// Google sign-in for a fresh ID token (#114/#116). A wrong proof, a
  /// dismissed Google sheet, or an offline attempt changes nothing.
  Future<void> _confirmDeleteAccount() async {
    final bool googleOnly = !_account.hasPassword;
    final GoogleAuthGateway google = ref.read(googleAuthGatewayProvider);
    final bool webGoogle =
        googleOnly && google.buttonStyle == GoogleSignInButtonStyle.webRendered;
    bool busy = false;
    String? error;
    FailureMessage? dialogFailure;
    String password = '';
    await showDialog<void>(
      context: context,
      builder: (BuildContext dialogContext) => StatefulBuilder(
        builder: (BuildContext context, StateSetter setDialogState) =>
            AlertDialog(
          title: Text(_copy.confirmDeleteAccount),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(_copy.deleteAccountDetails),
                const SizedBox(height: MayosSpacing.md),
                if (googleOnly)
                  Text(_copy.googleOnlyDeleteProof)
                else ...<Widget>[
                  _DeleteAccountPasswordField(
                    onChanged: (String value) => password = value,
                    label: _copy.password,
                    enabled: !busy,
                  ),
                ],
                if (webGoogle) ...<Widget>[
                  const SizedBox(height: MayosSpacing.md),
                  GoogleWebSignInButton(
                    key: const Key('delete_account_google_web_button'),
                    loading: busy,
                    fixedWidth: (MediaQuery.sizeOf(dialogContext).width -
                            2 * (MayosSpacing.xxxl + MayosSpacing.xl))
                        .clamp(0.0, MayosLayout.googleButtonMaxWidth),
                    onOutcome: (GoogleAuthOutcome outcome) =>
                        _handleGoogleDelete(
                      delete: () => ref
                          .read(authControllerProvider.notifier)
                          .deleteAccountWithGoogleOutcome(outcome),
                      isBusy: () => busy,
                      dialogContext: dialogContext,
                      updateDialog:
                          (bool nextBusy, FailureMessage? nextFailure) =>
                              setDialogState(() {
                        busy = nextBusy;
                        dialogFailure = nextFailure;
                      }),
                    ),
                  ),
                ],
                if (error != null || dialogFailure != null) ...<Widget>[
                  const SizedBox(height: MayosSpacing.sm),
                  Text(
                    error ??
                        MayosCopy(ref.read(displayLanguageProvider))
                            .failureMessage(dialogFailure!),
                    style: MayosTypography.of(context).bodySecondary
                        .copyWith(color: MayosTheme.of(context).danger),
                  ),
                ],
              ],
            ),
          ),
          actions: <Widget>[
            MayosButton(
              label: _copy.cancel,
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: busy ? null : () => Navigator.of(dialogContext).pop(),
            ),
            if (!webGoogle)
              MayosButton(
                key: const Key('delete_account_confirm_button'),
                label: _copy.deleteAccount,
                destructive: true,
                expand: false,
                loading: busy,
                onPressed: busy
                    ? null
                    : () async {
                        if (googleOnly) {
                          await _handleGoogleDelete(
                            delete: () => ref
                                .read(authControllerProvider.notifier)
                                .deleteAccountWithGoogle(),
                            isBusy: () => busy,
                            dialogContext: dialogContext,
                            updateDialog:
                                (bool nextBusy, FailureMessage? nextFailure) {
                              setDialogState(() {
                                busy = nextBusy;
                                dialogFailure = nextFailure;
                              });
                            },
                          );
                          return;
                        }
                        setDialogState(() {
                          busy = true;
                          error = null;
                          dialogFailure = null;
                        });
                        try {
                          await ref
                              .read(authControllerProvider.notifier)
                              .deleteAccount(password);
                          if (dialogContext.mounted) {
                            Navigator.of(dialogContext).pop();
                          }
                        } on ApiException catch (apiError) {
                          setDialogState(() {
                            busy = false;
                            dialogFailure = _accountMutationFailure(apiError);
                          });
                        }
                      },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _handleGoogleDelete({
    required Future<DeleteWithGoogleResult> Function() delete,
    required bool Function() isBusy,
    required BuildContext dialogContext,
    required void Function(bool busy, FailureMessage? failure) updateDialog,
  }) async {
    if (isBusy()) return;
    updateDialog(true, null);
    final DeleteWithGoogleResult result = await delete();
    if (result
        case DeleteWithGoogleRefused(
          :final message,
          :final failureMessage,
        )) {
      updateDialog(false, failureMessage ?? ServerFailureMessage(message));
      return;
    }
    if (result is DeleteWithGoogleDismissed) {
      updateDialog(
        false,
        const AppFailureMessage(
          AppFailureId.googleDeleteCancelled,
          kGoogleDeleteCancelledMessage,
        ),
      );
      return;
    }
    if (dialogContext.mounted) {
      Navigator.of(dialogContext).pop();
    }
  }

  /// The "Sign-in methods" card, driven entirely by `GET /auth/me` (#116):
  /// Password (set or change) and Google (connect or disconnect), where
  /// disconnecting is only offered while a password exists.
  Widget _buildSignInMethods(MayosThemeExtension c) {
    final Account account = _account;
    final GoogleAuthGateway google = ref.watch(googleAuthGatewayProvider);
    final bool hasPassword = account.hasPassword;
    final bool googleLinked = account.hasGoogleLink;
    return MayosCard(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.sm, vertical: MayosSpacing.xxs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _SignInMethodRow(
            leading: MayosIconChip(
              child: Icon(
                Icons.lock_outline,
                size: MayosIconSizes.medium,
                color: c.accent,
              ),
            ),
            title: _copy.passwordTitle,
            status: hasPassword ? _copy.passwordSet : _copy.noPasswordYet,
            action: MayosButton(
              key: Key(hasPassword
                  ? 'change_password_button'
                  : 'set_password_button'),
              label:
                  hasPassword ? _copy.changePassword : _copy.setPasswordAction,
              variant: MayosButtonVariant.secondary,
              onPressed: _methodBusy
                  ? null
                  : hasPassword
                      ? _promptChangePassword
                      : _promptSetPassword,
            ),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          const Divider(height: 1),
          const SizedBox(height: MayosSpacing.xxs),
          _SignInMethodRow(
            leading: const MayosIconChip(
                child: GoogleGLogo(size: MayosIconSizes.medium)),
            title: _copy.google,
            status: googleLinked ? _copy.connected : _copy.notConnected,
            hint: googleLinked && !hasPassword ? _copy.setPasswordFirst : null,
            action: googleLinked
                ? MayosButton(
                    key: const Key('disconnect_google_button'),
                    label: _copy.disconnectGoogle,
                    variant: MayosButtonVariant.secondary,
                    onPressed: _methodBusy || !hasPassword
                        ? null
                        : _confirmDisconnectGoogle,
                  )
                : google.buttonStyle == GoogleSignInButtonStyle.hidden
                    ? const SizedBox.shrink()
                    : google.buttonStyle == GoogleSignInButtonStyle.webRendered
                        ? GoogleWebSignInButton(
                            key: const Key('connect_google_web_button'),
                            loading: _methodBusy,
                            onOutcome: _connectGoogleOutcome,
                          )
                        : MayosButton(
                            key: const Key('connect_google_button'),
                            label: _copy.connectGoogle,
                            variant: MayosButtonVariant.secondary,
                            loading: _methodBusy,
                            onPressed: _methodBusy ? null : _connectGoogle,
                          ),
          ),
        ],
      ),
    );
  }

  Widget _buildSignInNotice(MayosThemeExtension c) {
    final String? notice = _methodFailure == null
        ? _methodNotice
        : displayCopyOf(context).failureMessage(_methodFailure!);
    if (notice == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.sm),
      child: FirstStrongDirection(
        text: notice,
        child: Text(
          notice,
          style: _methodNoticeIsError
              ? MayosTypography.of(context).bodySecondary.copyWith(color: c.danger)
              : MayosTypography.of(context).body,
        ),
      ),
    );
  }

  Widget _buildAccountDeletionSection(ProfileCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Divider(),
          const SizedBox(height: MayosSpacing.sm),
          MayosSectionHeader(
            title: copy.dangerZone,
            subtitle: copy.dangerZoneLead,
          ),
          const SizedBox(height: MayosSpacing.sm),
          MayosButton(
            key: const Key('delete_account_button'),
            label: copy.deleteAccount,
            icon: Icons.delete_forever_outlined,
            variant: MayosButtonVariant.secondary,
            destructive: true,
            expand: false,
            onPressed: _confirmDeleteAccount,
          ),
        ],
      );
}

/// One row of the "Sign-in methods" card: an icon chip beside the method's
/// name and live state (plus an optional hint), then its full-width action —
/// stacked so nothing is squeezed at 360dp (#116).
class _SignInMethodRow extends StatelessWidget {
  const _SignInMethodRow({
    required this.leading,
    required this.title,
    required this.status,
    required this.action,
    this.hint,
  });

  final Widget leading;
  final String title;
  final String status;
  final String? hint;
  final Widget action;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: <Widget>[
            leading,
            const SizedBox(width: MayosSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Text(
                    title,
                    style: text.titleSmall?.copyWith(color: c.textPrimary),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    status,
                    style: text.bodySmall?.copyWith(color: c.textMuted),
                  ),
                  if (hint != null) ...<Widget>[
                    const SizedBox(height: 2),
                    Text(
                      hint!,
                      style: text.bodySmall?.copyWith(color: c.warning),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: MayosSpacing.xs),
        action,
      ],
    );
  }
}
