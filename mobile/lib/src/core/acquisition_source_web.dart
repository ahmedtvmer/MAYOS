import 'package:web/web.dart' as web;

import 'browser_key_value_store.dart';
import 'first_touch.dart';

const String _firstTouchKey = 'mayos.first_touch';

AcquisitionSource createAcquisitionSource({
  FirstTouchPersistence? persistence,
  InstallReferrerReader? installReferrerReader,
}) {
  final BrowserKeyValueStore browserStore = createBrowserKeyValueStore();
  final _BrowserFirstTouchPersistence store =
      _BrowserFirstTouchPersistence(persistence, browserStore);
  FirstTouch? nextSnapshot = _currentWebSnapshot();
  return PersistentAcquisitionSource(
    persistence: store,
    clearOnRegistration: true,
    readCurrent: () async {
      final FirstTouch? snapshot = nextSnapshot;
      nextSnapshot = _currentWebSnapshot();
      return snapshot;
    },
  );
}

FirstTouch? _currentWebSnapshot() {
  final Uri location = Uri.parse(web.window.location.href);
  final Map<String, String> parameters = location.queryParameters;
  final String? host = Uri.tryParse(web.window.document.referrer)?.host;
  final FirstTouch touch = FirstTouch(
    utmSource: parameters['utm_source'],
    utmMedium: parameters['utm_medium'],
    utmCampaign: parameters['utm_campaign'],
    referrerHost: host == null || host.isEmpty ? null : host.toLowerCase(),
  );
  return touch.toJson().isEmpty ? null : touch;
}

class _BrowserFirstTouchPersistence implements FirstTouchPersistence {
  _BrowserFirstTouchPersistence(FirstTouchPersistence? supplied, BrowserKeyValueStore browser)
      : _supplied = supplied,
        _browser = browser;

  final FirstTouchPersistence? _supplied;
  final BrowserKeyValueStore _browser;

  @override
  Future<String?> read() async =>
      _supplied?.read() ?? Future<String?>.value(_browser.getItem(_firstTouchKey));

  @override
  Future<void> write(String value) async {
    final FirstTouchPersistence? supplied = _supplied;
    if (supplied != null) {
      await supplied.write(value);
    } else {
      _browser.setItem(_firstTouchKey, value);
    }
  }

  @override
  Future<void> clear() async {
    final FirstTouchPersistence? supplied = _supplied;
    if (supplied != null) {
      await supplied.clear();
    } else {
      _browser.removeItem(_firstTouchKey);
    }
  }
}
