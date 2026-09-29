import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/theme/mayos_theme.dart';
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
    final ThemeMode themeMode = ref.watch(themeModeControllerProvider);

    return MaterialApp.router(
      title: 'MAYOS',
      debugShowCheckedModeBanner: false,
      theme: MayosTheme.light,
      darkTheme: MayosTheme.dark,
      themeMode: themeMode,
      // Root messenger for permission one-liners raised outside a screen's
      // own messenger (the rest-alarm ask, #125).
      scaffoldMessengerKey: mayosMessengerKey,
      routerConfig: router,
      builder: (BuildContext context, Widget? child) {
        final MayosThemeExtension c = _effective(context, themeMode);
        return AnnotatedRegion<SystemUiOverlayStyle>(
          value: MayosTheme.overlayStyle(c),
          child: child ?? const SizedBox.shrink(),
        );
      },
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
