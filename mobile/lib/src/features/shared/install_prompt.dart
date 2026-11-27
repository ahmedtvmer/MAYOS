import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/analytics_client.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/install_prompt_copy.dart';
import '../../core/install_prompt_store.dart';
import '../../core/install_prompt_store_stub.dart'
    if (dart.library.js_interop) '../../core/install_prompt_store_web.dart'
    as platform;
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../providers.dart';
import '../../router.dart';
import '../player/tour/tour_controller.dart';
import '../player/tour/tour_targets.dart';
import '../../core/ui/mayos_logo.dart';

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
  bool _dialogOpened = false;

  Future<void> _load() async {
    final InstallPromptEnvironment environment = await _store.readEnvironment();
    state = _dismissedThisVisit || _installedThisVisit
        ? null
        : environment.variant;
    if (environment.variant != null) _lastVariant = environment.variant;
  }

  bool get dialogOpened => _dialogOpened;

  void markDialogOpened() {
    final InstallPromptVariant? variant = state;
    if (variant == null || _dialogOpened) return;
    _dialogOpened = true;
    _lastVariant = variant;
    _analytics.installPromptShown(variant);
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

final installPromptDelayProvider = Provider<Duration>(
  (ref) => const Duration(milliseconds: 1500),
);

final discoverySheetActiveProvider = StateProvider<bool>((ref) => false);
final installPromptDialogActiveProvider = StateProvider<bool>((ref) => false);

class InstallPromptHost extends ConsumerStatefulWidget {
  const InstallPromptHost({super.key, required this.child, this.enabled = true});

  final Widget child;
  final bool enabled;

  @override
  ConsumerState<InstallPromptHost> createState() => _InstallPromptHostState();
}

class _InstallPromptHostState extends ConsumerState<InstallPromptHost> {
  Timer? _timer;
  bool _scheduled = false;
  GoRouter? _observedRouter;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final GoRouter router = ref.read(routerProvider);
    if (_observedRouter != router) {
      _observedRouter?.routerDelegate.removeListener(_onRouteChanged);
      _observedRouter = router;
      router.routerDelegate.addListener(_onRouteChanged);
    }
    _schedule();
  }

  void _onRouteChanged() => _schedule();

  @override
  void didUpdateWidget(InstallPromptHost oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.enabled != widget.enabled) _schedule();
  }

  void _schedule() {
    _timer?.cancel();
    if (!widget.enabled || _scheduled) return;
    final Route<dynamic>? route = ModalRoute.of(context);
    if (route != null && !route.isCurrent) return;
    _timer = Timer(ref.read(installPromptDelayProvider), () {
      if (!mounted || !widget.enabled) return;
      final Route<dynamic>? currentRoute = ModalRoute.of(context);
      if (currentRoute != null && !currentRoute.isCurrent) return;
      final InstallPromptController controller =
          ref.read(installPromptProvider.notifier);
      final String route = currentTourRoutePath(ref.read(routerProvider));
      if (controller.dialogOpened || ref.read(installPromptProvider) == null) {
        return;
      }
      if (ref.read(tourControllerProvider) != null ||
          ref.read(discoverySheetActiveProvider) ||
          route == featureGuidePath || route == whatsNewPath) {
        return;
      }
      _scheduled = true;
      controller.markDialogOpened();
      ref.read(installPromptDialogActiveProvider.notifier).state = true;
      unawaited(showDialog<void>(
        context: context,
        barrierDismissible: true,
        builder: (BuildContext dialogContext) => _InstallPromptDialog(
          onDismiss: () => unawaited(controller.dismiss()),
          onInstall: controller.accept,
        ),
      ).then((_) {
        if (mounted) {
          ref.read(installPromptDialogActiveProvider.notifier).state = false;
        }
        if (mounted && ref.read(installPromptProvider) != null) {
          unawaited(controller.dismiss());
        }
      }));
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _observedRouter?.routerDelegate.removeListener(_onRouteChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<TourSession?>(tourControllerProvider, (_, next) {
      if (next == null) _schedule();
    });
    ref.listen<bool>(discoverySheetActiveProvider, (_, active) {
      if (active) {
        _timer?.cancel();
      } else {
        _schedule();
      }
    });
    ref.listen<InstallPromptVariant?>(installPromptProvider, (previous, next) {
      if (next != null && previous == null) _schedule();
    });
    return widget.child;
  }
}

class _InstallPromptDialog extends ConsumerWidget {
  const _InstallPromptDialog({required this.onDismiss, required this.onInstall});

  final VoidCallback onDismiss;
  final Future<void> Function() onInstall;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen<InstallPromptVariant?>(installPromptProvider, (previous, next) {
      if (previous != null && next == null && context.mounted) {
        Navigator.of(context).maybePop();
      }
    });
    final InstallPromptVariant? variant = ref.watch(installPromptProvider);
    if (variant == null) return const SizedBox.shrink();
    final String language = ref.watch(displayLanguageProvider);
    final InstallPromptCopy copy = InstallPromptCopy(language);
    final MayosThemeExtension colors = MayosTheme.of(context);
    final bool isButton = variant == InstallPromptVariant.button;
    final bool isArabic = language.toLowerCase().startsWith('ar');
    final String primary = isButton ? copy.install : copy.gotIt;
    return Dialog(
      backgroundColor: colors.surfaceElevated,
      shape: const RoundedRectangleBorder(borderRadius: MayosRadii.xlargeRadius),
      insetPadding: const EdgeInsets.all(MayosSpacing.lg),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 400),
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
            Align(
              alignment: isArabic ? Alignment.topLeft : Alignment.topRight,
              child: IconButton(
                tooltip: copy.dismiss,
                onPressed: () {
                  Navigator.of(context).pop();
                  onDismiss();
                },
                icon: const Icon(Icons.close),
              ),
            ),
            Semantics(
              label: 'MAYOS',
              image: true,
              child: const MayosBrandMark(size: 40),
            ),
            const SizedBox(height: MayosSpacing.md),
            Text(
              copy.title,
              style: MayosTypography.of(context)
                  .sectionHeading
                  .copyWith(color: colors.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.sm),
            if (isButton)
              Text(
                copy.benefit,
                textAlign: TextAlign.center,
                style: MayosTypography.of(context)
                    .body
                    .copyWith(color: colors.textSecondary),
              )
            else ...<Widget>[
              _StepRow(icon: Icons.ios_share, text: copy.shareStep),
              const SizedBox(height: MayosSpacing.sm),
              _StepRow(icon: Icons.add_box_outlined, text: copy.addStep),
            ],
            const SizedBox(height: MayosSpacing.xl),
            MayosButton(
              label: primary,
              onPressed: () {
                if (isButton) {
                  unawaited(onInstall());
                } else {
                  Navigator.of(context).pop();
                  onDismiss();
                }
              },
            ),
            if (isButton)
              MayosButton(
                label: copy.notNow,
                variant: MayosButtonVariant.tertiary,
                onPressed: () {
                  Navigator.of(context).pop();
                  onDismiss();
                },
              ),
          ]),
        ),
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.icon, required this.text});
  final IconData icon;
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xs),
        child: Row(children: <Widget>[
          Icon(icon, color: MayosTheme.of(context).textSecondary),
          const SizedBox(width: MayosSpacing.md),
          Expanded(child: Text(text, style: MayosTypography.of(context).body)),
        ]),
      );
}
