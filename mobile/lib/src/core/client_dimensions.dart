import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;

const String _configuredAppVersion =
    String.fromEnvironment('FLUTTER_BUILD_NAME');

String get clientAppVersion =>
    _configuredAppVersion.isEmpty ? 'unknown' : _configuredAppVersion;

String resolveClientPlatform({
  required bool isWeb,
  required TargetPlatform platform,
}) {
  if (isWeb) return 'web';
  return platform == TargetPlatform.android ? 'android' : 'unknown';
}

Map<String, String> analyticsCommonDimensions({required bool isRelease}) =>
    <String, String>{
      'platform': resolveClientPlatform(
        isWeb: kIsWeb,
        platform: defaultTargetPlatform,
      ),
      'app_version': clientAppVersion,
      'env': isRelease ? 'production' : 'development',
    };
