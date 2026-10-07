import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;

const String _configuredAppVersion =
    String.fromEnvironment('FLUTTER_BUILD_NAME');
const String _configuredBuildNumber =
    String.fromEnvironment('FLUTTER_BUILD_NUMBER');

String get clientAppVersion =>
    _configuredAppVersion.isEmpty ? 'unknown' : _configuredAppVersion;

/// The Android versionCode supplied by Flutter's Android build, or null when
/// a build omits it. A missing number sends no build header, so the server's
/// minimum-build policy fails open instead of blocking the install.
int? get clientAppBuildNumber {
  final int? parsedBuildNumber = int.tryParse(_configuredBuildNumber);
  return parsedBuildNumber != null && parsedBuildNumber >= 0
      ? parsedBuildNumber
      : null;
}

int? get clientAndroidBuildNumber {
  final String platform = resolveClientPlatform(
    isWeb: kIsWeb,
    platform: defaultTargetPlatform,
  );
  return platform == 'android' ? clientAppBuildNumber : null;
}

String? get clientAppBuildHeader {
  final int? buildNumber = clientAndroidBuildNumber;
  return buildNumber == null ? null : '$buildNumber';
}

String resolveClientPlatform({
  required bool isWeb,
  required TargetPlatform platform,
}) {
  if (isWeb) return 'web';
  return platform == TargetPlatform.android ? 'android' : 'unknown';
}

/// Returns a build header only for a valid Android build number.
String? buildHeaderForPlatform({
  required String platform,
  required int? buildNumber,
}) {
  if (platform != 'android' || buildNumber == null || buildNumber < 0) {
    return null;
  }
  return '$buildNumber';
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
