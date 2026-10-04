import 'dart:async';
import 'dart:convert';

const Duration firstTouchCaptureTimeout = Duration(milliseconds: 300);

/// The allowlisted first-touch labels sent only when a new Account is created.
class FirstTouch {
  const FirstTouch({
    this.utmSource,
    this.utmMedium,
    this.utmCampaign,
    this.referrerHost,
  });

  final String? utmSource;
  final String? utmMedium;
  final String? utmCampaign;
  final String? referrerHost;

  Map<String, String> toJson() => <String, String>{
        if (utmSource != null) 'utm_source': utmSource!,
        if (utmMedium != null) 'utm_medium': utmMedium!,
        if (utmCampaign != null) 'utm_campaign': utmCampaign!,
        if (referrerHost != null) 'referrer_host': referrerHost!,
      };

  static FirstTouch? fromJson(Object? value) {
    if (value is! Map) return null;
    String? field(String key) => value[key] is String ? value[key] as String : null;
    final FirstTouch touch = FirstTouch(
      utmSource: field('utm_source'),
      utmMedium: field('utm_medium'),
      utmCampaign: field('utm_campaign'),
      referrerHost: field('referrer_host'),
    );
    return touch.toJson().isEmpty ? null : touch;
  }

  static FirstTouch? fromInstallReferrer(String rawReferrer) {
    try {
      final Uri parsed = Uri.parse(
        rawReferrer.contains('?') ? rawReferrer : '?$rawReferrer',
      );
      final Map<String, String> parameters = parsed.queryParameters;
      return FirstTouch.fromJson(<String, String>{
        if (parameters['utm_source'] != null)
          'utm_source': parameters['utm_source']!,
        if (parameters['utm_medium'] != null)
          'utm_medium': parameters['utm_medium']!,
        if (parameters['utm_campaign'] != null)
          'utm_campaign': parameters['utm_campaign']!,
      });
    } on FormatException {
      return null;
    }
  }
}

abstract interface class FirstTouchPersistence {
  Future<String?> read();
  Future<void> write(String value);
  Future<void> clear();
}

typedef FirstTouchReader = Future<FirstTouch?> Function();
typedef InstallReferrerReader = Future<String?> Function();

/// Platform source injected by providers and replaced with a fake in tests.
abstract interface class AcquisitionSource {
  Future<FirstTouch?> captureFirstTouch();
  Future<void> clearAfterRegistration();
}

/// Reads a saved snapshot first and writes even an empty snapshot as a marker.
class PersistentAcquisitionSource implements AcquisitionSource {
  PersistentAcquisitionSource({
    required FirstTouchPersistence persistence,
    required FirstTouchReader readCurrent,
    this.clearOnRegistration = false,
  })  : _persistence = persistence,
        _readCurrent = readCurrent;

  final FirstTouchPersistence _persistence;
  final FirstTouchReader _readCurrent;
  final bool clearOnRegistration;
  Future<FirstTouch?>? _snapshot;

  @override
  Future<FirstTouch?> captureFirstTouch() => _snapshot ??= _readOrCapture();

  Future<FirstTouch?> _readOrCapture() async {
    String? saved;
    var hasSavedValue = false;
    try {
      saved = await _persistence.read();
      hasSavedValue = saved != null;
    } catch (_) {
      // Acquisition storage is best effort and never blocks registration.
    }
    if (hasSavedValue) {
      try {
        return FirstTouch.fromJson(jsonDecode(saved!));
      } catch (_) {
        return null;
      }
    }

    FirstTouch? touch;
    try {
      touch = await _readCurrent();
    } catch (_) {
      touch = null;
    }
    try {
      await _persistence.write(jsonEncode(touch?.toJson() ?? <String, String>{}));
    } catch (_) {
      // A storage failure must not affect sign-up.
    }
    return touch;
  }

  @override
  Future<void> clearAfterRegistration() async {
    if (!clearOnRegistration) return;
    try {
      await _persistence.clear();
    } on Object {
      // Clearing this optional snapshot must not turn a successful signup into failure.
    }
    _snapshot = null;
  }
}

/// Keeps capture bounded and isolated from the account-creation request.
class FirstTouchCapture {
  FirstTouchCapture(this._source);

  final AcquisitionSource _source;
  Future<FirstTouch?>? _capture;

  Future<FirstTouch?> capture() => _capture ??= _captureSafely();

  Future<FirstTouch?> _captureSafely() async {
    final Completer<FirstTouch?> timedOut = Completer<FirstTouch?>();
    final Timer timer = Timer(
      firstTouchCaptureTimeout,
      () => timedOut.complete(null),
    );
    try {
      final Future<FirstTouch?> source =
          Future<FirstTouch?>.sync(_source.captureFirstTouch).catchError(
        (Object error, StackTrace stack) => null,
      );
      return await Future.any<FirstTouch?>(<Future<FirstTouch?>>[
        source,
        timedOut.future,
      ]);
    } catch (_) {
      return null;
    } finally {
      timer.cancel();
    }
  }

  Future<void> clearAfterRegistration() async {
    try {
      await _source
          .clearAfterRegistration()
          .timeout(firstTouchCaptureTimeout);
    } catch (_) {
      // A storage failure must not fail a successful account creation.
    }
    _capture = null;
  }
}
