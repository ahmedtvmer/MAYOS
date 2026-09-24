import 'package:flutter/foundation.dart';

/// Build-time configuration.
///
/// The API base URL is injected with `--dart-define`:
/// `flutter run --dart-define=MAYOS_API_BASE_URL=https://api.example.com`.
///
/// In debug builds the URL defaults to the Android emulator's host loopback so
/// local development works out of the box. Release builds must supply an
/// explicit HTTPS URL: a bearer token is never sent over cleartext HTTP.
const String configuredApiBaseUrl =
    String.fromEnvironment('MAYOS_API_BASE_URL');

const String debugDefaultApiBaseUrl = 'http://10.0.2.2:8000';

/// Resolves the base URL for a build mode, failing fast on an unsafe release
/// configuration. Kept pure so both branches are unit-testable.
String resolveApiBaseUrl(
    {required bool isRelease, required String configured}) {
  if (configured.isEmpty) {
    if (isRelease) {
      throw StateError(
        'MAYOS_API_BASE_URL is required in release builds. '
        'Pass --dart-define=MAYOS_API_BASE_URL=https://<host>.',
      );
    }
    return debugDefaultApiBaseUrl;
  }
  if (isRelease && !configured.startsWith('https://')) {
    throw StateError(
      'MAYOS_API_BASE_URL must use https:// in release builds (got "$configured").',
    );
  }
  return configured;
}

String get apiBaseUrl => resolveApiBaseUrl(
    isRelease: kReleaseMode, configured: configuredApiBaseUrl);
