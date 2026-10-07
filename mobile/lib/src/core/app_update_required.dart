import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

/// One app-wide blocking update state, shared by Player and Coach mode.
class AppUpdateRequiredController extends StateNotifier<AppVersionPolicy?> {
  AppUpdateRequiredController({
    required ApiClient api,
    required int? Function() androidBuildNumber,
  })  : _api = api,
        _androidBuildNumber = androidBuildNumber,
        super(null);

  final ApiClient _api;
  final int? Function() _androidBuildNumber;

  void requireUpdate(AppVersionPolicy policy) => state = policy;

  /// Fails open when the public policy cannot be fetched or parsed.
  Future<void> checkPolicy() async {
    try {
      final AppVersionPolicy policy = await _api.appVersionPolicy();
      final int? currentBuild = _androidBuildNumber();
      if (currentBuild != null && policy.minBuild > currentBuild) {
        requireUpdate(policy);
      }
    } on ApiException {
      // An unavailable policy must never prevent normal app use.
    }
  }
}
