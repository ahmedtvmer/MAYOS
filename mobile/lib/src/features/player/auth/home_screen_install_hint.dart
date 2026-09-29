import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/home_screen_install_hint_store.dart';
import '../../../core/home_screen_install_hint_store_stub.dart'
    if (dart.library.js_interop) '../../../core/home_screen_install_hint_store_web.dart'
    as platform;
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../providers.dart';

export '../../../core/home_screen_install_hint_store.dart';

final Provider<HomeScreenInstallHintStore> homeScreenInstallHintStoreProvider =
    Provider<HomeScreenInstallHintStore>(
  (ref) => platform.createHomeScreenInstallHintStore(
    ref.watch(browserKeyValueStoreProvider),
  ),
);

final StateNotifierProvider<HomeScreenInstallHintController, bool>
    homeScreenInstallHintProvider =
    StateNotifierProvider<HomeScreenInstallHintController, bool>((ref) {
  return HomeScreenInstallHintController(
    ref.watch(homeScreenInstallHintStoreProvider),
  );
});

class HomeScreenInstallHintController extends StateNotifier<bool> {
  HomeScreenInstallHintController(this._store) : super(false) {
    unawaited(_load());
  }

  final HomeScreenInstallHintStore _store;

  Future<void> _load() async {
    final HomeScreenInstallHintEnvironment environment =
        await _store.readEnvironment();
    state = environment.shouldShow;
  }

  /// Hides the hint now; remembering it across visits is best-effort, so a
  /// browser that refuses storage still gets a working close button.
  Future<void> dismiss() async {
    if (!state) return;
    state = false;
    await _store.rememberDismissal();
  }
}

/// A stable auth-frame slot, so showing or dismissing the hint cannot recreate
/// authentication fields. It gives space back to the form while typing.
class HomeScreenInstallHintSlot extends ConsumerWidget {
  const HomeScreenInstallHintSlot({super.key, required this.enabled});

  final bool enabled;

  static const String message = 'Add MAYOS: Share → Add to Home Screen.';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool hintVisible =
        enabled && ref.watch(homeScreenInstallHintProvider);
    return AnimatedSize(
      key: const Key('home-screen-install-hint-slot'),
      alignment: Alignment.topCenter,
      duration: MayosMotion.fast,
      curve: Curves.easeOut,
      child: hintVisible
          ? SizedBox(
              height: kMayosMinTapTarget + MayosSpacing.xs,
              child: _HomeScreenInstallHintBanner(
                onDismiss: () => unawaited(
                  ref.read(homeScreenInstallHintProvider.notifier).dismiss(),
                ),
              ),
            )
          : const SizedBox.shrink(),
    );
  }
}

class _HomeScreenInstallHintBanner extends StatelessWidget {
  const _HomeScreenInstallHintBanner({required this.onDismiss});

  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surfaceElevated,
        borderRadius: MayosRadii.smallRadius,
        border: Border.all(color: colors.border),
      ),
      child: Padding(
        padding: const EdgeInsets.only(left: MayosSpacing.xs),
        child: Row(
          children: <Widget>[
            const Expanded(child: _HomeScreenInstallHintText()),
            _HomeScreenInstallHintDismissButton(onDismiss: onDismiss),
          ],
        ),
      ),
    );
  }
}

class _HomeScreenInstallHintText extends StatelessWidget {
  const _HomeScreenInstallHintText();

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Text(
      HomeScreenInstallHintSlot.message,
      maxLines: 1,
      softWrap: false,
      overflow: TextOverflow.ellipsis,
      style: MayosTypography.captionStrong.copyWith(color: colors.textPrimary),
    );
  }
}

class _HomeScreenInstallHintDismissButton extends StatelessWidget {
  const _HomeScreenInstallHintDismissButton({required this.onDismiss});

  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return IconButton(
      tooltip: 'Dismiss Home Screen hint',
      onPressed: onDismiss,
      constraints: const BoxConstraints(
        minWidth: kMayosMinTapTarget,
        minHeight: kMayosMinTapTarget,
      ),
      padding: EdgeInsets.zero,
      icon: Icon(
        Icons.close,
        size: MayosIconSizes.medium,
        color: colors.textSecondary,
      ),
    );
  }
}
