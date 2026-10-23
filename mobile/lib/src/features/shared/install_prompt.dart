import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/analytics_client.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/install_prompt_copy.dart';
import '../../core/install_prompt_store.dart';
import '../../core/install_prompt_store_stub.dart'
    if (dart.library.js_interop) '../../core/install_prompt_store_web.dart'
    as platform;
import '../../core/theme/myos_theme.dart';
import '../../providers.dart';

final Provider<InstallPromptStore> installPromptStoreProvider =
    Provider<InstallPromptStore>((ref) => platform.createInstallPromptStore(
          ref.watch(browserKeyValueStoreProvider),
        ));

final StateNotifierProvider<InstallPromptController, InstallPromptVariant?>
    installPromptProvider = StateNotifierProvider<InstallPromptController, InstallPromptVariant?>((ref) {
  return InstallPromptController(
    ref.watch(installPromptStoreProvider),
    ref.watch(analyticsClientProvider),
  );
});

class InstallPromptController extends StateNotifier<InstallPromptVariant?> {
  InstallPromptController(this._store, this._analytics) : super(null) {
    _store.listenForInstalled(_handleInstalled);
    _store.listenForInstallState(() {
      if (state == null) unawaited(_load());
    });
    if (_store.consumeInstalled()) _handleInstalled();
    unawaited(_load());
  }

  final InstallPromptStore _store;
  final AnalyticsClient _analytics;
  InstallPromptVariant? _lastVariant;
  bool _dismissedThisVisit = false;
  bool _installedThisVisit = false;
  bool _installationRecorded = false;
  InstallPromptVariant? _lastShownVariant;

  Future<void> _load() async {
    final InstallPromptEnvironment environment = await _store.readEnvironment();
    state = _dismissedThisVisit || _installedThisVisit
        ? null
        : environment.variant;
    final InstallPromptVariant? variant = state;
    if (variant == null) _lastShownVariant = null;
    if (variant != null && variant != _lastShownVariant) {
      _lastVariant = variant;
      _lastShownVariant = variant;
      _analytics.installPromptShown(variant);
    }
  }

  Future<void> dismiss() async {
    final InstallPromptVariant? variant = state;
    if (variant == null) return;
    await _dismiss(variant);
  }

  Future<void> accept() async {
    final InstallPromptVariant? variant = state;
    if (variant == null) return;
    final String outcome = await _store.promptInstall();
    if (outcome == 'accepted') {
      state = null;
      _analytics.installPromptAccepted(variant);
    } else if (outcome == 'dismissed') {
      await _dismiss(variant);
    }
  }

  Future<void> _dismiss(InstallPromptVariant variant) async {
    _dismissedThisVisit = true;
    state = null;
    _analytics.installPromptDismissed(variant);
    await _store.rememberDismissal();
  }

  void _handleInstalled() {
    if (_installationRecorded) return;
    _installationRecorded = true;
    _installedThisVisit = true;
    state = null;
    _analytics.appInstalled(_lastVariant ?? InstallPromptVariant.none);
  }
}

class InstallPromptBanner extends ConsumerWidget {
  const InstallPromptBanner({super.key, this.enabled = true});

  /// Lets a screen keep the banner's slot (and its own widget tree) stable
  /// while hiding it, so toggling never resets state below it.
  final bool enabled;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final InstallPromptVariant? variant = ref.watch(installPromptProvider);
    if (!enabled || variant == null) return const SizedBox.shrink();
    final InstallPromptCopy copy = InstallPromptCopy(ref.watch(displayLanguageProvider));
    final MyosThemeExtension colors = MyosTheme.of(context);
    return Card(
      color: colors.surfaceElevated,
      child: ListTile(
        title: Text(variant == InstallPromptVariant.button ? copy.button : copy.hint),
        trailing: IconButton(
          tooltip: copy.dismiss,
          onPressed: () => unawaited(ref.read(installPromptProvider.notifier).dismiss()),
          icon: const Icon(Icons.close),
        ),
        onTap: variant == InstallPromptVariant.button
            ? () => unawaited(ref.read(installPromptProvider.notifier).accept())
            : null,
      ),
    );
  }
}
