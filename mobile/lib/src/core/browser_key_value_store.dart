import 'browser_key_value_store_stub.dart'
    if (dart.library.js_interop) 'browser_key_value_store_web.dart' as platform;

/// The small localStorage surface used by the web Active workout.
abstract interface class BrowserKeyValueStore {
  String? getItem(String key);

  void setItem(String key, String value);

  void removeItem(String key);
}

BrowserKeyValueStore createBrowserKeyValueStore() =>
    platform.createBrowserKeyValueStore();
