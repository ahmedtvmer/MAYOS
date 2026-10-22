import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/home_screen_install_hint_store.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/home_screen_install_hint_store_stub.dart'
    if (dart.library.js_interop) '../../../core/home_screen_install_hint_store_web.dart'
    as platform;
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
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

  static const String message = 'Add MYOS: Share → Add to Home Screen.';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool hintVisible =
        enabled && ref.watch(homeScreenInstallHintProvider);
    return AnimatedSize(
      key: const Key('home-screen-install-hint-slot'),
      alignment: Alignment.topCenter,
      duration: MyosMotion.fast,
      curve: Curves.easeOut,
      child: hintVisible
          ? SizedBox(
              height: kMyosMinTapTarget + MyosSpacing.xs,
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
    final MyosThemeExtension colors = MyosTheme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surfaceElevated,
        borderRadius: MyosRadii.smallRadius,
        border: Border.all(color: colors.border),
      ),
      child: Padding(
        padding: const EdgeInsetsDirectional.only(start: MyosSpacing.xs),
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

class _HomeScreenInstallHintText extends ConsumerWidget {
  const _HomeScreenInstallHintText();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final MyosThemeExtension colors = MyosTheme.of(context);
    return Text(
      MyosCopy(ref.watch(displayLanguageProvider)).homeScreenHint,
      maxLines: 1,
      softWrap: false,
      overflow: TextOverflow.ellipsis,
      style: MyosTypography.of(context).captionStrong.copyWith(color: colors.textPrimary),
    );
  }
}

class _HomeScreenInstallHintDismissButton extends ConsumerWidget {
  const _HomeScreenInstallHintDismissButton({required this.onDismiss});

  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final MyosThemeExtension colors = MyosTheme.of(context);
    return IconButton(
      tooltip:
          MyosCopy(ref.watch(displayLanguageProvider)).dismissHomeScreenHint,
      onPressed: onDismiss,
      constraints: const BoxConstraints(
        minWidth: kMyosMinTapTarget,
        minHeight: kMyosMinTapTarget,
      ),
      padding: EdgeInsets.zero,
      icon: Icon(
        Icons.close,
        size: MyosIconSizes.medium,
        color: colors.textSecondary,
      ),
    );
  }
}
