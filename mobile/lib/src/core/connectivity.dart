import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'api_client.dart';
import 'connectivity_message.dart';
import 'theme/mayos_spacing.dart';
import 'theme/mayos_theme.dart';
import 'theme/mayos_typography.dart';

/// Whether this client may show the offline banner (#127): web only, so the
/// Android surface stays exactly as it was. Injectable so tests can force it.
final Provider<bool> offlineBannerEnabledProvider =
    Provider<bool>((ref) => kIsWeb);

/// Connectivity derived from the API client's own transport, with no
/// connectivity package and no polling (#127): an [ApiException] with a null
/// status code (`isNetworkFailure`) means the client cannot reach the
/// service — offline — and the next successful response means it can again.
///
/// `true` is online. The state lives on the provider so one overlay reads it.
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

/// The app's connectivity flag, fed by the interceptors on the shared
/// [ApiClient] (#127): offline on a transport failure, online on the next
/// successful response. Created on first read, which the offline banner
/// overlay performs on web only, so Android adds no behaviour at all.
final StateNotifierProvider<ConnectivityController, bool>
    connectivityControllerProvider =
    StateNotifierProvider<ConnectivityController, bool>((ref) {
  final ConnectivityController controller = ConnectivityController();
  ref.watch(apiClientProvider).dio.interceptors.add(
        InterceptorsWrapper(
          onResponse: (Response<dynamic> response,
              ResponseInterceptorHandler handler) {
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
        ),
      );
  return controller;
});

/// Compact, non-blocking "You're offline" line shown over the app while the
/// client cannot reach the service (#127). Web only; no interaction.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key});

  /// The banner's line, exposed so tests can find it.
  static const String message = "You're offline";

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Material(
      color: c.surfaceElevated,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: MayosSpacing.md,
            vertical: MayosSpacing.xs,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Icon(Icons.cloud_off, size: 16, color: c.textSecondary),
              const SizedBox(width: MayosSpacing.xs),
              Text(
                message,
                style: MayosTypography.body.copyWith(color: c.textPrimary),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
