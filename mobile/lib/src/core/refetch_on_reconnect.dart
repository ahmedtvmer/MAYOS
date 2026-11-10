import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';
import 'connectivity.dart';

/// Recovery comes from an explicit browser event or app resume, never from an
/// API response: refreshing must not trigger another round of refreshing.
final StateNotifierProvider<ReconnectController, int> reconnectProvider =
    StateNotifierProvider<ReconnectController, int>((ref) {
  final ReconnectController controller = ReconnectController();
  WidgetsBinding.instance.addObserver(controller);
  final StreamSubscription<bool> subscription = ref
      .watch(browserConnectivityEventsProvider)
      .listen(controller.browserStateChanged);
  ref.onDispose(() {
    WidgetsBinding.instance.removeObserver(controller);
    unawaited(subscription.cancel());
  });
  return controller;
});

class ReconnectController extends StateNotifier<int>
    with WidgetsBindingObserver {
  ReconnectController() : super(0);

  bool _receivedBrowserState = false;

  void browserStateChanged(bool online) {
    // The bridge emits navigator.onLine when subscribed. That initial snapshot
    // must not duplicate screens' initial loads.
    if (_receivedBrowserState && online) state += 1;
    _receivedBrowserState = true;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    if (lifecycle == AppLifecycleState.resumed) state += 1;
  }
}

/// Refetches data in place, preserving selections, forms and workout state.
/// Screens supply their existing read/refresh operation; writes never enter
/// this path. Hidden tabs and covered routes wait until they are visible.
mixin RefetchOnReconnect<T extends ConsumerStatefulWidget> on ConsumerState<T> {
  late final ProviderSubscription<int> _reconnectSubscription;
  bool _refreshingAfterReconnect = false;

  Future<void> refreshAfterReconnect();

  @override
  void initState() {
    super.initState();
    _reconnectSubscription = ref.listenManual<int>(
      reconnectProvider,
      (_, __) => unawaited(Future<void>.microtask(_refreshVisibleScreen)),
    );
  }

  bool get _visibleForRefresh {
    if (!TickerMode.of(context) || ModalRoute.of(context)?.isCurrent == false) {
      return false;
    }
    bool visible = true;
    context.visitAncestorElements((Element ancestor) {
      final Widget widget = ancestor.widget;
      if (widget is Offstage && widget.offstage) visible = false;
      return visible;
    });
    return visible;
  }

  Future<void> _refreshVisibleScreen() async {
    if (!mounted || _refreshingAfterReconnect || !_visibleForRefresh) return;
    _refreshingAfterReconnect = true;
    try {
      await refreshAfterReconnect();
    } on ApiException {
      // FutureBuilder-based screens retain the failed future to show the
      // error. A recovery signal is best-effort and must not leak that error.
    } finally {
      _refreshingAfterReconnect = false;
    }
  }

  @override
  void dispose() {
    _reconnectSubscription.close();
    super.dispose();
  }
}
