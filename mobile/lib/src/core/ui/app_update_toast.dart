import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../router.dart' show logWorkoutPath;
import '../app_update_store.dart';
import '../display_language/app_update_copy.dart';
import '../display_language/controller.dart';

class AppUpdateToast extends ConsumerStatefulWidget {
  const AppUpdateToast({
    required this.router,
    required this.child,
    super.key,
  });

  final GoRouter router;
  final Widget child;

  @override
  ConsumerState<AppUpdateToast> createState() => _AppUpdateToastState();
}

class _AppUpdateToastState extends ConsumerState<AppUpdateToast> {
  StreamSubscription<bool>? _subscription;
  bool _waiting = false;
  bool _dismissedThisSession = false;

  bool get _onLogger {
    final String path = widget.router.routeInformationProvider.value.uri.path;
    return path == logWorkoutPath || path.startsWith('$logWorkoutPath/');
  }

  @override
  void initState() {
    super.initState();
    widget.router.routeInformationProvider.addListener(_routeChanged);
    _subscription = ref
        .read(appUpdateStoreProvider)
        .updateWaiting
        .listen((bool waiting) {
      if (!mounted) return;
      setState(() => _waiting = waiting);
    });
  }

  void _routeChanged() => setState(() {});

  void _dismiss() => setState(() => _dismissedThisSession = true);

  Future<void> _applyUpdate() async {
    _dismiss();
    await ref.read(appUpdateStoreProvider).applyUpdate();
  }

  @override
  void dispose() {
    widget.router.routeInformationProvider.removeListener(_routeChanged);
    _subscription?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bool showToast = _waiting && !_dismissedThisSession && !_onLogger;
    // Always a Stack, so showing the toast never reparents the app's navigator.
    return Stack(
      fit: StackFit.expand,
      children: <Widget>[
        widget.child,
        if (showToast) _toast(context),
      ],
    );
  }

  Widget _toast(BuildContext context) {
    final AppUpdateCopy copy = AppUpdateCopy(ref.watch(displayLanguageProvider));
    final SnackBarThemeData snackBarTheme = Theme.of(context).snackBarTheme;
    final MediaQueryData mediaQuery = MediaQuery.of(context);
    final EdgeInsets inset =
        snackBarTheme.insetPadding ?? const EdgeInsets.all(16);
    return Positioned(
          left: inset.left,
          right: inset.right,
          bottom: mediaQuery.padding.bottom + 88,
          child: Material(
            color: snackBarTheme.backgroundColor ??
                Theme.of(context).colorScheme.inverseSurface,
            elevation: snackBarTheme.elevation ?? 0,
            shape: snackBarTheme.shape ??
                RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
            clipBehavior: Clip.antiAlias,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: <Widget>[
                  Expanded(
                    child: Text(
                      copy.newVersionAvailable,
                      style: snackBarTheme.contentTextStyle,
                    ),
                  ),
                  TextButton(
                    onPressed: _applyUpdate,
                    style: TextButton.styleFrom(
                      foregroundColor: snackBarTheme.actionTextColor,
                    ),
                    child: Text(copy.refresh),
                  ),
                  Semantics(
                    button: true,
                    label: copy.dismissUpdate,
                    onTap: _dismiss,
                    child: ExcludeSemantics(
                      child: IconButton(
                        onPressed: _dismiss,
                        icon: const Icon(Icons.close),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
  }
}
