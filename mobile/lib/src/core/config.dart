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

/// Build-time gate for ExerciseDB-derived exercise media (#53).
///
/// Exercise media is not bundled into the app and its provenance is not yet
/// resolved (see `docs/design-review/53/MEDIA-PROVENANCE.md`), so this defaults
/// to OFF. When OFF the exercise-detail hero is a typographic/muscle-group
/// header; no `Image` widget is ever built. Enable with
/// `--dart-define=MAYOS_EXERCISE_MEDIA=true` only after a served, rights-cleared
/// media URL exists.
const bool mayosExerciseMediaEnabled =
    String.fromEnvironment('MAYOS_EXERCISE_MEDIA') == 'true';
