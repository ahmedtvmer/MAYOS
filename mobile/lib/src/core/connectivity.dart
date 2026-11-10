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
/// when either connectivity source reports offline.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({this.showingSavedData = false, super.key});

  final bool showingSavedData;

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
            Flexible(
              child: Text(
                showingSavedData
                    ? displayCopyOf(context).offlineSavedData
                    : displayCopyOf(context).offlineBanner,
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
    final bool saved = ref.watch(authControllerProvider).isOffline;
    final bool online =
        enabled ? ref.watch(connectivityControllerProvider) : true;
    return Visibility(
      visible: saved || (enabled && !online),
      child: SizedBox(
        width: double.infinity,
        child: OfflineBanner(showingSavedData: saved),
      ),
    );
  }
}
