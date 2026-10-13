import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart'
    show MissingPluginException, PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../providers.dart';
import '../../../router.dart';

/// One short, account-scoped explanation before Home asks for rest-alert
/// permissions (#409). The active-workout prompt remains the fallback.
class RestAlertPermissionScreen extends ConsumerStatefulWidget {
  const RestAlertPermissionScreen({super.key, this.programMessage});

  final String? programMessage;

  @override
  ConsumerState<RestAlertPermissionScreen> createState() =>
      _RestAlertPermissionScreenState();
}

class _RestAlertPermissionScreenState
    extends ConsumerState<RestAlertPermissionScreen> {
  bool _loading = true;
  bool _working = false;
  bool _leavingHome = false;

  @override
  void initState() {
    super.initState();
    Future<void>.microtask(_prepare);
  }

  Future<void> _prepare() async {
    final access = ref.read(restAlertPermissionAccessProvider);
    final Account? account =
        ref.read(authControllerProvider).session?.account;
    final String? accountId = account?.accountId;
    if (!access.isSupported || accountId == null || accountId.isEmpty) {
      _goHome();
      return;
    }

    final store = ref.read(restAlertPermissionPromptStoreProvider);
    if (await store.wasShown(accountId)) {
      _goHome();
      return;
    }
    if (await access.areGranted()) {
      _goHome();
      return;
    }
    if (!mounted) return;

    // Persist before the actions become available so a fast app restart cannot
    // show the explanation a second time.
    await store.markShown(accountId);
    if (!mounted) return;
    setState(() {
      _loading = false;
    });
  }

  Future<void> _allow() async {
    if (_working) return;
    setState(() => _working = true);
    try {
      await ref.read(restAlertPermissionAccessProvider).request();
    } on PlatformException {
      // A system permission failure still allows onboarding to continue.
    } on MissingPluginException {
      // A system permission failure still allows onboarding to continue.
    } finally {
      _goHome();
    }
  }

  void _skip() {
    if (_working) return;
    setState(() => _working = true);
    _goHome();
  }

  void _goHome() {
    if (!mounted || _leavingHome) return;
    _leavingHome = true;
    context.go(homePath);
    final String? message = widget.programMessage;
    if (message != null && message.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        mayosMessengerKey.currentState?.showSnackBar(
          SnackBar(content: Text(message)),
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    return MayosScaffold(
      key: const Key('rest_alert_permission_screen'),
      title: copy.restAlertPermissionTitle,
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(MayosSpacing.lg),
              child: MayosCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Icon(
                      Icons.notifications_active_outlined,
                      size: 28,
                      color: colors.accent,
                    ),
                    const SizedBox(height: MayosSpacing.md),
                    Text(
                      copy.restAlertPermissionMessage,
                      style: MayosTypography.of(context)
                          .body
                          .copyWith(color: colors.textPrimary),
                    ),
                  ],
                ),
              ),
            ),
      bottomBar: _loading
          ? null
          : Padding(
              padding: const EdgeInsets.fromLTRB(
                MayosSpacing.lg,
                MayosSpacing.sm,
                MayosSpacing.lg,
                MayosSpacing.md,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  MayosButton(
                    key: const Key('rest_alert_permission_allow'),
                    label: copy.allow,
                    onPressed: _working ? null : _allow,
                    loading: _working,
                    icon: Icons.notifications_active_outlined,
                  ),
                  const SizedBox(height: MayosSpacing.xs),
                  MayosButton(
                    key: const Key('rest_alert_permission_not_now'),
                    label: copy.notNow,
                    variant: MayosButtonVariant.secondary,
                    onPressed: _working ? null : _skip,
                  ),
                ],
              ),
            ),
    );
  }
}
