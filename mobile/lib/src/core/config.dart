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

/// The public address of one catalog picture (#161): the configured API base
/// plus `GET /media/<image_path>` (`svc/routers/media.py`), which serves the
/// ExerciseDB paths the program payload carries. The route is public — the
/// caller must not attach the bearer token.
///
/// Each path segment is percent-encoded, so a payload can only address a file
/// inside the route's media directory — never a path that escapes it or a
/// query/fragment of its own.
///
/// Returns null when there is nothing to load, and when the value is an
/// absolute `http(s)` URL on a host other than the configured API base: a
/// catalog payload must never point the app at an arbitrary host.
String? mediaUrlFor(String? imagePath) {
  if (imagePath == null) {
    return null;
  }
  final String trimmed = imagePath.trim();
  if (trimmed.isEmpty) {
    return null;
  }
  final String base = apiBaseUrl.endsWith('/')
      ? apiBaseUrl.substring(0, apiBaseUrl.length - 1)
      : apiBaseUrl;
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
    final Uri? resolved = Uri.tryParse(trimmed);
    final Uri? configured = Uri.tryParse(base);
    if (resolved == null || configured == null) {
      return null;
    }
    // Only the API's own host may be addressed directly (the schema allows a
    // URL alongside the usual relative path); anything else is refused.
    return resolved.origin == configured.origin ? resolved.toString() : null;
  }
  final String relative =
      trimmed.startsWith('/') ? trimmed.substring(1) : trimmed;
  final String encoded = relative.split('/').map((String segment) {
    final String encoded = Uri.encodeComponent(segment);
    // `encodeComponent` leaves dots alone, so a dot-only segment would
    // otherwise travel as a path-traversal token; escape it (#53).
    final bool dotOnly =
        segment.isNotEmpty && segment.codeUnits.every((int unit) => unit == 0x2E);
    return dotOnly ? encoded.replaceAll('.', '%2E') : encoded;
  }).join('/');
  return '$base/media/$encoded';
}

/// Build-time gate for ExerciseDB/Gym visual exercise media (#53).
///
/// ON by default: the owner decided on 2026-09-29 to show the catalog's
/// images and GIFs (served by the API's public `/media` route) while MAYOS's
/// own licence from Gym visual is pending, subject to Gym visual's terms —
/// every use carries the credit below and media is never shown larger than
/// its native 180×180. `docs/design-review/53/MEDIA-PROVENANCE.md` records the
/// facts and the decision.
///
/// `--dart-define=MAYOS_EXERCISE_MEDIA=false` is the kill switch: OFF means
/// no `Image` widget is built for catalog media anywhere — the logger
/// thumbnail falls back to its icon and the exercise-detail hero is the
/// typographic/muscle-group header.
const bool mayosExerciseMediaEnabled =
    String.fromEnvironment('MAYOS_EXERCISE_MEDIA') != 'false';

/// The credit Gym visual's terms require on every use of its media.
const String gymVisualCreditShort = '© Gym visual — gymvisual.com';

/// The full credit line, verbatim as the terms state it.
const String gymVisualCredit = '© Gym visual — https://gymvisual.com/';

/// Where that notice points.
const String gymVisualUrl = 'https://gymvisual.com/';
