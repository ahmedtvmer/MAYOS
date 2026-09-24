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

class _MayosAppState extends ConsumerState<MayosApp> {
  @override
  void initState() {
    super.initState();
    // Resolve any persisted session once, off the first frame.
    Future<void>.microtask(
      () => ref.read(authControllerProvider.notifier).initialize(),
    );
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
