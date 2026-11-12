import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'api_client.dart';
import 'display_language/copy_context.dart';
import 'connectivity_events.dart';
import 'saved_player_reads.dart';
import '../features/player/auth/auth_controller.dart';
import 'theme/mayos_spacing.dart';
import 'theme/mayos_theme.dart';
import 'theme/mayos_typography.dart';

/// Shared connectivity signals and banners on web and Android (ADR 112).
final Provider<bool> offlineBannerEnabledProvider =
    Provider<bool>((ref) => true);

/// Platform network hints. The historical provider name is retained so existing
/// browser tests can inject their event stream without a browser runtime.
final Provider<Stream<bool>> browserConnectivityEventsProvider =
    Provider<Stream<bool>>(
      (ref) => browserConnectivityEvents().asBroadcastStream(),
    );

/// Connectivity combines browser events with the API client's transport:
/// browser events report navigator status, transport failures mean offline,
/// and completed API responses mean online (#127/#172).
///
/// `true` is online. Shared screen frames read the provider for the banner.
class ConnectivityController extends StateNotifier<bool> {
  ConnectivityController() : super(true);

  /// A transport failure or timeout prevents a complete response.
  void markOffline() {
    state = false;
  }

  /// Any completed response proves the connection is back.
  void markOnline() {
    if (!state) {
      state = true;
    }
  }
}

/// The app's connectivity flag, fed by browser events and interceptors on the
/// shared [ApiClient]. A cached response never proves connectivity.
final StateNotifierProvider<ConnectivityController, bool>
    connectivityControllerProvider =
    StateNotifierProvider<ConnectivityController, bool>((ref) {
  final ConnectivityController controller = ConnectivityController();
  final StreamSubscription<bool> browserEvents =
      ref.watch(browserConnectivityEventsProvider).listen((bool online) {
    if (online) {
      controller.markOnline();
    } else {
      controller.markOffline();
    }
  });
  final Interceptors interceptors =
      ref.watch(apiClientProvider).dio.interceptors;
  final InterceptorsWrapper watcher = InterceptorsWrapper(
    onResponse:
        (Response<dynamic> response, ResponseInterceptorHandler handler) {
      if (response.extra[SavedPlayerReads.cachedResponse] != true) {
        controller.markOnline();
      }
      handler.next(response);
    },
    onError: (DioException error, ErrorInterceptorHandler handler) {
      // A completed refusal proves reachability; a timeout may be partial.
      if (isTransportFailure(error)) {
        controller.markOffline();
      } else {
        controller.markOnline();
      }
      handler.next(error);
    },
  );
  interceptors.add(watcher);
  // A rebuilt provider must not leave its old watcher on the client, feeding a
  // disposed controller.
  ref.onDispose(() {
    unawaited(browserEvents.cancel());
    interceptors.remove(watcher);
  });
  return controller;
});

/// Compact, non-blocking connection or service status line in shared frames.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({this.label, this.icon, super.key});

  final String? label;
  final IconData? icon;

  /// The banner's line, exposed so tests can find it.
  static const String message = "You're offline";

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Material(
      color: c.surfaceElevated,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md,
          vertical: MayosSpacing.xs,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(icon ?? Icons.cloud_off,
                size: MayosIconSizes.small, color: c.textSecondary),
            const SizedBox(width: MayosSpacing.xs),
            Flexible(
              child: Text(
                label ?? displayCopyOf(context).offlineBanner,
                style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Banner slot kept in the same place in app frames. It collapses when online
/// and pushes content down when shown; keeping the slot mounted means
/// connectivity changes do not replace the focused auth field.
class OfflineBannerSlot extends ConsumerWidget {
  const OfflineBannerSlot({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool enabled = ref.watch(offlineBannerEnabledProvider);
    if (enabled && !kIsWeb) {
      ref.listen<bool>(
        connectivityControllerProvider,
        (bool? previous, bool online) {
          if (online && previous == false) {
            unawaited(
              ref.read(authControllerProvider.notifier).retrySavedSession(),
            );
          }
        },
      );
    }
    final SavedSessionIssue? savedIssue =
        ref.watch(authControllerProvider).savedSessionIssue;
    final bool saved = savedIssue != null;
    final bool online =
        enabled ? ref.watch(connectivityControllerProvider) : true;
    final String? message = switch (savedIssue) {
      null => null,
      SavedSessionIssue.offline => displayCopyOf(context).offlineSavedData,
      SavedSessionIssue.serviceProblem =>
        displayCopyOf(context).serviceUnavailable,
    };
    return Visibility(
      visible: saved || (enabled && !online),
      child: SizedBox(
        width: double.infinity,
        child: OfflineBanner(
          label: message,
          icon: savedIssue == SavedSessionIssue.serviceProblem
              ? Icons.warning_amber_rounded
              : null,
        ),
      ),
    );
  }
}
