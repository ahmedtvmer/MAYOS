import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_timezone/flutter_timezone.dart';

/// The device's IANA timezone, used to prefill the player's schedule timezone
/// before any schedule exists (#30, ADR 029).
///
/// It is a provider of a `Future<String>` so widget tests can inject a fake and
/// never touch the platform channel. A fetch failure falls back to `'UTC'`,
/// matching the service's own default.
final Provider<Future<String>> deviceTimezoneProvider =
    Provider<Future<String>>((ref) => deviceTimezone());

Future<String> deviceTimezone() async {
  try {
    final TimezoneInfo info = await FlutterTimezone.getLocalTimezone();
    final String identifier = info.identifier.trim();
    return identifier.isEmpty ? 'UTC' : identifier;
  } catch (_) {
    return 'UTC';
  }
}

/// The device's IANA timezone, or null when it genuinely could not be
/// determined — unlike [deviceTimezoneProvider], this never guesses `'UTC'`
/// as a fallback, so a caller that must not invent a timezone (the offline
/// workout logger, ADR 020/033) can tell "unknown" apart from an actual UTC
/// device.
final Provider<Future<String?>> deviceTimezoneOrNullProvider =
    Provider<Future<String?>>((ref) => deviceTimezoneOrNull());

Future<String?> deviceTimezoneOrNull() async {
  try {
    final TimezoneInfo info = await FlutterTimezone.getLocalTimezone();
    final String identifier = info.identifier.trim();
    return identifier.isEmpty ? null : identifier;
  } catch (_) {
    return null;
  }
}
