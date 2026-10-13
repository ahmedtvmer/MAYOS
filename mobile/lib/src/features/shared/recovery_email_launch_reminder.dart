import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/display_language/catalog.dart';
import '../../core/display_language/controller.dart';
import '../../providers.dart';
import '../../router.dart';
import '../player/auth/auth_controller.dart';

final Provider<Set<String>> _remindedAccountsProvider =
    Provider<Set<String>>((ref) => <String>{});

/// Offers the recovery-email reminder once per account during this app run.
class RecoveryEmailLaunchReminder extends ConsumerStatefulWidget {
  const RecoveryEmailLaunchReminder({
    super.key,
    required this.path,
    required this.child,
  });

  final String path;
  final Widget child;

  @override
  ConsumerState<RecoveryEmailLaunchReminder> createState() =>
      _RecoveryEmailLaunchReminderState();
}

class _RecoveryEmailLaunchReminderState
    extends ConsumerState<RecoveryEmailLaunchReminder> {
  String? _scheduledAccountId;

  @override
  Widget build(BuildContext context) {
    _scheduleReminder(ref.watch(authControllerProvider));
    return widget.child;
  }

  void _scheduleReminder(AuthState auth) {
    final account = auth.session?.account;
    final Set<String> remindedAccounts = ref.read(_remindedAccountsProvider);
    if (account == null ||
        account.recoveryEmailVerified ||
        !_isLandedAppPath(widget.path) ||
        remindedAccounts.contains(account.accountId) ||
        _scheduledAccountId == account.accountId) {
      return;
    }

    _scheduledAccountId = account.accountId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _showReminderIfEligible(account.accountId, widget.path);
    });
  }

  void _showReminderIfEligible(String accountId, String path) {
    if (!mounted) {
      _scheduledAccountId = null;
      return;
    }
    final account = ref.read(authControllerProvider).session?.account;
    final router = ref.read(routerProvider);
    final String currentPath =
        router.routerDelegate.currentConfiguration.uri.path;
    final Set<String> remindedAccounts = ref.read(_remindedAccountsProvider);
    if (account == null ||
        account.accountId != accountId ||
        account.recoveryEmailVerified ||
        currentPath != path ||
        remindedAccounts.contains(accountId)) {
      _scheduledAccountId = null;
      return;
    }

    _scheduledAccountId = null;
    remindedAccounts.add(accountId);
    unawaited(
      showDialog<void>(
        context: context,
        barrierDismissible: true,
        builder: (BuildContext dialogContext) => _RecoveryEmailReminderDialog(
          onLater: () => Navigator.of(dialogContext).pop(),
          onVerify: () {
            Navigator.of(dialogContext).pop();
            router.go(recoveryEmailPath);
          },
        ),
      ),
    );
  }

  bool _isLandedAppPath(String path) =>
      path != splashPath &&
      path != loginPath &&
      path != registerPath &&
      path != googleSignupPath &&
      path != recoveryEmailPath &&
      path != forgotPasswordPath &&
      path != resetPasswordPath &&
      path != appUpdateRequiredPath;
}

class _RecoveryEmailReminderDialog extends ConsumerWidget {
  const _RecoveryEmailReminderDialog({
    required this.onLater,
    required this.onVerify,
  });

  final VoidCallback onLater;
  final VoidCallback onVerify;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    return AlertDialog(
      title: Text(copy.recoveryEmailReminderTitle),
      content: Text(copy.recoveryEmailReminderBody),
      actions: <Widget>[
        TextButton(onPressed: onLater, child: Text(copy.later)),
        FilledButton(onPressed: onVerify, child: Text(copy.verifyNow)),
      ],
    );
  }
}
