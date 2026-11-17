import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

abstract class TourTargetLocation {
  const TourTargetLocation();

  bool matches(String routePath, int shellTabIndex);

  void navigate(GoRouter router, StateController<int> shellTabController);
}

String currentTourRoutePath(GoRouter router) {
  final RouteMatchList configuration =
      router.routerDelegate.currentConfiguration;
  return configuration.isEmpty
      ? router.routeInformationProvider.value.uri.path
      : router.routerDelegate.state.uri.path;
}

class TourShellTabLocation extends TourTargetLocation {
  const TourShellTabLocation({required this.tabIndex, this.routePath = '/home'});

  final int tabIndex;
  final String routePath;

  @override
  bool matches(String routePath, int shellTabIndex) =>
      routePath == this.routePath && shellTabIndex == tabIndex;

  @override
  void navigate(GoRouter router, StateController<int> shellTabController) {
    if (currentTourRoutePath(router) != routePath) {
      router.go(routePath);
    }
    shellTabController.state = tabIndex;
  }

  @override
  bool operator ==(Object other) =>
      other is TourShellTabLocation &&
      other.tabIndex == tabIndex &&
      other.routePath == routePath;

  @override
  int get hashCode => Object.hash(tabIndex, routePath);
}

class TourRouteLocation extends TourTargetLocation {
  const TourRouteLocation(this.path);

  final String path;

  @override
  bool matches(String routePath, int shellTabIndex) => routePath == path;

  @override
  void navigate(GoRouter router, StateController<int> shellTabController) {
    if (currentTourRoutePath(router) != path) {
      router.push(path);
    }
  }

  @override
  bool operator ==(Object other) =>
      other is TourRouteLocation && other.path == path;

  @override
  int get hashCode => path.hashCode;
}

class TourTargetHandle {
  const TourTargetHandle({
    required this.id,
    required this.key,
  });

  final String id;
  final GlobalKey key;
}

class TourTargetRegistry extends StateNotifier<Map<String, TourTargetHandle>> {
  TourTargetRegistry() : super(const <String, TourTargetHandle>{});

  void register(TourTargetHandle target) {
    state = <String, TourTargetHandle>{...state, target.id: target};
  }

  void unregister(String id, GlobalKey key) {
    if (!mounted) return;
    final TourTargetHandle? current = state[id];
    if (current == null || current.key != key) return;
    state = Map<String, TourTargetHandle>.of(state)..remove(id);
  }
}

final StateNotifierProvider<TourTargetRegistry,
        Map<String, TourTargetHandle>>
    tourTargetRegistryProvider = StateNotifierProvider<
        TourTargetRegistry, Map<String, TourTargetHandle>>(
      (ref) => TourTargetRegistry(),
    );

class TourTarget extends ConsumerStatefulWidget {
  const TourTarget({
    required this.id,
    required this.child,
    super.key,
  });

  final String id;
  final Widget child;

  @override
  ConsumerState<TourTarget> createState() => _TourTargetState();
}

class _TourTargetState extends ConsumerState<TourTarget> {
  final GlobalKey _targetKey = GlobalKey();
  late final TourTargetRegistry _registry;

  @override
  void initState() {
    super.initState();
    _registry = ref.read(tourTargetRegistryProvider.notifier);
    _register();
  }

  @override
  void didUpdateWidget(TourTarget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.id != widget.id) _unregister(oldWidget.id);
    if (oldWidget.id != widget.id) _register();
  }

  void _register() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _registry.register(
        TourTargetHandle(
          id: widget.id,
          key: _targetKey,
        ),
      );
    });
  }

  void _unregister(String id) {
    unawaited(Future<void>.microtask(() => _registry.unregister(id, _targetKey)));
  }

  @override
  void dispose() {
    _unregister(widget.id);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      KeyedSubtree(key: _targetKey, child: widget.child);
}

final StateProvider<Set<String>> tourLoadingDestinationsProvider =
    StateProvider<Set<String>>((ref) => const <String>{});

final StateProvider<Set<String>> tourLoadingTargetsProvider =
    StateProvider<Set<String>>((ref) => const <String>{});
