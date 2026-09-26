import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
    }
  }

  @override
  Widget build(BuildContext context) {
    final GoRouter router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'MAYOS',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: Colors.deepOrange,
        useMaterial3: true,
      ),
      routerConfig: router,
    );
  }
}
