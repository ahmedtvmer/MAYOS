import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'api_client.dart';
import 'display_language/copy_context.dart';
import 'connectivity_events.dart';
import 'connectivity_message.dart';
import 'theme/mayos_spacing.dart';
import 'theme/mayos_theme.dart';
import 'theme/mayos_typography.dart';

/// Whether this client may show the offline banner (#127): web only, so the
/// Android surface stays exactly as it was. Injectable so tests can force it.
final Provider<bool> offlineBannerEnabledProvider =
    Provider<bool>((ref) => kIsWeb);

/// Browser online/offline events. Tests can override this stream to exercise
/// the web connectivity source without a browser runtime.
final Provider<Stream<bool>> browserConnectivityEventsProvider =
    Provider<Stream<bool>>((ref) => browserConnectivityEvents());

/// Connectivity combines browser events with the API client's transport:
/// browser events report navigator status, a transport failure means offline,
/// and any API response means online (#127/#172).
///
/// `true` is online. Shared screen frames read the provider for the banner.
class ConnectivityController extends StateNotifier<bool> {
  ConnectivityController() : super(true);

  /// A transport failure: the service could not be reached at all.
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

/// True for the Dio error that [isNetworkFailure] would report: no response,
/// therefore no status code.
bool _isTransportFailure(DioException error) => isNetworkFailure(ApiException(
      error.message ?? '',
      statusCode: error.response?.statusCode,
    ));

/// The app's connectivity flag, fed by browser events and interceptors on the
/// shared [ApiClient]. Created only when web banner display is enabled, so
/// Android adds no behavior at all.
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
      controller.markOnline();
      handler.next(response);
    },
    onError: (DioException error, ErrorInterceptorHandler handler) {
      // A refusal still carries a response, so the service was reached.
      if (_isTransportFailure(error)) {
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

/// Compact, non-blocking "You're offline" line shown in shared screen frames
/// when either connectivity source reports offline. Web only; no interaction.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key});

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
            Icon(Icons.cloud_off,
                size: MayosIconSizes.small, color: c.textSecondary),
            const SizedBox(width: MayosSpacing.xs),
            Text(
              displayCopyOf(context).offlineBanner,
              style: MayosTypography.body.copyWith(color: c.textPrimary),
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
    final bool online =
        enabled ? ref.watch(connectivityControllerProvider) : true;
    return Visibility(
      visible: enabled && !online,
      child: const SizedBox(
        width: double.infinity,
        child: OfflineBanner(),
      ),
    );
  }
}
