import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/app_mode.dart';
import 'core/connectivity.dart';
import 'core/theme/mayos_spacing.dart';
import 'core/theme/mayos_theme.dart';
import 'core/ui/is_desktop_layout.dart';
import 'core/ui/mayos_app_mode_scope.dart';
import 'providers.dart';
import 'router.dart';

class MayosApp extends ConsumerStatefulWidget {
  const MayosApp({super.key});

  @override
  ConsumerState<MayosApp> createState() => _MayosAppState();
}

class _MayosAppState extends ConsumerState<MayosApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Keep API and browser signals alive during splash and auth startup, before
    // either shared screen frame has mounted its banner slot. Android remains
    // outside the provider because the banner flag is false there.
    if (ref.read(offlineBannerEnabledProvider)) {
      ref.read(connectivityControllerProvider);
    }
    // Eagerly build the draft sync service so its auth listener is attached
    // before any screen reads it, so a stored session starts syncing at app
    // start rather than only once the home screen mounts (ADR 020/033).
    ref.read(draftSyncServiceProvider);
    // Resolve any persisted session once, off the first frame.
    Future<void>.microtask(
      () => ref.read(authControllerProvider.notifier).initialize(),
    );
    // Load the persisted appearance choice off the first frame.
    Future<void>.microtask(
      () => ref.read(themeModeControllerProvider.notifier).initialize(),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      // Grants/revocations can happen elsewhere; refresh live capabilities.
      unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
      ref.read(draftSyncServiceProvider).resumeForeground();
    } else if (state == AppLifecycleState.paused) {
      // Offline drafts sync only while the app is in the foreground (ADR 020/033).
      ref.read(draftSyncServiceProvider).pauseForeground();
    } else if (state == AppLifecycleState.detached) {
      // The coach-assistant transcript is memory-only: drop it as the process
      // leaves so nothing lingers into a later launch (issue #45).
      ref.read(coachAssistantControllerProvider.notifier).clear();
    }
  }

  @override
  Widget build(BuildContext context) {
    final GoRouter router = ref.watch(routerProvider);
    // The capability caps the mode: a lost coach capability lays out as
    // Player mode whatever is stored.
    final AppMode appMode = resolveAppMode(
      isCoach:
          ref.watch(authControllerProvider).session?.account.isCoach ?? false,
      stored: ref.watch(appModeControllerProvider).mode,
    );
    final ThemeMode themeMode = ref.watch(themeModeControllerProvider);
    return MaterialApp.router(
      title: 'MAYOS',
      debugShowCheckedModeBanner: false,
      theme: MayosTheme.light,
      darkTheme: MayosTheme.dark,
      themeMode: themeMode,
      routerConfig: router,
      builder: (BuildContext context, Widget? child) {
        final MayosThemeExtension c = _effective(context, themeMode);
        return MayosAppModeScope(
          mode: appMode,
          child: Theme(
            data: _responsiveOverlayTheme(context, appMode, themeMode),
            child: ScaffoldMessenger(
              // Own the app's screen snackbars under the responsive theme.
              // The same messenger also receives permission prompts via its
              // global key.
              key: mayosMessengerKey,
              child: AnnotatedRegion<SystemUiOverlayStyle>(
                value: MayosTheme.overlayStyle(c),
                child: child ?? const SizedBox.shrink(),
              ),
            ),
          ),
        );
      },
    );
  }

  ThemeData _responsiveOverlayTheme(
    BuildContext context,
    AppMode mode,
    ThemeMode themeMode,
  ) {
    final bool desktop = isDesktopLayout(context);
    final double overlayMaxWidth;
    if (!desktop) {
      overlayMaxWidth = MediaQuery.sizeOf(context).width;
    } else if (mode == AppMode.player) {
      overlayMaxWidth = MayosLayout.playerColumnMaxWidth;
    } else {
      overlayMaxWidth = MayosLayout.coachOverlayMaxWidth;
    }
    final ThemeData theme = switch (themeMode) {
      ThemeMode.light => MayosTheme.light,
      ThemeMode.dark => MayosTheme.dark,
      ThemeMode.system =>
        MediaQuery.platformBrightnessOf(context) == Brightness.dark
            ? MayosTheme.dark
            : MayosTheme.light,
    };
    return theme.copyWith(
      bottomSheetTheme: theme.bottomSheetTheme.copyWith(
        constraints: BoxConstraints(maxWidth: overlayMaxWidth),
      ),
      snackBarTheme: theme.snackBarTheme.copyWith(
        width: desktop ? overlayMaxWidth : null,
      ),
    );
  }

  MayosThemeExtension _effective(BuildContext context, ThemeMode mode) {
    switch (mode) {
      case ThemeMode.light:
        return MayosThemeExtension.light;
      case ThemeMode.dark:
        return MayosThemeExtension.dark;
      case ThemeMode.system:
        final Brightness brightness = MediaQuery.platformBrightnessOf(context);
        return brightness == Brightness.dark
            ? MayosThemeExtension.dark
            : MayosThemeExtension.light;
    }
  }
}
